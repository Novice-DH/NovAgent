"""context_compressor_node 离线单元测试（FakeModel，不发起网络请求）。"""

import json
from datetime import datetime
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

import novagent.graph.nodes as graph_nodes
from novagent.core.state import RuntimeState
from novagent.graph.memory import build_layered_memory, format_layered_memory_for_prompt
from novagent.graph.nodes import context_compressor_node
from novagent.prompts.stage4 import CONTEXT_COMPRESSION_PROMPT


class FakeCompressorModel:
    """返回预设文本并记录 invoke 入参。"""

    def __init__(self, content):
        self.content = content
        self.calls = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        return AIMessage(content=self.content)


def _payload(**overrides) -> str:
    data = {
        "summary": "done summary",
        "active_goal": "finish the demo",
        "completed_work": "wrote file a",
        "open_todos": "run checks",
        "important_files": "src/a.py",
        "tool_findings": "tests pass",
        "sources": "https://example.com",
        "next_steps": "verify output",
        "risks": "none",
    }
    data.update(overrides)
    return json.dumps(data)


def _state(workspace=None, **overrides) -> dict:
    state = {
        "task": "demo task",
        "messages": [HumanMessage("hello"), AIMessage("step done")],
    }
    if workspace is not None:
        state["runtime"] = RuntimeState(workspace=workspace)
    state.update(overrides)
    return state


def _forbidden_create_model(*args, **kwargs):
    raise AssertionError("context_compressor_node must not call create_model here")


def test_prompt_constant():
    assert isinstance(CONTEXT_COMPRESSION_PROMPT, str) and CONTEXT_COMPRESSION_PROMPT
    assert CONTEXT_COMPRESSION_PROMPT.startswith(
        "You are the context_compressor node in novagent stage 4."
    )
    for key in (
        "summary",
        "active_goal",
        "completed_work",
        "open_todos",
        "important_files",
        "tool_findings",
        "sources",
        "next_steps",
        "risks",
    ):
        assert f"- {key}" in CONTEXT_COMPRESSION_PROMPT
    assert "Return only JSON with these keys" in CONTEXT_COMPRESSION_PROMPT


def test_model_call_construction(workspace):
    model = FakeCompressorModel(_payload())

    context_compressor_node(_state(workspace), model=model)

    assert len(model.calls) == 1
    system_message, human_message = model.calls[0]
    assert isinstance(system_message, SystemMessage)
    assert system_message.content == CONTEXT_COMPRESSION_PROMPT
    assert (
        graph_nodes.CONTEXT_COMPRESSION_PROMPT is CONTEXT_COMPRESSION_PROMPT
    )
    assert isinstance(human_message, HumanMessage)
    assert "demo task" in human_message.content
    assert "hello" in human_message.content
    assert "step done" in human_message.content
    memory_text = format_layered_memory_for_prompt(build_layered_memory(_state(workspace)))
    assert "working_memory" in human_message.content
    assert json.loads(memory_text)["working_memory"]


def test_message_replacement_and_fields(workspace):
    model = FakeCompressorModel(_payload())

    result = context_compressor_node(_state(workspace), model=model)

    remove, summary_message = result["messages"]
    assert isinstance(remove, RemoveMessage)
    assert remove.id == REMOVE_ALL_MESSAGES
    assert isinstance(summary_message, AIMessage)
    assert summary_message.content == "done summary"
    assert result["context_summary"] == "done summary"
    assert result["context_should_compress"] is False
    assert result["context_token_count"] == graph_nodes._estimate_text_tokens(
        "done summary"
    )


def test_history_summary_file_persisted(workspace):
    model = FakeCompressorModel(_payload())

    context_compressor_node(_state(workspace), model=model)

    content = (Path(workspace) / "HISTORY_SUMMARY.md").read_text(encoding="utf-8")
    for text in (
        "done summary",
        "finish the demo",
        "wrote file a",
        "run checks",
        "src/a.py",
        "tests pass",
        "https://example.com",
        "verify output",
        "none",
    ):
        assert text in content


def test_field_truncation(workspace):
    model = FakeCompressorModel(_payload(summary="s" * 2000))
    handoffs = [
        {"from_agent": "planner", "to_agent": "searchAgent", "instruction": str(i), "result": ""}
        for i in range(8)
    ]

    result = context_compressor_node(
        _state(workspace, research_notes="x" * 2000, agent_handoffs=handoffs),
        model=model,
    )

    assert len(result["research_notes"]) == 1600
    assert result["research_notes"].endswith("...")
    assert len(result["agent_handoffs"]) == 6
    assert result["agent_handoffs"] == handoffs[-6:]
    assert len(result["context_summary"]) == 1600
    assert result["context_summary"].endswith("...")


def test_compression_event_appended(workspace):
    old_event = {"node": "legacy", "reason": "old"}
    model = FakeCompressorModel(_payload())

    result = context_compressor_node(
        _state(workspace, compression_events=[old_event], context_token_limit=5000),
        model=model,
    )

    events = result["compression_events"]
    assert events[0] == old_event
    event = events[1]
    assert event["node"] == "context_compressor"
    assert event["reason"]
    transcript = graph_nodes._message_transcript([HumanMessage("hello"), AIMessage("step done")])
    assert event["token_count"] == graph_nodes._estimate_text_tokens(transcript)
    assert event["token_limit"] == 5000
    assert event["summary"] == "done summary"
    datetime.fromisoformat(event["created_at"])
    assert result["history_summary"] == "done summary"


def test_invalid_json_fallback(workspace, monkeypatch):
    monkeypatch.setattr(graph_nodes, "create_model", _forbidden_create_model)
    model = FakeCompressorModel("this is not json at all")

    result = context_compressor_node(_state(workspace), model=model)

    remove, summary_message = result["messages"]
    assert isinstance(remove, RemoveMessage)
    assert remove.id == REMOVE_ALL_MESSAGES
    assert isinstance(summary_message, AIMessage)
    assert summary_message.content
    assert (Path(workspace) / "HISTORY_SUMMARY.md").exists()


def test_missing_runtime_and_messages(monkeypatch):
    monkeypatch.setattr(graph_nodes, "create_model", _forbidden_create_model)
    model = FakeCompressorModel(_payload())

    result = context_compressor_node({}, model=model)

    for key in (
        "messages",
        "context_summary",
        "context_token_count",
        "context_should_compress",
        "research_notes",
        "agent_handoffs",
        "sources",
        "code_agent_summary",
        "history_summary",
        "compression_events",
    ):
        assert key in result
    assert result["context_summary"] == "done summary"
    assert result["compression_events"][0]["node"] == "context_compressor"


def test_persist_failure_is_tolerated(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_nodes, "create_model", _forbidden_create_model)
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    model = FakeCompressorModel(_payload())

    result = context_compressor_node(
        _state(blocked), model=model
    )

    assert result["context_summary"] == "done summary"
