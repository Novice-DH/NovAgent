"""core.trace 链路追踪：统计、时间线截断与 off 模式。"""

import json

from novagent.core.state import RuntimeState
from novagent.core.trace import TraceRecorder, normalize_trace_mode, tool_result_failed


def _recorder(workspace, mode="on", task="demo task"):
    runtime = RuntimeState(workspace=workspace, trace_mode=mode)
    return TraceRecorder(runtime, task=task), runtime


def test_normalize_trace_mode_falls_back_to_on():
    assert normalize_trace_mode(None) == "on"
    assert normalize_trace_mode("weird") == "on"
    assert normalize_trace_mode("on") == "on"
    assert normalize_trace_mode("off") == "off"


def test_failed_tool_result_rule():
    assert tool_result_failed({"type": "tool_result", "result": "Error: unknown tool x"})
    assert tool_result_failed({"type": "tool_result", "result": "exit_code: 3"})
    assert not tool_result_failed(
        {"type": "tool_result", "result": "exit_code: 0\nstdout: ok"}
    )
    assert not tool_result_failed(
        {"type": "tool_result", "result": '{"requires_approval": true}'}
    )
    assert not tool_result_failed({"type": "tool_call", "name": "bash"})
    assert not tool_result_failed({"type": "tool_result", "result": ""})


def test_trace_records_stats_and_files(workspace):
    recorder, runtime = _recorder(workspace)
    recorder.start({"task": "demo task"})
    runtime.approval_log.append(
        {"command": "pip install x", "mode": "auto", "approved": True}
    )
    recorder.record_custom_event({"type": "tool_call", "name": "bash"})
    recorder.record_custom_event(
        {"type": "tool_result", "name": "bash", "result": "exit_code: 1\nstderr: boom"}
    )
    recorder.record_custom_event({"type": "tool_call", "name": "write_file"})
    recorder.record_custom_event(
        {"type": "tool_result", "name": "write_file", "result": "ok"}
    )
    recorder.record_custom_event(
        {"type": "handoff", "from": "planner", "to": "codeAgent"}
    )
    recorder.record_custom_event({"type": "checkpoint_saved", "status": "running"})
    recorder.record_graph_update({"planner": {"todos": []}})
    recorder.record_graph_update({"verifier": {"passed": True}})
    recorder.record_graph_update({"planner": {"todos": []}})

    recorder.end(status="finished", latest_node="final", final_state={})

    assert (recorder.root / "trace.json").exists()
    assert (recorder.root / "events.jsonl").exists()
    assert (recorder.root / "timeline.md").exists()

    trace = json.loads(
        (recorder.root / "trace.json").read_text(encoding="utf-8")
    )
    assert trace["trace_id"] == recorder.trace_id
    assert trace["task"] == "demo task"
    assert trace["status"] == "finished"
    assert trace["duration_ms"] >= 0
    assert trace["node_visits"] == {"planner": 2, "verifier": 1}
    assert trace["tool_calls"] == 2
    assert trace["failed_tool_calls"] == 1
    assert trace["handoff_count"] == 1
    assert trace["checkpoint_count"] == 1
    assert trace["approval_count"] == 1
    assert trace["timeline_omitted"] == 0
    assert len(trace["timeline_head"]) <= 20
    assert len(trace["timeline_tail"]) <= 80
    # 行数不足 20 时全部落在 head；head+tail 覆盖首尾事件
    assert any("run_start" in line for line in trace["timeline_head"])
    all_lines = trace["timeline_head"] + trace["timeline_tail"]
    assert any("run_end" in line for line in all_lines)

    events = [
        json.loads(line)
        for line in (recorder.root / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert events[0]["event"]["type"] == "run_start"
    assert any(item["event"]["type"] == "handoff" for item in events)

    timeline_md = (recorder.root / "timeline.md").read_text(encoding="utf-8")
    assert "run_start" in timeline_md
    assert "handoff" in timeline_md


def test_trace_id_generated_once_and_reused(workspace):
    recorder, runtime = _recorder(workspace)
    assert recorder.trace_id
    # 首个 recorder 生成并回写 trace_id；后续 recorder 复用同一标识
    assert runtime.trace_id == recorder.trace_id
    again = TraceRecorder(runtime, task="demo task")
    assert again.trace_id == recorder.trace_id


def test_timeline_head_tail_truncation(workspace):
    recorder, _ = _recorder(workspace)
    recorder.start({})
    for index in range(150):
        recorder.record_custom_event({"type": "tool_call", "name": f"t{index}"})
    recorder.end(status="finished")

    trace = json.loads(
        (recorder.root / "trace.json").read_text(encoding="utf-8")
    )
    # run_start + 150 条 + run_end = 152 行；head 20 + tail 80，省略 52 行
    assert len(trace["timeline_head"]) == 20
    assert len(trace["timeline_tail"]) == 80
    assert trace["timeline_omitted"] == 52


def test_off_mode_is_noop(workspace):
    recorder, _ = _recorder(workspace, mode="off")
    recorder.start({})
    recorder.record_custom_event({"type": "tool_call", "name": "bash"})
    recorder.record_graph_update({"planner": {}})
    recorder.end(status="finished", latest_node="final")
    assert recorder.tool_calls == 0
    assert recorder.timeline == []
    assert not (workspace / ".novagent" / "traces").exists()
