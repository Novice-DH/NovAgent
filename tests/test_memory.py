"""三层 Memory 系统的离线单元测试（纯函数，不调用模型）。"""

import json

from novagent.core.state import RuntimeState
from novagent.graph.memory import (
    RULES_LAYER,
    build_layered_memory,
    format_layered_memory_for_prompt,
    memory_event,
    read_history_summary,
    read_notepad,
)
from novagent.graph.state import NovGraphState


def _runtime(workspace):
    return RuntimeState(workspace=workspace)


def test_rules_layer_structure():
    assert isinstance(RULES_LAYER, dict)
    assert RULES_LAYER["scope"] == "workspace"
    assert RULES_LAYER["storage"] == "internal"
    assert RULES_LAYER["rules"] == [
        "Work inside the current workspace only.",
        "Use paths relative to the workspace; do not prefix paths with workspace/.",
        "Keep durable task context outside the raw messages transcript when possible.",
        "Treat TODO.md as working plan state, NOTEPAD.md as durable notes, "
        "and HISTORY_SUMMARY.md as compressed history.",
        "Do not expose memory write tools to agents; layered memory is assembled "
        "by the runtime.",
    ]


def test_read_notepad_and_history_summary(workspace):
    (workspace / "NOTEPAD.md").write_text("durable note", encoding="utf-8")
    (workspace / "HISTORY_SUMMARY.md").write_text(
        "compressed history", encoding="utf-8"
    )
    runtime = _runtime(workspace)

    notepad = read_notepad(runtime)
    history = read_history_summary(runtime)
    assert notepad == {"exists": True, "content": "durable note"}
    assert history == {"exists": True, "content": "compressed history"}


def test_read_missing_files_tolerant(tmp_path):
    runtime = _runtime(tmp_path / "empty-ws")
    (tmp_path / "empty-ws").mkdir()

    assert read_notepad(runtime) == {"exists": False, "content": ""}
    assert read_history_summary(runtime) == {"exists": False, "content": ""}


def test_read_without_runtime_tolerant():
    assert read_notepad(None) == {"exists": False, "content": ""}
    assert read_history_summary(None) == {"exists": False, "content": ""}


def test_build_layered_memory_layer_keys(workspace):
    memory = build_layered_memory({"runtime": _runtime(workspace)})

    assert set(memory.keys()) == {
        "rules",
        "working_memory",
        "history_summary_store",
    }
    assert set(memory["working_memory"].keys()) == {
        "node",
        "task",
        "session_id",
        "session_turn",
        "plan_summary",
        "todos",
        "acceptance_criteria",
        "verification_commands",
        "research_notes",
        "sources",
        "agent_handoffs",
        "code_agent_summary",
        "verifier_summary",
        "last_error",
        "attempts",
        "max_attempts",
    }
    assert set(memory["history_summary_store"].keys()) == {
        "history_path",
        "history_exists",
        "history_summary",
        "notepad_path",
        "notepad_exists",
        "notepad",
        "context_summary",
        "compression_events",
    }


def test_build_layered_memory_values(workspace):
    handoffs = [
        {"from_agent": "planner", "to_agent": f"agent-{i}", "instruction": "", "result": ""}
        for i in range(8)
    ]
    state = {
        "runtime": _runtime(workspace),
        "task": "build a thing",
        "plan_summary": "plan",
        "todos": [{"id": "t1", "content": "step", "status": "pending", "note": ""}],
        "acceptance_criteria": ["works"],
        "verification_commands": ["pytest -q"],
        "research_notes": "notes",
        "sources": [
            {"title": "Doc", "url": "https://example.com", "content": "long", "score": 0.9}
        ],
        "agent_handoffs": handoffs,
        "code_agent_summary": "did it",
        "last_error": "boom",
        "attempts": 2,
        "max_attempts": 5,
        "context_summary": "earlier context",
        "compression_events": [{"node": f"n{i}"} for i in range(5)],
    }

    memory = build_layered_memory(state, node="planner")
    working = memory["working_memory"]
    assert working["node"] == "planner"
    assert working["task"] == "build a thing"
    assert working["session_id"] == ""
    assert working["session_turn"] == 0
    assert working["plan_summary"] == "plan"
    assert working["todos"] == state["todos"]
    assert working["acceptance_criteria"] == ["works"]
    assert working["verification_commands"] == ["pytest -q"]
    assert working["research_notes"] == "notes"
    assert working["sources"] == [{"title": "Doc", "url": "https://example.com"}]
    assert [h["to_agent"] for h in working["agent_handoffs"]] == [
        f"agent-{i}" for i in range(2, 8)
    ]
    assert working["code_agent_summary"] == "did it"
    assert working["verifier_summary"] == ""
    assert working["last_error"] == "boom"
    assert working["attempts"] == 2
    assert working["max_attempts"] == 5

    store = memory["history_summary_store"]
    assert store["history_path"] == "HISTORY_SUMMARY.md"
    assert store["history_exists"] is False
    assert store["history_summary"] == ""
    assert store["notepad_path"] == "NOTEPAD.md"
    assert store["notepad_exists"] is False
    assert store["notepad"] == ""
    assert store["context_summary"] == "earlier context"
    assert [event["node"] for event in store["compression_events"]] == [
        "n2",
        "n3",
        "n4",
    ]


def test_build_layered_memory_reads_files(workspace):
    (workspace / "NOTEPAD.md").write_text("keep this note", encoding="utf-8")
    (workspace / "HISTORY_SUMMARY.md").write_text("prior history", encoding="utf-8")

    memory = build_layered_memory({"runtime": _runtime(workspace)})
    store = memory["history_summary_store"]
    assert store["notepad_exists"] is True
    assert store["notepad"] == "keep this note"
    assert store["history_exists"] is True
    assert store["history_summary"] == "prior history"


def test_short_text_truncation():
    from novagent.graph.memory import _short_text

    long_text = "x" * 50
    result = _short_text(long_text, 10)
    assert len(result) <= 10
    assert result.endswith("...")
    assert result == "xxxxxxx..."

    assert _short_text("short", 10) == "short"
    assert _short_text("exactly10!", 10) == "exactly10!"


def test_named_truncation_limits_end_to_end(workspace):
    from novagent.graph.memory import (
        CODE_AGENT_SUMMARY_LIMIT,
        CONTEXT_SUMMARY_LIMIT,
        HISTORY_SUMMARY_LIMIT,
        LAST_ERROR_LIMIT,
        NOTEPAD_LIMIT,
        RESEARCH_NOTES_LIMIT,
        VERIFIER_SUMMARY_LIMIT,
    )

    (workspace / "NOTEPAD.md").write_text("n" * 9999, encoding="utf-8")
    (workspace / "HISTORY_SUMMARY.md").write_text("h" * 9999, encoding="utf-8")
    state = {
        "runtime": _runtime(workspace),
        "research_notes": "r" * 9999,
        "code_agent_summary": "c" * 9999,
        "verifier_summary": "v" * 9999,
        "last_error": "e" * 9999,
        "context_summary": "x" * 9999,
    }

    store = build_layered_memory(state)["history_summary_store"]
    working = build_layered_memory(state)["working_memory"]
    cases = [
        (working["research_notes"], RESEARCH_NOTES_LIMIT),
        (working["code_agent_summary"], CODE_AGENT_SUMMARY_LIMIT),
        (working["verifier_summary"], VERIFIER_SUMMARY_LIMIT),
        (working["last_error"], LAST_ERROR_LIMIT),
        (store["history_summary"], HISTORY_SUMMARY_LIMIT),
        (store["notepad"], NOTEPAD_LIMIT),
        (store["context_summary"], CONTEXT_SUMMARY_LIMIT),
    ]
    for text, limit in cases:
        assert len(text) == limit
        assert text.endswith("...")


def test_read_non_utf8_file_tolerant(workspace):
    (workspace / "NOTEPAD.md").write_bytes(b"\xff\xfe\x00binary")

    assert read_notepad(_runtime(workspace)) == {"exists": False, "content": ""}


def test_trim_handoffs_keeps_recent_six():
    from novagent.graph.memory import _trim_handoffs

    handoffs = [{"i": i} for i in range(8)]
    trimmed = _trim_handoffs(handoffs)
    assert [h["i"] for h in trimmed] == [2, 3, 4, 5, 6, 7]

    assert _trim_handoffs([{"i": 0}]) == [{"i": 0}]
    assert _trim_handoffs("not-a-list") == []
    assert _trim_handoffs(None) == []


def test_empty_state_tolerant():
    memory = build_layered_memory({})
    working = memory["working_memory"]
    assert working["node"] == "graph"
    assert working["task"] == ""
    assert working["session_id"] == ""
    assert working["session_turn"] == 0
    assert working["todos"] == []
    assert working["attempts"] == 0
    assert working["max_attempts"] == 3

    store = memory["history_summary_store"]
    assert store["history_exists"] is False
    assert store["notepad_exists"] is False
    assert store["compression_events"] == []


def test_build_layered_memory_does_not_mutate_state(workspace):
    state = {
        "runtime": _runtime(workspace),
        "task": "t",
        "sources": [{"title": "T", "url": "u", "content": "c"}],
        "agent_handoffs": [{"from_agent": "a"}],
    }
    snapshot = json.dumps(state, sort_keys=True, default=str)
    build_layered_memory(state)
    assert json.dumps(state, sort_keys=True, default=str) == snapshot


def test_format_layered_memory_for_prompt_roundtrip(workspace):
    memory = build_layered_memory(
        {"runtime": _runtime(workspace), "task": "中文任务"}
    )
    text = format_layered_memory_for_prompt(memory)
    assert isinstance(text, str)
    assert json.loads(text) == memory
    assert "中文任务" in text


def test_nov_graph_state_has_memory_fields():
    annotations = NovGraphState.__annotations__
    assert "context_summary" in annotations
    assert "context_token_count" in annotations
    assert "context_token_limit" in annotations
    assert "context_should_compress" in annotations
    assert "context_next_node" in annotations
    assert "compression_events" in annotations
    assert "memory_snapshot" in annotations
    assert "history_summary" in annotations


def test_memory_event_shape():
    memory = {"rules": {"scope": "workspace"}}
    event = memory_event(memory, node="planner")
    assert event == {"type": "memory", "node": "planner", "memory": memory}
    assert event["memory"] is memory
    assert memory_event(memory)["node"] == "graph"
