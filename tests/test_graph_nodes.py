"""graph.nodes 三节点与路由的离线行为（FakeModel，不发起网络请求）。"""

import json
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from novagent.core.state import RuntimeState
from novagent.graph.nodes import (
    PLANNER_PROMPT,
    VERIFIER_PROMPT,
    actor_node,
    planner_node,
    verifier_node,
    verifier_route,
)
from novagent.prompts.stage2 import ACTOR_PROMPT
from novagent.tools.todo_tools import create_todo_update_tool, create_todo_write_tool


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


def _graph_state(workspace, **overrides):
    state = {"task": "demo task", "runtime": RuntimeState(workspace=workspace)}
    state.update(overrides)
    return state


def test_todo_tools_schemas_and_no_side_effects():
    write_tool = create_todo_write_tool()
    update_tool = create_todo_update_tool()
    assert write_tool.name == "todo_write"
    assert set(write_tool.args_schema.model_fields) == {
        "plan_summary",
        "todos",
        "acceptance_criteria",
        "verification_commands",
    }
    assert update_tool.name == "todo_update"
    assert set(update_tool.args_schema.model_fields) == {"todo_id", "status", "note"}
    submitted = write_tool.invoke(
        {
            "plan_summary": "s",
            "todos": [],
            "acceptance_criteria": [],
            "verification_commands": [],
        }
    )
    assert "Plan submitted" in submitted
    updated = update_tool.invoke({"todo_id": "t1", "status": "completed"})
    assert "updated" in updated.lower()


def test_planner_creates_plan_from_todo_write(workspace):
    plan_args = {
        "plan_summary": "plan",
        "todos": [{"id": "t1", "content": "step"}],
        "acceptance_criteria": ["file exists"],
        "verification_commands": ["python -c 'pass'"],
    }
    model = FakeModel([_tool_call("todo_write", plan_args, "call_1")])

    update = planner_node(_graph_state(workspace), model=model)

    assert update["plan_summary"] == "plan"
    assert update["todos"] == [
        {"id": "t1", "content": "step", "status": "pending", "note": ""}
    ]
    assert update["acceptance_criteria"] == ["file exists"]
    assert update["verification_commands"] == ["python -c 'pass'"]
    assert [tool.name for tool in model.bound_tools] == ["todo_write"]
    system_message, human_message = model.calls[0]
    assert isinstance(system_message, SystemMessage)
    assert system_message.content == PLANNER_PROMPT
    assert isinstance(human_message, HumanMessage)
    assert "demo task" in human_message.content
    assert "passed" not in update
    assert "attempts" not in update


def test_planner_revises_after_failure(workspace):
    plan_args = {
        "plan_summary": "revised",
        "todos": [{"id": "t2", "content": "fix"}],
        "acceptance_criteria": [],
        "verification_commands": [],
    }
    model = FakeModel([_tool_call("todo_write", plan_args, "call_1")])
    state = _graph_state(
        workspace,
        todos=[{"id": "t1", "content": "old", "status": "in_progress", "note": ""}],
        last_error="boom",
        verification_results=[
            {
                "command": "fail.cmd",
                "ok": False,
                "exit_code": 1,
                "stdout": "",
                "stderr": "boom detail",
            }
        ],
    )

    update = planner_node(state, model=model)

    system_message, human_message = model.calls[0]
    assert system_message.content == PLANNER_PROMPT
    assert isinstance(human_message, HumanMessage)
    assert "boom" in human_message.content
    assert update["todos"] == [
        {"id": "t2", "content": "fix", "status": "pending", "note": ""}
    ]


def test_planner_requires_todo_write_call(workspace):
    model = FakeModel([AIMessage(content="no tools here")])
    with pytest.raises(ValueError, match="todo_write"):
        planner_node(_graph_state(workspace), model=model)


def test_actor_runs_react_loop_and_emits_events(workspace):
    model = FakeModel(
        [
            _tool_call(
                "write_file", {"file_path": "note.txt", "content": "hi"}, "call_1"
            ),
            AIMessage(content="All done."),
        ]
    )
    events = []

    update = actor_node(
        _graph_state(workspace, plan_summary="plan text"),
        model=model,
        on_event=events.append,
    )

    assert [event["type"] for event in events] == [
        "ai_message",
        "tool_call",
        "tool_result",
        "ai_message",
        "final_answer",
    ]
    assert events[-1] == {"type": "final_answer", "content": "All done."}
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "hi"
    assert update["last_actor_summary"] == "All done."
    assert [type(message).__name__ for message in update["messages"]] == [
        "AIMessage",
        "ToolMessage",
        "AIMessage",
    ]
    tool_message = update["messages"][1]
    assert tool_message.tool_call_id == "call_1"
    assert json.loads(tool_message.content) == events[2]["result"]
    assert [tool.name for tool in model.bound_tools] == [
        "read_file",
        "write_file",
        "edit_file",
        "grep",
        "bash",
        "todo_update",
    ]
    system_message, human_message = model.calls[0]
    assert system_message.content == ACTOR_PROMPT
    assert "demo task" in human_message.content
    assert "plan text" in human_message.content


def test_actor_applies_todo_updates(workspace):
    model = FakeModel(
        [
            _tool_call(
                "todo_update",
                {"todo_id": "t1", "status": "completed", "note": "done"},
                "call_1",
            ),
            AIMessage(content="step finished."),
        ]
    )
    state = _graph_state(
        workspace,
        todos=[{"id": "t1", "content": "step", "status": "in_progress", "note": ""}],
    )

    update = actor_node(state, model=model)

    assert update["todos"] == [
        {"id": "t1", "content": "step", "status": "completed", "note": "done"}
    ]


def test_actor_ignores_unknown_todo_id(workspace):
    model = FakeModel(
        [
            _tool_call(
                "todo_update",
                {"todo_id": "ghost", "status": "completed"},
                "call_1",
            ),
            AIMessage(content="whatever."),
        ]
    )
    state = _graph_state(
        workspace,
        todos=[{"id": "t1", "content": "step", "status": "pending", "note": ""}],
    )

    update = actor_node(state, model=model)

    assert update["todos"] == [
        {"id": "t1", "content": "step", "status": "pending", "note": ""}
    ]


def test_actor_and_verifier_require_runtime(workspace):
    with pytest.raises(ValueError, match="runtime"):
        actor_node({"task": "t"}, model=FakeModel([]))
    with pytest.raises(ValueError, match="runtime"):
        verifier_node({"task": "t"}, model=FakeModel([]))


def test_verifier_passes_and_runs_commands(workspace):
    verdict = {
        "passed": True,
        "reason": "all good",
        "checks": [{"name": "smoke", "passed": True, "detail": "ok"}],
        "recommended_next_instruction": "ship it",
    }
    model = FakeModel([AIMessage(content=json.dumps(verdict))])
    state = _graph_state(
        workspace,
        verification_commands=[f'"{sys.executable}" -c "print(\'ok\')"'],
        todos=[
            {"id": "t1", "content": "a", "status": "completed", "note": ""},
            {"id": "t2", "content": "b", "status": "in_progress", "note": ""},
        ],
        attempts=1,
    )

    update = verifier_node(state, model=model)

    assert update["passed"] is True
    assert update["attempts"] == 2
    (result,) = update["verification_results"]
    assert result["command"] == state["verification_commands"][0]
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "ok" in result["stdout"]
    assert result["stderr"] == ""
    assert update["verification_checks"] == [
        {"name": "smoke", "passed": True, "detail": "ok"}
    ]
    assert update["last_error"] == ""
    assert update["final_answer"] == "all good"
    assert all(todo["status"] == "completed" for todo in update["todos"])
    assert [tool.name for tool in model.bound_tools] == ["read_file", "grep"]
    system_message, human_message = model.calls[0]
    assert system_message.content == VERIFIER_PROMPT
    assert "demo task" in human_message.content


def test_verifier_parses_json_in_code_fence(workspace):
    verdict = {
        "passed": True,
        "reason": "ok",
        "checks": [],
        "recommended_next_instruction": "",
    }
    model = FakeModel([AIMessage(content=f"```json\n{json.dumps(verdict)}\n```")])

    update = verifier_node(_graph_state(workspace), model=model)

    assert update["passed"] is True
    assert update["last_error"] == ""


def test_verifier_failure_sets_error_and_blocks(workspace):
    verdict = {
        "passed": False,
        "reason": "tests broke",
        "checks": [{"name": "c1", "passed": False, "detail": "d"}],
        "recommended_next_instruction": "fix",
    }
    model = FakeModel([AIMessage(content=json.dumps(verdict))])
    state = _graph_state(
        workspace,
        verification_commands=[f'"{sys.executable}" -c "raise SystemExit(3)"'],
        todos=[{"id": "t1", "content": "a", "status": "in_progress", "note": ""}],
        attempts=1,
        max_attempts=3,
    )

    update = verifier_node(state, model=model)

    assert update["passed"] is False
    assert update["attempts"] == 2
    assert "tests broke" in update["last_error"]
    (result,) = update["verification_results"]
    assert result["ok"] is False
    assert result["exit_code"] == 3
    assert update["todos"][0]["status"] == "blocked"

    merged = dict(state)
    merged.update(update)
    assert verifier_route(merged) == "planner"


def test_verifier_invalid_json_counts_as_failure(workspace):
    model = FakeModel([AIMessage(content="I cannot decide.")])

    update = verifier_node(_graph_state(workspace), model=model)

    assert update["passed"] is False
    assert "valid JSON" in update["last_error"]
    assert update["verification_results"] == []
    assert update["attempts"] == 1


def test_verifier_route_branches():
    assert verifier_route({"passed": True}) == "final"
    assert verifier_route({"passed": False, "attempts": 3, "max_attempts": 3}) == "final"
    assert verifier_route({"passed": False, "attempts": 1, "max_attempts": 3}) == "planner"
    assert verifier_route({"passed": False, "attempts": 2}) == "planner"
    assert verifier_route({"passed": False, "attempts": 3}) == "final"
