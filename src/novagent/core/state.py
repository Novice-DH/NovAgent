"""Agent 运行时状态。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from novagent.core.approval import ApprovalRequest


@dataclass
class RuntimeState:
    """一次 agent 运行的共享状态。

    ``workspace`` 是所有工具操作的根目录：文件、搜索与命令工具
    都只能访问该目录之内（含子目录）的路径。

    Harness 配置（阶段五）随状态传递给每个工具：

    - ``approval_mode`` / ``approval_handler``：BashTool 风险命令的
      审批模式与 ``inline`` 模式的人类决策入口；
    - ``checkpoint_mode`` / ``trace_mode`` / ``trace_id``：检查点与
      链路追踪级别及本次运行的追踪标识；
    - ``approval_log``：运行期风险分流记录（command/risk_reason/
      mode/approved），供 trace 统计与诊断读取。
    """

    workspace: Path
    approval_mode: str = "inline"
    approval_handler: Optional[Callable[["ApprovalRequest"], object]] = None
    checkpoint_mode: str = "light"
    trace_mode: str = "on"
    trace_id: Optional[str] = None
    approval_log: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).expanduser().absolute()
