# 目标

在 `src/novagent/graph/nodes.py` 中实现 LangGraph 工作流的三个核心节点与路由函数：`planner_node`（用 `TodoWriteTool` 结构化输出生成或按失败修订计划）、`actor_node`（用 `build_tools(state)` + `TodoUpdateTool` 跑 ReAct 循环并逐事件产出）、`verifier_node`（用只读工具判定验收并同时运行 `verification_commands` 收集 `VerificationResult`）、`verifier_route`（passed 或 attempts 耗尽 → `"final"`，否则 → `"planner"`）。为此新增配套的 todo 工具、只读工具集，并扩展 `NovGraphState` 缺失的字段（`last_actor_summary`、`last_error`、`verification_checks`）。

# 范围

- 扩展 `src/novagent/graph/state.py`：
  - 新增 `VerificationCheck(TypedDict)`：`name: str`、`passed: bool`、`detail: str`；
  - `NovGraphState` 新增字段：`last_actor_summary: str`、`last_error: str`、`verification_checks: list[VerificationCheck]`（保持 `total=False`）。
- 新增 `src/novagent/tools/todo_tools.py`：
  - `create_todo_write_tool()` → `StructuredTool` 名 `todo_write`，args schema 含 `plan_summary: str`、`todos`（`{id, content, status, note}` 对象数组）、`acceptance_criteria: list[str]`、`verification_commands: list[str]`；invoke 返回确认文本（结构化输出载体，不产生副作用）。
  - `create_todo_update_tool()` → `StructuredTool` 名 `todo_update`，args schema 含 `todo_id: str`、`status: str`、`note: str = ""`；invoke 返回确认文本。
- `src/novagent/tools/registry.py` 新增 `build_read_only_tools(state) -> list[StructuredTool]`：仅含 `read_file`、`grep`（无写副作用、无命令执行）。
- `src/novagent/tools/bash_tool.py` 行为不变重构：提取模块级 `execute_command(command, cwd, timeout_seconds) -> tuple[int | None, str, str]`（exit_code/stdout/stderr；超时/异常时 exit_code 为 None），`bash` 工具内部改用它，外部行为（返回文本、超时杀进程树、报错）完全不变。
- 新增 `src/novagent/graph/nodes.py`：
  - 模块常量 `PLANNER_PROMPT`、`VERIFIER_PROMPT`（英文系统提示，说明各自的职责与输出约定）；
  - `planner_node(state, *, model=None) -> dict`：`model=None` 时 `create_model()`；`agent = model.bind_tools([todo_write])`。状态无 todos → 首次生成：消息为 `[SystemMessage(PLANNER_PROMPT), HumanMessage(task)]`；已有 todos 且 `last_error` 非空 → 修订：HumanMessage 额外携带 last_error 与最近验证失败信息。从 `todo_write` tool_call 的 args 提取 `plan_summary`、`todos`（补齐缺失键，非法 status 归一为 `"pending"`）、`acceptance_criteria`、`verification_commands`，作为节点更新返回；未发生 tool_call 或提取失败 → 抛出带说明的 `ValueError`。
  - `actor_node(state, *, model=None, on_event=None) -> dict`：`agent = model.bind_tools(build_tools(runtime) + [todo_update])`（共 6 个工具）；消息为 `[SystemMessage(ACTOR_PROMPT), HumanMessage(计划 + 任务)]`；ReAct 循环 `max_loops=10`，语义与 `core.agent.stream_agent_events` 一致（事件类型 `ai_message`/`tool_call`/`tool_result`/`final_answer`，错误转 `Error: ...` 文本、`ToolMessage` 用 `json.dumps`）；每个事件发生时调用 `on_event(event)`（on_event 为 None 时仅跳过发送）；循环中 `todo_update` tool_call 收集合并进 todos（按 id 匹配更新 status/note）；返回更新：`messages`（仅循环新增的 AI/ToolMessage，不含 System/Human）、`last_actor_summary`（最后一轮 AI 文本）、`todos`（若有 todo_update 调用）。
  - `verifier_node(state, *, model=None) -> dict`：从 `state["runtime"].workspace` 取工作区（缺失抛 `ValueError`）；`agent = model.bind_tools(build_read_only_tools(runtime))`；消息为 `[SystemMessage(VERIFIER_PROMPT), HumanMessage(计划 + 验收标准 + 验证命令 + 最近 actor 输出)]`，只读 ReAct 循环（同语义、max_loops=10，事件同样经 on_event？不——verifier 无 on_event 参数，事件丢弃）；最终 AI 文本解析 JSON `{passed, reason, checks, recommended_next_instruction}`；同时用 `execute_command` 逐条运行 `verification_commands`（默认 30s 超时）收集 `VerificationResult`（`ok = exit_code == 0`；超时/异常 `exit_code=None, ok=False`，stderr 记错误）；任何 LLM 判定失败、命令失败或 JSON 解析失败 → 整体 `passed=False`；返回更新：`passed`、`attempts`（原值 +1）、`verification_results`、`verification_checks`（来自 LLM checks，补齐缺失键）、`last_error`（失败时为 reason/诊断，通过时置空 `""`）、`todos`（passed → 全部非 completed 标 `completed`；失败 → 全部 in_progress 标 `blocked`）、`final_answer`（passed 时为 reason，否则不写）。
  - `verifier_route(state) -> str`：`state.get("passed")` 为真 → `"final"`；`attempts >= state.get("max_attempts", 3)` → `"final"`；否则 → `"planner"`。
- 新增 `tests/test_graph_nodes.py` 与必要的 todo 工具测试：全部离线（FakeModel 注入），覆盖下列验收场景。

# 非目标

- 不组装 StateGraph（不写节点注册、条件边、入口/出口、图的 compile）——仅提供节点函数与路由函数；图组装留给后续 change。
- 不修改 `core/agent.py` 的 `stream_agent_events` 对外行为与 CLI 行为。
- 不改变五个现有工具（read_file/write_file/edit_file/grep/bash）的行为与 `build_tools` 返回（`bash_tool.py` 仅做行为不变重构）。
- 不改变 `create_model` 的环境变量约定与错误信息。
- 不实现 checkpointing、中断恢复、人机协同等图执行能力。

# 验收示例

- A1: Scenario: planner_node 首次生成计划 WHEN 构造无 todos 的 `NovGraphState`（task 为 "demo task"，runtime 指向临时 workspace），注入 FakeModel（返回调用 `todo_write` 的 tool_call，args 含 plan_summary="plan"、todos 一条 `{id: "t1", content: "step"}`、acceptance_criteria 一条、verification_commands 一条）调用 `planner_node(state, model=fake)` THEN 返回更新的 `plan_summary == "plan"`、`todos` 为一条 TodoItem（id "t1"、status 归一为 "pending"、note 为 ""）、`acceptance_criteria` 与 `verification_commands` 与 args 一致 AND FakeModel 绑定的工具恰为 1 个且名为 `todo_write` AND 首轮消息依次为 SystemMessage（内容为 `PLANNER_PROMPT`）与 HumanMessage（内容含 task 文本）AND 返回更新不含 `passed`/`attempts` 键。
- A2: Scenario: planner_node 按失败修订 WHEN 状态已有 todos 且 `last_error == "boom"`（`verification_results` 含一条 ok=False）调用 `planner_node` THEN 发给模型的 HumanMessage 内容包含 "boom" AND 返回更新为修订后的计划（与本次 tool_call args 一致）AND 首轮仍为 SystemMessage(PLANNER_PROMPT)。
- A3: Scenario: actor_node 运行 ReAct 循环并逐事件产出 WHEN 状态 runtime 指向临时 workspace、注入 FakeModel（第一轮返回 `write_file` 写 `note.txt` 内容 "hi" 的 tool_call，第二轮返回纯文本 "All done."）、以列表收集事件调用 `actor_node(state, model=fake, on_event=events.append)` THEN 事件 `type` 依次为 `ai_message`、`tool_call`、`tool_result`、`ai_message`、`final_answer` AND 返回更新 `messages` 依次为 AIMessage、ToolMessage（tool_call_id 一致、content 为 json.dumps 结果）、AIMessage（content "All done."）AND `last_actor_summary == "All done."` AND workspace 出现 `note.txt` 内容 "hi" AND FakeModel 绑定工具名为 `read_file`、`write_file`、`edit_file`、`grep`、`bash`、`todo_update` 共 6 个。
- A4: Scenario: actor_node 收集 todo_update WHEN FakeModel 第一轮返回 `todo_update`（args `{todo_id: "t1", status: "completed", note: "done"}`）、第二轮纯文本结束，状态 todos 含 id "t1" 的条目 THEN 返回更新 `todos` 中 t1 的 `status == "completed"` 且 `note == "done"`。
- A5: Scenario: verifier_node 判定通过 WHEN 状态含 `verification_commands == ["<python> -c \"print('ok')\""]`（<python> 为 `sys.executable`）、todos 两条未完成，FakeModel 只读 agent 第二轮输出合法 JSON `{"passed": true, "reason": "all good", "checks": [{"name": "smoke", "passed": true, "detail": "ok"}], "recommended_next_instruction": "ship it"}` 调用 `verifier_node(state, model=fake)` THEN 返回更新 `passed is True`、`attempts` 为原值 +1、`verification_results` 恰一条且 `ok is True`、`exit_code == 0`、`stdout` 含 "ok"、`stderr == ""`、`verification_checks` 与 LLM checks 一致、`last_error == ""`、`final_answer == "all good"`、todos 全部 `completed` AND FakeModel 绑定工具恰为 `read_file`、`grep` 2 个。
- A6: Scenario: verifier_node 判定失败并记录错误 WHEN `verification_commands` 含一条必然非零退出的命令，FakeModel 输出 `{"passed": false, "reason": "tests broke", "checks": [{"name": "c1", "passed": false, "detail": "d"}], "recommended_next_instruction": "fix"}` THEN 返回更新 `passed is False`、`attempts` +1、`last_error` 含 "tests broke"、失败命令的 `VerificationResult.ok is False` 且 `exit_code != 0`、todos 中 `in_progress` 条目标为 `blocked` AND 后接调用 `verifier_route(合并后状态)` 返回 `"planner"`。
- A7: Scenario: verifier_route 三分支 WHEN 状态 `{"passed": True, ...}` 返回 `"final"` AND `{"passed": False, "attempts": 3, "max_attempts": 3}` 返回 `"final"` AND `{"passed": False, "attempts": 1, "max_attempts": 3}` 返回 `"planner"` AND 缺省 `max_attempts` 时按默认 3 判断（`attempts=2` → `"planner"`，`attempts=3` → `"final"`）。

# 约束与不变量

- 节点签名与 LangGraph 节点兼容：第一个位置参数为状态 dict，返回普通 dict 更新（不是生成器）；`model=None` 时内部 `create_model()`，支持离线注入。
- actor/verifier 的事件类型与错误语义延续 `core.agent.stream_agent_events`：`ai_message`/`tool_call`/`tool_result`/`final_answer`；未知工具与异常转 `Error: ...` 文本；`ToolMessage.content` 用 `json.dumps`。
- `verification_commands` 的执行复用 `bash_tool.py` 提取的 `execute_command`（与 bash 工具同语义：workspace 为 cwd、超时杀整棵进程树）。
- `NovGraphState` 保持 `total=False`；新字段全部可选；`runtime` 缺失时 actor/verifier 抛出说明性 `ValueError`。
- 全部测试离线（FakeModel / `sys.executable` 本地命令），不发真实网络请求；兼容 Python >= 3.10。

# 决策

- D1 state 扩展而非节点内私有容器：`last_actor_summary`、`last_error`、`verification_checks` 是节点间传递的用户可见状态，属于共享图状态，写入 `NovGraphState`；`checks` 结构新增 `VerificationCheck` TypedDict，与用户给定的 `{name, passed, detail}` 对应。
- D2 actor 事件用 `on_event` 回调而非生成器：LangGraph 节点必须返回 dict 更新，不能 yield；回调保持"每一步即时可见"的语义且不破坏节点签名；事件 schema 与 `stream_agent_events` 完全一致，消费方零适配。
- D3 `TodoUpdateTool` 的更新回写 state.todos：工具仅回确认文本给模型，节点收集 tool_call 并按 id 合并进返回更新（用户给定 actor 返回值在此基础上补充 `todos`，否则该工具形同虚设）。
- D4 verifier 的 todos 状态更新为程序性规则：passed → 非 completed 全标 `completed`；失败 → in_progress 标 `blocked`。用户给定的 verifier JSON 不含 todo 更新，规则保持确定性、可离线测试。
- D5 `execute_command` 从 `bash_tool.py` 提取：verifier 需要结构化 exit_code/stdout/stderr，而 bash 工具只返回文本；提取公共函数供两者复用，bash 对外行为不变（含 Windows 进程树终止）。
- D6 verifier 判定从最终 AI 文本解析 JSON：只读 agent 只 bind 只读工具（用户给定），无结构化输出工具；解析失败按失败处理并写入 `last_error`，保证循环可继续（planner 可修订）。
- D7 todo 工具放 `tools/todo_tools.py` 并延续闭包工厂模式：与现有 `create_*_tool(state)` 风格一致；`todo_write` 无副作用（纯结构化输出载体）故不依赖 state。
- D8 verifier 的 ReAct 循环不上报事件：用户仅要求 actor 逐步 yield 事件；verifier 内部循环不接 on_event，保持签名最小。

# 待解决问题

（无未解决项）

# 验证预期

- `uv sync` 成功且 `uv.lock` 一致（无新依赖）。
- `uv run pytest` 全部通过（含新增 `tests/test_graph_nodes.py`，离线）。
- `uv run novagent --help` 退出码 0（现有行为不受影响）。
