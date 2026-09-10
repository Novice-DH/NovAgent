"""代码实现专家 Agent：手写 ReAct 循环在工作区内执行文件与 shell 操作。

独立于 LangGraph 工作流（不接入 planner/actor/verifier），供上层编排按需
调用：给定任务、指令、session 上下文与 memory 快照，模型在工作区内使用
文件/shell 工具实现计划，并经 ``todo_update`` 工具显式汇报 todo 进度；
``writer`` 实时接收 ``ai_message``/``tool_call``/``tool_result``/
``final_answer`` 事件。
"""

import json
from typing import Callable, Mapping, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from novagent.providers.openai_provider import create_model
from novagent.tools.registry import build_tools
from novagent.tools.todo_tools import create_todo_update_tool

CODE_AGENT_PROMPT = """You are codeAgent, a focused implementation specialist.

You implement the planner's instruction inside the workspace using file and
shell tools.

Rules:
- You must update todo progress explicitly.
- Before starting a todo, call TodoUpdateTool with status "in_progress".
- After finishing that todo, call TodoUpdateTool with status "completed".
- If a todo is impossible, call TodoUpdateTool with status "blocked" and explain.
- Use FileWriteTool for new files.
- Use FileReadTool before editing existing files.
- Use FileEditTool for focused edits.
- Use BashTool for non-interactive checks.
- Use NotepadAppendTool to record durable findings, decisions, important files,
  blockers, and next-step context that should survive compression.
- Use NotepadReadTool when you need to recover prior notes.
- BashTool already runs inside the workspace. Use relative paths, never "cd /workspace".
- Incorporate research notes and source URLs when the task asks for researched content.
- End with a concise summary of files changed and checks run.
"""

DEFAULT_MAX_LOOPS = 10

_VALID_STATUS = {"pending", "in_progress", "completed", "blocked"}


def build_memory_snapshot(state: Mapping) -> str:
    """返回 layered memory 快照；预留接口，后续 memory 阶段实现真实快照。"""
    return ""


def _response_text(response) -> str:
    content = response.content
    return content if isinstance(content, str) else str(content)


def _execute_tool(tool_map: dict, call: dict) -> str:
    """执行单个 tool_call；未知工具与异常都转为错误文本回传模型。"""
    tool = tool_map.get(call["name"])
    if tool is None:
        return f"Error: unknown tool {call['name']!r}"
    try:
        return str(tool.invoke(call.get("args") or {}))
    except Exception as exc:  # noqa: BLE001 - 错误需回传给模型
        return f"Error: {exc}"


def _apply_todo_update(todos: list, args: dict) -> None:
    todo_id = str(args.get("todo_id", ""))
    for todo in todos:
        if todo.get("id") == todo_id:
            status = args.get("status")
            if status in _VALID_STATUS:
                todo["status"] = status
            if args.get("note"):
                todo["note"] = str(args["note"])
            return
    # 未知 todo_id：todos 由计划产生，忽略即可（与 actor_node 一致）。


def run_code_agent(
    state: Mapping,
    instruction: str,
    *,
    writer: Optional[Callable[[dict], None]] = None,
    max_loops: int = DEFAULT_MAX_LOOPS,
    model: Optional[BaseChatModel] = None,
) -> dict:
    """运行代码专家 ReAct 循环，返回实现摘要与 todo 进度。

    ``state`` 为图状态样 dict-like 映射：``runtime``（``RuntimeState``，
    必需，缺失抛 ``ValueError``）约束工具的 workspace 根；``task``、
    ``todos``、``session_context`` 可缺失。``writer`` 可调用时逐个接收
    ``ai_message``/``tool_call``/``tool_result``/``final_answer`` 事件。
    ``model=None`` 时内部 ``create_model()``，可注入 FakeModel 离线测试。
    """
    runtime = state.get("runtime")
    if runtime is None:
        raise ValueError(
            "run_code_agent: state['runtime'] (RuntimeState with workspace) is required"
        )
    if model is None:
        model = create_model()
    tools = build_tools(runtime) + [create_todo_update_tool()]
    agent = model.bind_tools(tools)
    tool_map = {tool.name: tool for tool in tools}

    task = str(state.get("task") or "")
    session_context = str(state.get("session_context") or "")
    memory_snapshot = build_memory_snapshot(state)
    human_text = (
        f"Task: {task}\n\n"
        f"Instruction: {instruction}\n\n"
        "Session context:\n"
        f"{session_context or '(no session context)'}\n\n"
        "Memory snapshot:\n"
        f"{memory_snapshot or '(no memory snapshot)'}"
    )
    messages = [
        SystemMessage(content=CODE_AGENT_PROMPT),
        HumanMessage(content=human_text),
    ]

    todos = [dict(todo) for todo in state.get("todos") or []]
    tool_events: list = []
    new_messages: list = []

    def emit(event: dict) -> None:
        tool_events.append(event)
        if writer is not None:
            writer(event)

    last_ai_content = ""
    for _ in range(max_loops):
        response = agent.invoke(messages)
        messages.append(response)
        new_messages.append(response)
        last_ai_content = _response_text(response)
        emit({"type": "ai_message", "content": last_ai_content})

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break
        for call in tool_calls:
            emit(
                {
                    "type": "tool_call",
                    "name": call["name"],
                    "args": call.get("args", {}),
                }
            )
            result = _execute_tool(tool_map, call)
            messages.append(
                ToolMessage(
                    content=json.dumps(result),
                    tool_call_id=call.get("id") or "",
                )
            )
            new_messages.append(messages[-1])
            if call["name"] == "todo_update":
                _apply_todo_update(todos, call.get("args") or {})
            emit(
                {
                    "type": "tool_result",
                    "name": call["name"],
                    "result": result,
                }
            )

    emit({"type": "final_answer", "content": last_ai_content})
    return {
        "ok": True,
        "summary": last_ai_content,
        "todos": todos,
        "messages": new_messages,
        "tool_events": tool_events,
    }
