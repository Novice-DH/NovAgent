"""code_agent 的离线行为（FakeModel，不发起网络请求）。"""

import json

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from novagent.agents.code_agent import (
    CODE_AGENT_PROMPT,
    build_memory_snapshot,
    run_code_agent,
)
from novagent.core.state import RuntimeState


class FakeModel:
    """按序返回预设响应并记录收到的消息与绑定工具。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        return self.responses.pop(0)


def _tool_call(name, args, call_id):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
    )


def _state(workspace, **overrides):
    state = {
        "task": "demo task",
        "runtime": RuntimeState(workspace=workspace),
    }
    state.update(overrides)
    return state


def test_binds_build_tools_plus_todo_update(workspace):
    model = FakeModel([AIMessage(content="done.")])

    result = run_code_agent(_state(workspace), "implement it", model=model)

    assert [tool.name for tool in model.bound_tools] == [
        "read_file",
        "write_file",
        "edit_file",
        "grep",
        "bash",
        "todo_update",
    ]
    assert result["ok"] is True


def test_message_construction_with_placeholders(workspace):
    model = FakeModel([AIMessage(content="ok.")])

    run_code_agent(
        _state(workspace, session_context="session notes here"),
        "implement it",
        model=model,
    )

    system_message, human_message = model.calls[0]
    assert isinstance(system_message, SystemMessage)
    assert system_message.content == CODE_AGENT_PROMPT
    assert "demo task" in human_message.content
    assert "implement it" in human_message.content
    assert "session notes here" in human_message.content
    assert "(no memory snapshot)" in human_message.content

    model = FakeModel([AIMessage(content="ok.")])
    run_code_agent(_state(workspace), "again", model=model)
    human_message = model.calls[0][1]
    assert "(no session context)" in human_message.content


def test_react_loop_updates_todos_and_emits_events(workspace):
    state = _state(
        workspace,
        todos=[{"id": "t1", "content": "step", "status": "pending", "note": ""}],
    )
    model = FakeModel(
        [
            _tool_call(
                "write_file",
                {"file_path": "result.txt", "content": "hi"},
                "call_1",
            ),
            _tool_call(
                "todo_update", {"todo_id": "t1", "status": "in_progress"}, "call_2"
            ),
            _tool_call(
                "todo_update",
                {"todo_id": "t1", "status": "completed", "note": "done"},
                "call_3",
            ),
            AIMessage(content="All done."),
        ]
    )
    events = []

    result = run_code_agent(state, "implement it", writer=events.append, model=model)

    assert (workspace / "result.txt").read_text(encoding="utf-8") == "hi"
    assert result["summary"] == "All done."
    assert result["todos"] == [
        {"id": "t1", "content": "step", "status": "completed", "note": "done"}
    ]
    assert [type(message).__name__ for message in result["messages"]] == [
        "AIMessage",
        "ToolMessage",
        "AIMessage",
        "ToolMessage",
        "AIMessage",
        "ToolMessage",
        "AIMessage",
    ]
    tool_message = result["messages"][1]
    assert tool_message.tool_call_id == "call_1"
    assert json.loads(tool_message.content)
    assert [event["type"] for event in result["tool_events"]] == [
        "ai_message",
        "tool_call",
        "tool_result",
        "ai_message",
        "tool_call",
        "tool_result",
        "ai_message",
        "tool_call",
        "tool_result",
        "ai_message",
        "final_answer",
    ]
    assert result["tool_events"][-1] == {"type": "final_answer", "content": "All done."}
    assert events == result["tool_events"]


def test_todo_blocked_and_unknown_id(workspace):
    state = _state(
        workspace,
        todos=[{"id": "t1", "content": "step", "status": "pending", "note": ""}],
    )
    model = FakeModel(
        [
            _tool_call(
                "todo_update",
                {"todo_id": "t1", "status": "blocked", "note": "impossible"},
                "call_1",
            ),
            _tool_call(
                "todo_update", {"todo_id": "ghost", "status": "completed"}, "call_2"
            ),
            AIMessage(content="cannot finish."),
        ]
    )

    result = run_code_agent(state, "try", model=model)

    assert result["todos"] == [
        {"id": "t1", "content": "step", "status": "blocked", "note": "impossible"}
    ]


def test_loop_stops_without_tool_calls(workspace):
    model = FakeModel([AIMessage(content="nothing to do.")])

    result = run_code_agent(_state(workspace), "check", model=model)

    assert len(model.calls) == 1
    assert result["summary"] == "nothing to do."
    assert result["tool_events"][-1] == {
        "type": "final_answer",
        "content": "nothing to do.",
    }


def test_loop_respects_max_loops(workspace):
    model = FakeModel(
        [
            _tool_call(
                "write_file",
                {"file_path": f"f{i}.txt", "content": "x"},
                f"call_{i}",
            )
            for i in range(5)
        ]
    )

    result = run_code_agent(_state(workspace), "many files", model=model, max_loops=2)

    assert len(model.calls) == 2
    assert (workspace / "f0.txt").exists()
    assert (workspace / "f1.txt").exists()
    assert not (workspace / "f2.txt").exists()
    # max_loops 耗尽时循环停在最后一轮的 ToolMessage，不再多调一次模型
    assert type(result["messages"][-1]).__name__ == "ToolMessage"


def test_unknown_tool_degrades_and_loop_continues(workspace):
    model = FakeModel(
        [
            _tool_call("notepad_append", {"content": "remember this"}, "call_1"),
            AIMessage(content="noted anyway."),
        ]
    )

    result = run_code_agent(_state(workspace), "use notes", model=model)

    payload = json.loads(result["messages"][1].content)
    assert payload.startswith("Error: unknown tool")
    assert "notepad_append" in payload
    assert len(model.calls) == 2
    assert result["ok"] is True


def test_runtime_is_required(workspace):
    with pytest.raises(ValueError, match="runtime"):
        run_code_agent({"task": "t"}, "i", model=FakeModel([]))


def test_build_memory_snapshot_is_reserved_interface(workspace):
    assert build_memory_snapshot(_state(workspace)) == ""
    assert build_memory_snapshot({"anything": 1}) == ""


def test_prompt_constant():
    assert CODE_AGENT_PROMPT.startswith(
        "You are codeAgent, a focused implementation specialist."
    )
    assert "TodoUpdateTool" in CODE_AGENT_PROMPT
    assert "NotepadAppendTool" in CODE_AGENT_PROMPT
    assert "BashTool" in CODE_AGENT_PROMPT
    assert CODE_AGENT_PROMPT.rstrip("\n").endswith(
        "End with a concise summary of files changed and checks run."
    )
