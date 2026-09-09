"""typer CLI 入口：novagent 命令。"""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape

from novagent.core.agent import stream_agent_events
from novagent.providers.openai_provider import create_model

app = typer.Typer(add_completion=False, help="NovAgent — 从 ToolCall 到通用 Agent。")
console = Console()
error_console = Console(stderr=True, style="red")


def _print_event(event: dict) -> None:
    """把一条 agent 事件实时打印到终端。"""
    kind = event["type"]
    if kind == "ai_message":
        console.print(escape(str(event["content"])))
    elif kind == "tool_call":
        console.print(
            f"[bold cyan]→[/bold cyan] {escape(str(event['name']))}"
            f" {escape(str(event['args']))}"
        )
    elif kind == "tool_result":
        console.print(f"[dim]{escape(str(event['result']))}[/dim]")
    elif kind == "final_answer":
        console.print(f"[bold green]{escape(str(event['content']))}[/bold green]")


@app.command()
def run(
    task: str = typer.Argument(..., help="要交给 agent 完成的任务描述。"),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        help="工作区目录，不存在时自动创建；默认为当前目录下的 workspace。",
    ),
) -> None:
    """在 workspace 内用 ReAct 循环完成 task，实时打印每个事件。"""
    workspace_path = workspace if workspace is not None else Path.cwd() / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)
    console.print(f"Workspace: {escape(str(workspace_path))}")

    try:
        model = create_model()
    except ValueError as exc:
        error_console.print(f"Configuration error: {escape(str(exc))}")
        raise typer.Exit(code=1) from exc

    for event in stream_agent_events(task, workspace=workspace_path, model=model):
        _print_event(event)


def main() -> None:
    app()
