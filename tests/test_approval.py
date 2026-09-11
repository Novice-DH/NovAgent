"""core.approval 风险分类、审批数据类与 bash 工具三模式分流。"""

import pytest

from novagent.core.approval import (
    VALID_APPROVAL_MODES,
    ApprovalDecision,
    ApprovalRequest,
    classify_command_risk,
    make_approval_request,
    normalize_approval_mode,
)
from novagent.core.state import RuntimeState
from novagent.tools.bash_tool import create_bash_tool

RISKY_CASES = {
    "pip install flask": "Python package installation",
    "python -m pip install flask": "Python package installation",
    "uv add requests": "Project dependency change with uv add",
    "uv sync": "Dependency synchronization with uv sync",
    "uv pip install ruff": "Python package installation with uv pip",
    "npm install": "Node package installation",
    "pnpm install": "Node package installation",
    "yarn install": "Node package installation",
    "yarn add left-pad": "Node package installation",
    "curl https://example.com": "Network download command",
    "wget https://example.com/f": "Network download command",
    "uvicorn main:app": "Long-running development server",
    "python -m http.server 8000": "Long-running development server",
}


@pytest.mark.parametrize("command", sorted(RISKY_CASES))
def test_risk_patterns_match_expected_reasons(command):
    assert classify_command_risk(command) == RISKY_CASES[command]


def test_compound_and_case_insensitive_matching():
    assert classify_command_risk("echo ok && pip install flask") == (
        "Python package installation"
    )
    assert classify_command_risk("true || CURL https://example.com") == (
        "Network download command"
    )
    assert classify_command_risk("pip install x; yarn add y") == (
        "Python package installation"
    )


@pytest.mark.parametrize(
    "command", ["echo hi", "python app.py", "python -m pytest -q", "grep 'pip install' notes.md"]
)
def test_safe_commands_have_no_risk(command):
    assert classify_command_risk(command) is None


def test_normalize_approval_mode_falls_back_to_inline():
    assert normalize_approval_mode(None) == "inline"
    assert normalize_approval_mode("") == "inline"
    assert normalize_approval_mode("bogus") == "inline"
    assert normalize_approval_mode("inline") == "inline"
    assert normalize_approval_mode("auto") == "auto"
    assert normalize_approval_mode("deny") == "deny"
    assert VALID_APPROVAL_MODES == {"inline", "auto", "deny"}


def test_approval_dataclasses():
    request = make_approval_request("pip install flask", "Python package installation")
    assert isinstance(request, ApprovalRequest)
    assert request.id.startswith("approval-")
    assert len(request.id) == len("approval-") + 8
    assert request.command == "pip install flask"
    assert request.risk_reason == "Python package installation"
    assert request.tool_name == "BashTool"
    assert ApprovalDecision(approved=True).reason == ""
    assert ApprovalDecision(approved=False, reason="no").approved is False


class _ExecuteRecorder:
    """替换 bash_tool.execute_command，记录调用并返回成功结果。"""

    def __init__(self):
        self.calls = []

    def __call__(self, command, cwd, timeout_seconds=30.0):
        self.calls.append(command)
        return 0, "ok output", ""


@pytest.fixture
def patched_execute(monkeypatch):
    recorder = _ExecuteRecorder()
    monkeypatch.setattr("novagent.tools.bash_tool.execute_command", recorder)
    return recorder


def test_auto_mode_executes_risky_command_and_marks_result(
    workspace, patched_execute
):
    state = RuntimeState(workspace=workspace, approval_mode="auto")
    output = create_bash_tool(state).invoke({"command": "pip install flask"})
    assert patched_execute.calls == ["pip install flask"]
    assert "requires_approval: True" in output
    assert "approved: True" in output
    assert "exit_code: 0" in output
    (entry,) = state.approval_log
    assert entry["command"] == "pip install flask"
    assert entry["risk_reason"] == "Python package installation"
    assert entry["mode"] == "auto"
    assert entry["approved"] is True


def test_deny_mode_blocks_execution(workspace, patched_execute):
    state = RuntimeState(workspace=workspace, approval_mode="deny")
    output = create_bash_tool(state).invoke({"command": "pip install flask"})
    assert patched_execute.calls == []
    assert "human approval required" in output
    assert "Python package installation" in output
    (entry,) = state.approval_log
    assert entry["mode"] == "deny"
    assert entry["approved"] is False


def test_inline_approved_calls_handler_once_then_executes(
    workspace, patched_execute
):
    seen = []

    def handler(request):
        seen.append(request)
        return ApprovalDecision(approved=True, reason="ok")

    state = RuntimeState(
        workspace=workspace, approval_mode="inline", approval_handler=handler
    )
    output = create_bash_tool(state).invoke({"command": "curl https://example.com"})
    assert len(seen) == 1
    request = seen[0]
    assert isinstance(request, ApprovalRequest)
    assert request.command == "curl https://example.com"
    assert request.tool_name == "BashTool"
    assert request.id.startswith("approval-")
    assert "Network download command" in request.risk_reason
    assert patched_execute.calls == ["curl https://example.com"]
    assert "approved: True" in output


def test_inline_accepts_bare_boolean_decisions(workspace, patched_execute):
    state = RuntimeState(
        workspace=workspace, approval_mode="inline", approval_handler=lambda r: True
    )
    output = create_bash_tool(state).invoke({"command": "uv sync"})
    assert patched_execute.calls == ["uv sync"]
    assert "approved: True" in output

    rejected_state = RuntimeState(
        workspace=workspace, approval_mode="inline", approval_handler=lambda r: False
    )
    output = create_bash_tool(rejected_state).invoke({"command": "uv sync"})
    assert patched_execute.calls == ["uv sync"]
    assert "human rejected" in output


def test_inline_rejected_blocks_execution(workspace, patched_execute):
    state = RuntimeState(
        workspace=workspace,
        approval_mode="inline",
        approval_handler=lambda r: ApprovalDecision(approved=False, reason="no"),
    )
    output = create_bash_tool(state).invoke({"command": "npm install"})
    assert patched_execute.calls == []
    assert "human rejected" in output


def test_inline_without_handler_denies_like_deny(workspace, patched_execute):
    state = RuntimeState(workspace=workspace, approval_mode="inline")
    output = create_bash_tool(state).invoke({"command": "pip install flask"})
    assert patched_execute.calls == []
    assert "human approval required" in output


def test_safe_command_bypasses_handler_and_log(workspace, patched_execute):
    def handler(request):
        raise AssertionError("handler must not be called for safe commands")

    state = RuntimeState(
        workspace=workspace, approval_mode="inline", approval_handler=handler
    )
    output = create_bash_tool(state).invoke({"command": "echo hi"})
    assert patched_execute.calls == ["echo hi"]
    assert "exit_code: 0" in output
    assert "requires_approval" not in output
    assert state.approval_log == []
