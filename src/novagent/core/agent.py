"""ReAct actor 循环：把执行过程作为事件流逐条产出。"""

import json
from pathlib import Path
from typing import Iterator, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from novagent.core.state import RuntimeState
from novagent.providers.openai_provider import create_model
from novagent.tools.registry import build_tools

ACTOR_PROMPT = """You are the actor node in novagent's ReAct workflow.

You implement the user's task using tools. Work inside the workspace only.

Rules:
- Use FileWriteTool for new files.
- Use FileReadTool before editing existing files.
- Use FileEditTool for focused edits.
- Use BashTool to run commands and test results.
- BashTool already runs inside the workspace. Use relative paths, never "cd /workspace".
- End with a concise summary of files changed and commands run.
"""


def _execute_tool(tool_map: dict, call: dict) -> str:
    """执行单个 tool_call；未知工具与异常都转为错误文本回传模型。"""
    tool = tool_map.get(call["name"])
    if tool is None:
        return f"Error: unknown tool {call['name']!r}"
    try:
        return str(tool.invoke(call["args"]))
    except Exception as exc:  # noqa: BLE001 - 错误需回传给模型
        return f"Error: {exc}"


def stream_agent_events(
    task: str,
    *,
    workspace: Path,
    max_loops: int = 10,
    model: Optional[BaseChatModel] = None,
) -> Iterator[dict]:
    """运行 ReAct 循环，把执行过程作为事件流逐条产出。

    事件为普通 dict（值均可 JSON 序列化），类型有：

    - ``ai_message``：模型每轮返回后立即产出，携带文本内容；
    - ``tool_call``：工具执行前产出，携带 ``name`` 与 ``args``；
    - ``tool_result``：工具执行后产出，携带原始返回字符串 ``result``；
    - ``final_answer``：循环结束时产出，内容为最后一轮 AI 消息文本。

    工具异常与未知工具名不向调用方抛出，统一转为 ``Error: ...`` 文本
    进入 ``ToolMessage`` 与 ``tool_result`` 事件，由模型下一轮修正。
    """
    state = RuntimeState(workspace=workspace)
    tools = build_tools(state)
    if model is None:
        model = create_model()
    agent = model.bind_tools(tools)
    tool_map = {tool.name: tool for tool in tools}

    messages: list = [
        SystemMessage(content=ACTOR_PROMPT),
        HumanMessage(content=task),
    ]
    last_ai_content = ""
    for _ in range(max_loops):
        response = agent.invoke(messages)
        messages.append(response)
        content = response.content
        last_ai_content = content if isinstance(content, str) else str(content)
        yield {"type": "ai_message", "content": last_ai_content}

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break
        for call in tool_calls:
            yield {
                "type": "tool_call",
                "name": call["name"],
                "args": call.get("args", {}),
            }
            result = _execute_tool(tool_map, call)
            messages.append(
                ToolMessage(
                    content=json.dumps(result),
                    tool_call_id=call.get("id") or "",
                )
            )
            yield {"type": "tool_result", "name": call["name"], "result": result}
    yield {"type": "final_answer", "content": last_ai_content}
