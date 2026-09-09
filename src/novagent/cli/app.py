"""typer CLI 入口：novagent 命令。"""

from pathlib import Path
from typing import Optional

import typer
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool

from novagent.core.state import RuntimeState
from novagent.providers.openai_provider import create_model
from novagent.tools.registry import build_tools

MAX_ITERATIONS = 25

app = typer.Typer(add_completion=False, help="NovAgent — 从 ToolCall 到通用 Agent。")


def _tool_system_prompt(state: RuntimeState) -> str:
    return (
        "You are NovAgent, a general agent that completes tasks by calling "
        "tools. All tools operate inside the workspace directory: "
        f"{state.workspace.resolve()}. Use read_file, write_file, edit_file, "
        "grep and bash to inspect and change files there. Prefer exact, "
        "verifiable actions, and when the task is finished reply with a "
        "short summary instead of calling tools."
    )


def _run_agent(
    model, tools: list[StructuredTool], state: RuntimeState, task: str
) -> str:
    """运行手工工具调用循环，返回模型最终文本回答。"""
    tool_map = {tool.name: tool for tool in tools}
    messages: list = [
        SystemMessage(content=_tool_system_prompt(state)),
        HumanMessage(content=task),
    ]
    for _ in range(MAX_ITERATIONS):
        ai_message: AIMessage = model.invoke(messages)
        messages.append(ai_message)
        tool_calls = getattr(ai_message, "tool_calls", None) or []
        if not tool_calls:
            return str(ai_message.content)
        for call in tool_calls:
            tool = tool_map.get(call["name"])
            if tool is None:
                result = f"Error: unknown tool {call['name']!r}"
            else:
                try:
                    result = str(tool.invoke(call["args"]))
                except Exception as exc:  # noqa: BLE001 - 错误需回传给模型
                    result = f"Error: {exc}"
            messages.append(
                ToolMessage(content=result, tool_call_id=call.get("id") or "")
            )
    return (
        f"Stopped after {MAX_ITERATIONS} model iterations without a final "
        "answer. Partial progress is recorded in the workspace."
    )


@app.command()
def run(
    task: str = typer.Argument(..., help="要交给 agent 完成的任务描述。"),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        help="工作区目录，不存在时自动创建；默认为当前目录下的 workspace。",
    ),
) -> None:
    """在 workspace 内用工具调用循环完成 task。"""
    workspace_path = workspace if workspace is not None else Path.cwd() / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)
    state = RuntimeState(workspace=workspace_path)
    typer.echo(f"Workspace: {state.workspace}")

    try:
        model = create_model()
    except ValueError as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    tools = build_tools(state)
    answer = _run_agent(model.bind_tools(tools), tools, state, task)
    typer.echo(answer)


def main() -> None:
    app()
