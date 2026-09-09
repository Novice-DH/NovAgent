"""工具注册表：把 workspace 约束注入全部工具。"""

from langchain_core.tools import StructuredTool

from novagent.core.state import RuntimeState
from novagent.tools.bash_tool import create_bash_tool
from novagent.tools.file_tools import (
    create_file_edit_tool,
    create_file_read_tool,
    create_file_write_tool,
)
from novagent.tools.grep_tool import create_grep_tool


def build_tools(state: RuntimeState) -> list[StructuredTool]:
    """构建绑定到 ``state.workspace`` 的全部工具，供 ``model.bind_tools`` 使用。"""
    return [
        create_file_read_tool(state),
        create_file_write_tool(state),
        create_file_edit_tool(state),
        create_grep_tool(state),
        create_bash_tool(state),
    ]
