"""Agent 运行时状态。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RuntimeState:
    """一次 agent 运行的共享状态。

    ``workspace`` 是所有工具操作的根目录：文件、搜索与命令工具
    都只能访问该目录之内（含子目录）的路径。
    """

    workspace: Path

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).expanduser().absolute()
