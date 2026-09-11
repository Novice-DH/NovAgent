"""core.agent 工作流事件流的离线行为（FakeModel，不发起网络请求）。"""

import json
import sys

import pytest
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


def test_pass_path_emits_planner_coordination_events(workspace):
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    model = FakeModel(
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
            # planner 轮 3：supervisor 总结
            AIMessage(content="Plan executed, result written."),
            # verifier
            AIMessage(content=PASS_JSON),
        ]
    )

    events = _collect_events(workspace, model)

    types_and_nodes = [(event["type"], event.get("node")) for event in events]
    assert ("node_output", "planner") in types_and_nodes
    assert ("node_output", "verifier") in types_and_nodes
    assert types_and_nodes[-1] == ("node_output", "final")
    # planner 内部事件带 node="planner"，在 planner 节点执行期间流出，
    # 因此先于 planner 完成时才产生的 node_output 事件
    assert types_and_nodes.index(("ai_message", "planner")) < types_and_nodes.index(
        ("node_output", "planner")
    )
    assert ("handoff", "planner") in types_and_nodes
    planner_custom = [event for event in events if event.get("node") == "planner"]
    # 首条 planner 内部事件为分层记忆事件，先于任何 ai_message；
    # 受托 codeAgent 的 memory 事件同样透传（身份在 memory.working_memory.node）。
    assert [event["type"] for event in planner_custom][0] == "memory"
    assert planner_custom[0]["memory"]["working_memory"]["node"] == "planner"
    memory_events = [
        event for event in planner_custom if event.get("type") == "memory"
    ]
    assert {event["memory"]["working_memory"]["node"] for event in memory_events} == {
        "planner",
        "codeAgent",
    }
    first_ai_index = [event["type"] for event in planner_custom].index("ai_message")
    assert first_ai_index == 1
    assert "handoff" in [event["type"] for event in planner_custom]
    # 受托 codeAgent 的内部事件也经 planner writer 透传
    assert ("tool_call", "planner") in types_and_nodes
    assert any(
        event.get("type") == "tool_call" and event.get("name") == "write_file"
        for event in planner_custom
    )

    planner_event = next(
        event for event in events if event["type"] == "node_output" and event["node"] == "planner"
    )
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

    assert len(model.calls) == 6
    assert (workspace / "result.txt").read_text(encoding="utf-8") == "done"


def test_failure_loop_emits_two_planner_outputs(workspace):
    bad_command = f'"{sys.executable}" -c "raise SystemExit(1)"'
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args([bad_command]), "c1"),
            AIMessage(content="Plan ready."),
            AIMessage(content=FAIL_JSON),
            _tool_call("todo_write", _plan_args([ok_command]), "c2"),
            AIMessage(content="Revised plan."),
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
            AIMessage(content="Plan ready."),
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


def test_events_carry_node_field_and_delegated_tools_run_in_workspace(workspace):
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args([ok_command]), "c1"),
            _tool_call(
                "call_code_agent",
                {"instruction": "run a check"},
                "c2",
            ),
            _tool_call("bash", {"command": "echo from-code-agent"}, "k1"),
            AIMessage(content="check done"),
            AIMessage(content="supervisor summary"),
            AIMessage(content=PASS_JSON),
        ]
    )

    events = _collect_events(workspace, model)

    assert all("node" in event for event in events)
    tool_events = [event for event in events if event["type"] == "tool_result"]
    assert tool_events and any("from-code-agent" in str(e["result"]) for e in tool_events)
    assert [binding[0] for binding in model.bindings] == [
        "todo_write",
        "read_file",
        "read_file",
    ]


def _pass_path_model(ok_command):
    return FakeModel(
        [
            _tool_call("todo_write", _plan_args([ok_command]), "c1"),
            _tool_call(
                "call_code_agent", {"instruction": "write the result file"}, "c2"
            ),
            _tool_call(
                "write_file", {"file_path": "result.txt", "content": "done"}, "k1"
            ),
            AIMessage(content="Wrote result.txt."),
            AIMessage(content="Plan executed, result written."),
            AIMessage(content=PASS_JSON),
        ]
    )


def test_checkpoint_and_trace_integrated_in_stream(workspace):
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    events = _collect_events(
        workspace,
        _pass_path_model(ok_command),
        checkpoint_mode="light",
        trace_mode="on",
    )

    checkpoint_events = [
        event for event in events if event["type"] == "checkpoint_saved"
    ]
    assert checkpoint_events
    assert all("node" in event for event in events)
    # 每个节点的 checkpoint_saved 先于该节点的 node_output 产出
    final_index = events.index(
        next(
            event
            for event in events
            if event["type"] == "node_output" and event["node"] == "final"
        )
    )
    assert events[-1]["type"] == "node_output"
    assert events[-1]["node"] == "final"
    assert final_index == len(events) - 1

    checkpoint = json.loads(
        (workspace / ".novagent" / "checkpoints" / "checkpoint.json")
        .read_text(encoding="utf-8")
    )
    assert checkpoint["status"] == "finished"
    assert checkpoint["latest_node"] == "final"
    assert checkpoint["task"] == "demo task"
    assert (workspace / ".novagent" / "checkpoints" / "RECOVERY.md").exists()

    (trace_dir,) = (workspace / ".novagent" / "traces").iterdir()
    trace = json.loads(
        (trace_dir / "trace.json").read_text(encoding="utf-8")
    )
    assert trace["status"] == "finished"
    assert trace["checkpoint_count"] >= 1
    assert trace["node_visits"].get("planner") == 1
    assert trace["node_visits"].get("verifier") == 1
    assert trace["node_visits"].get("final") == 1


def test_keyboard_interrupt_saves_interrupted_checkpoint(workspace):
    class InterruptedModel(FakeModel):
        def invoke(self, messages):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        list(
            stream_agent_events(
                "demo task",
                workspace=workspace,
                model=InterruptedModel([]),
                checkpoint_mode="light",
                trace_mode="on",
            )
        )

    checkpoint = json.loads(
        (workspace / ".novagent" / "checkpoints" / "checkpoint.json")
        .read_text(encoding="utf-8")
    )
    assert checkpoint["status"] == "interrupted"
    (trace_dir,) = (workspace / ".novagent" / "traces").iterdir()
    trace = json.loads((trace_dir / "trace.json").read_text(encoding="utf-8"))
    assert trace["status"] == "interrupted"


def test_approval_config_flows_through_delegated_code_agent(workspace):
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args([]), "c1"),
            _tool_call("call_code_agent", {"instruction": "install deps"}, "c2"),
            _tool_call("bash", {"command": "pip install demo-pkg"}, "k1"),
            AIMessage(content="blocked by approval policy"),
            AIMessage(content="supervisor summary"),
            AIMessage(content=PASS_JSON),
        ]
    )

    events = _collect_events(workspace, model, approval_mode="deny")

    bash_results = [
        event
        for event in events
        if event["type"] == "tool_result" and event.get("name") == "bash"
    ]
    assert bash_results
    assert "human approval required" in str(bash_results[0]["result"])
    assert "Python package installation" in str(bash_results[0]["result"])
    # 拒绝路径不得执行命令：事件里不出现任何安装成功输出
    assert all(
        "Successfully installed" not in str(event.get("result", ""))
        for event in events
    )


def test_resume_from_checkpoint_reruns_with_restored_inputs(workspace):
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    first = list(
        stream_agent_events(
            "demo task",
            workspace=workspace,
            model=_pass_path_model(ok_command),
            checkpoint_mode="light",
            trace_mode="off",
        )
    )
    assert first

    class RecordingModel(FakeModel):
        def invoke(self, messages):
            self.calls.append(list(messages))
            return AIMessage(content=PASS_JSON)

    resumed_model = RecordingModel([])
    events = list(
        stream_agent_events(
            None,
            workspace=workspace,
            model=resumed_model,
            checkpoint_mode="light",
            trace_mode="off",
            resume_workspace=workspace,
        )
    )

    resumed_events = [
        event for event in events if event["type"] == "resumed"
    ]
    assert resumed_events
    assert resumed_events[0]["task"] == "demo task"
    assert resumed_events[0]["attempts"] == 1
    # 恢复输入携带检查点中的 attempts（验证过一轮）
    assert events[-1]["type"] == "node_output"
    checkpoint = json.loads(
        (workspace / ".novagent" / "checkpoints" / "checkpoint.json")
        .read_text(encoding="utf-8")
    )
    assert checkpoint["status"] == "finished"


def test_consumer_close_persists_interrupted_state(workspace):
    """消费端中断（生成器被 close）同样落盘 interrupted 现场。"""
    ok_command = f'"{sys.executable}" -c "print(\'ok\')"'
    gen = stream_agent_events(
        "demo task",
        workspace=workspace,
        model=_pass_path_model(ok_command),
        checkpoint_mode="light",
        trace_mode="on",
    )
    next(gen)  # 只消费启动检查点事件即放弃
    gen.close()

    checkpoint = json.loads(
        (workspace / ".novagent" / "checkpoints" / "checkpoint.json")
        .read_text(encoding="utf-8")
    )
    assert checkpoint["status"] == "interrupted"
    (trace_dir,) = (workspace / ".novagent" / "traces").iterdir()
    trace = json.loads((trace_dir / "trace.json").read_text(encoding="utf-8"))
    assert trace["status"] == "interrupted"
