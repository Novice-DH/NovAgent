"""检查点保存与恢复（light / strict / off 三级）。

检查点目录位于 workspace 内（``.novagent/checkpoints``）：

- ``light``（默认）：``checkpoint.json`` 元数据 + ``RECOVERY.md``
  人类可读恢复指南 + git 影子仓库快照；
- ``strict``：额外保存完整图状态 ``state.json`` 与 ``events.jsonl``
  事件日志；
- ``off``：完全不保存。

git 快照使用检查点目录内的影子仓库（``git --git-dir --work-tree``），
不污染 workspace 用户文件；git 不可用时记录 ``git_error`` 并降级继续。
任何单点失败都不向工作流抛异常。
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.messages import messages_from_dict, messages_to_dict

CHECKPOINT_FILE = "checkpoint.json"
STATE_FILE = "state.json"
EVENTS_FILE = "events.jsonl"
RECOVERY_FILE = "RECOVERY.md"

VALID_CHECKPOINT_MODES = {"light", "strict", "off"}
DEFAULT_CHECKPOINT_MODE = "light"

# 影子仓库内排除 .novagent 自身，避免快照递归包含检查点产物
_SHADOW_GIT_EXCLUDE = ".novagent\n"


def normalize_checkpoint_mode(mode: str | None) -> str:
    """合法模式原样返回；``None``/未知值回落 ``light``。"""
    return mode if mode in VALID_CHECKPOINT_MODES else DEFAULT_CHECKPOINT_MODE


def workspace_manifest(workspace: Path) -> list[dict]:
    """workspace 文件清单（相对路径 + 字节大小；跳过 ``.novagent``）。"""
    entries: list[dict] = []
    root = Path(workspace)
    try:
        paths = sorted(root.rglob("*"))
    except OSError:
        return entries
    for path in paths:
        try:
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if ".novagent" in relative.parts:
                continue
            entries.append(
                {"path": relative.as_posix(), "size": path.stat().st_size}
            )
        except OSError:
            continue
    return entries


def serialize_state(state: dict) -> dict:
    """图状态转 JSON 安全 dict：``messages`` 经 langchain 往返，``runtime`` 跳过。"""
    payload: dict = {}
    for key, value in dict(state or {}).items():
        if key == "runtime":
            continue
        if key == "messages":
            payload[key] = messages_to_dict(list(value or []))
        else:
            payload[key] = json.loads(
                json.dumps(value, default=str, ensure_ascii=False)
            )
    return payload


def deserialize_state(payload: dict) -> dict:
    """:func:`serialize_state` 的逆操作（``messages`` 还原为 BaseMessage）。"""
    data = dict(payload or {})
    if "messages" in data:
        data["messages"] = messages_from_dict(data["messages"])
    return data


def _run_git(git_dir: Path, work_tree: Path, args: list[str]):
    """以影子仓库配置运行 git；cwd 固定在 workspace 使相对路径可预测。"""
    return subprocess.run(
        ["git", "--git-dir", str(git_dir), "--work-tree", str(work_tree), *args],
        cwd=str(work_tree),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def snapshot_workspace_git(
    checkpoint_root: Path, workspace: Path
) -> tuple[Optional[str], str]:
    """把 workspace 当前内容提交到检查点目录内的影子仓库。

    返回 ``(git_commit, git_error)``：成功时 commit 为 HEAD 摘要且
    error 为空串；失败时 commit 为 ``None`` 且 error 说明原因。git
    缺失（``FileNotFoundError`` 等 OSError）同样降级为 error 文本。
    """
    git_dir = checkpoint_root / ".git"
    try:
        if not (git_dir / "HEAD").exists():
            init = _run_git(git_dir, workspace, ["init"])
            if init.returncode != 0:
                return None, (init.stderr or "git init failed").strip()
            exclude = git_dir / "info" / "exclude"
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text(_SHADOW_GIT_EXCLUDE, encoding="utf-8")
        add = _run_git(git_dir, workspace, ["add", "-A"])
        if add.returncode != 0:
            return None, (add.stderr or "git add failed").strip()
        stamp = datetime.now(timezone.utc).isoformat()
        commit = _run_git(
            git_dir,
            workspace,
            [
                "-c",
                "user.name=novagent checkpoint",
                "-c",
                "user.email=novagent@localhost",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "-m",
                f"novagent checkpoint {stamp}",
            ],
        )
        if commit.returncode != 0:
            return None, (commit.stderr or "git commit failed").strip()
        head = _run_git(git_dir, workspace, ["rev-parse", "HEAD"])
        if head.returncode != 0:
            return None, (head.stderr or "git rev-parse failed").strip()
        return head.stdout.strip(), ""
    except OSError as exc:
        return None, f"git unavailable: {exc}"


def _restore_workspace_git(
    checkpoint_root: Path, workspace: Path, commit: str
) -> str:
    """把 workspace 文件强制恢复到快照提交；返回错误文本（空为成功）。"""
    result = _run_git(
        checkpoint_root / ".git", workspace, ["checkout", "-f", commit, "--", "."]
    )
    if result.returncode != 0:
        return (result.stderr or "git checkout failed").strip()
    return ""


def build_recovery_markdown(payload: dict) -> str:
    """把检查点元数据渲染为人类可读的恢复指南。"""
    commit = payload.get("git_commit")
    git_error = payload.get("git_error") or ""
    lines = [
        "# novagent Recovery Guide",
        "",
        f"- Task: {payload.get('task') or '(unknown)'}",
        f"- Status: {payload.get('status') or 'running'}",
        f"- Latest node: {payload.get('latest_node') or '(none)'}",
        f"- Checkpoint mode: {payload.get('mode') or 'light'}",
        f"- Saved at: {payload.get('saved_at') or '(unknown)'}",
        f"- Attempts: {payload.get('attempts') or 0}",
        f"- Workspace: {payload.get('workspace') or '(unknown)'}",
    ]
    if commit:
        lines.append(f"- Git commit: `{commit}`")
    else:
        lines.append("- Git commit: (none)")
        if git_error:
            lines.append(f"- Git error: {git_error}")
    lines.append("")
    lines.append("## Resume")
    lines.append("")
    workspace = payload.get("workspace")
    if workspace:
        lines.append(f"```bash\n{resume_command(workspace)}\n```")
    else:
        lines.append("```bash\nnovagent run --resume <workspace>\n```")
    lines.append("")
    lines.append("## Workspace files at checkpoint")
    lines.append("")
    manifest = payload.get("workspace_manifest") or []
    if not manifest:
        lines.append("(empty)")
    else:
        for entry in manifest[:50]:
            lines.append(f"- {entry.get('path', '')} ({entry.get('size', 0)} bytes)")
        if len(manifest) > 50:
            lines.append(f"- ... and {len(manifest) - 50} more")
    lines.append("")
    return "\n".join(lines)


def resume_command(workspace: Path) -> str:
    """生成恢复命令文本：``novagent run --resume <workspace 绝对路径>``。"""
    absolute = Path(workspace).expanduser().absolute()
    return f"novagent run --resume {absolute}"


class CheckpointManager:
    """按模式保存检查点并支持恢复。"""

    def __init__(self, runtime, task: str = ""):
        self.workspace = Path(runtime.workspace)
        self.mode = normalize_checkpoint_mode(
            getattr(runtime, "checkpoint_mode", None)
        )
        self.task = str(task or "")
        self.root = self.workspace / ".novagent" / "checkpoints"

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def save(
        self,
        state: dict,
        *,
        status: str = "running",
        latest_node: Optional[str] = None,
        event: Optional[dict] = None,
    ) -> Optional[dict]:
        """保存检查点；disabled 或落盘失败时返回 ``None``。

        ``state`` 为图状态样 dict；strict 模式下 ``event`` 非 None 时
        追加一行到 ``events.jsonl``，并额外写完整 ``state.json``。
        """
        if not self.enabled:
            return None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None

        state_dict = dict(state or {})
        if self.mode == "strict":
            if event is not None:
                self._append_event(event)
            try:
                _write_json(self.root / STATE_FILE, serialize_state(state_dict))
            except (OSError, TypeError, ValueError):
                pass

        manifest = workspace_manifest(self.workspace)
        git_commit, git_error = snapshot_workspace_git(self.root, self.workspace)
        payload = {
            "task": self.task,
            "status": status,
            "latest_node": latest_node,
            "mode": self.mode,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "attempts": int(state_dict.get("attempts") or 0),
            "workspace": str(self.workspace),
            "git_commit": git_commit,
            "git_error": git_error,
            "workspace_manifest": manifest,
        }
        try:
            _write_json(self.root / CHECKPOINT_FILE, payload)
            (self.root / RECOVERY_FILE).write_text(
                build_recovery_markdown(payload), encoding="utf-8"
            )
        except OSError:
            return None
        return {
            "type": "checkpoint_saved",
            "node": latest_node or "start",
            "mode": self.mode,
            "status": status,
            "latest_node": latest_node,
            "path": str(self.root),
        }

    def _append_event(self, event: dict) -> None:
        try:
            with (self.root / EVENTS_FILE).open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(event, ensure_ascii=False, default=str) + "\n"
                )
        except (OSError, TypeError, ValueError):
            pass

    @classmethod
    def load_resume_inputs(
        cls, runtime, task: Optional[str] = None, max_attempts: int = 3
    ) -> tuple[dict, dict]:
        """从 workspace 检查点恢复运行输入。

        读取 ``checkpoint.json``（缺失抛 ``FileNotFoundError``）；存在
        git 快照时把 workspace 文件恢复到快照内容；strict 且有
        ``state.json`` 时还原 ``messages``。返回 ``(inputs, resume_event)``。
        """
        manager = cls(runtime, task=task or "")
        checkpoint_path = manager.root / CHECKPOINT_FILE
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"no checkpoint found in {manager.root}")
        try:
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise FileNotFoundError(
                f"checkpoint at {checkpoint_path} is unreadable: {exc}"
            ) from exc

        git_error = ""
        commit = payload.get("git_commit")
        if commit:
            try:
                git_error = _restore_workspace_git(
                    manager.root, manager.workspace, commit
                )
            except OSError as exc:
                git_error = f"git unavailable: {exc}"

        inputs: dict = {
            "task": task or payload.get("task") or "",
            "runtime": runtime,
            "max_attempts": max_attempts,
            "attempts": int(payload.get("attempts") or 0),
        }
        if manager.mode == "strict":
            # 只从 state.json 恢复 messages：task/max_attempts/attempts 以
            # 调用参数与 checkpoint.json 为准，避免旧状态覆盖恢复配置。
            state_path = manager.root / STATE_FILE
            if state_path.exists():
                try:
                    saved = json.loads(state_path.read_text(encoding="utf-8"))
                    messages = deserialize_state(saved).get("messages")
                    if messages is not None:
                        inputs["messages"] = messages
                except (json.JSONDecodeError, OSError, TypeError, ValueError):
                    pass

        resume_event = {
            "type": "resumed",
            "node": "start",
            "task": inputs["task"],
            "latest_node": payload.get("latest_node"),
            "attempts": inputs["attempts"],
            "workspace": str(manager.workspace),
            "git_error": git_error,
        }
        return inputs, resume_event


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
