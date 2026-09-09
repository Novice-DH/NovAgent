"""LangGraph 工作流节点：planner / actor / verifier 与条件路由。

节点与 LangGraph 节点签名兼容：第一个位置参数为状态 dict，返回普通
dict 更新。事件不通过生成器产出（LangGraph 节点不能 yield），而是经
``on_event`` 回调即时发出，事件 schema 与 ``core.agent.stream_agent_events``
完全一致。
"""

import json
from typing import Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from novagent.core.agent import ACTOR_PROMPT, _execute_tool
from novagent.core.state import RuntimeState
from novagent.providers.openai_provider import create_model
from novagent.tools.bash_tool import execute_command
from novagent.tools.registry import build_read_only_tools, build_tools
from novagent.tools.todo_tools import create_todo_update_tool, create_todo_write_tool

DEFAULT_MAX_LOOPS = 10
DEFAULT_MAX_ATTEMPTS = 3

_VALID_STATUS = {"pending", "in_progress", "completed", "blocked"}

PLANNER_PROMPT = """You are the planner node in novagent's LangGraph workflow.

You break the user's task into an executable plan.

Rules:
- Submit the plan by calling the todo_write tool exactly once.
- todos are ordered concrete steps; each has a unique id, a content
  description, a status (start every step as "pending") and a note.
- acceptance_criteria are observable statements that mean "done".
- verification_commands are shell commands (run inside the workspace)
  that objectively check the acceptance criteria.
- When asked to revise, address the reported failure while keeping the
  rest of the plan stable.
"""

VERIFIER_PROMPT = """You are the verifier node in novagent's LangGraph workflow.

You verify the actor's work. You are read-only: inspect the workspace
with the read-only tools, never try to fix anything.

Rules:
- Check every acceptance criterion against the actual workspace state.
- Take the already-executed verification commands and their results
  into account.
- Reply with a single JSON object and nothing else:
  {"passed": bool, "reason": str, "checks": [{"name": str, "passed": bool,
  "detail": str}], "recommended_next_instruction": str}
- "passed" is true only when every acceptance criterion is met.
"""


def _format_failed_verification(result: dict) -> str:
    detail = result.get("stderr", "") or "exit code {}".format(result.get("exit_code"))
    return f"- {result.get('command', '')}: {detail}"


def _render_todos(todos) -> str:
    if not todos:
        return "(no todos yet)"
    lines = []
    for todo in todos:
        lines.append(
            f"- [{todo.get('id', '')}] {todo.get('content', '')}"
            f" ({todo.get('status', 'pending')}) {todo.get('note', '')}".rstrip()
        )
    return "\n".join(lines)


def _emit(on_event: Optional[Callable[[dict], None]], event: dict) -> None:
    if on_event is not None:
        on_event(event)


def _response_text(response) -> str:
    content = response.content
    return content if isinstance(content, str) else str(content)


def planner_node(state: dict, *, model: Optional[BaseChatModel] = None) -> dict:
    """生成或修订计划；结构化输出经 ``todo_write`` 工具提交。"""
    if model is None:
        model = create_model()
    agent = model.bind_tools([create_todo_write_tool()])

    task = state.get("task", "")
    last_error = state.get("last_error") or ""
    if state.get("todos") and last_error:
        failed = [
            result
            for result in state.get("verification_results") or []
            if not result.get("ok")
        ]
        failed_lines = "\n".join(_format_failed_verification(r) for r in failed)
        instruction = (
            f"Task: {task}\n\n"
            "The previous plan failed and must be revised.\n"
            f"Last error: {last_error}\n"
            f"Failed verifications:\n{failed_lines or '(none)'}\n\n"
            "Submit a revised plan with the todo_write tool."
        )
    else:
        instruction = f"Task: {task}\n\nCreate a plan and submit it with the todo_write tool."

    messages = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=instruction),
    ]
    response = agent.invoke(messages)
    call = next(
        (
            c
            for c in getattr(response, "tool_calls", None) or []
            if c["name"] == "todo_write"
        ),
        None,
    )
    if call is None:
        raise ValueError(
            "planner_node: the model did not submit a plan via the todo_write tool"
        )
    args = call.get("args", {})
    return {
        "plan_summary": str(args.get("plan_summary", "")),
        "todos": [_normalize_todo(raw) for raw in args.get("todos") or []],
        "acceptance_criteria": [str(c) for c in args.get("acceptance_criteria") or []],
        "verification_commands": [
            str(c) for c in args.get("verification_commands") or []
        ],
    }


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


def actor_node(
    state: dict,
    *,
    model: Optional[BaseChatModel] = None,
    on_event: Optional[Callable[[dict], None]] = None,
) -> dict:
    """运行 actor ReAct 循环；每个事件经 ``on_event`` 即时发出。"""
    runtime = _require_runtime(state, "actor_node")
    if model is None:
        model = create_model()
    tools = build_tools(runtime) + [create_todo_update_tool()]
    agent = model.bind_tools(tools)
    tool_map = {tool.name: tool for tool in tools}

    human_text = (
        f"Task: {state.get('task', '')}\n\n"
        f"Plan summary: {state.get('plan_summary', '')}\n\n"
        f"Todos:\n{_render_todos(state.get('todos') or [])}"
    )
    messages = [
        SystemMessage(content=ACTOR_PROMPT),
        HumanMessage(content=human_text),
    ]

    todos = [dict(todo) for todo in state.get("todos") or []]
    todos_changed = False
    new_messages = []
    last_ai_content = ""
    for _ in range(DEFAULT_MAX_LOOPS):
        response = agent.invoke(messages)
        messages.append(response)
        new_messages.append(response)
        last_ai_content = _response_text(response)
        _emit(on_event, {"type": "ai_message", "content": last_ai_content})

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break
        for call in tool_calls:
            _emit(
                on_event,
                {"type": "tool_call", "name": call["name"], "args": call.get("args", {})},
            )
            result = _execute_tool(tool_map, call)
            tool_message = ToolMessage(
                content=json.dumps(result),
                tool_call_id=call.get("id") or "",
            )
            messages.append(tool_message)
            new_messages.append(tool_message)
            _emit(on_event, {"type": "tool_result", "name": call["name"], "result": result})
            if call["name"] == "todo_update":
                _apply_todo_update(todos, call.get("args", {}))
                todos_changed = True

    _emit(on_event, {"type": "final_answer", "content": last_ai_content})
    update = {"messages": new_messages, "last_actor_summary": last_ai_content}
    if todos_changed:
        update["todos"] = todos
    return update


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
    # 未知 todo_id：todos 由 planner 计划产生，actor 不能新增，忽略即可。


def verifier_node(state: dict, *, model: Optional[BaseChatModel] = None) -> dict:
    """只读核查验收标准，运行验证命令，产出验收结论。"""
    runtime = _require_runtime(state, "verifier_node")
    if model is None:
        model = create_model()
    tools = build_read_only_tools(runtime)
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
    return update


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


def verifier_route(state: dict) -> str:
    """verifier 之后的条件路由：通过或预算耗尽走 ``final``，否则回 planner。"""
    if state.get("passed"):
        return "final"
    attempts = state.get("attempts") or 0
    if attempts >= state.get("max_attempts", DEFAULT_MAX_ATTEMPTS):
        return "final"
    return "planner"
