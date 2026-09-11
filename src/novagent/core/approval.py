"""命令风险分类与人类在环审批。

BashTool 执行前经 :func:`classify_command_risk` 识别有副作用的命令
（依赖安装、网络下载、长驻服务），再按 ``inline`` / ``auto`` / ``deny``
三种模式分流：安全命令直接放行；风险命令要么自动放行（auto）、
要么直接拒绝（deny 或 inline 缺少 handler）、要么等待人类决策（inline）。
"""

import re
from dataclasses import dataclass, field
from uuid import uuid4

# (正则, 风险原因)。全部锚定行首或 &&/||/; 复合边界之后，避免误伤
# 参数位置（如 grep "pip install"）。
RISK_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?:^|&&|\|\||;)\s*(?:python\s+-m\s+)?pip\s+install\b",
        "Python package installation",
    ),
    (r"(?:^|&&|\|\||;)\s*uv\s+add\b", "Project dependency change with uv add"),
    (r"(?:^|&&|\|\||;)\s*uv\s+sync\b", "Dependency synchronization with uv sync"),
    (
        r"(?:^|&&|\|\||;)\s*uv\s+pip\s+install\b",
        "Python package installation with uv pip",
    ),
    (r"(?:^|&&|\|\||;)\s*npm\s+install\b", "Node package installation"),
    (r"(?:^|&&|\|\||;)\s*pnpm\s+install\b", "Node package installation"),
    (r"(?:^|&&|\|\||;)\s*yarn\s+(?:install\b|add\b)", "Node package installation"),
    (r"(?:^|&&|\|\||;)\s*(?:curl|wget)\b", "Network download command"),
    (r"(?:^|&&|\|\||;)\s*uvicorn\b", "Long-running development server"),
    (
        r"(?:^|&&|\|\||;)\s*python\s+-m\s+http\.server\b",
        "Long-running development server",
    ),
]

VALID_APPROVAL_MODES = {"inline", "auto", "deny"}
DEFAULT_APPROVAL_MODE = "inline"


@dataclass(frozen=True)
class ApprovalRequest:
    """一次风险命令的审批请求；``id`` 缺省时自动生成短随机标识。"""

    id: str = field(default_factory=lambda: f"approval-{uuid4().hex[:8]}")
    command: str = ""
    risk_reason: str = ""
    tool_name: str = "BashTool"


@dataclass(frozen=True)
class ApprovalDecision:
    """审批方（人类或自动策略）对请求的决策。"""

    approved: bool
    reason: str = ""


def classify_command_risk(command: str) -> str | None:
    """命中风险模式返回原因字符串；安全命令返回 ``None``。"""
    for pattern, reason in RISK_PATTERNS:
        if re.search(pattern, command or "", flags=re.IGNORECASE):
            return reason
    return None


def normalize_approval_mode(mode: str | None) -> str:
    """合法模式原样返回；``None``/未知值回落 ``inline``。"""
    return mode if mode in VALID_APPROVAL_MODES else DEFAULT_APPROVAL_MODE


def make_approval_request(
    command: str, risk_reason: str, *, tool_name: str = "BashTool"
) -> ApprovalRequest:
    """以短随机 id 构造审批请求。"""
    return ApprovalRequest(
        id=f"approval-{uuid4().hex[:8]}",
        command=command,
        risk_reason=risk_reason,
        tool_name=tool_name,
    )
