# 目标

把 `src/novagent/graph/nodes.py` 的 `planner_node` 升级为 stage3 supervisor：绑定三个工具（`todo_write` 发布/修订计划、`call_search_agent` 委托搜索、`call_code_agent` 委托实现），以手写 ReAct 循环协调专家 Agent；委托工具内部调用 `run_search_agent`/`run_code_agent`，先发 `handoff` 事件并把产物写回图状态（`research_notes`/`sources`/`agent_handoffs`/`code_agent_summary`/`todos`/`messages`）。新增 `prompts/stage3.py` 的 supervisor 版 `PLANNER_PROMPT`（逐字用户原文）与 `graph/state.py` 的 `AgentHandoff`/`SourceItem` 类型及四个新状态字段；从图中移除 actor 节点，拓扑变为 START → planner → verifier →（条件路由）final/planner → END。

# 范围

- `src/novagent/prompts/stage3.py`（新增）：`PLANNER_PROMPT` 常量，逐字使用用户给定英文原文（"You are the planner/supervisor node in novagent stage 3." 开头；三工具说明；Always call TodoWriteTool before delegating new work 等四条 Rules；"End with a concise supervisor summary after the needed specialist calls." 结尾）；`VERIFIER_PROMPT` 常量，逐字使用用户给定英文原文（"You are verifier, a model-based reviewer node." 开头；能力描述含读文件/grep/安全 shell 检查/搜索网络；NotepadReadTool 规则；JSON 输出约定，"an empty string when passed" 结尾）。
- `src/novagent/prompts/stage2.py`：移除被取代的 `PLANNER_PROMPT`、`ACTOR_PROMPT` 与 `VERIFIER_PROMPT`；仅保留 `FINAL_PROMPT`。
- `src/novagent/graph/state.py`：新增 `SourceItem(TypedDict, total=False)`（url/title/content/score）与 `AgentHandoff(TypedDict, total=False)`（from_agent/to_agent/instruction/result）；`NovGraphState` 新增 `research_notes: str`、`sources: list[SourceItem]`、`agent_handoffs: list[AgentHandoff]`、`code_agent_summary: str`。
- `src/novagent/graph/nodes.py`：
  - `planner_node(state, *, model=None, on_event=None, max_loops=10) -> dict` 重写：`bind_tools([todo_write, call_search_agent, call_code_agent])`（恰 3 个）；委托工具为闭包 `StructuredTool`（内部 `_call_search_agent_tool(state, writer, instruction)` / `_call_code_agent_tool(state, writer, instruction)`）；保留首次生成/`last_error` 修订两种 HumanMessage 构造；手写 ReAct 循环（默认 `max_loops=10`，每轮先发 `ai_message`，无 tool_calls 提前结束，逐工具发 `tool_call`/`tool_result`，`ToolMessage(json.dumps(result))` 回传）；委托调用透传注入的 `model` 并使用合并视图（state 叠加本节点内已产生的 `todos`/`research_notes`），保证多次委托链式一致与离线可注入；
  - `call_search_agent`：先发 `{"type": "handoff", "from": "planner", "to": "searchAgent", "instruction"}`，调用 `run_search_agent(state, instruction, writer=writer)`；更新 `research_notes`（追加，空行连接）、`sources`（按 url 去重保序合并 `SourceItem`，明细取自 ok 的 `search_results` 事件）、`agent_handoffs`（追加记录，result 为 agent summary）；
  - `call_code_agent`：先发 `handoff`（to `codeAgent`），调用 `run_code_agent(state, instruction, writer=writer)`；更新 `todos`（取委托返回）、`code_agent_summary`、`agent_handoffs`、`messages`（并入委托新增消息）；
  - 删除 `actor_node`、`_apply_todo_update`、`_render_todos` 及 `ACTOR_PROMPT` 导入；`PLANNER_PROMPT` 与 `VERIFIER_PROMPT` 改从 `stage3` 导入；`verifier_node` 仅改提示词来源与绑定工具集，`final_node`/`verifier_route` 语义不变。
- `src/novagent/graph/nodes.py` 的 `verifier_node` 工具集扩展：`build_read_only_tools(runtime) + [create_bash_tool(runtime), WebSearchTool]`（恰 4 个：read_file/grep/bash/web_search），与新版 VERIFIER_PROMPT 的能力描述一致；验证命令的程序化执行（`execute_command`）保持不变；`web_search` 缺 `TAVILY_API_KEY` 时走既有错误降级。
- `src/novagent/graph/workflow.py`：不注册 `"actor"`；planner 经图内包装桥接 `get_stream_writer()` 为 `on_event`（每个事件复制并补 `"node": "planner"`）；边改为 `START → planner → verifier`，verifier 条件路由与 `final → END` 不变。
- 测试重写/新增：`tests/test_graph_nodes.py`（planner 三工具、委托语义与状态更新、循环边界、actor 移除）、`tests/test_graph_workflow.py`（三节点拓扑与桥接事件标签）、`tests/test_graph_state.py`（新类型与新字段）、`tests/test_agent_loop.py`（stage3 协调端到端）；`tests/test_cli.py` 保持不变（CLI 行为本 change 未改）。

# 非目标

- 不改 `final_node`/`verifier_route` 语义与 CLI 渲染（`node="planner"` 的内部事件当前不渲染，渲染分支留给后续 change）；`verifier_node` 仅改提示词来源与绑定工具集，其判定与更新逻辑（JSON 解析、验证命令程序化执行、attempts/todos/last_error 更新）不变；`last_actor_summary` 不再由图内节点产生，verifier 的「最近执行输出」通常为空，本 change 不补接。
- 不改 `run_search_agent`/`run_code_agent`/`WebSearchTool` 与工具注册表；委托是 planner 侧的编排能力。
- 不实现 notepad 工具与 layered memory 真实快照（`run_code_agent` 内部接口保持现状）。
- 不新增运行依赖；不提供新的 CLI 入口/选项。

# 验收示例

- A1: Scenario: stage3 提示词与导入 WHEN 导入 `novagent.prompts.stage3` THEN `PLANNER_PROMPT` 以 "You are the planner/supervisor node in novagent stage 3." 开头、含 "TodoWriteTool"、"CallSearchAgentTool"、"CallCodeAgentTool"、"Always call TodoWriteTool before delegating new work." 且以 "End with a concise supervisor summary after the needed specialist calls." 结尾 AND `novagent.graph.nodes.PLANNER_PROMPT` 与 stage3 常量为同一对象 AND `novagent.prompts.stage2` 不再有 `PLANNER_PROMPT`/`ACTOR_PROMPT`/`VERIFIER_PROMPT` 属性、仍有 `FINAL_PROMPT`。
- A12: Scenario: verifier 提示词与工具集 WHEN 导入 `novagent.prompts.stage3` THEN `VERIFIER_PROMPT` 以 "You are verifier, a model-based reviewer node." 开头、含 "NotepadReadTool"、"search the web"、"Run the provided verification commands when they are relevant." 且以 "an empty string when passed" 结尾 AND `novagent.graph.nodes.VERIFIER_PROMPT` 与 stage3 常量为同一对象 AND `verifier_node` 绑定工具名序列恰为 `["read_file", "grep", "bash", "web_search"]`。
- A2: Scenario: planner 工具绑定 WHEN 注入 FakeModel 调用 `planner_node` THEN FakeModel 绑定的工具名序列恰为 `["todo_write", "call_search_agent", "call_code_agent"]`。
- A3: Scenario: 委托搜索 WHEN FakeModel 依次返回 `todo_write` 计划、`call_search_agent`（注入 fake TavilyClient 返回带 title/url 的结果）、纯文本结束 THEN 返回更新含计划四字段、`research_notes`（agent summary）、`sources`（`SourceItem` 列表，url/title/content/score 且按 url 去重保序）、`agent_handoffs` 恰含一条 `{"from_agent": "planner", "to_agent": "searchAgent", "instruction", "result"}` AND 事件序列中 `handoff` 事件先于受托 agent 的内部事件 AND 全程事件带 `node="planner"`（经 writer 收集断言）。
- A4: Scenario: 委托实现 WHEN FakeModel 依次返回 `todo_write`、`call_code_agent`（state 含 runtime 指向临时 workspace 与 todos）、纯文本 THEN 受托循环真实写文件并迁移 todo（in_progress→completed）AND 返回更新 `todos` 为委托后状态、`code_agent_summary` 为 agent summary、`agent_handoffs` 含 to `codeAgent` 记录、`messages` 并入委托新增 AIMessage/ToolMessage。
- A5: Scenario: 数据结构与状态字段 WHEN 导入 `novagent.graph.state` THEN 存在 `SourceItem`（url/title/content/score）与 `AgentHandoff`（from_agent/to_agent/instruction/result）且均为 `total=False` AND `NovGraphState` 含 `research_notes`/`sources`/`agent_handoffs`/`code_agent_summary` 字段。
- A6: Scenario: 图拓扑 WHEN 调用 `build_workflow()` THEN 编译图节点集合恰为 `{"planner", "verifier", "final"}` AND `START` 出边指向 planner AND planner 出边指向 verifier AND verifier 条件边路由 `{"final", "planner"}` AND final 出边指向 END。
- A7: Scenario: 离线端到端 WHEN 初始 state（task、runtime、max_attempts=3、verification command 为 `"<python>" -c "print('ok')"`）注入 FakeModel（planner 轮 1 `todo_write`、轮 2 `call_code_agent` 写 `result.txt` 并完成 todo、轮 3 纯文本；verifier 输出 `passed=true` JSON）并 `build_workflow(model=fake).invoke(state)` THEN 最终 `passed is True`、`final_answer` 成功格式、`code_agent_summary` 与 `agent_handoffs` 已写入、workspace 出现 `result.txt`。
- A8: Scenario: 修订路径 WHEN 构造 `todos` 非空且 `last_error` 非空的 state 调用 `planner_node` THEN 发给模型的 HumanMessage 包含 `last_error` 与失败验证信息。
- A9: Scenario: actor 移除 WHEN 导入 `novagent.graph.nodes` 与 `novagent.graph.workflow` THEN 无 `actor_node` 属性、`build_workflow()` 图中无 `"actor"` 节点。
- A10: Scenario: 循环边界 WHEN FakeModel 第一轮即纯文本 THEN 模型只被调用 1 次 AND WHEN 每轮都返回 tool_call 且 `max_loops=2` THEN 恰调用 2 次。
- A11: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且无新依赖、lock 一致 AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0。
- A13: Scenario: verifier 绑定与降级 WHEN 注入 FakeModel 调用 `verifier_node`（state 含 runtime 与 verification_commands）THEN 绑定工具名序列恰为 `["read_file", "grep", "bash", "web_search"]` AND HumanMessage 含计划、验收标准与验证命令 AND 全部测试离线（web_search 在测试环境不发起真实请求）。

# 约束与不变量

- `PLANNER_PROMPT` 与 `VERIFIER_PROMPT`（stage3）逐字使用用户给定英文原文，不改写、不翻译。
- planner 绑定工具恰 3 个：`todo_write` + 两个委托工具；委托工具名 `call_search_agent`/`call_code_agent`，args schema 为 `{instruction: str}`。
- `handoff` 事件先于受托 agent 的任何内部事件发出；受托 agent 的 writer 与 planner 相同（事件透传）。
- planner 循环为手写 ReAct（与既有循环同风格）：默认 `max_loops=10`、无 tool_calls 提前结束、错误以 `Error: ...` 文本回传不中断。
- verifier 绑定工具恰 4 个（read_file/grep/bash/web_search）；bash 只读性由提示词约束（安全检查），验证命令的程序化执行与 `passed`/`attempts`/`todos`/`last_error` 更新逻辑不变。
- 图拓扑恰为 START → planner → verifier →（条件）final/planner → END，无 actor；`verifier_route` 判定逻辑不变。
- `final_node`/`verifier_route`/CLI 的代码路径本 change 零修改（CLI 渲染分支自然不匹配新事件，行为为忽略）。
- 全部测试离线运行（FakeModel / fake TavilyClient / 临时 workspace），不发起真实网络请求，兼容 Python >= 3.10。

# 决策

- D1 planner_node 升级为手写 ReAct 循环：新提示词要求「先 TodoWriteTool 再委托、按需多次委托、最后总结」，单轮调用无法表达；循环风格（max_loops=10、事件序列、json.dumps ToolMessage、错误回传）与既有 actor/搜索/代码 Agent 循环保持一致。
- D2 委托工具实现为闭包 `StructuredTool`（名 `call_search_agent`/`call_code_agent`，args `{instruction: str}`），内部函数保持用户伪代码签名 `_call_search_agent_tool(state, writer, instruction)`/`_call_code_agent_tool(state, writer, instruction)`：`bind_tools` 需要 LangChain 工具对象，闭包捕获 state 与 writer。
- D3 `research_notes` 语义为「累积的研究笔记」：每次搜索委托把 agent summary 追加（空行连接）而非覆盖，`sources` 按 url 去重保序合并；`SourceItem` 镜像 `WebSearchTool` 结果条目（url/title/content/score，total=False），明细从 ok 的 `search_results` 事件提取（`run_search_agent` 返回的 `sources` 仅含 URL 列表）。
- D4 `todos`/`code_agent_summary` 取最后一次代码委托的返回（多次委托时后者覆盖前者）；`messages` 经 `add_messages` reducer 并入委托新增消息；`agent_handoffs` 为全量追加日志。
- D5 删除 `actor_node`/`_apply_todo_update`/`_render_todos` 与 stage2 的 `PLANNER_PROMPT`/`ACTOR_PROMPT`：图不再注册 actor，保留死代码与死常量会误导后续演进；用户明确「从图中移除 actor 节点」，代码级清除是该意图的直接落实。
- D6 planner 事件经 workflow 桥接并显式标注 `node="planner"`：复用 actor 时代的 `get_stream_writer()` 桥接模式；`core.agent` 的兜底 `setdefault` 保留不改（planner 事件已带标签）。
- D7 CLI 不改：用户未要求；CLI 的事件分支只识别 `node="actor"`/`node_output`，planner 内部事件被自然忽略，统一事件流本身完整可用（CLI 渲染为后续 change）。
- D8 verifier 的「最近执行输出」（`last_actor_summary`）不补接：新增字段清单未包含它；verifier 仍依赖验收标准与验证命令判定，接线 `code_agent_summary` 留给后续 change。
- D9 修订分支保留既有构造（`last_error` + 失败验证信息注入 HumanMessage）：提示词 Rule「If the verifier failed, revise the plan and delegate only the missing fix」依赖该输入。
- D10 `VERIFIER_PROMPT` 迁移到 `prompts/stage3.py` 并逐字替换为用户新给定原文（用户明确指定位置与文本）：stage2 仅保留预留的 `FINAL_PROMPT`；verifier 输出 JSON 契约（passed/reason/checks/recommended_next_instruction）不变，`_parse_verifier_json` 解析逻辑无需改动。
- D11 verifier 工具集扩展为 4 个（用户在澄清中选择）：`build_read_only_tools` 注册表函数保持不变（仍为 read_file/grep），扩展发生在 `verifier_node` 内；bash 的写风险由提示词「must not modify files / safe shell checks」约束兜底；`NotepadReadTool` 按既有先例不实现不绑定（提示词保留提及）；web_search 复用 `WebSearchTool`（缺 key 走既有错误降级）。

# 待解决问题

（无未解决项）

# 验证预期

- `uv sync` 成功且无新依赖、`uv.lock` 一致。
- `uv run pytest` 全部通过（重写后的 graph/agent-loop 测试与既有工具测试，离线）。
- `uv run novagent --help` 退出码 0（CLI 行为不受影响）。
