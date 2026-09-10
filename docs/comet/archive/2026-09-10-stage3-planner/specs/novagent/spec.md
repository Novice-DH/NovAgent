# novagent 完整目标规格

本规格描述 change 归档后 `novagent` 项目的完整行为。项目由 uv 管理，src layout，包名 `novagent`。

## 项目与依赖

- `pyproject.toml`：`name = "novagent"`，src layout（uv_build 后端指向 `src/novagent`），`requires-python >= 3.10`，控制台脚本 `novagent = novagent.cli.app:main`。
- 运行依赖：`langchain-openai`、`typer`、`python-dotenv`、`rich`、`langgraph`、`tavily-python`。开发依赖：`pytest`。
- `uv.lock` 存在且与 `pyproject.toml` 一致；`uv sync` 可在新环境完成安装；锁中不引入完整 `langchain` 发行包。
- 包结构：

```text
src/novagent/
├── __init__.py
├── __main__.py
├── agents/
│   ├── __init__.py
│   ├── code_agent.py
│   └── search_agent.py
├── core/
│   ├── __init__.py
│   ├── agent.py
│   ├── state.py
│   └── paths.py
├── graph/
│   ├── __init__.py
│   ├── nodes.py
│   ├── state.py
│   └── workflow.py
├── prompts/
│   ├── __init__.py
│   └── stage2.py
├── tools/
│   ├── __init__.py
│   ├── registry.py
│   ├── file_tools.py
│   ├── grep_tool.py
│   ├── bash_tool.py
│   ├── todo_tools.py
│   └── web_search_tool.py
├── providers/
│   ├── __init__.py
│   └── openai_provider.py
└── cli/
    ├── __init__.py
    └── app.py
```

## core.state — RuntimeState

- `@dataclass RuntimeState`，字段 `workspace: Path`。
- 构造时可将相对路径规范化为绝对路径；`workspace` 是所有工具的根约束。

## core.paths — 工作区路径工具

- 提供 `resolve_in_workspace(state, raw_path) -> Path`：
  1. 以 `workspace` 为基准解析相对路径（支持子目录如 `sub/dir/file.txt`）；
  2. `Path.resolve()` 归一化 `..`、`.` 与符号链接；
  3. 解析结果不在 `workspace.resolve()` 内时抛出 `ValueError`，错误信息包含被拒绝的路径；
  4. workspace 本身不存在时不隐式创建，由调用方（CLI/写工具）决定创建。

## core.agent — LangGraph 工作流事件流

模块 `novagent.core.agent` 不包含手写 ReAct 循环，而是驱动 stage3 LangGraph 工作流并把图事件解析为统一格式的事件流。

- `stream_agent_events(task, *, workspace, max_attempts=3, model=None)` 为生成器：
  1. 创建 `RuntimeState(workspace)`；
  2. `graph = build_workflow(model=model)`；
  3. `inputs = {"task": task, "runtime": state, "max_attempts": max_attempts}`；
  4. `for mode, payload in graph.stream(inputs, stream_mode=["updates", "custom"])`：
     - `mode == "custom"`：payload 为 planner 协调期间的内部事件（`ai_message`/`tool_call`/`tool_result`/`handoff`，以及受托 searchAgent/codeAgent 的内部事件），由 workflow 的 planner 桥接显式标注 `"node": "planner"` 后原样转发；
     - `mode == "updates"`：payload 为 `{node_name: 更新dict}`，解析为 `{"type": "node_output", "node": ..., ...}` 事件：
       - `planner` → 携带 `plan_summary`、`todos`、`acceptance_criteria`、`verification_commands`；
       - `verifier` → 携带 `passed`、`reason`、`verification_results`、`verification_checks`；
       - `final` → 携带 `final_answer`。
- 统一事件格式：每个事件为普通 dict（值均可 JSON 序列化），至少含 `type`，并含 `node` 字段（"planner"/"verifier"/"final"）。
- `stream_agent_events` 的签名与 `updates` 解析语义保持不变；无 node 标签的 custom 事件兜底标注保留历史值 `"node": "actor"`（planner 桥接产生的事件均已显式携带 `"node": "planner"`，该兜底在 stage3 实际不触发）。

## graph.state — LangGraph 图共享状态

模块 `novagent.graph.state` 定义 LangGraph 图的共享状态类型，均为 `typing.TypedDict`：

- `TodoItem(TypedDict)`，字段与类型：
  - `id: str`
  - `content: str`
  - `status: str` —— 注释标注取值 `"pending" | "in_progress" | "completed" | "blocked"`
  - `note: str`
- `VerificationResult(TypedDict)`，字段与类型：
  - `command: str`
  - `ok: bool`
  - `exit_code: int | None`
  - `stdout: str`
  - `stderr: str`
- `VerificationCheck(TypedDict)`，字段与类型：
  - `name: str`
  - `passed: bool`
  - `detail: str`
- `SourceItem(TypedDict, total=False)`，字段与类型（镜像 WebSearchTool 结果条目）：
  - `url: str`
  - `title: str`
  - `content: str`
  - `score: float`
- `AgentHandoff(TypedDict, total=False)`，字段与类型：
  - `from_agent: str`
  - `to_agent: str`
  - `instruction: str`
  - `result: str`
- `NovGraphState(TypedDict, total=False)`，字段与类型：
  - `task: str`
  - `runtime: RuntimeState`（`novagent.core.state.RuntimeState`，直接复用，不复制）
  - `messages: Annotated[list[BaseMessage], add_messages]`
  - `plan_summary: str`
  - `todos: list[TodoItem]`
  - `acceptance_criteria: list[str]`
  - `verification_commands: list[str]`
  - `verification_results: list[VerificationResult]`
  - `research_notes: str`
  - `sources: list[SourceItem]`
  - `agent_handoffs: list[AgentHandoff]`
  - `code_agent_summary: str`
  - `passed: bool`
  - `attempts: int`
  - `max_attempts: int`
  - `final_answer: str`
  - `last_actor_summary: str`
  - `last_error: str`
  - `verification_checks: list[VerificationCheck]`

导入约定：

- `add_messages` 从 langgraph 导入（`langgraph.graph.message` 或 langgraph 公开顶层）；
- `BaseMessage` 从 `langchain_core.messages` 导入；
- `RuntimeState` 从 `novagent.core.state` 导入。

行为约定：

- `NovGraphState` 所有字段可选（`total=False`），图可以部分状态启动与更新；
- `messages` 通道使用 `add_messages` reducer：图执行中对 `messages` 的更新按 LangGraph 语义追加/合并（如按消息 ID 去重更新），而不是整体覆盖；
- 其余字段为默认覆盖语义的普通通道。

## prompts.stage2 — 收尾系统提示（保持既有语义）

模块 `novagent.prompts.stage2` 仅保留预留常量 `FINAL_PROMPT`（未接线到任何 LLM 调用）。旧有的 `PLANNER_PROMPT`、`ACTOR_PROMPT`、`VERIFIER_PROMPT` 均已迁出/移除：planner 与 verifier 系统提示由 stage3 提供（supervisor 协调体系），actor 节点随 stage3 改造移除。

## prompts.stage3 — Supervisor 协调提示

模块 `novagent.prompts.stage3` 是 stage3（supervisor 协调）系统提示的唯一权威来源，提供模块常量（均为非空英文字符串、逐字使用用户给定原文）：

- `PLANNER_PROMPT`：

```text
You are the planner/supervisor node in novagent stage 3.

You coordinate specialist agents through tools. You cannot directly edit files
or search the web yourself; delegate specialist work through tool calls.

Available tools:
- TodoWriteTool: publish or revise the plan, todos, acceptance criteria.
- CallSearchAgentTool: delegate web/document research.
- CallCodeAgentTool: delegate file/code implementation.

Rules:
- Always call TodoWriteTool before delegating new work.
- For tasks that require current facts, call CallSearchAgentTool before CallCodeAgentTool.
- If the verifier failed, revise the plan and delegate only the missing fix.
- End with a concise supervisor summary after the needed specialist calls.
```

- `VERIFIER_PROMPT`：

```text
You are verifier, a model-based reviewer node.

You decide whether the user's task is complete by inspecting state and using
read-only tools. You may read files, grep, run safe shell checks, and search
the web. You must not modify files.

Rules:
- Check the actual workspace, not only the previous agent summaries.
- Read NOTEPAD.md with NotepadReadTool when prior durable context matters.
- Run the provided verification commands when they are relevant.
- For researched content, confirm the output cites useful sources.
- Return only JSON with these keys:
  passed: boolean
  reason: short human-readable explanation
  checks: list of {name, passed, detail}
  recommended_next_instruction: what planner should ask a specialist to fix, or
    an empty string when passed
```

## graph.nodes — 规划/执行/验证/收尾节点与路由

模块 `novagent.graph.nodes` 实现 LangGraph 节点函数与条件路由。节点与 LangGraph 节点签名兼容：第一个位置参数为状态 dict，返回普通 dict 更新；`model=None` 时内部 `create_model()`，支持离线注入 FakeModel。提示词导入约定：`PLANNER_PROMPT`、`VERIFIER_PROMPT` 均从 `novagent.prompts.stage3` 导入（模块级名字与常量为同一对象）。

- `planner_node(state, *, model=None, on_event=None, max_loops=10) -> dict`：
  1. `tools = [create_todo_write_tool(), call_search_agent 工具, call_code_agent 工具]`（恰 3 个）；`agent = model.bind_tools(tools)`；
  2. 委托工具为闭包实现的 `StructuredTool`（内部实现 `_call_search_agent_tool(state, writer, instruction)` / `_call_code_agent_tool(state, writer, instruction)`，`writer` 为 `on_event` 包装：`on_event=None` 时事件仅收集、不外发）；
  3. 状态 `todos` 为空 → 首次生成：消息 `[SystemMessage(PLANNER_PROMPT), HumanMessage(task)]`；已有 `todos` 且 `last_error` 非空 → 修订：HumanMessage 额外携带 `last_error` 与最近失败的验证信息，要求修订并只委托缺失修复；
  4. 手写 ReAct 循环最多 `max_loops=10` 轮：每轮 `response = agent.invoke(messages)` 并追加、发 `{"type": "ai_message", "content": <AI 文本>}`；无 `tool_calls` 立即结束；否则逐个 tool_call：执行前发 `{"type": "tool_call", "name": ..., "args": ...}`，结果以 `ToolMessage(json.dumps(result))` 回传，执行后发 `{"type": "tool_result", "name": ..., "result": ...}`；
  5. `todo_write` tool_call：从 args 提取 `plan_summary`、`todos`（补齐缺失键、非法 status 归一 `"pending"`）、`acceptance_criteria`、`verification_commands`（多次调用取最后一次）；
  6. `call_search_agent` tool_call（args `{instruction: str}`）：先发 `{"type": "handoff", "from": "planner", "to": "searchAgent", "instruction": ...}`，调用 `run_search_agent(<合并视图>, instruction, writer=writer, model=model)`（合并视图 = state 叠加本节点内已产生的 `todos`/`research_notes` 更新，`model` 为 planner 收到的注入模型，保证多次委托链式一致且可离线注入）；状态更新——`research_notes` 追加 agent summary（已有内容以空行连接）、`sources` 按 url 去重保序合并 `SourceItem`（从 ok 的 `search_results` 事件提取 title/url/content/score，无明细时仅 url）、`agent_handoffs` 追加 `{"from_agent": "planner", "to_agent": "searchAgent", "instruction", "result": <summary>}`；
  7. `call_code_agent` tool_call（args `{instruction: str}`）：先发 `{"type": "handoff", "from": "planner", "to": "codeAgent", "instruction": ...}`，调用 `run_code_agent(<合并视图>, instruction, writer=writer, model=model)`；状态更新——`todos` 取该次委托返回的 todos、`code_agent_summary` 为 agent summary、`agent_handoffs` 追加 `{"from_agent": "planner", "to_agent": "codeAgent", "instruction", "result"}`、`messages` 并入委托新增的 AIMessage/ToolMessage；
  8. 返回更新 dict：计划四字段（发生 `todo_write` 时）+ `research_notes`/`sources`/`agent_handoffs`/`code_agent_summary`/`todos`/`messages`（发生对应委托时，仅包含有更新的键）。
- `verifier_node(state, *, model=None) -> dict`：
  1. 从 `state["runtime"]` 取 `RuntimeState`（缺失抛 `ValueError`）；`tools = build_read_only_tools(runtime) + [create_bash_tool(runtime), WebSearchTool]`（恰 4 个：`read_file`/`grep`/`bash`/`web_search`）；
  2. 消息 `[SystemMessage(VERIFIER_PROMPT), HumanMessage(计划 + 验收标准 + 验证命令 + 最近执行输出)]`；ReAct 循环（同语义、`max_loops=10`，无事件上报）；「最近执行输出」取 `state.get("last_actor_summary", "")`——stage3 中该字段不再由图内节点产生、通常为空；bash 的只读性由提示词约束（安全检查），验证命令的程序化执行（下述第 4 步）保持不变，`web_search` 缺 `TAVILY_API_KEY` 时走既有错误降级；
  3. 最终 AI 文本解析 JSON `{passed, reason, checks, recommended_next_instruction}`（容忍代码围栏）；解析失败按判定失败处理；
  4. 同时用 `execute_command` 逐条运行 `verification_commands`（workspace 为 cwd，默认 30 秒超时），构造 `VerificationResult`：`ok = exit_code == 0`；超时/异常 → `exit_code=None`、`ok=False`、stderr 记录错误信息；
  5. 整体 `passed = llm_passed and all(command ok)`；
  6. 返回更新：`passed`、`attempts`（原值 +1）、`verification_results`、`verification_checks`、`last_error`（失败时为 reason/命令失败/解析诊断，通过时为 `""`）、`final_answer`（整体通过时为 reason）、`todos`（整体通过 → 非 completed 全标 `completed`；失败 → in_progress 全标 `blocked`）。
- `final_node(state) -> dict`：确定性节点（不调用 LLM、不修改 `passed`），返回更新仅含 `final_answer`：
  - `passed` 为真：成功格式文本 `"Task completed in <N> attempt(s). <reason>"`；
  - `passed` 为假：失败格式文本 `"Task failed after <N> attempt(s).\nLast error: <last_error>"`。
- `verifier_route(state) -> str`：`state.get("passed")` 为真 → `"final"`；`state.get("attempts", 0) >= state.get("max_attempts", 3)` → `"final"`；否则 → `"planner"`。

## graph.workflow — LangGraph 工作流组装

模块 `novagent.graph.workflow` 组装可执行的 stage3 工作流：

- `build_workflow(*, model=None)`：
  - `graph = StateGraph(NovGraphState)`；
  - 注册节点：`"planner"` → 图内包装——经 `functools.partial` 绑定注入的 `model`，执行时调用 `langgraph.config.get_stream_writer()`，把每个事件复制并补 `"node": "planner"` 后作为 `on_event` 传给 `planner_node`（协调事件进入 custom 流；`invoke()` 等不消费 custom 流的场景下 writer 静默丢弃）；`"verifier"` → `verifier_node`（经 `functools.partial` 绑定注入的 `model`）；`"final"` → `final_node`；不注册 `"actor"`；
  - 边：`START → "planner"`、`"planner" → "verifier"`；
  - `"verifier"` 经 `verifier_route` 条件边路由：`{"final": "final", "planner": "planner"}`；
  - `"final" → END`；
  - 返回 `graph.compile()`。
- 图拓扑恰为：START → planner → verifier →（通过或预算耗尽）final → END，或 verifier →（未通过且预算未耗尽）planner。
- 本模块不提供 CLI 入口。

## agents.search_agent — 搜索专家 Agent

模块 `novagent.agents.search_agent` 提供独立的搜索专家 Agent（手写 ReAct 循环，不依赖 LangGraph 工作流，不引入 agent 执行器库）。`src/novagent/agents/__init__.py` 为空包文件。

- 模块常量 `SEARCH_AGENT_PROMPT`（非空英文字符串，逐字使用用户给定原文）：

```text
You are searchAgent, a focused research specialist.

Your only external capability is WebSearchTool. Search for reliable information
needed by the planner and codeAgent.

Rules:
- Use WebSearchTool for factual research.
- Prefer official or encyclopedia-style sources when available.
- Return a concise research summary and list the useful source URLs.
- Do not write files or produce application code.
```

- `run_search_agent(state, instruction, *, writer=None, max_loops=4, model=None) -> dict`：
  1. `model=None` 时内部 `create_model()`；`agent = model.bind_tools([WebSearchTool])`（唯一绑定工具）；
  2. 初始消息为 `[SystemMessage(SEARCH_AGENT_PROMPT), HumanMessage(human_text)]`；`human_text` 依次包含任务（`state.get("task", "")`）、`instruction` 与已有研究笔记（`state.get("research_notes", "")`，缺失时明确标注暂无笔记）；`state` 为图状态样 dict-like 映射，本模块不修改 `NovGraphState` schema；
  3. 手写 ReAct 循环最多 `max_loops` 轮：每轮 `response = agent.invoke(messages)` 并把 response 追加进消息；无 `tool_calls` 时立即结束循环；否则对每个 tool_call：
     - 已知工具 `web_search`：执行 `WebSearchTool.invoke(args)`，工具异常转为 `{"ok": False, "query": <args 中的 query 或 "">, "error": "<异常信息>"}`；
     - 未知工具名：结果为 `{"ok": False, "error": "unknown tool <name>"}`，不执行任何工具；
     - 每个结果构造 `ToolMessage(content=json.dumps(result), tool_call_id=call["id"])` 追加进消息；
     - 收集：`queries` 追加每次 `web_search` 调用的 `query`（失败调用也记录）；`sources` 按 `ok=True` 结果的 `results` 顺序追加 `url`（去重保序）；
     - 事件：执行前发 `{"type": "tool_call", "name": <工具名>, "args": <call args>}`，执行后发 `{"type": "search_results", "name": "web_search", "query": <本次 query>, "result": <结果 dict>}`；`writer` 为可调用对象时逐个调用 `writer(event)`，`writer=None` 时跳过写入；全部事件同时收集进 `tool_events`；
  4. 返回 `{"ok": True, "summary": <最后一轮 AI 文本>, "queries": [...], "sources": [...], "messages": <循环内新增的 AIMessage/ToolMessage 列表>, "tool_events": [...]}`；
  5. AI 文本提取与 `graph.nodes` 同语义（`content` 为 str 原样返回，非 str 转为 str）。

## agents.code_agent — 代码专家 Agent

模块 `novagent.agents.code_agent` 提供独立的代码实现专家 Agent（手写 ReAct 循环，不依赖 LangGraph 工作流，不引入 agent 执行器库）。

- 模块常量 `CODE_AGENT_PROMPT`（非空英文字符串，逐字使用用户给定原文）：

```text
You are codeAgent, a focused implementation specialist.

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
```

- 模块函数 `build_memory_snapshot(state) -> str`：layered memory 快照的预留接口，当前返回空字符串（不调用 LLM、无网络、无副作用）；后续 memory 阶段实现真实快照。
- `run_code_agent(state, instruction, *, writer=None, max_loops=10, model=None) -> dict`：
  1. 从 `state["runtime"]` 取 `RuntimeState`（缺失或为 None 抛 `ValueError`，与 `actor_node` 一致）；`tools = build_tools(runtime) + [create_todo_update_tool()]`（恰 6 个）；`model=None` 时内部 `create_model()`；`agent = model.bind_tools(tools)`；
  2. 初始消息 `[SystemMessage(CODE_AGENT_PROMPT), HumanMessage(human_text)]`；`human_text` 依次包含任务（`state.get("task", "")`）、`instruction`、session 上下文（`state.get("session_context", "")`，缺失时标注 `(no session context)`）与 memory 快照（`build_memory_snapshot(state)` 为空时标注 `(no memory snapshot)`）；
  3. 手写 ReAct 循环最多 `max_loops` 轮（默认 10）：每轮 `response = agent.invoke(messages)` 并追加消息、发 `{"type": "ai_message", "content": <AI 文本>}`；无 `tool_calls` 立即结束；否则逐个 tool_call：
     - 执行前发 `{"type": "tool_call", "name": <工具名>, "args": <call args>}`；
     - 未知工具（含提示词提及但未绑定的 notepad 工具）结果文本为 `Error: unknown tool <name>`；工具执行异常转为 `Error: <异常信息>`（与 `graph.nodes._execute_tool` 同语义）；
     - 每个结果构造 `ToolMessage(content=json.dumps(result), tool_call_id=call["id"])` 追加进消息；
     - 执行后发 `{"type": "tool_result", "name": <工具名>, "result": <结果文本>}`；
     - `todo_update` 调用额外把 args 按 `todo_id` 合并进 todos：`status` 仅在取值 `pending|in_progress|completed|blocked` 时更新，`note` 在提供时更新，未知 `todo_id` 忽略（与 `actor_node` 一致）；
     - 全部事件同时收集进 `tool_events` 并逐个调用 `writer`（`writer=None` 时跳过写入）；
  4. 循环结束发 `{"type": "final_answer", "content": <最后一轮 AI 文本>}`；
  5. 返回 `{"ok": True, "summary": <最后一轮 AI 文本>, "todos": <更新后的 todos 列表>, "messages": <循环内新增的 AIMessage/ToolMessage>, "tool_events": [...]}`；todos 的持久化方式即经返回 dict 交给调用方（图接入后走 `NovGraphState.todos` 状态通道），本模块不引入文件持久化。

## prompts.stage2 之外的工具与提供者（保持既有语义）

## tools.todo_tools

- `create_todo_write_tool() -> StructuredTool`，名 `todo_write`：args schema 含 `plan_summary: str`、`todos`（`{id, content, status, note}` 数组）、`acceptance_criteria: list[str]`、`verification_commands: list[str]`；无副作用，invoke 返回确认文本。
- `create_todo_update_tool() -> StructuredTool`，名 `todo_update`：args schema 含 `todo_id: str`、`status: str`、`note: str = ""`；无副作用，invoke 返回确认文本。

## tools.file_tools

三个工具均为闭包工厂，接收 `RuntimeState`，内部通过 `resolve_in_workspace` 校验后执行：

- `FileReadTool` → `read_file(file_path: str, offset: int = 1, limit: int | None = None) -> str`
  - 读取 UTF-8 文本，返回内容；`offset` 为起始行（1-based），`limit` 为最多返回行数；
  - 文件不存在、是目录或逃逸 workspace 时报错。
- `FileWriteTool` → `write_file(file_path: str, content: str) -> str`
  - 创建含缺失父目录的目标文件或整体覆写；成功返回确认信息；
  - 逃逸 workspace 时报错。
- `FileEditTool` → `edit_file(file_path: str, old_text: str, new_text: str) -> str`
  - `old_text` 必须在文件中恰好出现一次，替换后写回，返回确认信息；
  - 出现 0 次或多次时报错且文件内容保持不变；
  - 文件不存在或逃逸 workspace 时报错。

## tools.grep_tool — GrepTool

`grep(pattern: str, path: str = ".", glob: str = "**/*", head_limit: int = 20, ignore_case: bool = False) -> str`

- 在 `path`（必须位于 workspace 内，逃逸报错）下递归遍历匹配 `glob` 的文件；
- 按行应用 `re` 正则，`ignore_case=True` 时忽略大小写；
- 命中行以 `相对路径:行号:行内容` 输出，最多 `head_limit` 条；
- 跳过无法按 UTF-8 解码的二进制文件与超大小文件，不因个别文件失败中断；
- 无匹配返回提示信息；非法正则报错。

## tools.bash_tool — BashTool 与 execute_command

- 模块级 `execute_command(command, cwd, timeout_seconds=30.0) -> tuple[int | None, str, str]`：
  - 以 `cwd` 为工作目录执行 shell 命令，返回 `(exit_code, stdout, stderr)`；
  - 超过 `timeout_seconds` 终止整棵子进程树并抛 `TimeoutError`（Windows 按 taskkill /T，POSIX 按 killpg）；
  - 命令无法执行/异常时向调用方抛出。
- `create_bash_tool(state) -> StructuredTool`，名 `bash`：`bash(command: str, timeout_seconds: float = 30) -> str` 内部调用 `execute_command`；
  - 返回包含退出码、stdout、stderr 的文本；
  - 非零退出码不抛异常，正常返回输出并标注退出码。

## tools.registry — build_tools 与 build_read_only_tools

- `build_tools(state: RuntimeState) -> list[StructuredTool]`；
- 依次注册 `read_file`、`write_file`、`edit_file`、`grep`、`bash` 五个工具，args schema 由函数签名自动推导；
- 返回列表可直接用于 `model.bind_tools(tools)`。
- `build_read_only_tools(state: RuntimeState) -> list[StructuredTool]`：仅含 `read_file`、`grep`。
- `WebSearchTool` 不进入 `build_tools`/`build_read_only_tools` 注册表，仅供搜索专家 Agent 绑定。

## tools.web_search_tool — WebSearchTool

模块 `novagent.tools.web_search_tool` 提供联网搜索工具（Tavily Search API）。本模块不依赖 `RuntimeState`/workspace，可独立使用；`tavily` 仅在本模块导入，不向其他模块扩散。

- 模块级 `WebSearchTool: StructuredTool`，工具名 `web_search`，供 `model.bind_tools([WebSearchTool])` 直接使用；args schema：`query: str`（必填）、`max_results: int = 5`。
- 执行语义（返回普通 dict，可 JSON 序列化，不向模型抛异常）：
  1. 先 `load_dotenv(find_dotenv(usecwd=True))`（与 `create_model` 一致），再读取环境变量 `TAVILY_API_KEY`；缺失时直接返回 `{"ok": False, "query": query, "error": "missing TAVILY_API_KEY"}`，不构造客户端、不发起网络请求；
  2. 有 key 时构造 `TavilyClient(api_key=...)` 并调用 `search(query, max_results=max_results, include_answer=True)`；
  3. 成功返回 `{"ok": True, "query": query, "answer": <API 返回的 answer 或 "">, "results": [{"title", "url", "content", "score"}, ...]}`——`results` 各项仅保留这四个键，API 缺失的键补空值（`""`/`0.0`）；
  4. 客户端构造或搜索过程抛出的异常不外泄，返回 `{"ok": False, "query": query, "error": "<异常信息>"}`。

## providers.openai_provider — create_model

- `create_model() -> ChatOpenAI`：
  1. `load_dotenv()` 加载项目根 `.env`；
  2. 读取 `OPENAI_API_KEY`，缺失时抛出说明配置方法的 `ValueError`；
  3. `OPENAI_MODEL` 可选，默认 `gpt-4o-mini`；`OPENAI_BASE_URL` 可选，设置时传入 `base_url`；
  4. 返回 `langchain_openai.ChatOpenAI` 实例。

## cli.app — novagent 命令

- `novagent <task> --workspace <path> --max-attempts <n>`：`task` 为位置参数；`--workspace` 默认 `<cwd>/workspace`；`--max-attempts` 默认 3（必须 >= 1）。
- 执行流程：
  1. 解析并自动创建 workspace（`parents=True, exist_ok=True`），打印 workspace 路径；
  2. 调用 `create_model()`；`OPENAI_API_KEY` 缺失等配置错误以清晰错误信息退出（非零退出码），不打印未捕获 traceback；
  3. 调用 `core.agent.stream_agent_events(task, workspace=..., max_attempts=..., model=...)` 消费统一事件流，用 `rich.Console` 按节点徽标实时渲染：
     - `node_output` + `planner` → `📋 Planner` 行 + 计划摘要与 todos 列表；
     - `node=actor` 的 `ai_message`/`tool_call`/`tool_result` → 首次前打印 `🔧 Actor` 标头，随后打印 AI 文本、`→ tool args` 与结果（全部 `escape` 转义）；
     - `node_output` + `verifier` → `✅ Verifier`（通过）或 `❌ Verifier`（失败）+ reason + 每条验证命令的退出码结果；
     - `node_output` + `final` → `📝 Final` + 最终回答；
     - `node="actor"` 的 `final_answer` 内部事件与 `node_output`+`actor` 忽略（内容已被其他事件覆盖）；
     - `node="planner"` 的内部事件（`ai_message`/`tool_call`/`tool_result`/`handoff` 及受托 agent 事件）当前不渲染——CLI 渲染分支为后续 change 预留，不影响事件流本身。
- `python -m novagent` 与控制台脚本 `novagent` 行为一致（`__main__.py` 调用 `cli.app`）。

## tests

- `tests/test_agent_loop.py` 重写为 stage3 协调语义（FakeModel 离线驱动整图）：通过路径（planner 轮 1 `todo_write` 发布计划、轮 2 `call_code_agent` 委托实现、轮 3 纯文本结束 → verifier 输出 `passed=true` JSON → final），事件顺序（planner `node_output` → planner 内部事件（带 `node="planner"`，含 `handoff`）→ verifier `node_output` → final `node_output`），`final_answer` 以 "Task completed" 开头，文件落盘；失败回环（planner 收到含 `last_error` 的修订 HumanMessage 后 `todo_write` 修订，最终通过）；`max_attempts=1` 预算耗尽直接 final；
- `tests/test_cli.py`：`--help` 含 `--max-attempts` 与 `--workspace`；workspace 自动创建与缺 key 清晰报错（退出码 1）；统一事件格式的 fake 流驱动 CLI 渲染——输出依次包含 📋 Planner、🔧 Actor、✅ Verifier、📝 Final 与工具详情、最终回答；fake 断言 `--max-attempts` 默认 3 与显式传值生效；
- `tests/test_graph_nodes.py` 重写：planner 绑定工具恰为 `["todo_write", "call_search_agent", "call_code_agent"]`；消息构造（首次生成与含 `last_error` 的修订 HumanMessage）；`todo_write` 计划归一化与多次调用取最后一次；委托语义——`call_search_agent`/`call_code_agent` 先发 `handoff` 事件再调 `run_search_agent`/`run_code_agent`（注入 fake TavilyClient / 真实 workspace），状态更新（`research_notes` 追加、`sources` 按 url 去重保序、`agent_handoffs` 记录 from/to/instruction/result、`code_agent_summary`、`todos`、`messages`）；循环边界（无 tool_calls 提前结束、`max_loops` 上限）；`novagent.graph.nodes` 不再含 `actor_node`；
- `tests/test_graph_workflow.py` 重写：编译图节点集合恰为 `{"planner", "verifier", "final"}`，`START → planner`、`planner → verifier`、verifier 条件边、`final → END`；planner 桥接事件带 `node="planner"`；端到端 verifier 绑定恰为 `["read_file", "grep", "bash", "web_search"]`；
- `tests/test_graph_state.py`：新增 `SourceItem`/`AgentHandoff` 类型与 `NovGraphState` 新字段（`research_notes`/`sources`/`agent_handoffs`/`code_agent_summary`），`add_messages` 语义不变；
- `tests/test_graph_nodes.py` 另含 verifier 断言：`VERIFIER_PROMPT` 为 stage3 同一对象且以 "You are verifier, a model-based reviewer node." 开头、含 "NotepadReadTool"、以 "an empty string when passed" 结尾；verifier 绑定工具恰 4 个（read_file/grep/bash/web_search）；
- `tests/test_cli.py`：保持既有覆盖（CLI 行为本 change 未变，fake 流继续驱动渲染断言）；
- `tests/test_web_search_tool.py`：缺 `TAVILY_API_KEY` 时返回 `ok=False` 且 `error == "missing TAVILY_API_KEY"`（monkeypatch 删除环境变量，不发起网络请求）；注入 fake `TavilyClient` 时返回 `ok=True` 的完整 dict（`query`/`answer`/`results` 四键归一化）；异常转为 `ok=False` 的 error dict；工具名为 `web_search`；
- `tests/test_search_agent.py`（FakeModel 离线驱动）：消息构造（SystemMessage 为 `SEARCH_AGENT_PROMPT`，HumanMessage 含 task、instruction 与 research_notes）；ReAct 循环返回值 `{ok, summary, queries, sources, messages, tool_events}`（FakeModel 第一轮 `web_search` tool_call、第二轮纯文本；writer 收集到 `tool_call` 与 `search_results` 两类事件且与 `tool_events` 一致；sources 去重保序）；无 `tool_calls` 提前结束与 `max_loops` 上限；`SEARCH_AGENT_PROMPT` 常量内容断言（开头句、"WebSearchTool"、禁写文件句）；
- `tests/test_code_agent.py`（FakeModel 离线驱动）：工具绑定恰为 `["read_file", "write_file", "edit_file", "grep", "bash", "todo_update"]`；消息构造（SystemMessage 即 `CODE_AGENT_PROMPT`，HumanMessage 同时含 task、instruction、session_context 与 memory 段及缺失占位标注）；ReAct 返回 `{ok, summary, todos, messages, tool_events}`（write_file 真实落盘、todo_update 迁移 in_progress→completed、事件类型序列含 ai_message/tool_call/tool_result/final_answer、writer 收到同一批事件）；blocked 迁移与未知 todo_id 忽略；无 tool_calls 提前结束（1 次调用）与 `max_loops` 上限（恰 N 次调用）；未知工具错误回传 `Error: unknown tool` 且循环继续；`runtime` 缺失抛 `ValueError`；`build_memory_snapshot` 当前返回空字符串；
- `tests/test_registry.py`、`tests/test_file_tools.py`、`tests/test_grep_tool.py`、`tests/test_bash_tool.py`、`tests/test_paths.py`、`tests/test_openai_provider.py` 保持既有覆盖；
- 全部测试离线运行，不发起真实网络请求。
