# 目标

在 `src/novagent/agents/code_agent.py` 中实现独立的代码实现专家 Agent：`run_code_agent(state, instruction, *, writer=None, max_loops=10)` 绑定 `build_tools(state["runtime"]) + [TodoUpdateTool]`（6 个工具），以手写 ReAct 循环在工作区内执行文件与 shell 操作；`todo_update` 调用实时迁移 todo 状态；`writer` 实时写出 `ai_message`/`tool_call`/`tool_result`/`final_answer` 事件；layered memory 快照先留接口（`build_memory_snapshot`，当前返回空）；返回 `{ok: True, summary, todos, messages, tool_events}`。

# 范围

- 新增 `src/novagent/agents/__init__.py`（空包文件）与 `src/novagent/agents/code_agent.py`：
  - 模块常量 `CODE_AGENT_PROMPT`：逐字使用用户给定的英文系统提示（"You are codeAgent, a focused implementation specialist." 开头；强制 todo 进度更新；FileWrite/FileRead/FileEdit/Bash 使用规则；提及 NotepadAppendTool/NotepadReadTool；相对路径不 "cd /workspace"；吸收 research notes；结尾汇总改动文件与运行过的检查）；
  - 模块函数 `build_memory_snapshot(state) -> str`：layered memory 快照的预留接口，本 change 返回空字符串（不调用 LLM、无网络、无副作用）；
  - `run_code_agent(state, instruction, *, writer=None, max_loops=10, model=None) -> dict`：从 `state["runtime"]` 取 `RuntimeState`（缺失抛 `ValueError`）；`bind_tools(build_tools(runtime) + [create_todo_update_tool()])`；消息为 `SystemMessage(CODE_AGENT_PROMPT)` + `HumanMessage(task + instruction + session_context + memory snapshot)`；手写 ReAct 循环最多 `max_loops` 轮（无 tool_calls 提前结束）；逐个执行 tool_call（未知工具与异常转为 `Error: ...` 文本回传，与 `graph.nodes._execute_tool` 同语义；`ToolMessage(json.dumps(result))`）；`todo_update` 按 `todo_id` 合并进 todos（`status` 限 `pending|in_progress|completed|blocked`，`note` 提供时更新，未知 id 忽略）；事件与 `actor_node` 同类型（`ai_message`/`tool_call`/`tool_result`/`final_answer`）并收集进 `tool_events`；返回 `{ok: True, summary, todos, messages, tool_events}`。
- 新增 `tests/test_code_agent.py`（FakeModel 离线驱动，全部用例不发起网络请求）。

# 非目标

- 不实现 notepad 工具（`NotepadAppendTool`/`NotepadReadTool`）：提示词按用户原文保留对其的提及，但本 change 不实现、不绑定；模型若调用将由未知工具分支优雅降级（notepad 工具与 layered memory 真实快照同属后续 memory 阶段）。
- 不把 `run_code_agent` 接入 LangGraph 工作流（planner/actor/verifier/final 节点与 `build_workflow` 不变），不修改 `NovGraphState` schema（不新增 `session_context` 通道）。
- 不实现 layered memory 的真实快照逻辑（仅预留 `build_memory_snapshot` 接口）。
- 不引入 todo 的文件持久化：更新后的 todos 经返回 dict 交给调用方（图接入后走状态通道）。
- 不改动既有工具、`build_tools`/`build_read_only_tools` 注册表、`create_model` 环境变量约定；不新增运行依赖。
- 不提供 CLI 入口。

# 验收示例

- A1: Scenario: 工具绑定 WHEN 以含 `runtime`（指向临时 workspace）的 state 注入 FakeModel 调用 `run_code_agent` THEN FakeModel 绑定的工具名序列恰为 `["read_file", "write_file", "edit_file", "grep", "bash", "todo_update"]`。
- A2: Scenario: 消息构造 WHEN 调用 `run_code_agent`（state 含 task 与 session_context）THEN 发给模型的首条消息为 SystemMessage 且内容即 `CODE_AGENT_PROMPT` AND 第二条 HumanMessage 同时包含 task、instruction、session_context 文本与 memory 快照段 AND 快照与 session 缺失时包含占位标注。
- A3: Scenario: ReAct 循环与返回结构 WHEN 注入 FakeModel（write_file 写文件 → `todo_update` 置 in_progress → `todo_update` 置 completed → 纯文本结束）与收集型 writer THEN 返回 `ok is True` AND `summary` 为最后 AI 文本 AND `todos` 中对应 todo 状态经 pending→in_progress→completed AND workspace 出现写入文件 AND `messages` 类型序列以 AIMessage 开始、含 ToolMessage（内容为合法 JSON）、以 AIMessage 结束 AND `tool_events` 类型序列为 `ai_message`、`tool_call`、`tool_result`（每工具一对）、`ai_message`、`final_answer` AND writer 收到同一批事件。
- A4: Scenario: todo 状态迁移边界 WHEN FakeModel 调用 `todo_update` 将某 todo 置 `blocked`（含 note）THEN 返回 `todos` 对应项 status 为 `blocked` 且 note 已更新 AND WHEN 调用未知 `todo_id` THEN `todos` 保持不变且不报错。
- A5: Scenario: 循环边界 WHEN FakeModel 第一轮即纯文本 THEN 模型只被调用 1 次（提前结束）AND WHEN FakeModel 每轮都返回 tool_call 且 `max_loops=2` THEN 模型恰被调用 2 次后返回。
- A6: Scenario: runtime 缺失 WHEN 以不含 `runtime` 的 state 调用 `run_code_agent` THEN 抛出 `ValueError`。
- A7: Scenario: 未知工具降级 WHEN FakeModel 调用未绑定的 `notepad_append` THEN 该调用结果文本以 `Error: unknown tool` 开头并作为 ToolMessage 回传 AND 循环继续不中断。
- A8: Scenario: 提示词常量 WHEN 导入 `novagent.agents.code_agent` THEN `CODE_AGENT_PROMPT` 以 "You are codeAgent, a focused implementation specialist." 开头 AND 含 "TodoUpdateTool"、"NotepadAppendTool"、"BashTool" AND 以 "End with a concise summary of files changed and checks run." 结尾。
- A9: Scenario: memory 接口预留 WHEN 调用 `build_memory_snapshot(state)` THEN 返回空字符串 AND 全程不发起模型调用或网络请求。
- A10: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且无新依赖、lock 一致 AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0。

# 约束与不变量

- `CODE_AGENT_PROMPT` 逐字使用用户给定英文原文，不改写、不翻译（包括对 notepad 工具的提及）。
- `run_code_agent` 对用户给定签名 `run_code_agent(state, instruction, *, writer=None, max_loops=10)` 完全兼容；`model` 为追加的 keyword-only 可选参数（None 时内部 `create_model()`）。
- 绑定工具集恰为 `build_tools(runtime)`（5 个）+ `todo_update`（1 个），共 6 个；不注册 notepad 工具、不注册 WebSearchTool。
- 事件类型与 `actor_node` 现有约定一致：`ai_message`/`tool_call`/`tool_result`/`final_answer`；未知工具与工具异常以 `Error: ...` 文本回传，不中断循环。
- 返回 dict 契约固定为 `{ok: True, summary, todos, messages, tool_events}`；配置错误（如缺 `OPENAI_API_KEY`）由 `create_model` 抛异常，不经 `ok` 表达。
- `build_memory_snapshot` 为纯接口：本 change 恒返回空字符串，无副作用。
- 全部测试离线运行（FakeModel + 临时 workspace），不发起真实网络请求，兼容 Python >= 3.10。

# 决策

- D1 `state` 为图状态样 dict、经 `state["runtime"]` 取 `RuntimeState`：用户伪代码写 `build_tools(state)`，但任务/todos/session 上下文只能来自 dict 状态，且 `actor_node` 已确立 "state 为 dict、runtime 取键" 的既有模式；RuntimeState 仅含 workspace 无法承载 HumanMessage 所需的任务与 todos。缺失 `runtime` 抛 `ValueError` 与 `actor_node` 一致。
- D2 `run_code_agent` 追加 keyword-only `model=None`：沿用项目既有先例（`planner_node`/`actor_node`、search-agent change D1），None 时内部 `create_model()`，用户给定调用方式完全不变，测试可离线注入 FakeModel。
- D3 事件类型沿用 `actor_node` 约定（`ai_message`/`tool_call`/`tool_result`/`final_answer`）：本 Agent 是 workspace 执行型 Agent，与 actor 的事件语义最接近；用户本轮未指定事件类型，沿库内先例而非 search-agent 的两事件方案。
- D4 todos 的"持久化"= 更新后的列表经返回 dict 交给调用方：与 `actor_node` 经状态通道持久化的语义一致；本模块独立使用时不引入文件持久化（待图接入后由状态通道承载）。
- D5 notepad 工具不在本 change 实现或绑定：用户实现步骤明确绑定集为 `build_tools + [TodoUpdateTool]`，notepad 与 layered memory 同属后续 memory 阶段；提示词按原文保留提及，未知工具分支保证模型幻觉调用时优雅降级。
- D6 session 上下文键名取 `state.get("session_context", "")`：`NovGraphState` 无此字段，本 change 不改 schema；键名选择为库内新约定，缺失时以占位标注进入 HumanMessage。
- D7 `CODE_AGENT_PROMPT` 与 `build_memory_snapshot` 定义在 `code_agent.py`：常量与接口职责专属该 Agent（与 search-agent change D3 同理）；`prompts/stage2.py` 保持 stage2 工作流专用。
- D8 无新增依赖：实现仅需既有 `langchain-core`/项目内模块；notepad/layered memory 依赖留待后续 change 评估。

# 待解决问题

（无未解决项）

# 验证预期

- `uv sync` 成功且无新依赖、`uv.lock` 一致。
- `uv run pytest` 全部通过（含新增 `tests/test_code_agent.py`，离线）。
- `uv run novagent --help` 退出码 0（现有行为不受影响）。
