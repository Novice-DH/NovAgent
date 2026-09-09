"""resolve_in_workspace 的路径安全行为。"""

import pytest

from novagent.core.paths import resolve_in_workspace


def test_relative_path_resolves_inside_workspace(state, workspace):
    resolved = resolve_in_workspace(state, "sub/dir/file.txt")
    assert resolved == (workspace / "sub" / "dir" / "file.txt").resolve()


def test_workspace_root_itself_is_allowed(state, workspace):
    assert resolve_in_workspace(state, ".") == workspace.resolve()


def test_parent_escape_is_rejected(state):
    with pytest.raises(ValueError, match="escapes the workspace"):
        resolve_in_workspace(state, "../outside.txt")


def test_absolute_path_outside_workspace_is_rejected(state, tmp_path):
    outside = tmp_path / "elsewhere.txt"
    with pytest.raises(ValueError, match="escapes the workspace"):
        resolve_in_workspace(state, str(outside))


def test_nested_dotdot_that_stays_inside_is_allowed(state, workspace):
    resolved = resolve_in_workspace(state, "sub/../file.txt")
    assert resolved == (workspace / "file.txt").resolve()
