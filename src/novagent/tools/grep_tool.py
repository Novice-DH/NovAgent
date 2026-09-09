"""工作区内正则搜索工具。"""

import fnmatch
import os
import re
from pathlib import Path

from langchain_core.tools import StructuredTool

from novagent.core.paths import resolve_in_workspace
from novagent.core.state import RuntimeState

_MAX_FILE_BYTES = 5 * 1024 * 1024


def _matches_glob(relative: str, filename: str, pattern: str) -> bool:
    if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(filename, pattern):
        return True
    # pathlib 语义：**/ 匹配零层或多层目录，因此 "**/x" 也作用于根级文件
    if pattern.startswith("**/"):
        rest = pattern[3:]
        return fnmatch.fnmatch(relative, rest) or fnmatch.fnmatch(filename, rest)
    return False


def _matching_files(root: Path, glob_pattern: str):
    # os.walk 不跟随目录符号链接，避免在 <3.13 的 Python 上被循环链接卡死
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            full = Path(dirpath) / filename
            relative = full.relative_to(root).as_posix()
            if _matches_glob(relative, filename, glob_pattern):
                yield full


def create_grep_tool(state: RuntimeState) -> StructuredTool:
    def grep(
        pattern: str,
        path: str = ".",
        glob: str = "**/*",
        head_limit: int = 20,
        ignore_case: bool = False,
    ) -> str:
        """Search files in the workspace with a regular expression.

        Args:
            pattern: Python regular expression applied to each line.
            path: Directory (or file) to search, inside the workspace.
            glob: Glob pattern selecting which files to search,
                e.g. ``*.py`` or ``**/*.md``.
            head_limit: Maximum number of matching lines to return.
            ignore_case: Perform a case-insensitive search.

        Returns:
            Matches formatted as ``relative/path:line:text``, or a note
            when nothing matched.
        """
        if head_limit < 1:
            raise ValueError(f"head_limit must be >= 1, got {head_limit}")
        try:
            regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as exc:
            raise ValueError(f"Invalid regex {pattern!r}: {exc}") from exc

        root = resolve_in_workspace(state, path)
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = sorted(_matching_files(root, glob))
        else:
            raise FileNotFoundError(f"Search path not found: {root}")

        matches: list[str] = []
        workspace = state.workspace.resolve()
        for file_path in files:
            if file_path.stat().st_size > _MAX_FILE_BYTES:
                continue
            try:
                text = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            relative = file_path.relative_to(workspace).as_posix()
            for line_number, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{relative}:{line_number}:{line}")
                    if len(matches) >= head_limit:
                        return "\n".join(matches)
        if not matches:
            return f"No matches for pattern {pattern!r} under {path!r}"
        return "\n".join(matches)

    return StructuredTool.from_function(grep, name="grep")
