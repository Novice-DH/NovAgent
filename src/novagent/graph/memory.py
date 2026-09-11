"""三层 Memory 系统（Context Engineering 数据层）。

分层记忆的纯组装层：不调用模型、无网络、不写文件、不修改传入的
state；所有状态键容错读取（``state.get``），状态残缺不抛异常。
"""

import json
from pathlib import Path
from typing import TypedDict

from novagent.core.state import RuntimeState

HANDOFF_KEEP = 6
COMPRESSION_EVENT_KEEP = 3

RESEARCH_NOTES_LIMIT = 1600
CODE_AGENT_SUMMARY_LIMIT = 1000
VERIFIER_SUMMARY_LIMIT = 1000
LAST_ERROR_LIMIT = 1400
HISTORY_SUMMARY_LIMIT = 2200
NOTEPAD_LIMIT = 1800
CONTEXT_SUMMARY_LIMIT = 1600


class CompressionEvent(TypedDict, total=False):
    """一次上下文压缩事件的预留描述（当前无图内写入方）。"""

    node: str
    reason: str
    token_count: int
    token_limit: int
    summary: str
    created_at: str


class LayeredMemory(TypedDict, total=False):
    """``build_layered_memory`` 返回结构的类型视图。"""

    rules: dict
    working_memory: dict
    history_summary_store: dict


RULES_LAYER: dict = {
    "scope": "workspace",
    "storage": "internal",
    "rules": [
        "Work inside the current workspace only.",
        "Use paths relative to the workspace; do not prefix paths with workspace/.",
        "Keep durable task context outside the raw messages transcript when possible.",
        "Treat TODO.md as working plan state, NOTEPAD.md as durable notes, "
        "and HISTORY_SUMMARY.md as compressed history.",
        "Do not expose memory write tools to agents; layered memory is assembled "
        "by the runtime.",
    ],
}


def _read_workspace_file(runtime, filename: str) -> dict:
    """只读 workspace 根下的固定文件；缺失或读取失败按不存在处理。"""
    workspace = getattr(runtime, "workspace", None)
    if workspace is None:
        return {"exists": False, "content": ""}
    path = Path(workspace) / filename
    try:
        return {"exists": True, "content": path.read_text(encoding="utf-8")}
    except (OSError, UnicodeDecodeError):
        return {"exists": False, "content": ""}


def read_notepad(runtime: RuntimeState | None) -> dict:
    """读取 workspace 根下的 ``NOTEPAD.md``（持久笔记，只读）。"""
    return _read_workspace_file(runtime, "NOTEPAD.md")


def read_history_summary(runtime: RuntimeState | None) -> dict:
    """读取 workspace 根下的 ``HISTORY_SUMMARY.md``（压缩历史，只读）。"""
    return _read_workspace_file(runtime, "HISTORY_SUMMARY.md")


def _short_text(text, limit: int) -> str:
    """超长文本截断到总长不超过 ``limit`` 且以 ``...`` 结尾。"""
    value = str(text)
    if len(value) <= limit:
        return value
    if limit <= 3:
        return "..."[:limit]
    return value[: limit - 3] + "..."


def _trim_handoffs(handoffs, keep: int = HANDOFF_KEEP) -> list:
    """只保留最近 ``keep`` 条交接记录（末尾 keep 条、顺序保持）。"""
    if not isinstance(handoffs, list):
        return []
    return list(handoffs[-keep:])


def _norm_sources(sources) -> list:
    """sources 只保留 ``title`` 和 ``url``。"""
    if not isinstance(sources, list):
        return []
    normalized = []
    for item in sources:
        entry = item if isinstance(item, dict) else {}
        normalized.append(
            {
                "title": str(entry.get("title", "")),
                "url": str(entry.get("url", "")),
            }
        )
    return normalized


def build_layered_memory(state: dict, *, node: str = "graph") -> dict:
    """组装 rules / working_memory / history_summary_store 三层记忆。"""
    runtime = state.get("runtime")
    notepad = read_notepad(runtime)
    history = read_history_summary(runtime)

    working_memory = {
        "node": node,
        "task": str(state.get("task") or ""),
        "session_id": str(state.get("session_id") or ""),
        "session_turn": state.get("session_turn") or 0,
        "plan_summary": str(state.get("plan_summary") or ""),
        "todos": list(state.get("todos") or []),
        "acceptance_criteria": list(state.get("acceptance_criteria") or []),
        "verification_commands": list(state.get("verification_commands") or []),
        "research_notes": _short_text(
            state.get("research_notes") or "", RESEARCH_NOTES_LIMIT
        ),
        "sources": _norm_sources(state.get("sources") or []),
        "agent_handoffs": _trim_handoffs(state.get("agent_handoffs") or []),
        "code_agent_summary": _short_text(
            state.get("code_agent_summary") or "", CODE_AGENT_SUMMARY_LIMIT
        ),
        "verifier_summary": _short_text(
            state.get("verifier_summary") or "", VERIFIER_SUMMARY_LIMIT
        ),
        "last_error": _short_text(state.get("last_error") or "", LAST_ERROR_LIMIT),
        "attempts": state.get("attempts") or 0,
        "max_attempts": state.get("max_attempts") or 3,
    }

    history_summary_store = {
        "history_path": "HISTORY_SUMMARY.md",
        "history_exists": history.get("exists", False),
        "history_summary": _short_text(
            history.get("content", ""), HISTORY_SUMMARY_LIMIT
        ),
        "notepad_path": "NOTEPAD.md",
        "notepad_exists": notepad.get("exists", False),
        "notepad": _short_text(notepad.get("content", ""), NOTEPAD_LIMIT),
        "context_summary": _short_text(
            state.get("context_summary") or "", CONTEXT_SUMMARY_LIMIT
        ),
        "compression_events": list(
            state.get("compression_events") or []
        )[-COMPRESSION_EVENT_KEEP:],
    }

    return {
        "rules": dict(RULES_LAYER),
        "working_memory": working_memory,
        "history_summary_store": history_summary_store,
    }


def format_layered_memory_for_prompt(memory: dict) -> str:
    """把分层记忆序列化为可注入 prompt 的 JSON 文本。"""
    return json.dumps(memory, ensure_ascii=False)


def memory_event(memory: dict, *, node: str = "graph") -> dict:
    """构造运行时的分层记忆事件：统一事件流中的 ``type="memory"`` 事件。"""
    return {"type": "memory", "node": node, "memory": memory}
