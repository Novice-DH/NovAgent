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
│   ├── memory.py
│   ├── nodes.py
│   ├── state.py
│   └── workflow.py
├── prompts/
│   ├── __init__.py
│   ├── stage2.py
│   └── stage3.py
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
  2. `graph = build_complex_workflow(model=model)`；
  3. `inputs = {"task": task, "runtime": state, "max_attempts": max_attempts}`；
  4. `for mode, payload in graph.stream(inputs, stream_mode=["updates", "custom"])`：
     - `mode == "custom"`：payload 为 planner 协调事件（含受托专家 Agent 的内部事件），转发时补 `"node": "planner"`；
     - `mode == "updates"`：payload 为 `{node_name: 更新dict}`，解析为 `{"type": "node_output", "node": ..., ...}` 事件：
       - `planner` → 携带 `plan_summary`、`todos`、`acceptance_criteria`、`verification_commands`；
       - `verifier` → 携带 `passed`、`reason`、`verification_results`、`verification_checks`；
       - `final` → 携带 `final_answer`；
       - `context_monitor`/`context_compressor` → 无对应解析分支，不产生事件。
- 统一事件格式：每个事件为普通 dict（值均可 JSON 序列化），至少含 `type`，并含 `node` 字段（"planner"/"verifier"/"final"）。

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
- `CompressionEvent(TypedDict, total=False)`，字段与类型（一次上下文压缩事件的预留描述，`context_summary`/`compression_events` 的真实写入方属后续压缩器 change）：
  - `node: str`
  - `reason: str`
  - `token_count: int`
  - `token_limit: int`
  - `summary: str`
  - `created_at: str`
- `LayeredMemory(TypedDict, total=False)`，字段与类型（`build_layered_memory` 返回结构的类型视图）：
  - `rules: dict`
  - `working_memory: dict`
  - `history_summary_store: dict`
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
  - `context_summary: str`
  - `context_token_count: int`
  - `context_token_limit: int`
  - `context_should_compress: bool`
  - `context_next_node: str`
  - `compression_events: list[CompressionEvent]`
  - `memory_snapshot: LayeredMemory`
  - `history_summary: str`

导入约定：

- `add_messages` 从 langgraph 导入（`langgraph.graph.message` 或 langgraph 公开顶层）；
- `BaseMessage` 从 `langchain_core.messages` 导入；
- `RuntimeState` 从 `novagent.core.state` 导入；
- `CompressionEvent`、`LayeredMemory` 类型定义于 `novagent.graph.memory`，`graph.state` 从该模块导入（`memory.py` 不得反向导入 `graph.state`，避免循环导入）。

行为约定：

- `NovGraphState` 所有字段可选（`total=False`），图可以部分状态启动与更新；
- `messages` 通道使用 `add_messages` reducer：图执行中对 `messages` 的更新按 LangGraph 语义追加/合并（如按消息 ID 去重更新），而不是整体覆盖；
- 其余字段为默认覆盖语义的普通通道；
- `context_summary`/`context_token_count`/`context_token_limit`/`context_should_compress`/`context_next_node`/`compression_events`/`memory_snapshot`/`history_summary` 为分层记忆与上下文压缩机制的承载字段：`memory_snapshot` 由 `build_layered_memory` 产出，`context_token_count`/`context_token_limit`/`context_should_compress`/`context_next_node` 已有图内写入方（`context_monitor_node` 及 planner/verifier 的上游设置、compressor 占位清标记），`context_summary`/`compression_events`/`history_summary` 为压缩机制的 schema 预留（当前无图内写入方，属预期状态）。

## graph.memory — 三层 Memory 系统（Context Engineering 数据层）

模块 `novagent.graph.memory` 实现分层记忆的纯组装层：不调用模型、无网络、不写文件、不修改传入的 state；所有状态键容错读取（`state.get`），状态残缺不抛异常。

- 常量 `RULES_LAYER: dict`（固定规则层），结构恰为：

```python
{
    "scope": "workspace",
    "storage": "internal",
    "rules": [
        "Work inside the current workspace only.",
        "Use paths relative to the workspace; do not prefix paths with workspace/.",
        "Keep durable task context outside the raw messages transcript when possible.",
        "Treat TODO.md as working plan state, NOTEPAD.md as durable notes, and HISTORY_SUMMARY.md as compressed history.",
        "Do not expose memory write tools to agents; layered memory is assembled by the runtime.",
    ],
}
```

  规则文字逐字采用上述 5 条英文原文，不改写、不翻译。

- 文件读取辅助（NOTEPAD.md 持久笔记与 HISTORY_SUMMARY.md 压缩历史的只读入口）：
  - `read_notepad(runtime) -> dict`：读取 `runtime.workspace / "NOTEPAD.md"`；文件存在返回 `{"exists": True, "content": <UTF-8 全文>}`；文件不存在或读取失败返回 `{"exists": False, "content": ""}`，不抛异常；
  - `read_history_summary(runtime) -> dict`：同语义，读取 `runtime.workspace / "HISTORY_SUMMARY.md"`；
  - 两函数均只读；`runtime` 为 `RuntimeState`（使用其 `workspace` 属性），不校验路径逃逸（文件名固定、位于 workspace 根）。
- 内部辅助：
  - `_short_text(text, limit) -> str`：`str(text)` 长度超过 `limit` 时返回前 `limit - 3` 个字符 + `"..."`（结果总长不超过 `limit` 且以 "..." 结尾）；未超长时原样返回；
  - `_trim_handoffs(handoffs, keep=6) -> list`：输入为 list 时保留最近 `keep` 条（末尾 `keep` 条、顺序保持），非 list 返回 `[]`；
  - `_norm_sources(sources) -> list[dict]`：每项仅保留 `title` 与 `url` 两个键（缺失补 `""`），非 list 返回 `[]`。
- `build_layered_memory(state, *, node="graph") -> dict`：组装并返回 `{"rules", "working_memory", "history_summary_store"}` 三层（返回 dict 恰含这三键）：
  - `rules`：`dict(RULES_LAYER)`（复制，避免外部改动共享常量）；
  - `runtime = state.get("runtime")`：缺失或异常时文件读取层按不存在处理（`exists=False`、`content=""`）；
  - `working_memory`（当前任务状态层），键集恰为（16 键）：
    - `node`: 参数 `node`（默认 `"graph"`）
    - `task`: `state.get("task", "")`
    - `session_id`: `state.get("session_id", "")`（schema 预留键，缺失占位）
    - `session_turn`: `state.get("session_turn", 0)`（schema 预留键，缺失占位）
    - `plan_summary`: `state.get("plan_summary", "")`
    - `todos`: `state.get("todos", [])` 的浅拷贝列表
    - `acceptance_criteria`: `state.get("acceptance_criteria", [])` 的浅拷贝列表
    - `verification_commands`: `state.get("verification_commands", [])` 的浅拷贝列表
    - `research_notes`: `_short_text(state.get("research_notes", ""), 1600)`
    - `sources`: `_norm_sources(state.get("sources", []))`（仅 title/url）
    - `agent_handoffs`: `_trim_handoffs(state.get("agent_handoffs", []))`（最近 6 条）
    - `code_agent_summary`: `_short_text(state.get("code_agent_summary", ""), 1000)`
    - `verifier_summary`: `_short_text(state.get("verifier_summary", ""), 1000)`（schema 预留键，缺失占位）
    - `last_error`: `_short_text(state.get("last_error", ""), 1400)`
    - `attempts`: `state.get("attempts", 0)`
    - `max_attempts`: `state.get("max_attempts", 3)`
  - `history_summary_store`（压缩历史层），键集恰为（8 键）：
    - `history_path`: `"HISTORY_SUMMARY.md"`
    - `history_exists`: `read_history_summary(runtime).get("exists", False)`
    - `history_summary`: `_short_text(<read_history_summary 的 content>, 2200)`
    - `notepad_path`: `"NOTEPAD.md"`
    - `notepad_exists`: `read_notepad(runtime).get("exists", False)`
    - `notepad`: `_short_text(<read_notepad 的 content>, 1800)`
    - `context_summary`: `_short_text(state.get("context_summary", ""), 1600)`
    - `compression_events`: `state.get("compression_events", [])` 的最近 3 条（末尾 3 条、顺序保持）
- `format_layered_memory_for_prompt(memory) -> str`：`json.dumps(memory, ensure_ascii=False)`；返回值可被 `json.loads` 还原为与输入相等的数据。
- 模块同时定义 `CompressionEvent`、`LayeredMemory` 两个 TypedDict（供 `graph.state` 引用）。
- 本模块不提供任何 memory 写工具或写函数（layered memory 由 runtime 组装，规则见 `RULES_LAYER`）。

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

## graph.nodes — 规划/执行/验证/监控/压缩/收尾节点与路由

模块 `novagent.graph.nodes` 实现 LangGraph 节点函数与条件路由。节点与 LangGraph 节点签名兼容：第一个位置参数为状态 dict，返回普通 dict 更新；`model=None` 时内部 `create_model()`，支持离线注入 FakeModel。提示词导入约定：`PLANNER_PROMPT`、`VERIFIER_PROMPT` 均从 `novagent.prompts.stage3` 导入（模块级名字与常量为同一对象）。模块内 `planner_node`/`verifier_node`/`final_node`/`context_compressor_node` 不导入、不调用 `novagent.graph.memory`；`context_monitor_node` 是唯一例外（见下）。

- `planner_node(state, *, model=None, on_event=None, max_loops=10) -> dict`：
  1. `tools = [create_todo_write_tool(), call_search_agent 工具, call_code_agent 工具]`（恰 3 个）；`agent = model.bind_tools(tools)`；
  2. 委托工具为闭包实现的 `StructuredTool`（内部实现 `_call_search_agent_tool(state, writer, instruction)` / `_call_code_agent_tool(state, writer, instruction)`，`writer` 为 `on_event` 包装：`on_event=None` 时事件仅收集、不外发）；
  3. 状态 `todos` 为空 → 首次生成：消息 `[SystemMessage(PLANNER_PROMPT), HumanMessage(task)]`；已有 `todos` 且 `last_error` 非空 → 修订：HumanMessage 额外携带 `last_error` 与最近失败的验证信息，要求修订并只委托缺失修复；
  4. 手写 ReAct 循环最多 `max_loops=10` 轮：每轮 `response = agent.invoke(messages)` 并追加、发 `{"type": "ai_message", "content": <AI 文本>}`；无 `tool_calls` 立即结束；否则逐个 tool_call：执行前发 `{"type": "tool_call", "name": ..., "args": ...}`，结果以 `ToolMessage(json.dumps(result))` 回传，执行后发 `{"type": "tool_result", "name": ..., "result": ...}`；
  5. `todo_write` tool_call：从 args 提取 `plan_summary`、`todos`（补齐缺失键、非法 status 归一 `"pending"`）、`acceptance_criteria`、`verification_commands`（多次调用取最后一次）；
  6. `call_search_agent` tool_call（args `{instruction: str}`）：先发 `{"type": "handoff", "from": "planner", "to": "searchAgent", "instruction": ...}`，调用 `run_search_agent(<合并视图>, instruction, writer=writer, model=model)`（合并视图 = state 叠加本节点内已产生的 `todos`/`research_notes` 更新，`model` 为 planner 收到的注入模型，保证多次委托链式一致且可离线注入）；状态更新——`research_notes` 追加 agent summary（已有内容以空行连接）、`sources` 按 url 去重保序合并 `SourceItem`（从 ok 的 `search_results` 事件提取 title/url/content/score，无明细时仅 url）、`agent_handoffs` 追加 `{"from_agent": "planner", "to_agent": "searchAgent", "instruction", "result": <summary>}`；
  7. `call_code_agent` tool_call（args `{instruction: str}`）：先发 `{"type": "handoff", "from": "planner", "to": "codeAgent", "instruction": ...}`，调用 `run_code_agent(<合并视图>, instruction, writer=writer, model=model)`；状态更新——`todos` 取该次委托返回的 todos、`code_agent_summary` 为 agent summary、`agent_handoffs` 追加 `{"from_agent": "planner", "to_agent": "codeAgent", "instruction", "result"}`、`messages` 并入委托新增的 AIMessage/ToolMessage；
  8. 返回更新 dict：计划四字段（发生 `todo_write` 时）+ `research_notes`/`sources`/`agent_handoffs`/`code_agent_summary`/`todos`/`messages`（发生对应委托时，仅包含有更新的键）+ `context_next_node`（恒为 `"verifier"`，每次返回都包含——上游设置约定：规划完成后进入验证）。
- `verifier_node(state, *, model=None) -> dict`：
  1. 从 `state["runtime"]` 取 `RuntimeState`（缺失抛 `ValueError`）；`tools = build_read_only_tools(runtime) + [create_bash_tool(runtime), WebSearchTool]`（恰 4 个：`read_file`/`grep`/`bash`/`web_search`）；
  2. 消息 `[SystemMessage(VERIFIER_PROMPT), HumanMessage(计划 + 验收标准 + 验证命令 + 最近执行输出)]`；ReAct 循环（同语义、`max_loops=10`，无事件上报）；「最近执行输出」取 `state.get("last_actor_summary", "")`——stage3 中该字段不再由图内节点产生、通常为空；bash 的只读性由提示词约束（安全检查），验证命令的程序化执行（下述第 4 步）保持不变，`web_search` 缺 `TAVILY_API_KEY` 时走既有错误降级；
  3. 最终 AI 文本解析 JSON `{passed, reason, checks, recommended_next_instruction}`（容忍代码围栏）；解析失败按判定失败处理；
  4. 同时用 `execute_command` 逐条运行 `verification_commands`（workspace 为 cwd，默认 30 秒超时），构造 `VerificationResult`：`ok = exit_code == 0`；超时/异常 → `exit_code=None`、`ok=False`、stderr 记录错误信息；
  5. 整体 `passed = llm_passed and all(command ok)`；
  6. 返回更新：`passed`、`attempts`（原值 +1）、`verification_results`、`verification_checks`、`last_error`（失败时为 reason/命令失败/解析诊断，通过时为 `""`）、`final_answer`（整体通过时为 reason）、`todos`（整体通过 → 非 completed 全标 `completed`；失败 → in_progress 全标 `blocked`）；此外，未通过且自增后的 `attempts < max_attempts`（缺省 3）时返回另含 `context_next_node="planner"`（上游设置约定：失败回到规划修订），通过或预算耗尽时不包含该键（路由由 `context_monitor_route` 的 `passed`/预算判断优先终止）。
- `final_node(state) -> dict`：确定性节点（不调用 LLM、不修改 `passed`），返回更新仅含 `final_answer`：
  - `passed` 为真：成功格式文本 `"Task completed in <N> attempt(s). <reason>"`；
  - `passed` 为假：失败格式文本 `"Task failed after <N> attempt(s).\nLast error: <last_error>"`。
- `context_monitor_node(state, *, model=None) -> dict`：上下文监控节点（压缩机制第一步：token 监控）。确定性节点：不调用模型对话（`invoke`）、无网络、不写文件、不修改传入 state；`model=None` 时不构造模型（不调用 `create_model`）。
  1. 构造 memory payload：`memory_payload = HumanMessage(content=format_layered_memory_for_prompt(build_layered_memory(state)))`——`build_layered_memory` 与 `format_layered_memory_for_prompt` 从 `novagent.graph.memory` 导入（模块内唯一使用 `novagent.graph.memory` 的函数）；
  2. 计数输入 = `list(state.get("messages") or []) + [memory_payload]`；
  3. token 估算：`model is not None` 时调用 `model.get_num_tokens_from_messages(<计数输入>)`；`model` 为 None、模型无该方法（`AttributeError`）或调用抛出任何异常时，fallback 为 `len(text) // 4`——`text` 为计数输入全部消息文本内容的顺序拼接（消息文本取 `content` 为 str 时原样，非 str 时 `str(content)`）；
  4. 压缩判定：`limit = state.get("context_token_limit") or 400000`；`should_compress = token_count > limit`（严格大于，等于不触发）；
  5. `context_next_node` 仅透传上游设置值（planner 后为 `"verifier"`，verifier 失败后为 `"planner"`；本节点不自行决策），缺失时取 `"verifier"`；
  6. 返回更新恰为 `{"context_token_count": <int>, "context_should_compress": <bool>, "context_next_node": <str>}`。
- `context_monitor_route(state) -> str`：上下文监控后的条件路由（由 `build_complex_workflow` 接线）：`state.get("passed")` 为真 → `"final"`（优先级最高）；`state.get("attempts", 0) >= state.get("max_attempts", 3)` → `"final"`（预算耗尽，先于压缩判定——无条件边直连 final，终止语义由本路由承担）；`state.get("context_should_compress")` 为真 → `"context_compressor"`；否则 → `state.get("context_next_node") or "verifier"`。
- `context_compressor_node(state) -> dict`：上下文压缩占位节点（压缩机制接线占位，真实压缩逻辑——摘要生成、`messages` 裁剪、`context_summary`/`compression_events`/`history_summary` 写入——属后续 change）。确定性节点：不调用模型对话（`invoke`）、不构造模型（不调用 `create_model`）、无网络、不写文件、不修改传入 state；返回更新恰为 `{"context_should_compress": False}`（清除压缩标记，避免 compressor 分支在后续 monitor 轮次重复触发）。
- `context_compressor_route(state) -> str`：`state.get("context_next_node") or "verifier"`。

## graph.workflow — LangGraph 工作流组装

模块 `novagent.graph.workflow` 组装可执行的 stage3 工作流：

- `build_complex_workflow(*, model=None)`（唯一构建函数；旧 `build_workflow` 已移除）：
  - `graph = StateGraph(NovGraphState)`；
  - 注册节点：`"planner"` → 图内包装——经 `functools.partial` 绑定注入的 `model`，执行时调用 `langgraph.config.get_stream_writer()`，把每个事件复制并补 `"node": "planner"` 后作为 `on_event` 传给 `planner_node`（协调事件进入 custom 流；`invoke()` 等不消费 custom 流的场景下 writer 静默丢弃）；`"context_monitor"` → `context_monitor_node`（经 `functools.partial` 绑定注入的 `model`，供精确 token 估算）；`"context_compressor"` → `context_compressor_node`（直接注册，确定性节点不接模型）；`"verifier"` → `verifier_node`（经 `functools.partial` 绑定注入的 `model`）；`"final"` → `final_node`；不注册 `"actor"`；
  - 边：`START → "planner"`、`"planner" → "context_monitor"`、`"verifier" → "context_monitor"`、`"final" → END`；
  - `"context_monitor"` 经 `context_monitor_route` 条件边路由：`{"context_compressor": "context_compressor", "verifier": "verifier", "planner": "planner", "final": "final"}`；
  - `"context_compressor"` 经 `context_compressor_route` 条件边路由：`{"verifier": "verifier", "planner": "planner", "final": "final"}`；
  - 返回 `graph.compile()`。
- 图拓扑恰为：START → planner → context_monitor；context_monitor →（通过或预算耗尽）final，或 →（应压缩）context_compressor，或 →（否则）`context_next_node`；context_compressor →（`context_next_node`）verifier/planner/final；verifier → context_monitor；final → END。
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

- 模块函数 `build_memory_snapshot(state) -> str`：layered memory 快照的预留接口，返回空字符串（不调用 LLM、无网络、无副作用）；本 change 不接入 `novagent.graph.memory`，真实快照属后续 change。
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

- `tests/test_context_monitor.py` 扩展（离线测试，不发起网络请求）：既有覆盖保持——精确估算（注入实现 `get_num_tokens_from_messages` 的假模型：返回恰三键、`context_token_count` 为模型返回值、计数输入恰为 `messages + [memory_payload]`（长度 +1）且末项为 `HumanMessage`、文本可 `json.loads` 并与 `format_layered_memory_for_prompt(build_layered_memory(state))` 一致）、fallback（`model=None` 时文本拼接长度整除 4 且不调用 `create_model`；注入抛 `RuntimeError` 的假模型同样容错）、阈值判定（等于 limit 不压缩、超过压缩、缺失默认 400000）、`context_next_node` 透传、路由优先级（`passed` → `"final"` 即使应压缩；应压缩 → `"context_compressor"`；否则透传）、纯函数性；新增——预算耗尽路由：`passed` 假且 `attempts >= max_attempts` → `"final"`（即使 `context_should_compress` 为真），优先级位于 `passed` 之后、`should_compress` 之前；`context_compressor_node` 返回恰 `{"context_should_compress": False}` 且不修改传入 state、不调用 `create_model`；`context_compressor_route` 四取值映射（`"planner"`/`"verifier"`/`"final"` 透传、缺失默认 `"verifier"`）；
- `tests/test_memory.py` 保持（纯函数离线测试，不调用模型、不发起网络请求）：`RULES_LAYER` 常量结构（scope/storage/5 条规则逐字）；`build_layered_memory` 返回恰含三层且 `working_memory` 16 键、`history_summary_store` 8 键齐全；workspace 有/无 `NOTEPAD.md` 与 `HISTORY_SUMMARY.md` 时 `read_notepad`/`read_history_summary` 的 exists/content 行为（缺失不抛异常）；`_short_text` 截断（结果 ≤ limit 且以 "..." 结尾）与短文本原样；`_trim_handoffs` 超 6 条保留最近 6 条且顺序保持；`sources` 收敛为仅 title/url；`context_summary` 截断与 `compression_events` 最近 3 条；`format_layered_memory_for_prompt` 返回可 `json.loads` 且与输入相等；`NovGraphState` 含 8 个新字段；空 state 容错（不抛异常、占位值正确）；
- `tests/test_agent_loop.py` 保持 stage3 协调语义覆盖（FakeModel 离线经 `stream_agent_events` 驱动新图）：通过路径（planner 轮 1 `todo_write` 发布计划、轮 2 `call_code_agent` 委托实现、轮 3 纯文本结束 → verifier 输出 `passed=true` JSON → final），事件顺序（planner `node_output` → planner 内部事件（带 `node="planner"`，含 `handoff`）→ verifier `node_output` → final `node_output`——`context_monitor`/`context_compressor` 不产生统一事件），`final_answer` 以 "Task completed" 开头，文件落盘；失败回环（verifier 首轮失败 → `context_next_node="planner"` 经 context_monitor 回 planner，收到含 `last_error` 的修订 HumanMessage 后 `todo_write` 修订，最终通过；全程无 `GraphRecursionError`）；`max_attempts=1` 预算耗尽经 context_monitor 直接 final（"Task failed"）；
- `tests/test_cli.py`：`--help` 含 `--max-attempts` 与 `--workspace`；workspace 自动创建与缺 key 清晰报错（退出码 1）；统一事件格式的 fake 流驱动 CLI 渲染——输出依次包含 📋 Planner、🔧 Actor、✅ Verifier、📝 Final 与工具详情、最终回答；fake 断言 `--max-attempts` 默认 3 与显式传值生效；
- `tests/test_graph_nodes.py` 更新：planner 绑定工具恰为 `["todo_write", "call_search_agent", "call_code_agent"]`；消息构造（首次生成与含 `last_error` 的修订 HumanMessage）；`todo_write` 计划归一化与多次调用取最后一次；委托语义——`call_search_agent`/`call_code_agent` 先发 `handoff` 事件再调 `run_search_agent`/`run_code_agent`，状态更新（`research_notes` 追加、`sources` 按 url 去重保序、`agent_handoffs` 记录、`code_agent_summary`、`todos`、`messages`）；循环边界；planner 返回恒含 `context_next_node="verifier"`；`novagent.graph.nodes` 不含 `actor_node` 且不再提供 `verifier_route`；verifier 断言（`VERIFIER_PROMPT` 为 stage3 同一对象、绑定工具恰 4 个 read_file/grep/bash/web_search）新增：失败且自增后 `attempts < max_attempts` 返回含 `context_next_node="planner"`、通过时不含该键；
- `tests/test_graph_workflow.py` 更新：编译图（`build_complex_workflow()`）节点集合恰为 `{"planner", "context_monitor", "context_compressor", "verifier", "final"}`，`START → planner`、`planner → context_monitor`、`verifier → context_monitor`、context_monitor 条件边恰四目标（context_compressor/verifier/planner/final）、context_compressor 条件边恰三目标（verifier/planner/final）、`final → END`；`novagent.graph.workflow` 不再提供 `build_workflow`；planner 桥接事件带 `node="planner"`；端到端 verifier 绑定恰为 `["read_file", "grep", "bash", "web_search"]`；updates 流执行序列断言——成功路径恰为 planner→context_monitor→verifier→context_monitor→final，预算耗尽（`max_attempts=1`）同序终止于 final，压缩路径（`context_token_limit=1`）恰为 planner→context_monitor→context_compressor→verifier→context_monitor→final 且 compressor 更新恰 `{"context_should_compress": False}`；
- `tests/test_graph_state.py` 保持：`NovGraphState` 8 个 context/memory 字段与 `CompressionEvent`/`LayeredMemory` 类型，`add_messages` 语义不变；
- `tests/test_web_search_tool.py`、`tests/test_search_agent.py`、`tests/test_code_agent.py`、`tests/test_registry.py`、`tests/test_file_tools.py`、`tests/test_grep_tool.py`、`tests/test_bash_tool.py`、`tests/test_paths.py`、`tests/test_openai_provider.py` 保持既有覆盖；
- 全部测试离线运行，不发起真实网络请求。
