"""build_tools 注册行为。"""

import sys

from langchain_core.tools import StructuredTool

from novagent.tools.registry import build_tools

EXPECTED_NAMES = ["read_file", "write_file", "edit_file", "grep", "bash"]


def test_returns_five_structured_tools_in_order(state, workspace):
    tools = build_tools(state)
    assert [tool.name for tool in tools] == EXPECTED_NAMES
    assert all(isinstance(tool, StructuredTool) for tool in tools)


def test_tool_schemas_expose_expected_arguments(state):
    tools = {tool.name: tool for tool in build_tools(state)}
    assert set(tools["read_file"].args_schema.model_fields) == {
        "file_path",
        "offset",
        "limit",
    }
    assert set(tools["write_file"].args_schema.model_fields) == {
        "file_path",
        "content",
    }
    assert set(tools["edit_file"].args_schema.model_fields) == {
        "file_path",
        "old_text",
        "new_text",
    }
    assert set(tools["bash"].args_schema.model_fields) == {
        "command",
        "timeout_seconds",
    }


def test_tools_are_bound_to_their_own_workspace(tmp_path):
    from novagent.core.state import RuntimeState

    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    by_name_a = {t.name: t for t in build_tools(RuntimeState(workspace=ws_a))}
    by_name_b = {t.name: t for t in build_tools(RuntimeState(workspace=ws_b))}
    by_name_a["write_file"].invoke({"file_path": "which.txt", "content": "a"})
    assert (ws_a / "which.txt").exists()
    assert not (ws_b / "which.txt").exists()
    command = f'"{sys.executable}" -c "import os; print(os.getcwd())"'
    output = by_name_b["bash"].invoke({"command": command})
    assert str(ws_b.resolve()) in output
