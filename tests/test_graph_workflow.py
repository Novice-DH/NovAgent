"""graph.workflow 组装与离线端到端行为（FakeModel，不发起网络请求）。"""

import json
import sys

from langchain_core.messages import AIMessage, HumanMessage

from novagent.core.state import RuntimeState
from novagent.graph import nodes as graph_nodes
from novagent.graph.nodes import final_node
from novagent.graph.workflow import build_workflow
from novagent.prompts import stage2, stage3


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


def test_builds_three_node_graph():
    graph = build_workflow()

    assert set(graph.nodes) == {"planner", "verifier", "final", "__start__"}
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("__start__", "planner") in edges
    assert ("planner", "verifier") in edges
    assert ("final", "__end__") in edges


def test_end_to_end_passes_first_try(workspace):
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    fake = FakeModel(
        [
            # planner 轮 1：发布计划
            _tool_call("todo_write", _plan_args([ok_command]), "c1"),
            # planner 轮 2：委托 codeAgent（受托内部：写文件 → 总结）
            _tool_call(
                "call_code_agent",
                {"instruction": "write the result file"},
                "c2",
            ),
            _tool_call(
                "write_file", {"file_path": "result.txt", "content": "done"}, "k1"
            ),
            AIMessage(content="Wrote result.txt."),
            # planner 轮 3：supervisor 总结，纯文本结束
            AIMessage(content="Plan executed, result written."),
            # verifier
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
    assert final["code_agent_summary"] == "Wrote result.txt."
    assert final["agent_handoffs"] == [
        {
            "from_agent": "planner",
            "to_agent": "codeAgent",
            "instruction": "write the result file",
            "result": "Wrote result.txt.",
        }
    ]
    assert (workspace / "result.txt").read_text(encoding="utf-8") == "done"
    assert len(fake.calls) == 6
    assert fake.bindings[0] == ["todo_write", "call_search_agent", "call_code_agent"]
    assert fake.bindings[1][0] == "read_file"
    assert fake.bindings[2] == ["read_file", "grep"]


def test_end_to_end_retries_after_failure(workspace):
    bad_command = f'"{sys.executable}" -c "raise SystemExit(1)"'
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    fake = FakeModel(
        [
            # 第一轮 planner：发布计划后直接结束
            _tool_call("todo_write", _plan_args([bad_command]), "c1"),
            AIMessage(content="Plan ready."),
            AIMessage(content=FAIL_JSON),
            # 第二轮 planner：修订计划后直接结束
            _tool_call("todo_write", _plan_args([ok_command]), "c2"),
            AIMessage(content="Revised plan."),
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


def test_stage3_prompts_and_node_imports():
    assert stage3.PLANNER_PROMPT.startswith(
        "You are the planner/supervisor node in novagent stage 3."
    )
    assert "CallSearchAgentTool" in stage3.PLANNER_PROMPT
    assert stage2.VERIFIER_PROMPT
    assert stage2.FINAL_PROMPT
    assert not hasattr(stage2, "PLANNER_PROMPT")
    assert not hasattr(stage2, "ACTOR_PROMPT")
    assert graph_nodes.PLANNER_PROMPT is stage3.PLANNER_PROMPT
    assert graph_nodes.VERIFIER_PROMPT is stage2.VERIFIER_PROMPT
    assert not hasattr(graph_nodes, "actor_node")
