"""工作区内 shell 命令执行工具（含风险命令人类在环审批）。"""

import json
import os
import subprocess

from langchain_core.tools import StructuredTool

from novagent.core.approval import (
    ApprovalDecision,
    classify_command_risk,
    make_approval_request,
    normalize_approval_mode,
)
from novagent.core.state import RuntimeState

_KILL_COLLECT_GRACE_SECONDS = 5.0


def _resolve_approval(state: RuntimeState, command: str) -> dict | None:
    """风险命令审批分流；安全命令返回 ``None`` 直接放行。

    命中 ``RISK_PATTERNS`` 时按 ``approval_mode`` 处理：``auto`` 放行；
    ``deny``（或 ``inline`` 缺少 handler）拒绝；``inline`` 调用
    ``approval_handler`` 等待人类决策。每次风险分流都向
    ``state.approval_log`` 追加一条记录。
    """
    risk_reason = classify_command_risk(command)
    if risk_reason is None:
        return None

    mode = normalize_approval_mode(getattr(state, "approval_mode", None))
    if mode == "auto":
        approved = True
        denial = None
    elif mode == "deny" or state.approval_handler is None:
        approved = False
        denial = f"human approval required: {risk_reason}"
    else:
        request = make_approval_request(command, risk_reason)
        decision = state.approval_handler(request)
        approved = (
            decision.approved
            if isinstance(decision, ApprovalDecision)
            else bool(decision)
        )
        denial = None if approved else f"human rejected: {risk_reason}"

    state.approval_log.append(
        {
            "command": command,
            "risk_reason": risk_reason,
            "mode": mode,
            "approved": approved,
        }
    )
    result = {
        "requires_approval": True,
        "risk_reason": risk_reason,
        "command": command,
        "approved": approved,
    }
    if denial is not None:
        result["ok"] = False
        result["error"] = denial
    return result


def _popen_kwargs() -> dict:
    if os.name == "nt":
        # cmd.exe 只是直接子进程；超时需要按整棵进程树终止（taskkill /T）
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    # 新会话让子进程成为进程组长，超时可 killpg 整棵树
    return {"start_new_session": True}


def _kill_process_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        import signal

        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()


def execute_command(
    command: str, cwd, timeout_seconds: float = 30.0
) -> tuple[int | None, str, str]:
    """以 ``cwd`` 为工作目录执行 shell 命令，返回 ``(exit_code, stdout, stderr)``。

    超过 ``timeout_seconds`` 时终止整棵子进程树并抛出 ``TimeoutError``；
    命令无法执行时向调用方抛出底层异常。
    """
    if timeout_seconds <= 0:
        raise ValueError(f"timeout_seconds must be > 0, got {timeout_seconds}")
    process = subprocess.Popen(
        command,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        **_popen_kwargs(),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=_KILL_COLLECT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        raise TimeoutError(
            f"Command timed out after {timeout_seconds} seconds: {command}"
        ) from None
    return process.returncode, stdout, stderr


def create_bash_tool(state: RuntimeState) -> StructuredTool:
    def bash(command: str, timeout_seconds: float = 30.0) -> str:
        """Run a shell command with the workspace as working directory.

        Uses the platform shell (cmd.exe on Windows). On timeout the whole
        child process tree is killed before the error is raised.

        Risky commands (dependency installs, downloads, dev servers) go
        through human approval first: they are executed only when the
        approval mode allows it, and the result text carries
        ``requires_approval``/``approved`` marker lines.

        Args:
            command: The shell command line to execute.
            timeout_seconds: Kill the child process tree and fail after
                this many seconds.

        Returns:
            The exit code together with captured stdout and stderr, or a
            JSON approval-denial payload when the command was blocked.
        """
        approval = _resolve_approval(state, command)
        if approval is not None and not approval.get("approved"):
            return json.dumps(approval, ensure_ascii=False)
        exit_code, stdout, stderr = execute_command(
            command, cwd=state.workspace, timeout_seconds=timeout_seconds
        )
        parts = []
        if approval is not None:
            parts.append("requires_approval: True")
            parts.append("approved: True")
        parts.append(f"exit_code: {exit_code}")
        if stdout:
            parts.append(f"stdout:\n{stdout.rstrip()}")
        if stderr:
            parts.append(f"stderr:\n{stderr.rstrip()}")
        return "\n".join(parts)

    return StructuredTool.from_function(bash, name="bash")
