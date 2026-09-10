"""core.agent 工作流事件流的离线行为（FakeModel，不发起网络请求）。"""

import json
import sys

from langchain_core.messages import AIMessage

from novagent.core.agent import stream_agent_events
from novagent.core.state import RuntimeState


class FakeModel:
    """按序返回预设响应并记录调用与绑定工具。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.bindings = []

    def bind_tools(self, tools):
        self.bindings.append([tool.name for tool in tools])
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        return self.responses.pop(0)


def _tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _plan_args(commands):
    return {
        "plan_summary": "plan",
        "todos": [{"id": "t1", "content": "step"}],
        "acceptance_criteria": ["result exists"],
        "verification_commands": commands,
    }


PASS_JSON = json.dumps(
    {
        "passed": True,
        "reason": "all good",
        "checks": [],
        "recommended_next_instruction": "",
    }
)
FAIL_JSON = json.dumps(
    {
        "passed": False,
        "reason": "tests broke",
        "checks": [],
        "recommended_next_instruction": "fix",
    }
)


def _collect_events(workspace, model, **kwargs):
    return list(
        stream_agent_events("demo task", workspace=workspace, model=model, **kwargs)
    )


def test_pass_path_emits_node_and_actor_events(workspace):
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args([ok_command]), "c1"),
            _tool_call(
                "write_file", {"file_path": "result.txt", "content": "done"}, "c2"
            ),
            AIMessage(content="All steps done."),
            AIMessage(content=PASS_JSON),
        ]
    )

    events = _collect_events(workspace, model)

    types_and_nodes = [(event["type"], event.get("node")) for event in events]
    assert ("node_output", "planner") in types_and_nodes
    assert ("node_output", "verifier") in types_and_nodes
    assert types_and_nodes[-1] == ("node_output", "final")
    assert types_and_nodes.index(("node_output", "planner")) < types_and_nodes.index(
        ("ai_message", "actor")
    )
    actor_events = [event for event in events if event.get("node") == "actor"]
    assert [event["type"] for event in actor_events] == [
        "ai_message",
        "tool_call",
        "tool_result",
        "ai_message",
        "final_answer",
    ]

    planner_event = events[0]
    assert planner_event["type"] == "node_output"
    assert planner_event["plan_summary"] == "plan"
    assert planner_event["todos"] == [
        {"id": "t1", "content": "step", "status": "pending", "note": ""}
    ]
    assert ok_command in planner_event["verification_commands"]

    verifier_event = next(
        event for event in events if event["type"] == "node_output" and event["node"] == "verifier"
    )
    assert verifier_event["passed"] is True
    assert verifier_event["reason"] == "all good"
    (result,) = verifier_event["verification_results"]
    assert result["ok"] is True and result["exit_code"] == 0

    final_event = events[-1]
    assert final_event["final_answer"].startswith("Task completed")

    assert len(model.calls) == 4
    assert (workspace / "result.txt").read_text(encoding="utf-8") == "done"


def test_failure_loop_emits_two_planner_outputs(workspace):
    bad_command = f'"{sys.executable}" -c "raise SystemExit(1)"'
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args([bad_command]), "c1"),
            AIMessage(content="Tried the step."),
            AIMessage(content=FAIL_JSON),
            _tool_call("todo_write", _plan_args([ok_command]), "c2"),
            AIMessage(content="Fixed."),
            AIMessage(content=PASS_JSON),
        ]
    )

    events = _collect_events(workspace, model)

    planner_events = [
        event for event in events if event["type"] == "node_output" and event["node"] == "planner"
    ]
    assert len(planner_events) == 2
    failed_verifier = next(
        event
        for event in events
        if event["type"] == "node_output"
        and event["node"] == "verifier"
        and not event["passed"]
    )
    assert failed_verifier["reason"] == "tests broke"
    (result,) = failed_verifier["verification_results"]
    assert result["ok"] is False and result["exit_code"] == 1
    final_event = events[-1]
    assert final_event["final_answer"].startswith("Task completed")
    assert len(model.calls) == 6


def test_exhausted_budget_goes_straight_to_final(workspace):
    bad_command = f'"{sys.executable}" -c "raise SystemExit(1)"'
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args([bad_command]), "c1"),
            AIMessage(content="Tried the step."),
            AIMessage(content=FAIL_JSON),
        ]
    )

    events = _collect_events(workspace, model, max_attempts=1)

    planner_events = [
        event for event in events if event["type"] == "node_output" and event["node"] == "planner"
    ]
    assert len(planner_events) == 1
    verifier_event = next(
        event for event in events if event["type"] == "node_output" and event["node"] == "verifier"
    )
    assert verifier_event["passed"] is False
    final_event = events[-1]
    assert final_event["final_answer"].startswith("Task failed")
    assert "tests broke" in final_event["final_answer"]
    assert len(model.calls) == 3


def test_events_carry_node_field_and_actor_tools_run_in_workspace(workspace):
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args([ok_command]), "c1"),
            _tool_call("bash", {"command": "echo from-actor"}, "c2"),
            AIMessage(content="done"),
            AIMessage(content=PASS_JSON),
        ]
    )

    events = _collect_events(workspace, model)

    assert all("node" in event for event in events)
    tool_events = [event for event in events if event["type"] == "tool_result"]
    assert tool_events and "from-actor" in tool_events[0]["result"]
    assert [binding[0] for binding in model.bindings] == [
        "todo_write",
        "read_file",
        "read_file",
    ]
