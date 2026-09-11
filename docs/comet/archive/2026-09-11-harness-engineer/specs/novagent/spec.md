# novagent 完整目标规格

本规格描述 change 归档后 `novagent` 项目的完整行为。项目由 uv 管理，src layout，包名 `novagent`。本阶段（阶段五 Harness Engineer）新增人类在环审批、Checkpoint 检查点与 Trace 链路追踪；阶段一～四的既有行为保持不变。

## 项目与依赖

- `pyproject.toml`：`name = "novagent"`，src layout（uv_build 后端指向 `src/novagent`），`requires-python >= 3.10`，控制台脚本 `novagent = novagent.cli.app:main`。
- 运行依赖不变：`langchain-openai`、`typer`、`python-dotenv`、`rich`、`langgraph`、`tavily-python`。开发依赖：`pytest`。本阶段不新增任何运行依赖。
- `uv.lock` 存在且与 `pyproject.toml` 一致；`uv sync` 可在新环境完成安装。
- 包结构（新增 `core/approval.py`、`core/checkpoint.py`、`core/trace.py`）：

```text
src/novagent/
├── agents/
│   ├── code_agent.py
│   └── search_agent.py
├── cli/
│   └── app.py
├── core/
│   ├── agent.py
│   ├── approval.py      # 新增：风险分类与审批
│   ├── checkpoint.py    # 新增：检查点保存与恢复
│   ├── paths.py
│   ├── state.py
│   └── trace.py         # 新增：链路追踪
├── graph/
│   ├── memory.py
│   ├── nodes.py
│   ├── state.py
│   └── workflow.py
├── prompts/
│   ├── stage2.py
│   ├── stage3.py
│   └── stage4.py
├── providers/
│   └── openai_provider.py
└── tools/
    ├── bash_tool.py
    ├── file_tools.py
    ├── grep_tool.py
    ├── registry.py
    ├── todo_tools.py
    └── web_search_tool.py
```

## core.state — RuntimeState

- `@dataclass RuntimeState`，既有字段 `workspace: Path`（构造时规范化为绝对路径）之上新增字段（均带默认值，既有构造调用 `RuntimeState(workspace=...)` 不受影响）：
  - `approval_mode: str = "inline"` —— 审批模式，经 `normalize_approval_mode` 归一；
  - `approval_handler: Callable[[ApprovalRequest], object] | None = None` —— `inline` 模式的人类决策入口，返回 `ApprovalDecision` 或布尔值；
  - `checkpoint_mode: str = "light"` —— 检查点模式，经 `normalize_checkpoint_mode` 归一；
  - `trace_mode: str = "on"` —— 追踪模式，经 `normalize_trace_mode` 归一；
  - `trace_id: str | None = None` —— 追踪标识，首次由 TraceRecorder 生成并回写；
  - `approval_log: list = field(default_factory=list)` —— 运行期风险分流记录（见 core.approval）。

## core.approval — 风险分类与审批

- `RISK_PATTERNS: list[tuple[str, str]]`，恰为以下 10 条 `(正则, 风险原因)`，全部锚定行首或 `&&`/`||`/`;` 之后：
  1. `(?:^|&&|\|\||;)\s*(?:python\s+-m\s+)?pip\s+install\b` — Python package installation
  2. `(?:^|&&|\|\||;)\s*uv\s+add\b` — Project dependency change with uv add
  3. `(?:^|&&|\|\||;)\s*uv\s+sync\b` — Dependency synchronization with uv sync
  4. `(?:^|&&|\|\||;)\s*uv\s+pip\s+install\b` — Python package installation with uv pip
  5. `(?:^|&&|\|\||;)\s*npm\s+install\b` — Node package installation
  6. `(?:^|&&|\|\||;)\s*pnpm\s+install\b` — Node package installation
  7. `(?:^|&&|\|\||;)\s*yarn\s+(?:install\b|add\b)` — Node package installation
  8. `(?:^|&&|\|\||;)\s*(?:curl|wget)\b` — Network download command
  9. `(?:^|&&|\|\||;)\s*uvicorn\b` — Long-running development server
  10. `(?:^|&&|\|\||;)\s*python\s+-m\s+http\.server\b` — Long-running development server
- `classify_command_risk(command: str) -> str | None`：按序匹配 `RISK_PATTERNS`（`re.IGNORECASE`），命中返回风险原因字符串，否则返回 `None`。
- `@dataclass(frozen=True) ApprovalRequest`：`id: str`（`"approval-{uuid4().hex[:8]}"`）、`command: str`、`risk_reason: str`、`tool_name: str = "BashTool"`。
- `@dataclass(frozen=True) ApprovalDecision`：`approved: bool`、`reason: str = ""`。
- `VALID_APPROVAL_MODES = {"inline", "auto", "deny"}`。
- `normalize_approval_mode(mode: str | None) -> str`：值属于 `VALID_APPROVAL_MODES` 时原样返回，否则（含 `None`/空串/未知值）返回 `"inline"`。

## tools.bash_tool — 审批分流

- `execute_command(command, cwd, timeout_seconds)` 低层执行器行为不变。
- `create_bash_tool(state)` 返回的 `bash` 工具在执行前经 `_resolve_approval(state, command) -> dict | None`：
  - `classify_command_risk` 为 `None`（安全命令）→ 返回 `None`，直接执行，行为与现状一致；
  - 命中风险时先向 `state.approval_log` 追加一条 `{"command", "risk_reason", "mode", "approved"}` 记录，然后：
    - `auto` → 放行执行，返回 dict `{"requires_approval": True, "approved": True, "risk_reason", "command"}`；
    - `deny`，或 `inline` 且 `approval_handler` 为 `None` → 不执行，返回 dict `{"requires_approval": True, "approved": False, "ok": False, "error": "human approval required: <risk_reason>"}`；
    - `inline` → 以 `ApprovalRequest` 调用 `state.approval_handler(request)`；返回值为 `ApprovalDecision` 时取其 `approved`，为布尔值时直接采用；批准 → 放行执行（同 auto 的放行 dict）；拒绝 → 不执行，返回 dict `{"requires_approval": True, "approved": False, "ok": False, "error": "human rejected: <risk_reason>"}`；
  - 被拒绝时 `bash()` 不调用 `execute_command`，工具返回的错误文本为该 dict 的 JSON 序列化；放行时正常执行，返回文本在既有 `exit_code/stdout/stderr` 文本前附 `requires_approval: True` 与 `approved: True` 标记行（仅风险命令）。
- 审批同样作用于 verifier 节点内 `create_bash_tool(runtime)` 构造的工具（配置随 RuntimeState 传递）；`_run_verification_commands` 的直执行路径不经审批。

## core.checkpoint — 检查点保存与恢复

- `VALID_CHECKPOINT_MODES = {"light", "strict", "off"}`；`normalize_checkpoint_mode(mode) -> str`：合法原样返回，否则 `"light"`。
- `CheckpointManager(runtime, task="")`：
  - `mode = normalize_checkpoint_mode(runtime.checkpoint_mode)`；`enabled = mode != "off"`；
  - `root = workspace / ".novagent" / "checkpoints"`；文件名常量：`CHECKPOINT_FILE = "checkpoint.json"`、`STATE_FILE = "state.json"`、`EVENTS_FILE = "events.jsonl"`、`RECOVERY_FILE = "RECOVERY.md"`。
- `save(state, *, status="running", latest_node=None, event=None)`（`state` 为图状态样 dict）：
  - disabled → 返回 `None`，不创建任何目录；
  - strict 且 `event` 非 None → 向 `events.jsonl` 追加一行 JSON；
  - strict → 以 `serialize_state` 写 `state.json`（`messages` 经 langchain `messages_to_dict` 往返，`runtime` 不序列化）；
  - light 与 strict 共同：`workspace_manifest(workspace)` 文件清单（相对路径 + 大小；跳过 `.novagent`）；git 影子仓库快照；
  - git 快照：影子仓库位于 `root/.git`（首次 `git init`），经 `git --git-dir=<root/.git> --work-tree=<workspace> add -A && commit` 提交当前工作区；git 不可用或失败时记录 `git_error`（非空字符串），不抛异常；
  - 写 `checkpoint.json`：`task`、`status`、`latest_node`、`mode`、`saved_at`、`attempts`、`git_commit`（可为 None）、`git_error`、`workspace_manifest`；
  - 写 `RECOVERY.md`（`build_recovery_markdown(payload)`）：任务、状态、最近节点、文件清单摘要、git commit、恢复命令；
  - 返回 `checkpoint_saved` 事件 dict：`{"type": "checkpoint_saved", "mode", "status", "latest_node", "path": str(root)}`；
  - 单点失败（JSON/IO/git）一律降级：捕获后记录 `git_error`/跳过该产物，不向工作流抛异常。
- `load_resume_inputs(runtime, task=None, max_attempts=3) -> tuple[dict, dict]`：读取 `checkpoint.json`（不存在抛 `FileNotFoundError`）；存在 `git_commit` 时把 workspace 文件恢复到快照内容；重建 inputs——`task`（参数优先，其次检查点）、`runtime`（重建的 `RuntimeState`）、`max_attempts`、`attempts`；strict 模式下 `state.json` 存在时另含 `messages`（`messages_from_dict` 还原）。返回 `(inputs, resume_event)`，`resume_event` 为 `{"type": "resumed", ...}` 样事件。
- `resume_command(workspace) -> str`：返回 `"novagent run --resume <workspace 绝对路径>"`。

## core.trace — 链路追踪

- `VALID_TRACE_MODES = {"on", "off"}`；`normalize_trace_mode(mode) -> str`：合法原样返回，否则 `"on"`。
- `TraceRecorder(runtime, task="")`：`mode`、`trace_id`（`runtime.trace_id` 非空则用之，否则 `uuid4().hex[:8]` 并回写 `runtime.trace_id`）、`root = workspace / ".novagent" / "traces" / trace_id`；计数器 `node_visits: dict[str, int]`、`tool_calls`、`failed_tool_calls`、`approval_count`、`checkpoint_count`、`handoff_count`（均初始 0/空）；时间线 `timeline: list[str]`。
- mode 为 `off` 时所有方法为 no-op，不创建目录。
- `start(inputs, *, resumed=False, resume_event=None)`：记录 `run_start` 时间线行（含 task 与 resumed 标记）并写 `events.jsonl`。
- `record_custom_event(event)`：追加时间线行与 `events.jsonl` 行，并更新统计：
  - `type=="tool_call"` → `tool_calls += 1`；
  - `type=="tool_result"` 且失败（结果文本以 `Error` 开头，或首行为 `exit_code: <n>` 且 n≠0）→ `failed_tool_calls += 1`；
  - `type=="handoff"` → `handoff_count += 1`；
  - `type=="checkpoint_saved"` → `checkpoint_count += 1`。
- `record_graph_update(event)`：对 updates payload 的每个节点名 `node_visits[node] += 1` 并记录时间线行。
- `approval_count` 在 `end` 时取 `len(runtime.approval_log)`（风险分流总次数，含 auto）。
- `end(*, status, latest_node, final_state)`：写 `trace.json` —— `trace_id`、`task`、`status`、`started_at`、`ended_at`、`duration_ms`、`node_visits`、`tool_calls`、`failed_tool_calls`、`approval_count`、`checkpoint_count`、`handoff_count`、`timeline_head`（前 20 条）、`timeline_tail`（后 80 条）、`timeline_omitted`（被省略条数）；写人类可读的 `timeline.md`（逐行时间线）。

## core.agent — 主循环集成与恢复

- `stream_agent_events(task, *, workspace, max_attempts=3, model=None, approval_mode="inline", approval_handler=None, checkpoint_mode="light", trace_mode="on", resume_workspace=None)`：
  1. 构造 `RuntimeState(workspace, approval_mode=..., approval_handler=..., checkpoint_mode=..., trace_mode=...)`；
  2. `resume_workspace` 非 None → 以指向该 workspace 的 RuntimeState 调用 `CheckpointManager.load_resume_inputs` 得到 inputs 与 resume 事件（task/attempt/messages 恢复），workspace 即 resume 目录；
  3. `manager = CheckpointManager(state, task=...)`；`trace = TraceRecorder(state, task=...)`；
  4. `trace.start(inputs, resumed=..., resume_event=...)`；`manager.save(inputs, status="started" 或 "resumed", latest_node="start")`，其 `checkpoint_saved` 事件进入输出流；
  5. 图流循环（`stream_mode=["updates", "custom"]`）：
     - `custom` → `trace.record_custom_event(event)`；事件为失败的 `tool_result` 时 `manager.save(current_state, status="running", latest_node=..., event=event)`；事件按既有 schema 转发（含 `node` 补齐与 `checkpoint_saved` 透传）；
     - `updates` → 按 reducer 语义把更新并入 `current_state`（`messages` 追加、`RemoveMessage(id=REMOVE_ALL_MESSAGES)` 清空后重置），`trace.record_graph_update(event)`，`manager.save(current_state, status="running", latest_node=node)` 并输出 `checkpoint_saved` 事件；随后按既有 schema 产出 `node_output` 事件（planner/verifier/final 字段与现状完全一致）；
  6. 正常结束：`manager.save(current_state, status="finished", latest_node=...)` 与 `trace.end(status="finished", ...)`；
  7. `KeyboardInterrupt`：先 `manager.save(current_state, status="interrupted", ...)` 与 `trace.end(status="interrupted", ...)`，再向调用方重新抛出。
- 既有统一事件格式不变；新增事件类型：`checkpoint_saved`、`resumed`。

## cli.app — 命令行入口

- `novagent run [TASK]` 选项在 `--workspace` / `--max-attempts` 之外新增：
  - `--approval-mode [inline|auto|deny]`（默认 `inline`）；
  - `--checkpoint-mode [light|strict|off]`（默认 `light`）；
  - `--trace-mode [on|off]`（默认 `on`）；
  - `--resume <PATH>`（默认 None）：指向含 `.novagent/checkpoints` 的 workspace 目录。
- `TASK` 改为可选参数：无 `--resume` 且省略 TASK → 报错退出（非零，提示用法）；`--resume` 时省略 TASK → 使用检查点中的 task，显式给出 → 覆盖。
- `--resume` 与 `--workspace` 同时给出且解析为不同目录 → 报错退出（错误信息含两个路径）；否则 workspace 取 resume 目录。
- `inline` 审批 handler：rich 终端提示 `⚠️ Human Approval Required`、风险原因、完整命令，循环读取输入直至 `y/yes`（批准）或 `n/no`（拒绝，含空输入与 EOF，不区分大小写），返回 `ApprovalDecision`。
- 渲染新增：`checkpoint_saved` 事件打印 `💾 Checkpoint saved`（含 mode/status/最近节点）；`resumed` 事件打印恢复信息（task/最近节点/attempts）；`KeyboardInterrupt` 捕获后打印中断与恢复命令提示（`resume_command(workspace)`），以非零退出码（130）退出。
- 既有渲染（planner/verifier/final 徽标、actor 工具事件）与 `OPENAI_API_KEY` 缺失时的干净失败（exit 1）不变。

## 既有模块（本阶段不变）

- `graph/workflow.py`、`graph/nodes.py`、`graph/state.py`、`graph/memory.py`：图组装、planner(supervisor)/verifier/context monitor/context compressor/final、分层记忆全部不变。
- `agents/code_agent.py`、`agents/search_agent.py`：ReAct 循环与事件发射不变；codeAgent 经 `build_tools(runtime)` 间接获得审批生效的 bash 工具。
- `tools/registry.py`、`file_tools.py`、`grep_tool.py`、`todo_tools.py`、`web_search_tool.py`、`providers/openai_provider.py`、`prompts/*`：不变。
- `core/paths.py`：不变。

## 测试（全部离线）

- 新增 `tests/test_approval.py`（分类/归一/数据类/A4–A8 分流行为，`execute_command` 以 monkeypatch 观测）、`tests/test_checkpoint.py`（A10–A14）、`tests/test_trace.py`（A15–A16）。
- 更新 `tests/test_bash_tool.py`（安全命令路径回归 + 审批标记文本）、`tests/test_agent_loop.py`（FakeModel 端到端：checkpoint_saved 事件、finished/interrupted 落盘、审批经 RuntimeState 生效）、`tests/test_cli.py`（帮助文本含新选项、task/resume 校验、resume 指向无检查点目录时干净报错）。
- 不发起真实 LLM/网络调用；无 API key 环境全部可验证；兼容 Python >= 3.10。
