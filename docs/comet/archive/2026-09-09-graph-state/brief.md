# 目标

在 `src/novagent/graph/state.py` 中定义 LangGraph 图的共享状态：新增 `TodoItem`、`VerificationResult`、`NovGraphState` 三个 TypedDict，其中 `messages` 字段使用 `Annotated[list[BaseMessage], add_messages]`，使 LangGraph 在图执行时自动合并消息而不是覆盖。为使 `add_messages` 可导入，在 `pyproject.toml` 中显式引入 `langgraph` 运行依赖并同步 `uv.lock`。

# 范围

- 新增 `src/novagent/graph/__init__.py`：与项目其他子包一致的空包文件。
- 新增 `src/novagent/graph/state.py`，逐字遵循用户给定定义：
  - `TodoItem(TypedDict)`：`id: str`、`content: str`、`status: str`（"pending" | "in_progress" | "completed" | "blocked"）、`note: str`；
  - `VerificationResult(TypedDict)`：`command: str`、`ok: bool`、`exit_code: int | None`、`stdout: str`、`stderr: str`；
  - `NovGraphState(TypedDict, total=False)`：`task: str`、`runtime: RuntimeState`、`messages: Annotated[list[BaseMessage], add_messages]`、`plan_summary: str`、`todos: list[TodoItem]`、`acceptance_criteria: list[str]`、`verification_commands: list[str]`、`verification_results: list[VerificationResult]`、`passed: bool`、`attempts: int`、`max_attempts: int`、`final_answer: str`。
- `runtime` 字段复用 `novagent.core.state.RuntimeState`（现有 dataclass），不复制定义。
- `pyproject.toml` 运行依赖新增 `langgraph`（不引入完整 `langchain` 发行包），并同步 `uv.lock`。
- 新增 `tests/test_graph_state.py`：离线验证类型定义、`messages` 注解形式与 reducer 合并语义。

# 非目标

- 不组装具体 LangGraph 图（StateGraph、节点、边、条件路由）——仅定义共享状态；图的构建留给后续 change。
- 不修改现有手写 ReAct 循环（`core/agent.py`）与 CLI 行为。
- 不实现 checkpointing、中断恢复、多 Agent 等图执行能力。
- 不改变五个工具（read_file/write_file/edit_file/grep/bash）的行为与 `build_tools` 注册方式。
- 不改变 `create_model` 的环境变量约定与错误信息。

# 验收示例

- A1: Scenario: 共享状态类型定义 WHEN 导入 `novagent.graph.state` THEN 模块提供 `TodoItem`、`VerificationResult`、`NovGraphState` 三个 TypedDict AND `TodoItem` 注解恰为 id: str、content: str、status: str、note: str AND `VerificationResult` 注解恰为 command: str、ok: bool、exit_code: int | None、stdout: str、stderr: str AND `NovGraphState` 注解恰为 task: str、runtime: RuntimeState、messages、plan_summary: str、todos: list[TodoItem]、acceptance_criteria: list[str]、verification_commands: list[str]、verification_results: list[VerificationResult]、passed: bool、attempts: int、max_attempts: int、final_answer: str AND `NovGraphState` 的 `__total__` 为 False（所有字段可选）。
- A2: Scenario: messages 使用 add_messages reducer WHEN 检查 `NovGraphState.__annotations__["messages"]` THEN 其为 `Annotated[list[BaseMessage], add_messages]` 形式（`typing.get_args` 可取出 list[BaseMessage] 与 add_messages）AND `add_messages` 可从 langgraph 导入 AND `BaseMessage` 来自 langchain_core.messages。
- A3: Scenario: LangGraph 自动合并消息 WHEN 用仅含 messages 通道的最小 StateGraph 以初始 `[SystemMessage("s")]` invoke 后再以 `[HumanMessage("hi")]` 更新 THEN 通道内消息为两条的拼接（`[SystemMessage("s"), HumanMessage("hi")]`）而不是覆盖 AND 直接调用 `add_messages(["a"], ["b"])` 追加为 `["a", "b"]`。
- A4: Scenario: 依赖与现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 安装成功且 `uv.lock` 与 `pyproject.toml` 一致 AND `pyproject.toml` 运行依赖新增 `langgraph` 且未引入完整 `langchain` 发行包 AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0。

# 约束与不变量

- `messages` 字段必须为 `Annotated[list[BaseMessage], add_messages]`；`add_messages` 从 langgraph 导入，`BaseMessage` 从 `langchain_core.messages` 导入。
- `NovGraphState` 使用 `total=False`，所有字段可选，允许图以部分状态启动与更新。
- `runtime` 直接引用 `novagent.core.state.RuntimeState`，不在本模块重复定义。
- 类型定义逐字遵循用户提供的字段名、顺序与类型（`status` 的四种取值以注释形式保留在源码中）。
- 兼容 Python >= 3.10；全部测试离线运行，不发真实网络请求。

# 决策

- D1 显式新增 `langgraph` 运行依赖：`add_messages` 由 langgraph 包提供，用户明确要求 LangGraph 的自动合并语义，这是唯一可行实现；只加 `langgraph`，不引入完整 `langchain` 发行包（延续最小依赖集决策）。
- D2 本 change 仅定义共享状态，不组装 StateGraph：用户请求明确限定在 `graph/state.py` 的状态定义；A3 中仅用最小临时 StateGraph 作为 reducer 语义的可观察证明，不落盘为产品代码。
- D3 `runtime` 复用 `core.state.RuntimeState`：`NovGraphState.runtime` 直接引用现有 dataclass 类型，避免两处定义漂移；LangGraph 状态通道允许任意类型，无碍后续建图。
- D4 新增 `graph/` 子包并按项目 src layout 惯例提供 `__init__.py`，与 `core/`、`tools/`、`providers/`、`cli/` 结构一致。

# 待解决问题

（无未解决项）

# 验证预期

- `uv sync` 成功且 `uv.lock` 一致。
- `uv run pytest` 全部通过（含新增 `tests/test_graph_state.py`，离线）。
- `uv run novagent --help` 退出码 0（现有行为不受影响）。
