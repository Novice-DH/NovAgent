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


def _print_todos(todos) -> None:
    for todo in todos:
        console.print(
            f"   • {escape(str(todo.get('id', '')))} "
            f"{escape(str(todo.get('content', '')))} "
            f"[dim]({escape(str(todo.get('status', 'pending')))})[/dim]"
        )


def _print_event(event: dict, state: dict) -> None:
    """把一条统一事件渲染到终端；state 承载跨事件的渲染状态。"""
    kind = event["type"]
    node = event.get("node", "")
    if kind == "node_output":
        if node == "planner":
            console.print(f"[bold blue]📋 Planner[/bold blue] {escape(str(event['plan_summary']))}")
            _print_todos(event.get("todos") or [])
        elif node == "verifier":
            if event.get("passed"):
                console.print(f"[bold green]✅ Verifier[/bold green] {escape(str(event['reason']))}")
            else:
                console.print(f"[bold red]❌ Verifier[/bold red] {escape(str(event['reason']))}")
            for result in event.get("verification_results") or []:
                if result.get("ok"):
                    status = "exit 0"
                elif result.get("exit_code") is None:
                    status = "failed to run"
                else:
                    status = f"exit {result['exit_code']}"
                console.print(
                    f"   [dim]$ {escape(str(result.get('command', '')))}"
                    f" → {escape(status)}[/dim]"
                )
        elif node == "final":
            console.print("[bold magenta]📝 Final[/bold magenta]")
            console.print(escape(str(event["final_answer"])))
        return
    if node == "actor":
        if kind == "final_answer":
            return
        if not state.get("actor_header"):
            console.print("[bold yellow]🔧 Actor[/bold yellow]")
            state["actor_header"] = True
        if kind == "ai_message":
            console.print(escape(str(event["content"])))
        elif kind == "tool_call":
            console.print(
                f"[bold cyan]→[/bold cyan] {escape(str(event['name']))}"
                f" {escape(str(event['args']))}"
            )
        elif kind == "tool_result":
            console.print(f"[dim]{escape(str(event['result']))}[/dim]")


@app.command()
def run(
    task: str = typer.Argument(..., help="要交给 agent 完成的任务描述。"),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        help="工作区目录，不存在时自动创建；默认为当前目录下的 workspace。",
    ),
    max_attempts: int = typer.Option(
        3,
        "--max-attempts",
        min=1,
        help="验证失败后回 planner 修订的最大尝试次数。",
    ),
) -> None:
    """在 workspace 内运行 planner→actor→verifier 工作流完成 task，实时打印节点输出。"""
    workspace_path = workspace if workspace is not None else Path.cwd() / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)
    console.print(f"Workspace: {escape(str(workspace_path))}")

    try:
        model = create_model()
    except ValueError as exc:
        error_console.print(f"Configuration error: {escape(str(exc))}")
        raise typer.Exit(code=1) from exc

    render_state: dict = {}
    for event in stream_agent_events(
        task, workspace=workspace_path, max_attempts=max_attempts, model=model
    ):
        _print_event(event, render_state)


def main() -> None:
    app()
