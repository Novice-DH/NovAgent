"""graph.workflow 组装与离线端到端行为（FakeModel，不发起网络请求）。"""

import json
import sys

from langchain_core.messages import AIMessage, HumanMessage

from novagent.core.agent import ACTOR_PROMPT as STAGE1_ACTOR_PROMPT
from novagent.core.state import RuntimeState
from novagent.graph import nodes as graph_nodes
from novagent.graph.nodes import final_node
from novagent.graph.workflow import build_workflow
from novagent.prompts import stage2


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
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
    )


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


def _initial_state(workspace):
    return {
        "task": "demo task",
        "runtime": RuntimeState(workspace=workspace),
        "max_attempts": 3,
    }


def test_builds_four_node_graph():
    graph = build_workflow()

    assert {"planner", "actor", "verifier", "final"} <= set(graph.nodes)
    assert not (set(graph.nodes) - {"planner", "actor", "verifier", "final", "__start__"})
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("__start__", "planner") in edges
    assert ("planner", "actor") in edges
    assert ("actor", "verifier") in edges
    assert ("final", "__end__") in edges


def test_end_to_end_passes_first_try(workspace):
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    fake = FakeModel(
        [
            _tool_call("todo_write", _plan_args([ok_command]), "c1"),
            _tool_call(
                "write_file", {"file_path": "result.txt", "content": "done"}, "c2"
            ),
            AIMessage(content="All steps done."),
            AIMessage(content=PASS_JSON),
        ]
    )

    final = build_workflow(model=fake).invoke(_initial_state(workspace))

    assert final["passed"] is True
    assert final["attempts"] == 1
    assert "completed" in final["final_answer"]
    assert "1" in final["final_answer"]
    assert "all good" in final["final_answer"]
    assert all(todo["status"] == "completed" for todo in final["todos"])
    assert (workspace / "result.txt").read_text(encoding="utf-8") == "done"
    assert len(fake.calls) == 4
    assert [binding[0] for binding in fake.bindings] == [
        "todo_write",
        "read_file",
        "read_file",
    ]


def test_end_to_end_retries_after_failure(workspace):
    bad_command = f'"{sys.executable}" -c "raise SystemExit(1)"'
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    fake = FakeModel(
        [
            _tool_call("todo_write", _plan_args([bad_command]), "c1"),
            AIMessage(content="Tried the step."),
            AIMessage(content=FAIL_JSON),
            _tool_call("todo_write", _plan_args([ok_command]), "c2"),
            AIMessage(content="Fixed."),
            AIMessage(content=PASS_JSON),
        ]
    )

    final = build_workflow(model=fake).invoke(_initial_state(workspace))

    assert final["passed"] is True
    assert final["attempts"] == 2
    assert len(fake.calls) == 6
    revise_call = fake.calls[3]
    assert isinstance(revise_call[1], HumanMessage)
    assert "tests broke" in revise_call[1].content


def test_final_node_formats_success_and_failure():
    update = final_node(
        {"passed": True, "attempts": 1, "final_answer": "all good"}
    )
    assert update["final_answer"] == "Task completed in 1 attempt(s). all good"
    assert "passed" not in update

    update = final_node({"passed": False, "attempts": 3, "last_error": "boom"})
    assert update["final_answer"] == (
        "Task failed after 3 attempt(s).\nLast error: boom"
    )
    assert "passed" not in update


def test_stage2_prompts_and_node_imports():
    assert stage2.PLANNER_PROMPT
    assert stage2.ACTOR_PROMPT
    assert stage2.VERIFIER_PROMPT
    assert stage2.FINAL_PROMPT
    assert "todo_write" in stage2.PLANNER_PROMPT
    assert stage2.ACTOR_PROMPT.startswith(
        "You are the actor node in novagent's LangGraph workflow."
    )
    assert '"passed"' in stage2.VERIFIER_PROMPT
    assert graph_nodes.PLANNER_PROMPT is stage2.PLANNER_PROMPT
    assert graph_nodes.VERIFIER_PROMPT is stage2.VERIFIER_PROMPT
    assert graph_nodes.ACTOR_PROMPT is stage2.ACTOR_PROMPT


def test_stage1_actor_prompt_unchanged():
    assert STAGE1_ACTOR_PROMPT.startswith(
        "You are the actor node in novagent's ReAct workflow."
    )
    assert STAGE1_ACTOR_PROMPT is not stage2.ACTOR_PROMPT
