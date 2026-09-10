"""搜索专家 Agent：手写 ReAct 循环驱动 WebSearchTool 完成事实研究。

独立于 LangGraph 工作流（不接入 planner/actor/verifier），供上层编排按需
调用：给定任务、指令与已有研究笔记，模型自主发起 ``web_search`` 工具调用，
循环结束后返回研究摘要、已用查询与来源 URL 列表；``writer`` 可实时接收
``tool_call``/``search_results`` 事件。
"""

import json
from typing import Callable, Mapping, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from novagent.providers.openai_provider import create_model
from novagent.tools.web_search_tool import WebSearchTool

SEARCH_AGENT_PROMPT = """You are searchAgent, a focused research specialist.

Your only external capability is WebSearchTool. Search for reliable information
needed by the planner and codeAgent.

Rules:
- Use WebSearchTool for factual research.
- Prefer official or encyclopedia-style sources when available.
- Return a concise research summary and list the useful source URLs.
- Do not write files or produce application code.
"""

DEFAULT_MAX_LOOPS = 4


def _response_text(response) -> str:
    content = response.content
    return content if isinstance(content, str) else str(content)


def _execute_tool(tool_map: dict, call: dict) -> dict:
    """执行单个 tool_call；未知工具与异常都转为结构化错误 dict 回传模型。"""
    tool = tool_map.get(call["name"])
    if tool is None:
        return {"ok": False, "error": f"unknown tool {call['name']!r}"}
    args = call.get("args") or {}
    try:
        return tool.invoke(args)
    except Exception as exc:  # noqa: BLE001 - 错误需回传给模型
        return {"ok": False, "query": str(args.get("query", "")), "error": str(exc)}


def run_search_agent(
    state: Mapping,
    instruction: str,
    *,
    writer: Optional[Callable[[dict], None]] = None,
    max_loops: int = DEFAULT_MAX_LOOPS,
    model: Optional[BaseChatModel] = None,
) -> dict:
    """运行搜索专家 ReAct 循环，返回研究摘要、查询与来源。

    ``state`` 为图状态样 dict-like 映射，读取 ``task`` 与 ``research_notes``
    （均可缺失）；``instruction`` 是本次研究任务的指令；``writer`` 可调用时
    逐个接收 ``tool_call``/``search_results`` 事件。``model=None`` 时内部
    ``create_model()``，可注入 FakeModel 离线测试。
    """
    if model is None:
        model = create_model()
    agent = model.bind_tools([WebSearchTool])
    tool_map = {"web_search": WebSearchTool}

    task = str(state.get("task") or "")
    research_notes = str(state.get("research_notes") or "")
    human_text = (
        f"Task: {task}\n\n"
        f"Instruction: {instruction}\n\n"
        "Existing research notes:\n"
        f"{research_notes or '(no research notes yet)'}"
    )
    messages = [
        SystemMessage(content=SEARCH_AGENT_PROMPT),
        HumanMessage(content=human_text),
    ]

    queries: list = []
    sources: list = []
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
            if call["name"] == "web_search":
                query = str((call.get("args") or {}).get("query", ""))
                queries.append(query)
                if result.get("ok"):
                    for item in result.get("results") or []:
                        url = str(item.get("url") or "")
                        if url and url not in sources:
                            sources.append(url)
            emit(
                {
                    "type": "search_results",
                    "name": call["name"],
                    "query": str((call.get("args") or {}).get("query", "")),
                    "result": result,
                }
            )

    return {
        "ok": True,
        "summary": last_ai_content,
        "queries": queries,
        "sources": sources,
        "messages": new_messages,
        "tool_events": tool_events,
    }
