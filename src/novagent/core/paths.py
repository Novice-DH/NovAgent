"""工作区路径安全工具。"""

from pathlib import Path

from novagent.core.state import RuntimeState


def resolve_in_workspace(state: RuntimeState, raw_path: str | Path) -> Path:
    """把 ``raw_path`` 解析并限制在 ``state.workspace`` 内。

    相对路径以 workspace 为基准；绝对路径原样解析。解析会归一化
    ``..`` 与已有符号链接，逃逸出 workspace 时抛出 :class:`ValueError`。
    """
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = state.workspace / candidate
    resolved = candidate.resolve()
    root = state.workspace.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(
            f"Path {raw_path!r} escapes the workspace ({root}); "
            f"resolved to {resolved}, which is outside it."
        )
    return resolved
