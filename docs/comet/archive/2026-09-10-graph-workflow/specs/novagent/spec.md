# novagent 完整目标规格

本规格描述 change 归档后 `novagent` 项目的完整行为。项目由 uv 管理，src layout，包名 `novagent`。

## 项目与依赖

- `pyproject.toml`：`name = "novagent"`，src layout（uv_build 后端指向 `src/novagent`），`requires-python >= 3.10`，控制台脚本 `novagent = novagent.cli.app:main`。
- 运行依赖：`langchain-openai`、`typer`、`python-dotenv`、`rich`、`langgraph`。开发依赖：`pytest`。
- `uv.lock` 存在且与 `pyproject.toml` 一致；`uv sync` 可在新环境完成安装；锁中不引入完整 `langchain` 发行包。
- 包结构：

```text
src/novagent/
├── __init__.py
├── __main__.py
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
│   └── todo_tools.py
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

## core.agent — ReAct 循环与事件流（stage1，保持不变）

- 模块常量 `ACTOR_PROMPT`（stage1 版本），内容以 "You are the actor node in novagent's ReAct workflow." 开头，约定：只用 FileWriteTool 新建文件、编辑已有文件前先用 FileReadTool 读取、聚焦修改用 FileEditTool、用 BashTool 运行命令并验证结果；BashTool 已在 workspace 内运行，使用相对路径而非 "cd /workspace"；结束时给出已改动文件与已运行命令的简洁摘要。
- `stream_agent_events(task, *, workspace, max_loops=10, model=None)` 为生成器，逐步产出普通 dict 事件，类型为 `ai_message`、`tool_call`、`tool_result`、`final_answer`：
  1. 创建 `RuntimeState(workspace)`，构建 `tools = build_tools(state)`；
  2. `model` 为 None 时调用 `create_model()` 创建；随后 `agent = model.bind_tools(tools)`；
  3. 消息列表初始化为 `[SystemMessage(ACTOR_PROMPT), HumanMessage(task)]`；
  4. 最多循环 `max_loops` 次：`response = agent.invoke(messages)`；`messages.append(response)`；yield `{"type": "ai_message", "content": <response 文本内容>}`；
     - `response.tool_calls` 为空时 break；
     - 否则对每个 tool_call 依次：yield `{"type": "tool_call", "name": ..., "args": ...}`；执行工具并把结果字符串经 `json.dumps` 序列化后构造 `ToolMessage(tool_call_id=<call id>)` append 到消息列表；yield `{"type": "tool_result", "name": ..., "result": <工具原始返回字符串>}`；
  5. 循环结束（自然结束或 break）后 yield `{"type": "final_answer", "content": <最后一轮 AI 消息文本>}`。
- 工具执行语义：
  - 未知工具名：不抛出，结果为包含 `unknown tool` 的错误文本；
  - 工具抛出异常：不向调用方传播，结果为 `Error: <异常信息>` 文本；
  - 两种错误文本同样进入 `ToolMessage` 与 `tool_result` 事件，供模型下一轮修正。
- 达到 `max_loops` 上限仍未出现无 tool_calls 的响应时，循环停止并照常产出 `final_answer`（内容为最后一轮 AI 消息文本）。

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
- `NovGraphState(TypedDict, total=False)`，字段与类型：
  - `task: str`
  - `runtime: RuntimeState`（`novagent.core.state.RuntimeState`，直接复用，不复制）
  - `messages: Annotated[list[BaseMessage], add_messages]`
  - `plan_summary: str`
  - `todos: list[TodoItem]`
  - `acceptance_criteria: list[str]`
  - `verification_commands: list[str]`
  - `verification_results: list[VerificationResult]`
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

## prompts.stage2 — LangGraph 工作流系统提示

模块 `novagent.prompts.stage2` 是 stage2（LangGraph 工作流）系统提示的唯一权威来源，提供四个模块常量（均为非空字符串）：

- `PLANNER_PROMPT`：planner 系统提示，说明职责（把任务拆解为可执行计划）与输出约定（调用 `todo_write` 工具提交计划：`plan_summary`、有序 todos（唯一 id、content、status 从 `"pending"` 开始、note）、可观察的 `acceptance_criteria`、`verification_commands`；被要求修订时在保持其余稳定的前提下处理报告的失败）。
- `ACTOR_PROMPT`：actor 系统提示，以 "You are the actor node in novagent's LangGraph workflow." 开头；约定：按当前计划逐步执行、只在工作区内操作工具、文件工具与 BashTool 的使用规则（与 stage1 一致：先读后改、聚焦编辑、BashTool 已在 workspace 内运行用相对路径）、用 `todo_update` 工具汇报每个步骤的进度、结束时给出已改动文件与已运行命令的简洁摘要。
- `VERIFIER_PROMPT`：verifier 系统提示，说明只读核查职责（检查每条验收标准、考虑已执行的验证命令及结果、不得修改任何内容）与输出约定（最终回复单个 JSON `{"passed": bool, "reason": str, "checks": [{"name", "passed", "detail"}], "recommended_next_instruction": str}`，仅当全部验收标准满足时 `passed` 为 true）。
- `FINAL_PROMPT`：最终总结提示（预留常量，本阶段未接线到任何 LLM 调用）：说明输入为任务、计划摘要与验证结果，输出为面向用户的简洁最终总结。

## graph.nodes — 规划/执行/验证/收尾节点与路由

模块 `novagent.graph.nodes` 实现 LangGraph 节点函数与条件路由。节点与 LangGraph 节点签名兼容：第一个位置参数为状态 dict，返回普通 dict 更新；`model=None` 时内部 `create_model()`，支持离线注入 FakeModel。提示词导入约定：`PLANNER_PROMPT`、`VERIFIER_PROMPT`、`ACTOR_PROMPT` 均从 `novagent.prompts.stage2` 导入（模块级名字与 stage2 常量为同一对象）。

- `planner_node(state, *, model=None) -> dict`：
  1. `agent = model.bind_tools([create_todo_write_tool()])`；
  2. 状态 `todos` 为空 → 首次生成：消息 `[SystemMessage(PLANNER_PROMPT), HumanMessage(task)]`；
  3. 已有 `todos` 且 `last_error` 非空 → 修订：HumanMessage 额外携带 `last_error` 与最近失败的验证信息，要求修订计划；
  4. 调用 agent 一轮；从 `todo_write` 的 tool_call args 提取 `plan_summary`、`todos`、`acceptance_criteria`、`verification_commands`；todos 每项补齐缺失键为 `""`/`"pending"`，非法 `status` 归一为 `"pending"`；
  5. 返回更新 `{"plan_summary", "todos", "acceptance_criteria", "verification_commands"}`；
  6. 无 `todo_write` tool_call：抛出带说明的 `ValueError`。
- `actor_node(state, *, model=None, on_event=None) -> dict`：
  1. 从 `state["runtime"]` 取 `RuntimeState`（缺失抛 `ValueError`）；`tools = build_tools(runtime) + [create_todo_update_tool()]`（6 个）；`agent = model.bind_tools(tools)`；
  2. 消息 `[SystemMessage(stage2.ACTOR_PROMPT), HumanMessage(计划 + 任务)]`（含 `plan_summary` 与 todos 列表的可读渲染）；
  3. ReAct 循环 `max_loops=10`，语义与 `core.agent.stream_agent_events` 一致（事件类型、错误回传、`json.dumps` ToolMessage）；每个事件产生时调用 `on_event(event)`（None 时跳过）；
  4. 循环中 `todo_update` tool_call 按 `todo_id` 合并进 todos（更新 `status`/`note`；未知 id 忽略）；
  5. 返回更新：`messages`（仅循环新增的 AIMessage/ToolMessage）、`last_actor_summary`（最后一轮 AI 文本）、`todos`（发生 todo_update 时）。
- `verifier_node(state, *, model=None) -> dict`：
  1. 从 `state["runtime"]` 取 `RuntimeState`（缺失抛 `ValueError`）；`agent = model.bind_tools(build_read_only_tools(runtime))`；
  2. 消息 `[SystemMessage(VERIFIER_PROMPT), HumanMessage(计划 + 验收标准 + 验证命令 + 最近 actor 输出)]`；只读 ReAct 循环（同语义、`max_loops=10`，无事件上报）；
  3. 最终 AI 文本解析 JSON `{passed, reason, checks, recommended_next_instruction}`（容忍代码围栏）；解析失败按判定失败处理；
  4. 同时用 `execute_command` 逐条运行 `verification_commands`（workspace 为 cwd，默认 30 秒超时），构造 `VerificationResult`：`ok = exit_code == 0`；超时/异常 → `exit_code=None`、`ok=False`、stderr 记录错误信息；
  5. 整体 `passed = llm_passed and all(command ok)`；
  6. 返回更新：`passed`、`attempts`（原值 +1）、`verification_results`、`verification_checks`、`last_error`（失败时为 reason/命令失败/解析诊断，通过时为 `""`）、`final_answer`（整体通过时为 reason）、`todos`（整体通过 → 非 completed 全标 `completed`；失败 → in_progress 全标 `blocked`）。
- `final_node(state) -> dict`：确定性节点（不调用 LLM、不修改 `passed`），返回更新仅含 `final_answer`：
  - `passed` 为真：成功格式文本，包含 "completed"、attempts 数值与 verifier 原因（既有 `final_answer`/reason）；
  - `passed` 为假：失败格式文本，包含 "failed"、attempts 数值与 `last_error` 内容。
- `verifier_route(state) -> str`：`state.get("passed")` 为真 → `"final"`；`state.get("attempts", 0) >= state.get("max_attempts", 3)` → `"final"`；否则 → `"planner"`。

## graph.workflow — LangGraph 工作流组装

模块 `novagent.graph.workflow` 组装可执行的 stage2 工作流：

- `build_workflow(*, model=None)`：
  - `graph = StateGraph(NovGraphState)`；
  - 注册节点：`"planner"` → `planner_node`、`"actor"` → `actor_node`、`"verifier"` → `verifier_node`（三者经 `functools.partial` 绑定注入的 `model`，None 时节点内部 `create_model()`）；`"final"` → `final_node`；
  - 边：`START → "planner"`、`"planner" → "actor"`、`"actor" → "verifier"`；
  - `"verifier"` 经 `verifier_route` 条件边路由：`{"final": "final", "planner": "planner"}`；
  - `"final" → END`；
  - 返回 `graph.compile()`。
- 图拓扑恰为：START → planner → actor → verifier →（通过或预算耗尽）final → END，或 verifier →（未通过且预算未耗尽）planner。
- 本模块不提供 CLI 入口；图的使用方由后续 change 提供。

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
  - 返回包含退出码、stdout、stderr 的文本（对外行为与历史一致）；
  - 非零退出码不抛异常，正常返回输出并标注退出码。

## tools.registry — build_tools 与 build_read_only_tools

- `build_tools(state: RuntimeState) -> list[StructuredTool]`；
- 依次注册 `read_file`、`write_file`、`edit_file`、`grep`、`bash` 五个工具，args schema 由函数签名自动推导；
- 返回列表可直接用于 `model.bind_tools(tools)`。
- `build_read_only_tools(state: RuntimeState) -> list[StructuredTool]`：仅含 `read_file`、`grep`（无写副作用、无命令执行），供只读 verifier agent 使用。

## providers.openai_provider — create_model

- `create_model() -> ChatOpenAI`：
  1. `load_dotenv()` 加载项目根 `.env`；
  2. 读取 `OPENAI_API_KEY`，缺失时抛出说明配置方法的 `ValueError`；
  3. `OPENAI_MODEL` 可选，默认 `gpt-4o-mini`；`OPENAI_BASE_URL` 可选，设置时传入 `base_url`；
  4. 返回 `langchain_openai.ChatOpenAI` 实例。

## cli.app — novagent 命令

- `novagent <task> --workspace <path>`：`task` 为位置参数；`--workspace` 默认 `<cwd>/workspace`；
- 执行流程：
  1. 解析并自动创建 workspace（`parents=True, exist_ok=True`），打印 workspace 路径；
  2. 调用 `create_model()`；`OPENAI_API_KEY` 缺失等配置错误以清晰错误信息退出（非零退出码），不打印未捕获 traceback；
  3. 调用 `core.agent.stream_agent_events(task, workspace=..., model=...)` 消费事件流，用 `rich.Console` 实时打印每个事件：
     - `ai_message` → 打印 AI 文本内容；
     - `tool_call` → 打印工具名与参数；
     - `tool_result` → 打印工具结果；
     - `final_answer` → 打印最终回答；
- `python -m novagent` 与控制台脚本 `novagent` 行为一致（`__main__.py` 调用 `cli.app`）。
- CLI 不保留独立的内联工具调用循环；循环逻辑唯一来源于 `core.agent.stream_agent_events`。

## tests

- `tests/` 使用 pytest 覆盖：路径安全（`..` 与绝对路径逃逸）、三个文件工具语义（含多匹配报错且文件不变）、grep 参数行为、bash 的 cwd 与超时、`build_tools` 返回 5 个工具及命名、`create_model` 读取 `.env` 与缺 key 报错、CLI workspace 自动创建与缺 key 清晰报错（typer CliRunner）；
- `tests/test_agent_loop.py` 以 FakeModel 离线覆盖 `stream_agent_events`（stage1，ACTOR_PROMPT 为 `core.agent` 版本）：事件序列与顺序、首轮消息构建、`ToolMessage` 的 `tool_call_id` 与 `json.dumps` 内容、错误回传、`max_loops`；
- `tests/test_graph_state.py` 离线覆盖 LangGraph 共享状态：TypedDict 字段注解、`total=False`、`messages` reducer 注解与合并语义；
- `tests/test_graph_nodes.py` 以 FakeModel 离线覆盖节点与路由（actor 系统提示断言使用 `prompts.stage2.ACTOR_PROMPT`）：planner 首次生成与按失败修订、actor ReAct 事件与 todo 回写（含未知 id 忽略）、verifier 通过/失败语义、`verifier_route` 分支、todo 工具 schema；
- `tests/test_graph_workflow.py` 离线覆盖工作流组装与端到端：图结构（编译、四节点集合、START→planner、final→END）、注入 FakeModel 的端到端一次通过路径（planner→actor→verifier→final，passed、final_answer 成功格式、todos 全 completed、模型调用次数证明路径）、失败重试路径（回 planner 修订且 HumanMessage 含失败原因，attempts==2 后通过）、`final_node` 通过/失败格式化、stage2 常量非空与内容特征、`nodes.py` 引用与 stage2 同一对象；
- CLI 测试以 monkeypatch 假事件流离线验证 rich 打印；
- 全部测试离线运行，不发起真实网络请求。
