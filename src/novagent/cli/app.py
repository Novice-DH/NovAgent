"""typer CLI 入口：novagent 命令。"""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape

from novagent.core.agent import stream_agent_events
from novagent.core.approval import ApprovalDecision, ApprovalRequest
from novagent.core.checkpoint import CHECKPOINT_FILE, resume_command
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


def _console_approval_handler(request: ApprovalRequest) -> ApprovalDecision:
    """inline 审批的终端确认：y/yes 批准，n/no/空/EOF 拒绝。"""
    console.print("[bold yellow]⚠️  Human Approval Required[/bold yellow]")
    console.print(f"    Tool: {escape(request.tool_name)}")
    console.print(f"    Risk: {escape(request.risk_reason)}")
    console.print(f"    Command: {escape(request.command)}")
    while True:
        try:
            choice = console.input("    [Y] Approve  [N] Deny > ")
        except EOFError:
            return ApprovalDecision(approved=False, reason="no interactive input")
        choice = choice.strip().lower()
        if choice in {"y", "yes"}:
            return ApprovalDecision(approved=True, reason="approved by user")
        if choice in {"n", "no", ""}:
            return ApprovalDecision(approved=False, reason="rejected by user")
        console.print("    请输入 y 或 n")


def _print_event(event: dict, state: dict) -> None:
    """把一条统一事件渲染到终端；state 承载跨事件的渲染状态。"""
    kind = event["type"]
    node = event.get("node", "")
    if kind == "checkpoint_saved":
        console.print(
            f"💾 Checkpoint saved [dim]({escape(str(event.get('mode', '')))} mode, "
            f"{escape(str(event.get('status', '')))}, "
            f"node={escape(str(event.get('latest_node') or ''))})[/dim]"
        )
        return
    if kind == "resumed":
        console.print(
            f"🔄 Resumed from checkpoint [dim](task="
            f"{escape(str(event.get('task') or ''))}, node="
            f"{escape(str(event.get('latest_node') or ''))}, "
            f"attempts={escape(str(event.get('attempts', 0)))})[/dim]"
        )
        git_error = str(event.get("git_error") or "")
        if git_error:
            console.print(
                f"   [yellow]⚠ 文件恢复失败：{escape(git_error)}[/yellow]"
            )
        return
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
    task: Optional[str] = typer.Argument(
        None, help="要交给 agent 完成的任务描述；--resume 时可省略（默认取检查点中的任务）。"
    ),
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
    approval_mode: str = typer.Option(
        "inline",
        "--approval-mode",
        help="风险命令审批模式：inline（终端确认）/ auto（放行并标记）/ deny（拒绝）。",
    ),
    checkpoint_mode: str = typer.Option(
        "light",
        "--checkpoint-mode",
        help="检查点级别：light（元数据+恢复指南+git 快照）/ strict（另存完整状态与事件）/ off。",
    ),
    trace_mode: str = typer.Option(
        "on",
        "--trace-mode",
        help="链路追踪开关：on（记录 trace.json/events.jsonl/timeline.md）/ off。",
    ),
    resume: Optional[Path] = typer.Option(
        None,
        "--resume",
        help="从该 workspace 的 .novagent/checkpoints 检查点恢复运行。",
    ),
) -> None:
    """在 workspace 内运行 planner→verifier 工作流完成 task，实时打印节点输出。"""
    resume_path = resume.expanduser().absolute() if resume is not None else None
    if resume_path is not None:
        if (
            workspace is not None
            and workspace.expanduser().absolute() != resume_path
        ):
            error_console.print(
                f"--workspace 与 --resume 指向不同目录："
                f"{escape(str(workspace))} vs {escape(str(resume_path))}"
            )
            raise typer.Exit(code=2)
        workspace_path = resume_path
        if not (resume_path / ".novagent" / "checkpoints" / CHECKPOINT_FILE).exists():
            error_console.print(
                f"no checkpoint found in {escape(str(resume_path))}"
            )
            raise typer.Exit(code=1)
    else:
        if task is None:
            error_console.print(
                "缺少 task：直接运行请提供任务描述；从检查点恢复请使用 --resume <workspace>。"
            )
            raise typer.Exit(code=2)
        workspace_path = workspace if workspace is not None else Path.cwd() / "workspace"
        workspace_path.mkdir(parents=True, exist_ok=True)
    console.print(f"Workspace: {escape(str(workspace_path))}")

    try:
        model = create_model()
    except ValueError as exc:
        error_console.print(f"Configuration error: {escape(str(exc))}")
        raise typer.Exit(code=1) from exc

    render_state: dict = {}
    try:
        for event in stream_agent_events(
            task,
            workspace=workspace_path,
            max_attempts=max_attempts,
            model=model,
            approval_mode=approval_mode,
            approval_handler=(
                _console_approval_handler if approval_mode == "inline" else None
            ),
            checkpoint_mode=checkpoint_mode,
            trace_mode=trace_mode,
            resume_workspace=resume_path,
        ):
            _print_event(event, render_state)
    except KeyboardInterrupt:
        console.print(
            f"\n[bold yellow]⏸ Interrupted.[/bold yellow] Resume with: "
            f"{escape(resume_command(workspace_path))}"
        )
        raise typer.Exit(code=130) from None


def main() -> None:
    app()
