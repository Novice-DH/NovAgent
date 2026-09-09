"""共享 fixtures：临时工作区与工具集。"""

import pytest

from novagent.core.state import RuntimeState
from novagent.tools.registry import build_tools


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def state(workspace):
    return RuntimeState(workspace=workspace)


@pytest.fixture
def tools(state):
    return build_tools(state)


@pytest.fixture
def by_name(tools):
    return {tool.name: tool for tool in tools}
