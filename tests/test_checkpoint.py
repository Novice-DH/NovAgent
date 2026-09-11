"""core.checkpoint 检查点保存与恢复（light/strict/off、git 快照、resume）。"""

import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

import novagent.core.checkpoint as checkpoint_module
from novagent.core.checkpoint import (
    CHECKPOINT_FILE,
    EVENTS_FILE,
    RECOVERY_FILE,
    STATE_FILE,
    CheckpointManager,
    normalize_checkpoint_mode,
    resume_command,
)
from novagent.core.state import RuntimeState


def _manager(workspace, mode="light", task="demo task"):
    return CheckpointManager(
        RuntimeState(workspace=workspace, checkpoint_mode=mode), task=task
    )


def test_normalize_checkpoint_mode_falls_back_to_light():
    assert normalize_checkpoint_mode(None) == "light"
    assert normalize_checkpoint_mode("") == "light"
    assert normalize_checkpoint_mode("bogus") == "light"
    assert normalize_checkpoint_mode("light") == "light"
    assert normalize_checkpoint_mode("strict") == "strict"
    assert normalize_checkpoint_mode("off") == "off"


def test_light_save_writes_metadata_and_recovery(workspace):
    (workspace / "app.py").write_text("print('hi')", encoding="utf-8")
    manager = _manager(workspace)
    event = manager.save(
        {"task": "demo task", "attempts": 2},
        status="running",
        latest_node="planner",
    )
    assert event["type"] == "checkpoint_saved"
    assert event["node"] == "planner"
    assert event["mode"] == "light"
    assert event["latest_node"] == "planner"

    checkpoint = json.loads(
        (manager.root / CHECKPOINT_FILE).read_text(encoding="utf-8")
    )
    assert checkpoint["task"] == "demo task"
    assert checkpoint["status"] == "running"
    assert checkpoint["latest_node"] == "planner"
    assert checkpoint["attempts"] == 2
    assert checkpoint["workspace"] == str(workspace)
    assert checkpoint["git_commit"]
    assert checkpoint["git_error"] == ""
    assert checkpoint["workspace_manifest"]
    assert any(
        entry["path"] == "app.py" for entry in checkpoint["workspace_manifest"]
    )
    assert not (manager.root / STATE_FILE).exists()

    recovery = (manager.root / RECOVERY_FILE).read_text(encoding="utf-8")
    assert resume_command(workspace) in recovery
    assert "demo task" in recovery
    assert checkpoint["git_commit"] in recovery


def test_off_mode_writes_nothing(workspace):
    manager = _manager(workspace, mode="off")
    assert manager.save({"task": "t"}) is None
    assert not (workspace / ".novagent" / "checkpoints").exists()


def test_strict_mode_writes_state_and_appends_events(workspace):
    manager = _manager(workspace, mode="strict")
    manager.save(
        {"task": "t", "attempts": 0},
        event={"type": "tool_result", "name": "bash"},
    )
    manager.save(
        {"task": "t", "attempts": 1, "messages": []},
        event={"type": "node_update", "node": "verifier"},
    )
    assert (manager.root / STATE_FILE).exists()
    lines = (manager.root / EVENTS_FILE).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "tool_result"
    assert json.loads(lines[1])["node"] == "verifier"


def test_strict_save_without_event_does_not_touch_events_log(workspace):
    manager = _manager(workspace, mode="strict")
    manager.save({"task": "t"})
    assert (manager.root / STATE_FILE).exists()
    assert not (manager.root / EVENTS_FILE).exists()


def test_git_snapshot_restores_files_on_resume(workspace):
    target = workspace / "a.txt"
    target.write_text("v1", encoding="utf-8")
    manager = _manager(workspace)
    manager.save({"task": "t"}, status="running")
    target.write_text("v2", encoding="utf-8")

    runtime = RuntimeState(workspace=workspace, checkpoint_mode="light")
    inputs, resume_event = CheckpointManager.load_resume_inputs(
        runtime, max_attempts=5
    )
    assert target.read_text(encoding="utf-8") == "v1"
    assert inputs["task"] == "demo task"
    assert inputs["attempts"] == 0
    assert inputs["max_attempts"] == 5
    assert inputs["runtime"].workspace == workspace.resolve()
    assert resume_event["type"] == "resumed"
    assert resume_event["attempts"] == 0


def test_strict_resume_restores_messages(workspace):
    manager = _manager(workspace, mode="strict")
    manager.save(
        {"task": "t", "messages": [HumanMessage(content="hello")], "attempts": 1}
    )
    runtime = RuntimeState(workspace=workspace, checkpoint_mode="strict")
    inputs, _ = CheckpointManager.load_resume_inputs(runtime)
    (message,) = inputs["messages"]
    assert message.type == "human"
    assert message.content == "hello"
    assert inputs["attempts"] == 1


def test_load_resume_inputs_prefers_explicit_task(workspace):
    manager = _manager(workspace)
    manager.save({"task": "from-checkpoint"})
    runtime = RuntimeState(workspace=workspace, checkpoint_mode="light")
    inputs, _ = CheckpointManager.load_resume_inputs(runtime, task="override")
    assert inputs["task"] == "override"


def test_load_resume_inputs_without_checkpoint_raises(workspace):
    with pytest.raises(FileNotFoundError):
        CheckpointManager.load_resume_inputs(_manager(workspace))


def test_git_failure_is_degraded_not_raised(workspace, monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("git executable not found")

    monkeypatch.setattr(checkpoint_module, "_run_git", boom)
    manager = _manager(workspace)
    event = manager.save({"task": "t"}, status="running", latest_node="planner")
    assert event is not None
    checkpoint = json.loads(
        (manager.root / CHECKPOINT_FILE).read_text(encoding="utf-8")
    )
    assert checkpoint["git_commit"] is None
    assert "git unavailable" in checkpoint["git_error"]


def test_resume_command_targets_cli(tmp_path):
    ws = tmp_path / "ws"
    command = resume_command(ws)
    assert command.startswith("novagent run --resume ")
    assert command.endswith(str(ws.absolute()))


def test_strict_resume_keeps_explicit_task_and_max_attempts(workspace):
    """strict 恢复只取 messages：显式 task 与 max_attempts 不被旧状态覆盖。"""
    manager = _manager(workspace, mode="strict", task="old task")
    manager.save(
        {
            "task": "old task",
            "max_attempts": 3,
            "attempts": 2,
            "messages": [HumanMessage(content="hello")],
            "todos": [{"id": "t1", "status": "completed"}],
        },
        status="running",
        latest_node="verifier",
    )
    runtime = RuntimeState(workspace=workspace, checkpoint_mode="strict")
    inputs, _ = CheckpointManager.load_resume_inputs(
        runtime, task="new task", max_attempts=7
    )
    assert inputs["task"] == "new task"
    assert inputs["max_attempts"] == 7
    assert inputs["attempts"] == 2
    assert [m.content for m in inputs["messages"]] == ["hello"]
    assert "todos" not in inputs

    runtime2 = RuntimeState(workspace=workspace, checkpoint_mode="strict")
    inputs2, _ = CheckpointManager.load_resume_inputs(runtime2)
    assert inputs2["task"] == "old task"
    assert inputs2["max_attempts"] == 3
