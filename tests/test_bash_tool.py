"""bash 工具的执行、工作目录与超时行为。"""

import sys
import time

import pytest


def test_returns_exit_code_and_output(by_name):
    output = by_name["bash"].invoke({"command": "echo hello-shell"})
    assert "exit_code: 0" in output
    assert "hello-shell" in output


def test_runs_inside_workspace(by_name, workspace):
    by_name["bash"].invoke({"command": "echo marker > marker.txt"})
    assert (workspace / "marker.txt").exists()


def test_nonzero_exit_code_is_reported_without_raising(by_name):
    output = by_name["bash"].invoke({"command": "exit 3"})
    assert "exit_code: 3" in output


def test_timeout_kills_process_tree_within_time_bound(by_name):
    command = f'"{sys.executable}" -c "import time; time.sleep(30)"'
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out"):
        by_name["bash"].invoke({"command": command, "timeout_seconds": 2})
    elapsed = time.monotonic() - start
    # 孙进程持有时 shell=True 只杀 shell 会让 communicate 阻塞到其自然
    # 退出（30s）；进程树终止必须把总耗时压在远小于 sleep 时长以内。
    assert elapsed < 8, f"timeout returned after {elapsed:.1f}s"


def test_timeout_must_be_positive(by_name):
    with pytest.raises(ValueError, match="timeout_seconds"):
        by_name["bash"].invoke({"command": "echo hi", "timeout_seconds": 0})


def test_risky_command_with_auto_mode_carries_approval_markers(state, monkeypatch):
    from novagent.core.state import RuntimeState
    from novagent.tools.bash_tool import create_bash_tool

    monkeypatch.setattr(
        "novagent.tools.bash_tool.execute_command",
        lambda command, cwd, timeout_seconds=30.0: (0, "ok output", ""),
    )
    auto_state = RuntimeState(workspace=state.workspace, approval_mode="auto")
    output = create_bash_tool(auto_state).invoke({"command": "pip install flask"})
    assert "requires_approval: True" in output
    assert "approved: True" in output
    assert "exit_code: 0" in output


def test_default_state_denies_risky_commands_without_execution(state, monkeypatch):
    from novagent.core.state import RuntimeState
    from novagent.tools.bash_tool import create_bash_tool

    def fail(*args, **kwargs):
        raise AssertionError("command must not be executed without approval")

    monkeypatch.setattr("novagent.tools.bash_tool.execute_command", fail)
    output = create_bash_tool(state).invoke({"command": "npm install"})
    assert "human approval required" in output
