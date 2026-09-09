"""工作区内 shell 命令执行工具。"""

import os
import subprocess

from langchain_core.tools import StructuredTool

from novagent.core.state import RuntimeState

_KILL_COLLECT_GRACE_SECONDS = 5.0


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


def create_bash_tool(state: RuntimeState) -> StructuredTool:
    def bash(command: str, timeout_seconds: float = 30.0) -> str:
        """Run a shell command with the workspace as working directory.

        Uses the platform shell (cmd.exe on Windows). On timeout the whole
        child process tree is killed before the error is raised.

        Args:
            command: The shell command line to execute.
            timeout_seconds: Kill the child process tree and fail after
                this many seconds.

        Returns:
            The exit code together with captured stdout and stderr.
        """
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be > 0, got {timeout_seconds}")
        process = subprocess.Popen(
            command,
            cwd=state.workspace,
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
                stdout, stderr = process.communicate(
                    timeout=_KILL_COLLECT_GRACE_SECONDS
                )
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            raise TimeoutError(
                f"Command timed out after {timeout_seconds} seconds: {command}"
            ) from None
        parts = [f"exit_code: {process.returncode}"]
        if stdout:
            parts.append(f"stdout:\n{stdout.rstrip()}")
        if stderr:
            parts.append(f"stderr:\n{stderr.rstrip()}")
        return "\n".join(parts)

    return StructuredTool.from_function(bash, name="bash")
