"""LangGraph 工作流节点：planner（supervisor）/ verifier / 上下文监控与压缩 / final 与条件路由。

节点与 LangGraph 节点签名兼容：第一个位置参数为状态 dict，返回普通
dict 更新。planner 的协调事件（含受托专家 Agent 的内部事件）经
``on_event`` 即时发出，事件 schema 与统一事件流一致。
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from novagent.agents.code_agent import run_code_agent
from novagent.agents.search_agent import run_search_agent
from novagent.core.state import RuntimeState
from novagent.graph.memory import (
    CODE_AGENT_SUMMARY_LIMIT,
    CONTEXT_SUMMARY_LIMIT,
    HISTORY_SUMMARY_LIMIT,
    RESEARCH_NOTES_LIMIT,
    _norm_sources,
    _short_text,
    _trim_handoffs,
    build_layered_memory,
    format_layered_memory_for_prompt,
)
from novagent.graph.state import AgentHandoff, SourceItem
from novagent.prompts.stage3 import PLANNER_PROMPT, VERIFIER_PROMPT
from novagent.prompts.stage4 import CONTEXT_COMPRESSION_PROMPT
from novagent.providers.openai_provider import create_model
from novagent.tools.bash_tool import create_bash_tool, execute_command
from novagent.tools.registry import build_read_only_tools
from novagent.tools.todo_tools import create_todo_write_tool
from novagent.tools.web_search_tool import WebSearchTool

DEFAULT_MAX_LOOPS = 10
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_CONTEXT_TOKEN_LIMIT = 400_000
DEFAULT_CONTEXT_NEXT_NODE = "verifier"

# 压缩摘要九键中除 summary 外各字段的截断上限
COMPRESSION_DETAIL_LIMIT = 800

_VALID_STATUS = {"pending", "in_progress", "completed", "blocked"}


def _format_failed_verification(result: dict) -> str:
    detail = result.get("stderr", "") or "exit code {}".format(result.get("exit_code"))
    return f"- {result.get('command', '')}: {detail}"


def _normalize_todo(raw) -> dict:
    if not isinstance(raw, dict):
        raw = {"content": str(raw)}
    status = raw.get("status")
    return {
        "id": str(raw.get("id", "")),
        "content": str(raw.get("content", "")),
        "status": status if status in _VALID_STATUS else "pending",
        "note": str(raw.get("note", "")),
    }


def _response_text(response) -> str:
    content = response.content
    return content if isinstance(content, str) else str(content)


def planner_node(
    state: dict,
    *,
    model: Optional[BaseChatModel] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    max_loops: int = DEFAULT_MAX_LOOPS,
) -> dict:
    """运行 supervisor 协调循环；每个事件经 ``on_event`` 即时发出。

    绑定三个工具：``todo_write`` 发布/修订计划、``call_search_agent``
    委托搜索、``call_code_agent`` 委托实现。委托产物写回返回更新：
    ``research_notes``/``sources``/``agent_handoffs``/``code_agent_summary``/
    ``todos``/``messages``（以及发生 ``todo_write`` 时的计划四字段）。
    """
    if model is None:
        model = create_model()

    # 上游设置约定：规划完成后进入验证，供 context_monitor_route 回环决策
    updates: dict = {"context_next_node": DEFAULT_CONTEXT_NEXT_NODE}
    handoffs: list[AgentHandoff] = []
    research_notes = str(state.get("research_notes") or "")
    sources: list[SourceItem] = list(state.get("sources") or [])
    seen_urls = {str(item.get("url") or "") for item in sources}

    def _writer(event: dict) -> None:
        if on_event is not None:
            on_event(event)

    def _delegation_state() -> dict:
        # 委托应看到本节点内已产生的更新（计划 todos、研究笔记），
        # 保证同一轮内多次委托链式一致。
        merged = dict(state)
        if "todos" in updates:
            merged["todos"] = updates["todos"]
        merged["research_notes"] = research_notes
        return merged

    def _call_search_agent_tool(state, writer, instruction):
        """委托 searchAgent 研究；更新 research_notes/sources/agent_handoffs。"""
        nonlocal research_notes
        writer(
            {
                "type": "handoff",
                "from": "planner",
                "to": "searchAgent",
                "instruction": instruction,
            }
        )
        result = run_search_agent(state, instruction, writer=writer, model=model)
        summary = str(result.get("summary") or "")
        research_notes = (
            f"{research_notes}\n\n{summary}" if research_notes else summary
        )
        updates["research_notes"] = research_notes
        new_items: list[SourceItem] = []
        for event in result.get("tool_events") or []:
            if event.get("type") != "search_results":
                continue
            payload = event.get("result") or {}
            if not payload.get("ok"):
                continue
            for item in payload.get("results") or []:
                url = str(item.get("url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                new_items.append(
                    {
                        "url": url,
                        "title": str(item.get("title") or ""),
                        "content": str(item.get("content") or ""),
                        "score": float(item.get("score") or 0.0),
                    }
                )
        if new_items:
            sources.extend(new_items)
            updates["sources"] = sources
        handoffs.append(
            {
                "from_agent": "planner",
                "to_agent": "searchAgent",
                "instruction": str(instruction),
                "result": summary,
            }
        )
        updates["agent_handoffs"] = handoffs
        return {
            "ok": True,
            "summary": summary,
            "queries": list(result.get("queries") or []),
            "sources": list(result.get("sources") or []),
        }

    def _call_code_agent_tool(state, writer, instruction):
        """委托 codeAgent 实现；更新 todos/code_agent_summary/agent_handoffs/messages。"""
        writer(
            {
                "type": "handoff",
                "from": "planner",
                "to": "codeAgent",
                "instruction": instruction,
            }
        )
        result = run_code_agent(state, instruction, writer=writer, model=model)
        summary = str(result.get("summary") or "")
        updates["todos"] = list(result.get("todos") or [])
        updates["code_agent_summary"] = summary
        # 同一轮内多次代码委托时累加，保持 reducer 并入语义
        updates["messages"] = (updates.get("messages") or []) + list(
            result.get("messages") or []
        )
        handoffs.append(
            {
                "from_agent": "planner",
                "to_agent": "codeAgent",
                "instruction": str(instruction),
                "result": summary,
            }
        )
        updates["agent_handoffs"] = handoffs
        return {"ok": True, "summary": summary}

    def _call_search_agent(instruction: str) -> dict:
        """Delegate web/document research to the searchAgent.

        Args:
            instruction: Research instruction for the search agent.

        Returns:
            A dict with ``ok``, the agent ``summary``, issued ``queries``
            and ``sources`` (URLs).
        """
        return _call_search_agent_tool(_delegation_state(), _writer, instruction)

    def _call_code_agent(instruction: str) -> dict:
        """Delegate file/code implementation to the codeAgent.

        Args:
            instruction: Implementation instruction for the code agent.

        Returns:
            A dict with ``ok`` and the agent ``summary``.
        """
        return _call_code_agent_tool(_delegation_state(), _writer, instruction)

    tools = [
        create_todo_write_tool(),
        StructuredTool.from_function(_call_search_agent, name="call_search_agent"),
        StructuredTool.from_function(_call_code_agent, name="call_code_agent"),
    ]
    agent = model.bind_tools(tools)
    tool_map = {tool.name: tool for tool in tools}

    task = str(state.get("task") or "")
    last_error = str(state.get("last_error") or "")
    if state.get("todos") and last_error:
        failed = [
            result
            for result in state.get("verification_results") or []
            if not result.get("ok")
        ]
        failed_lines = "\n".join(_format_failed_verification(r) for r in failed)
        instruction_text = (
            f"Task: {task}\n\n"
            "The previous plan failed and must be revised.\n"
            f"Last error: {last_error}\n"
            f"Failed verifications:\n{failed_lines or '(none)'}\n\n"
            "Revise the plan with the todo_write tool and delegate only "
            "the missing fix."
        )
    else:
        instruction_text = (
            f"Task: {task}\n\n"
            "Create a plan with the todo_write tool, then delegate "
            "specialist work as needed."
        )

    messages = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=instruction_text),
    ]

    last_ai_content = ""
    for _ in range(max_loops):
        response = agent.invoke(messages)
        messages.append(response)
        last_ai_content = _response_text(response)
        _writer({"type": "ai_message", "content": last_ai_content})

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break
        for call in tool_calls:
            _writer(
                {
                    "type": "tool_call",
                    "name": call["name"],
                    "args": call.get("args", {}),
                }
            )
            if call["name"] == "todo_write":
                args = call.get("args") or {}
                updates["plan_summary"] = str(args.get("plan_summary", ""))
                updates["todos"] = [
                    _normalize_todo(raw) for raw in args.get("todos") or []
                ]
                updates["acceptance_criteria"] = [
                    str(c) for c in args.get("acceptance_criteria") or []
                ]
                updates["verification_commands"] = [
                    str(c) for c in args.get("verification_commands") or []
                ]
                result: object = "Plan submitted."
            else:
                tool = tool_map.get(call["name"])
                if tool is None:
                    result = f"Error: unknown tool {call['name']!r}"
                else:
                    try:
                        result = tool.invoke(call.get("args") or {})
                    except Exception as exc:  # noqa: BLE001 - 错误需回传给模型
                        result = f"Error: {exc}"
            messages.append(
                ToolMessage(
                    content=json.dumps(result),
                    tool_call_id=call.get("id") or "",
                )
            )
            _writer({"type": "tool_result", "name": call["name"], "result": result})

    return updates


def verifier_node(state: dict, *, model: Optional[BaseChatModel] = None) -> dict:
    """只读核查验收标准，运行验证命令，产出验收结论。"""
    runtime = _require_runtime(state, "verifier_node")
    if model is None:
        model = create_model()
    tools = build_read_only_tools(runtime) + [
        create_bash_tool(runtime),
        WebSearchTool,
    ]
    agent = model.bind_tools(tools)
    tool_map = {tool.name: tool for tool in tools}

    commands = state.get("verification_commands") or []
    human_text = (
        f"Task: {state.get('task', '')}\n\n"
        f"Plan summary: {state.get('plan_summary', '')}\n\n"
        f"Acceptance criteria:\n"
        + "\n".join(f"- {c}" for c in state.get("acceptance_criteria") or [])
        + "\n\nVerification commands (already executed):\n"
        + "\n".join(f"- {c}" for c in commands or [])
        + f"\n\nLast actor output:\n{state.get('last_actor_summary', '')}\n\n"
        "Inspect the workspace with the read-only tools, then reply with "
        "a JSON object {\"passed\": bool, \"reason\": str, \"checks\": "
        "[{\"name\", \"passed\", \"detail\"}], \"recommended_next_instruction\": str}."
    )
    messages = [
        SystemMessage(content=VERIFIER_PROMPT),
        HumanMessage(content=human_text),
    ]

    last_ai_content = ""
    for _ in range(DEFAULT_MAX_LOOPS):
        response = agent.invoke(messages)
        messages.append(response)
        last_ai_content = _response_text(response)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break
        for call in tool_calls:
            result = _execute_tool(tool_map, call)
            messages.append(
                ToolMessage(
                    content=json.dumps(result),
                    tool_call_id=call.get("id") or "",
                )
            )

    parsed = _parse_verifier_json(last_ai_content)
    verification_results = _run_verification_commands(runtime.workspace, commands)
    commands_ok = all(result["ok"] for result in verification_results)
    passed = bool(parsed and parsed.get("passed")) and commands_ok

    attempts = int(state.get("attempts") or 0) + 1
    update = {
        "passed": passed,
        "attempts": attempts,
        "verification_results": verification_results,
        "verification_checks": _normalize_checks(parsed.get("checks") if parsed else []),
    }
    todos = [dict(todo) for todo in state.get("todos") or []]
    if passed:
        update["last_error"] = ""
        update["final_answer"] = str(parsed.get("reason", ""))
        for todo in todos:
            if todo.get("status") != "completed":
                todo["status"] = "completed"
    else:
        update["last_error"] = _build_last_error(parsed, last_ai_content, verification_results)
        for todo in todos:
            if todo.get("status") == "in_progress":
                todo["status"] = "blocked"
    if todos:
        update["todos"] = todos
    if not passed and attempts < state.get("max_attempts", DEFAULT_MAX_ATTEMPTS):
        # 上游设置约定：失败且预算未尽时回到 planner 修订
        update["context_next_node"] = "planner"
    return update


def _execute_tool(tool_map: dict, call: dict) -> str:
    """执行单个 tool_call；未知工具与异常都转为错误文本回传模型。"""
    tool = tool_map.get(call["name"])
    if tool is None:
        return f"Error: unknown tool {call['name']!r}"
    try:
        return str(tool.invoke(call["args"]))
    except Exception as exc:  # noqa: BLE001 - 错误需回传给模型
        return f"Error: {exc}"


def _require_runtime(state: dict, node_name: str) -> RuntimeState:
    runtime = state.get("runtime")
    if runtime is None:
        raise ValueError(
            f"{node_name}: state['runtime'] (RuntimeState with workspace) is required"
        )
    return runtime


def _run_verification_commands(workspace, commands) -> list:
    results = []
    for command in commands:
        try:
            exit_code, stdout, stderr = execute_command(command, cwd=workspace)
        except Exception as exc:  # noqa: BLE001 - 超时等异常记为失败结果
            results.append(
                {
                    "command": command,
                    "ok": False,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": f"Error: {exc}",
                }
            )
            continue
        results.append(
            {
                "command": command,
                "ok": exit_code == 0,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
            }
        )
    return results


def _normalize_checks(raw_checks) -> list:
    checks = []
    for raw in raw_checks or []:
        if not isinstance(raw, dict):
            checks.append({"name": str(raw), "passed": False, "detail": ""})
            continue
        checks.append(
            {
                "name": str(raw.get("name", "")),
                "passed": bool(raw.get("passed")),
                "detail": str(raw.get("detail", "")),
            }
        )
    return checks


def _parse_verifier_json(text: str):
    cleaned = text.strip()
    for candidate in (
        cleaned,
        _strip_code_fence(cleaned),
        _extract_json_object(cleaned),
    ):
        if candidate is None:
            continue
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _strip_code_fence(text: str):
    if not text.startswith("```"):
        return None
    lines = text.splitlines()
    if len(lines) < 2:
        return None
    body = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    return body.strip() or None


def _extract_json_object(text: str):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    return text[start : end + 1]


def _build_last_error(parsed, raw_text: str, verification_results: list) -> str:
    parts = []
    for result in verification_results:
        if not result["ok"]:
            detail = result["stderr"] or result["stdout"] or "(no output)"
            parts.append(f"command failed ({result['command']}): {detail}".rstrip())
    if parsed is None:
        parts.append(f"verifier did not return valid JSON: {raw_text[:200]}")
    elif parsed.get("reason"):
        parts.append(str(parsed["reason"]))
    return "\n".join(parts)


def final_node(state: dict) -> dict:
    """确定性格式化最终结论；不调用模型、不修改 ``passed``。"""
    attempts = state.get("attempts") or 0
    if state.get("passed"):
        reason = state.get("final_answer") or state.get("last_actor_summary") or ""
        answer = f"Task completed in {attempts} attempt(s). {reason}".strip()
    else:
        answer = (
            f"Task failed after {attempts} attempt(s).\n"
            f"Last error: {state.get('last_error') or '(unknown)'}"
        )
    return {"final_answer": answer}


def _estimate_tokens(messages, model) -> int:
    """优先用模型的 tokenizer 计数；不可用时按字符数粗估（约 4 字符/token）。"""
    if model is not None:
        try:
            return int(model.get_num_tokens_from_messages(messages))
        except Exception:  # noqa: BLE001 - 估算失败一律落入字符粗估
            pass
    text = "".join(_response_text(message) for message in messages)
    return len(text) // 4


def context_monitor_node(state: dict, *, model=None) -> dict:
    """估算当前上下文 token 数并判定是否需要压缩（确定性节点，不调模型对话）。

    计数输入为 ``messages + [memory_payload]``，其中 memory payload 为
    分层记忆快照的 JSON 文本（复用 ``novagent.graph.memory``）。压缩判定
    为严格大于 ``context_token_limit``（缺失默认 400000）；
    ``context_next_node`` 由上游节点设置，本节点仅透传。
    """
    memory_payload = HumanMessage(
        content=format_layered_memory_for_prompt(build_layered_memory(state))
    )
    counted = list(state.get("messages") or []) + [memory_payload]

    token_count = _estimate_tokens(counted, model)
    limit = state.get("context_token_limit") or DEFAULT_CONTEXT_TOKEN_LIMIT
    return {
        "context_token_count": token_count,
        "context_should_compress": token_count > limit,
        "context_next_node": state.get("context_next_node")
        or DEFAULT_CONTEXT_NEXT_NODE,
    }


def context_monitor_route(state: dict) -> str:
    """context monitor 之后的条件路由（build_complex_workflow 接线）。

    优先级：passed → final；预算耗尽 → final（verifier 无条件边直连
    final，终止语义由本路由承担）；应压缩 → context_compressor；否则
    按上游设置的 ``context_next_node`` 回环（缺失默认 verifier）。
    """
    if state.get("passed"):
        return "final"
    attempts = state.get("attempts") or 0
    if attempts >= state.get("max_attempts", DEFAULT_MAX_ATTEMPTS):
        return "final"
    if state.get("context_should_compress"):
        return "context_compressor"
    return state.get("context_next_node") or DEFAULT_CONTEXT_NEXT_NODE


_COMPRESSION_FIELD_KEYS = (
    "active_goal",
    "completed_work",
    "open_todos",
    "important_files",
    "tool_findings",
    "sources",
    "next_steps",
    "risks",
)

_COMPRESSION_FIELD_TITLES = {
    "summary": "Summary",
    "active_goal": "Active Goal",
    "completed_work": "Completed Work",
    "open_todos": "Open Todos",
    "important_files": "Important Files",
    "tool_findings": "Tool Findings",
    "sources": "Sources",
    "next_steps": "Next Steps",
    "risks": "Risks",
}


def _estimate_text_tokens(text) -> int:
    """按字符数粗估 token（约 4 字符/token）；空文本为 0。

    与 monitor 的 ``_estimate_tokens(messages, model)`` 区分：本函数只面向
    纯文本，供压缩节点估算压缩前后规模，不引入 tokenizer 依赖。
    """
    value = str(text or "")
    if not value:
        return 0
    return max(1, len(value) // 4)


def _message_transcript(messages) -> str:
    """把消息列表格式化为 ``序号. [type] content`` 的多行文本。"""
    lines = []
    for index, message in enumerate(messages, start=1):
        kind = getattr(message, "type", "message")
        lines.append(f"{index}. [{kind}] {_response_text(message)}")
    return "\n".join(lines)


def _fallback_summary(messages) -> str:
    """LLM 响应不可解析时的确定性回退摘要：既有消息文本的截断拼接。"""
    text = "\n".join(_response_text(message) for message in messages)
    return _short_text(text, CONTEXT_SUMMARY_LIMIT)


def _persist_history_summary(workspace, summary: str, fields: dict) -> None:
    """把九个截断后的压缩字段写成 Markdown 小节；失败静默跳过。"""
    lines = [
        "# History Summary",
        "",
        f"Compressed by context_compressor_node at "
        f"{datetime.now(timezone.utc).isoformat()}.",
        "",
    ]
    keyed_fields = {"summary": summary, **fields}
    for key, title in _COMPRESSION_FIELD_TITLES.items():
        lines.append(f"## {title}")
        lines.append(keyed_fields.get(key) or "(empty)")
        lines.append("")
    try:
        (Path(workspace) / "HISTORY_SUMMARY.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )
    except OSError:
        pass


def context_compressor_node(state: dict, *, model=None) -> dict:
    """用 LLM 把消息历史压缩为结构化摘要并重置消息窗口。

    计数输入为当前全部消息与分层记忆快照；LLM 返回九键 JSON（容忍代码
    围栏），解析失败时回退为既有消息的截断拼接。压缩后以
    ``RemoveMessage(id=REMOVE_ALL_MESSAGES) + AIMessage(summary)`` 替换
    消息历史，九字段截断后持久化到 ``HISTORY_SUMMARY.md``，并追加一条
    ``CompressionEvent``；解析或持久化失败均不抛异常。
    """
    if model is None:
        model = create_model()

    messages = list(state.get("messages") or [])
    transcript = _message_transcript(messages)
    memory_text = format_layered_memory_for_prompt(
        build_layered_memory(state, node="context_compressor")
    )

    human_text = (
        f"Task: {state.get('task') or ''}\n\n"
        f"Current messages:\n{transcript or '(no messages)'}\n\n"
        f"Layered memory snapshot (JSON):\n{memory_text}"
    )
    response = model.invoke(
        [
            SystemMessage(content=CONTEXT_COMPRESSION_PROMPT),
            HumanMessage(content=human_text),
        ]
    )

    parsed = _parse_verifier_json(_response_text(response))
    if parsed is None:
        summary = _fallback_summary(messages)
        fields = {key: "" for key in _COMPRESSION_FIELD_KEYS}
    else:
        summary = _short_text(
            str(parsed.get("summary") or ""), CONTEXT_SUMMARY_LIMIT
        )
        fields = {
            key: _short_text(str(parsed.get(key) or ""), COMPRESSION_DETAIL_LIMIT)
            for key in _COMPRESSION_FIELD_KEYS
        }

    compression_events = list(state.get("compression_events") or [])
    compression_events.append(
        {
            "node": "context_compressor",
            "reason": "context window compressed for resume",
            "token_count": _estimate_text_tokens(transcript),
            "token_limit": int(state.get("context_token_limit") or 0),
            "summary": summary,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    workspace = getattr(state.get("runtime"), "workspace", None)
    if workspace is not None:
        _persist_history_summary(workspace, summary, fields)

    return {
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            AIMessage(content=summary),
        ],
        "context_summary": summary,
        "context_token_count": _estimate_text_tokens(summary),
        "context_should_compress": False,
        "research_notes": _short_text(
            state.get("research_notes") or "", RESEARCH_NOTES_LIMIT
        ),
        "agent_handoffs": _trim_handoffs(state.get("agent_handoffs") or []),
        "sources": _norm_sources(state.get("sources") or []),
        "code_agent_summary": _short_text(
            state.get("code_agent_summary") or "", CODE_AGENT_SUMMARY_LIMIT
        ),
        "history_summary": _short_text(summary, HISTORY_SUMMARY_LIMIT),
        "compression_events": compression_events,
    }


def context_compressor_route(state: dict) -> str:
    """context compressor 之后的条件路由：按上游设置的 ``context_next_node`` 回环。"""
    return state.get("context_next_node") or DEFAULT_CONTEXT_NEXT_NODE
