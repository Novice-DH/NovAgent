"""驱动 stage3 LangGraph 工作流，把图事件解析为统一事件流。

在既有事件流之上叠加 Harness（阶段五）：CheckpointManager 在启动、
每个图节点更新、失败 tool_result、正常结束与 KeyboardInterrupt 时保存
检查点；TraceRecorder 全程记录事件与统计。``resume_workspace`` 指向
含检查点的 workspace 时，先恢复文件与输入再重跑工作流。
"""

from pathlib import Path
from typing import Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from novagent.core.checkpoint import CheckpointManager
from novagent.core.state import RuntimeState
from novagent.core.trace import TraceRecorder, tool_result_failed
from novagent.graph.workflow import build_complex_workflow


def _merge_update(current_state: dict, update: dict) -> None:
    """按 reducer 语义把节点更新并入累积状态。

    非 messages 字段直接覆盖；``messages`` 追加，出现
    ``RemoveMessage(REMOVE_ALL_MESSAGES)`` 时先清空（context compressor
    的压缩语义），使累积状态可安全作为 strict 检查点与恢复输入。
    """
    messages_update = None
    for key, value in update.items():
        if key == "messages":
            messages_update = value
            continue
        current_state[key] = value
    if messages_update is None:
        return
    incoming = list(messages_update or [])
    reset = any(
        isinstance(message, RemoveMessage)
        and getattr(message, "id", None) == REMOVE_ALL_MESSAGES
        for message in incoming
    )
    keep = [message for message in incoming if not isinstance(message, RemoveMessage)]
    if reset:
        current_state["messages"] = keep
    else:
        current_state["messages"] = (
            list(current_state.get("messages") or []) + keep
        )


def stream_agent_events(
    task: Optional[str],
    *,
    workspace: Path,
    max_attempts: int = 3,
    model: Optional[BaseChatModel] = None,
    approval_mode: str = "inline",
    approval_handler: Optional[Callable] = None,
    checkpoint_mode: str = "light",
    trace_mode: str = "on",
    resume_workspace: Optional[Path] = None,
):
    """运行 planner→verifier 工作流，逐事件产出统一格式 dict。

    每个事件含 ``type`` 与 ``node`` 字段：

    - ``node_output``：某节点完成（``updates`` 流解析），携带该节点的
      关键输出——planner（plan_summary/todos/acceptance_criteria/
      verification_commands）、verifier（passed/reason/
      verification_results/verification_checks）、final（final_answer）；
    - ``ai_message``/``tool_call``/``tool_result``：planner 协调与受托
      专家 Agent 的内部事件（``custom`` 流实时转发）；
    - ``checkpoint_saved``/``resumed``：Harness 事件（阶段五新增）。

    Harness 参数：``approval_mode``/``approval_handler`` 控制 BashTool
    风险命令审批；``checkpoint_mode``（light/strict/off）与
    ``trace_mode``（on/off）控制检查点与追踪；``resume_workspace`` 指向
    含检查点的 workspace 时从检查点恢复（文件 + task/attempts，strict
    另含 messages）后重跑工作流。
    """
    resume_path = (
        Path(resume_workspace).expanduser().absolute()
        if resume_workspace is not None
        else None
    )
    effective_workspace = (
        resume_path if resume_path is not None else Path(workspace)
    )
    state = RuntimeState(
        workspace=effective_workspace,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        trace_mode=trace_mode,
    )

    resume_event = None
    if resume_path is not None:
        inputs, resume_event = CheckpointManager.load_resume_inputs(
            state, task=task, max_attempts=max_attempts
        )
    else:
        inputs = {"task": task, "runtime": state, "max_attempts": max_attempts}

    effective_task = str(inputs.get("task") or task or "")
    manager = CheckpointManager(state, task=effective_task)
    trace = TraceRecorder(state, task=effective_task)
    graph = build_complex_workflow(model=model)

    current_state = dict(inputs)
    latest_node = "start"

    try:
        trace.start(
            inputs, resumed=resume_event is not None, resume_event=resume_event
        )
        if resume_event is not None:
            yield resume_event
        start_status = "resumed" if resume_event is not None else "started"
        start_checkpoint = manager.save(
            current_state, status=start_status, latest_node=latest_node
        )
        if start_checkpoint is not None:
            trace.record_custom_event(start_checkpoint)
            yield start_checkpoint

        for mode, payload in graph.stream(inputs, stream_mode=["updates", "custom"]):
            if mode == "custom":
                event = dict(payload)
                event.setdefault("node", "planner")
                trace.record_custom_event(event)
                if event.get("type") == "tool_result" and tool_result_failed(event):
                    saved = manager.save(
                        current_state,
                        status="running",
                        latest_node=latest_node,
                        event=event,
                    )
                    if saved is not None:
                        trace.record_custom_event(saved)
                        yield saved
                yield event
                continue
            for node_name, update in payload.items():
                latest_node = node_name
                _merge_update(current_state, update)
                trace.record_graph_update(payload)
                saved = manager.save(
                    current_state, status="running", latest_node=node_name
                )
                if saved is not None:
                    trace.record_custom_event(saved)
                    yield saved
                if node_name == "planner":
                    yield {
                        "type": "node_output",
                        "node": "planner",
                        "plan_summary": update.get("plan_summary", ""),
                        "todos": update.get("todos", []),
                        "acceptance_criteria": update.get(
                            "acceptance_criteria", []
                        ),
                        "verification_commands": update.get(
                            "verification_commands", []
                        ),
                    }
                elif node_name == "verifier":
                    last_error = update.get("last_error") or ""
                    if update.get("passed"):
                        reason = update.get("final_answer", "")
                    else:
                        # last_error 由命令失败详情与结论原因拼成；事件层的
                        # reason 只取结论原因，命令详情见 verification_results。
                        reason = last_error.splitlines()[-1] if last_error else ""
                    yield {
                        "type": "node_output",
                        "node": "verifier",
                        "passed": update.get("passed", False),
                        "reason": reason,
                        "verification_results": update.get(
                            "verification_results", []
                        ),
                        "verification_checks": update.get(
                            "verification_checks", []
                        ),
                    }
                elif node_name == "final":
                    yield {
                        "type": "node_output",
                        "node": "final",
                        "final_answer": update.get("final_answer", ""),
                    }

        # 正常收尾静默保存（不产出事件，保持事件流以 final node_output 结束）
        manager.save(current_state, status="finished", latest_node=latest_node)
        trace.end(status="finished", latest_node=latest_node, final_state=current_state)
    except KeyboardInterrupt:
        manager.save(current_state, status="interrupted", latest_node=latest_node)
        trace.end(
            status="interrupted", latest_node=latest_node, final_state=current_state
        )
        raise
    except GeneratorExit:
        # 消费端中断（如 CLI 渲染期 Ctrl+C）时生成器被关闭；同样落盘
        # interrupted 现场，再按协议重新抛出 GeneratorExit。
        manager.save(current_state, status="interrupted", latest_node=latest_node)
        trace.end(
            status="interrupted", latest_node=latest_node, final_state=current_state
        )
        raise
