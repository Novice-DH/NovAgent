"""文件读取、写入与编辑工具。

工具返回供模型阅读的字符串；路径逃逸、文件缺失、编辑目标
不唯一等校验失败以异常形式报错。
"""

from langchain_core.tools import StructuredTool

from novagent.core.paths import resolve_in_workspace
from novagent.core.state import RuntimeState

_MAX_FILE_BYTES = 5 * 1024 * 1024


def _check_regular_file(path) -> None:
    if path.is_dir():
        raise IsADirectoryError(f"{path} is a directory, not a file.")
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")


def create_file_read_tool(state: RuntimeState) -> StructuredTool:
    def read_file(file_path: str, offset: int = 1, limit: int | None = None) -> str:
        """Read a text file inside the workspace.

        Args:
            file_path: File path relative to the workspace (or an absolute
                path that must resolve inside the workspace).
            offset: 1-based line number to start reading from.
            limit: Maximum number of lines to return; omit for all lines.

        Returns:
            The requested file content.
        """
        if offset < 1:
            raise ValueError(f"offset must be >= 1, got {offset}")
        if limit is not None and limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        path = resolve_in_workspace(state, file_path)
        _check_regular_file(path)
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError(f"{path} is larger than {_MAX_FILE_BYTES} bytes")
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = offset - 1
        selected = lines[start:] if limit is None else lines[start : start + limit]
        return "\n".join(selected)

    return StructuredTool.from_function(read_file, name="read_file")


def create_file_write_tool(state: RuntimeState) -> StructuredTool:
    def write_file(file_path: str, content: str) -> str:
        """Create or overwrite a text file inside the workspace.

        Args:
            file_path: File path relative to the workspace; missing parent
                directories are created automatically.
            content: Full text content to write.

        Returns:
            A confirmation message.
        """
        path = resolve_in_workspace(state, file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {path.relative_to(state.workspace.resolve())}"

    return StructuredTool.from_function(write_file, name="write_file")


def create_file_edit_tool(state: RuntimeState) -> StructuredTool:
    def edit_file(file_path: str, old_text: str, new_text: str) -> str:
        """Replace the unique occurrence of ``old_text`` with ``new_text``.

        Args:
            file_path: File path relative to the workspace.
            old_text: Exact text to replace; it must occur exactly once.
            new_text: Replacement text.

        Returns:
            A confirmation message.
        """
        if not old_text:
            raise ValueError("old_text must not be empty")
        path = resolve_in_workspace(state, file_path)
        _check_regular_file(path)
        text = path.read_text(encoding="utf-8")
        occurrences = text.count(old_text)
        if occurrences == 0:
            raise ValueError(f"old_text not found in {path}")
        if occurrences > 1:
            raise ValueError(
                f"old_text matches {occurrences} times in {path}; "
                "it must match exactly once"
            )
        path.write_text(text.replace(old_text, new_text), encoding="utf-8")
        return f"Replaced 1 occurrence in {path.relative_to(state.workspace.resolve())}"

    return StructuredTool.from_function(edit_file, name="edit_file")
