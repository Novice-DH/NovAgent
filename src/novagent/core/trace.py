"""链路追踪（on / off 两级）。

每次运行在 ``workspace/.novagent/traces/{trace_id}/`` 下产出：

- ``events.jsonl``：每条事件一行 JSON；
- ``trace.json``：运行结束时的统计概览（节点访问、工具调用、审批、
  检查点、交接数与时间线摘要）；
- ``timeline.md``：人类可读时间线。

``off`` 模式下所有方法为 no-op，不创建任何文件。所有落盘失败一律
降级跳过，不影响工作流。
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

VALID_TRACE_MODES = {"on", "off"}
DEFAULT_TRACE_MODE = "on"

TRACE_HEAD_LIMIT = 20
TRACE_TAIL_LIMIT = 80

_EXIT_CODE_PREFIX = re.compile(r"exit_code:\s*(-?\d+)")


def normalize_trace_mode(mode: str | None) -> str:
    """合法模式原样返回；``None``/未知值回落 ``on``。"""
    return mode if mode in VALID_TRACE_MODES else DEFAULT_TRACE_MODE


def tool_result_failed(event: dict) -> bool:
    """tool_result 失败的确定性判定规则。

    结果文本以 ``Error`` 开头，或首行为 ``exit_code: <n>`` 且 n≠0
    时视为失败；其余（含 JSON 审批拒绝文本）不算失败。
    """
    if event.get("type") != "tool_result":
        return False
    text = str(event.get("result") or "")
    if text.startswith("Error"):
        return True
    first_line = text.splitlines()[0] if text else ""
    match = _EXIT_CODE_PREFIX.match(first_line)
    return bool(match and int(match.group(1)) != 0)


class TraceRecorder:
    """逐事件记录运行轨迹并维护统计计数。"""

    def __init__(self, runtime, task: str = ""):
        self.runtime = runtime
        self.workspace = Path(runtime.workspace)
        self.mode = normalize_trace_mode(getattr(runtime, "trace_mode", None))
        trace_id = getattr(runtime, "trace_id", None)
        if not trace_id:
            trace_id = uuid4().hex[:8]
            runtime.trace_id = trace_id
        self.trace_id = str(trace_id)
        self.task = str(task or "")
        self.root = self.workspace / ".novagent" / "traces" / self.trace_id
        self.node_visits: dict[str, int] = {}
        self.tool_calls = 0
        self.failed_tool_calls = 0
        self.approval_count = 0
        self.checkpoint_count = 0
        self.handoff_count = 0
        self.timeline: list[str] = []
        self._start_monotonic: float | None = None
        self._started_at: str | None = None

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def start(
        self,
        inputs: dict | None = None,
        *,
        resumed: bool = False,
        resume_event: dict | None = None,
    ) -> None:
        """记录 run_start 事件；``resumed`` 标记本次运行来自检查点恢复。"""
        if not self.enabled:
            return
        self._start_monotonic = time.monotonic()
        self._started_at = datetime.now(timezone.utc).isoformat()
        suffix = " resumed" if resumed else ""
        self._record(
            f"run_start: task={self.task!r}{suffix}",
            {"type": "run_start", "resumed": resumed},
        )

    def record_custom_event(self, event: dict) -> None:
        """记录 custom 流事件并更新统计计数。"""
        if not self.enabled:
            return
        kind = str(event.get("type") or "event")
        if kind == "tool_call":
            self.tool_calls += 1
        elif kind == "tool_result" and tool_result_failed(event):
            self.failed_tool_calls += 1
        elif kind == "handoff":
            self.handoff_count += 1
        elif kind == "checkpoint_saved":
            self.checkpoint_count += 1
        detail = event.get("name") or event.get("status") or ""
        if kind == "handoff":
            detail = f"{event.get('from', '')}→{event.get('to', '')}"
        suffix = f": {detail}" if detail else ""
        self._record(f"{kind}{suffix}", event)

    def record_graph_update(self, event: dict) -> None:
        """记录 updates 流事件（``{节点名: 更新}``），累计节点访问数。"""
        if not self.enabled:
            return
        for node_name in dict(event or {}):
            self.node_visits[node_name] = self.node_visits.get(node_name, 0) + 1
            self._record(
                f"node:{node_name}", {"type": "node_update", "node": node_name}
            )

    def end(
        self,
        *,
        status: str,
        latest_node: str | None = None,
        final_state: dict | None = None,
    ) -> None:
        """结束追踪：写 ``trace.json`` 统计概览与 ``timeline.md``。"""
        if not self.enabled:
            return
        self._record(
            f"run_end: status={status} latest_node={latest_node or '(none)'}",
            {"type": "run_end", "status": status, "latest_node": latest_node},
        )
        ended_at = datetime.now(timezone.utc).isoformat()
        if self._start_monotonic is not None:
            duration_ms = int((time.monotonic() - self._start_monotonic) * 1000)
        else:
            duration_ms = 0
        self.approval_count = len(
            getattr(self.runtime, "approval_log", None) or []
        )

        timeline = self.timeline
        head = timeline[:TRACE_HEAD_LIMIT]
        if len(timeline) <= TRACE_HEAD_LIMIT + TRACE_TAIL_LIMIT:
            tail = timeline[TRACE_HEAD_LIMIT:]
            omitted = 0
        else:
            tail = timeline[-TRACE_TAIL_LIMIT:]
            omitted = len(timeline) - TRACE_HEAD_LIMIT - TRACE_TAIL_LIMIT

        overview = {
            "trace_id": self.trace_id,
            "task": self.task,
            "status": status,
            "started_at": self._started_at,
            "ended_at": ended_at,
            "duration_ms": duration_ms,
            "node_visits": dict(self.node_visits),
            "tool_calls": self.tool_calls,
            "failed_tool_calls": self.failed_tool_calls,
            "approval_count": self.approval_count,
            "checkpoint_count": self.checkpoint_count,
            "handoff_count": self.handoff_count,
            "timeline_head": head,
            "timeline_tail": tail,
            "timeline_omitted": omitted,
        }
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "trace.json").write_text(
                json.dumps(overview, ensure_ascii=False, default=str, indent=2),
                encoding="utf-8",
            )
            (self.root / "timeline.md").write_text(
                _render_timeline_markdown(overview), encoding="utf-8"
            )
        except OSError:
            pass

    def _record(self, line: str, event: dict | None = None) -> None:
        """追加一条时间线与 events.jsonl 行；失败静默跳过。"""
        self.timeline.append(line)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            payload = {"at": datetime.now(timezone.utc).isoformat()}
            if event is not None:
                payload["event"] = event
            payload["line"] = line
            with (self.root / "events.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(
                    json.dumps(payload, ensure_ascii=False, default=str) + "\n"
                )
        except (OSError, TypeError, ValueError):
            pass


def _render_timeline_markdown(overview: dict) -> str:
    """把统计概览与完整时间线索引渲染为人类可读 Markdown。"""
    lines = [
        f"# novagent Trace {overview.get('trace_id', '')}",
        "",
        f"- Task: {overview.get('task') or '(unknown)'}",
        f"- Status: {overview.get('status')}",
        f"- Duration: {overview.get('duration_ms', 0)} ms",
        f"- Node visits: {overview.get('node_visits') or '{}'}",
        f"- Tool calls: {overview.get('tool_calls', 0)}"
        f" (failed: {overview.get('failed_tool_calls', 0)})",
        f"- Approvals: {overview.get('approval_count', 0)}",
        f"- Checkpoints: {overview.get('checkpoint_count', 0)}",
        f"- Handoffs: {overview.get('handoff_count', 0)}",
        "",
        "## Timeline",
        "",
    ]
    head = overview.get("timeline_head") or []
    tail = overview.get("timeline_tail") or []
    omitted = overview.get("timeline_omitted", 0)
    for entry in head:
        lines.append(f"- {entry}")
    if omitted:
        lines.append(f"- ... ({omitted} entries omitted) ...")
    for entry in tail:
        lines.append(f"- {entry}")
    lines.append("")
    return "\n".join(lines)
