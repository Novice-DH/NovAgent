# 目标

把已归档的三层 Memory 系统（`novagent.graph.memory`）接入 stage3 运行时的每个节点输入，让 planner、codeAgent、verifier 的 HumanMessage 都携带完整的分层记忆（rules / working_memory / history_summary_store）：

- `planner_node`：入口 `memory = build_layered_memory(state, node="planner")`，经事件通道发出 `memory_event(memory, node="planner")`，HumanMessage 由 `_planner_input(state, memory)` 构造——既有首轮/修订指令文本之后拼接 `format_layered_memory_for_prompt(memory)` 的 JSON；
- `run_code_agent`（codeAgent）：入口 `memory = build_layered_memory(state, node="codeAgent")`，发出 `memory_event(memory, node="codeAgent")`，HumanMessage 由 `_code_agent_input(state, instruction, memory)` 构造——Task/Instruction/Session context 之后以分层记忆 JSON 取代原 `(no memory snapshot)` 占位段；
- `verifier_node`：入口 `memory = build_layered_memory(state, node="verifier")`，HumanMessage 由 `_verifier_input(state, memory)` 构造（既有验收文本之后拼接分层记忆 JSON）；verifier 无事件出口，不发 memory 事件。

# 范围

- 修改 `src/novagent/graph/memory.py`：新增 `memory_event(memory, *, node="graph") -> dict`，返回恰为 `{"type": "memory", "node": node, "memory": memory}`；既有纯组装语义不变。
- 修改 `src/novagent/graph/nodes.py`：
  - 从 `novagent.graph.memory` 导入 `build_layered_memory` / `format_layered_memory_for_prompt` / `memory_event`；
  - 新增模块内辅助 `_planner_input(state, memory)`（收拢既有首轮/修订文本分支并拼接记忆 JSON）与 `_verifier_input(state, memory)`（既有验收文本拼接记忆 JSON）；
  - `planner_node`：入口构造 memory、发出 memory 事件（先于本节点所有其他事件）、HumanMessage 改用 `_planner_input`；
  - `verifier_node`：入口构造 memory、HumanMessage 改用 `_verifier_input`；签名与事件行为不变。
- 修改 `src/novagent/agents/code_agent.py`：
  - 移除预留接口 `build_memory_snapshot`（其 docstring 明确由本阶段真实化）；新增模块内辅助 `_code_agent_input(state, instruction, memory)`；
  - `run_code_agent`：入口构造 memory、经 `emit` 发出 memory 事件（同时进入 `tool_events` 首位与 `writer`）、HumanMessage 改用 `_code_agent_input`；不再出现 `(no memory snapshot)` 占位。
- 更新测试（全部离线，FakeModel + 临时 workspace）：`tests/test_memory.py`（memory_event 形状）、`tests/test_graph_nodes.py`（planner/verifier 消息含记忆 JSON、planner 首条事件为 memory）、`tests/test_code_agent.py`（消息含记忆 JSON、memory 事件、`build_memory_snapshot` 移除）、`tests/test_agent_loop.py`（整图事件顺序纳入 memory 事件）、`tests/test_cli.py`（memory 事件不渲染）。

# 非目标

- 不实现上下文压缩执行逻辑（token 计数、`context_should_compress` 判定、压缩摘要生成、`HISTORY_SUMMARY.md` 写入、`context_next_node` 路由）——仍为 schema 预留。
- 不把 memory 写入图状态：`memory_snapshot`/`history_summary` 等状态字段保持无写入方（memory 只进 prompt 与事件流，不落 state）。
- 不给 `verifier_node` 增加事件出口，不修改 `workflow.py`（图组装、custom 流桥接与顶层 `node="planner"` 标签约定不变）。
- 不修改 CLI 渲染：`memory` 事件与既有 planner 内部事件一致，当前不渲染。
- 不给 `run_search_agent` 注入 memory（用户范围仅 planner / codeAgent / verifier 三个节点）。
- 不新增 memory 写工具，不新增运行依赖，不改提示词常量原文。

# 验收示例

- A1: Scenario: memory_event 形状 WHEN 调用 `memory_event(memory, node="planner")` THEN 返回 dict 恰为 `{"type": "memory", "node": "planner", "memory": <传入的同一 memory>}` AND 缺省 node 时为 `"graph"`。
- A2: Scenario: planner 注入 WHEN 以 FakeModel 分别驱动 `planner_node` 的首轮（无 todos）与修订（todos + `last_error`）输入 THEN 捕获的首条 HumanMessage 分别以首轮指令文本（`Task: ...`）与修订文本（含 `Last error:` 与失败验证）开头 AND 消息包含 `format_layered_memory_for_prompt(memory)` 的完整 JSON，`json.loads` 后 `working_memory.node == "planner"` 且 `working_memory.task` 与 state 一致。
- A3: Scenario: planner memory 事件 WHEN 以 FakeModel 驱动 `planner_node` 并收集 `on_event` 事件 THEN 第一条事件为 `{"type": "memory", "node": "planner", "memory": <三层结构>}` 且先于任何 `ai_message`。
- A4: Scenario: codeAgent 注入 WHEN 以 FakeModel 驱动 `run_code_agent` THEN 捕获的首条 HumanMessage 含 Task/Instruction/Session context 段 AND 含分层记忆 JSON（解析后 `working_memory.node == "codeAgent"`）AND 不包含 `(no memory snapshot)`。
- A5: Scenario: codeAgent memory 事件 WHEN 以 FakeModel 驱动 `run_code_agent` 并以列表收集 `writer` THEN 第一条事件为 memory 事件（解析后 `working_memory.node == "codeAgent"`）AND 同一事件位于返回 `tool_events` 首位。
- A6: Scenario: verifier 注入 WHEN 以 FakeModel 驱动 `verifier_node` THEN 捕获的首条 HumanMessage 含既有验收文本（Task / Plan summary / Acceptance criteria / Verification commands）AND 含分层记忆 JSON（解析后 `working_memory.node == "verifier"`）AND `verifier_node` 签名不变（无事件参数）。
- A7: Scenario: 预留接口移除 WHEN 检查 `novagent.agents.code_agent` 模块 THEN 不存在 `build_memory_snapshot` 属性。
- A8: Scenario: searchAgent 保持 WHEN 以 FakeModel 驱动 `run_search_agent` THEN 其首条 HumanMessage 不包含分层记忆 JSON（行为与现状一致）。
- A9: Scenario: 既有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且无新增依赖、`uv.lock` 不变 AND `uv run pytest` 全部通过（离线）。

# 约束与不变量

- 注入为纯读取：`build_layered_memory` 容错组装、不修改传入 state、不调用模型、无网络、不写文件；状态残缺或 workspace 缺失时节点照常运行（占位值）。
- HumanMessage 中的分层记忆为 `format_layered_memory_for_prompt(memory)` 原文（`json.dumps(..., ensure_ascii=False)`），拼接处不做二次截断（字段级上限由组装层保证）。
- 事件流向后兼容：`memory` 为新增事件类型，出现在各节点首轮 `ai_message` 之前；既有事件类型的语义与相对顺序不变。经 workflow 桥接的事件顶层 `node` 标签沿用既有约定（planner 子树统一 `"planner"`），Agent 身份由 `memory.working_memory.node` 区分。
- 全部测试离线运行（FakeModel + 临时 workspace），不发起网络请求，兼容 Python >= 3.10。

# 决策

- D1 `memory_event` 定义在 `memory.py`：事件构造属于分层记忆的运行时语义，与 `format_layered_memory_for_prompt` 同层；形状 `{"type": "memory", "node", "memory"}` 与统一事件流约定（普通 dict、含 `type`）一致。
- D2 planner 与 codeAgent 发 memory 事件，verifier 不发：用户伪代码仅对 planner/codeAgent 给出 writer 调用；`verifier_node` 当前无事件出口（`workflow.py` 以 partial 注册、无 stream writer），为其新增出口超出本次范围。
- D3 codeAgent 的 memory 事件经 `emit()`：与该 Agent 其余事件一致地同时进入 `tool_events` 与 `writer`，保持「全部事件收集进 tool_events」的既有约定。
- D4 `build_memory_snapshot` 移除而非保留：其 docstring 明确为「后续 memory 阶段真实化」的预留接口，本次即该阶段；保留恒空函数会与 `_code_agent_input` 双轨混淆。
- D5 记忆 JSON 以 `Layered memory:` 标头行拼接在 HumanMessage 末尾；验收以「包含 `format_layered_memory_for_prompt(memory)` 原文且可解析」判定，不依赖标头措辞。
- D6 `_planner_input(state, memory)` 收拢首轮/修订文本分支（与用户伪代码签名一致），planner 循环体只负责 ReAct；`_verifier_input`、`_code_agent_input` 分别定义在 `nodes.py` 与 `code_agent.py`。
- D7 planner 的 memory 基于节点入口 state 组装；codeAgent 的 memory 在 `run_code_agent` 内基于传入 state 组装——委托路径上 planner 已把本节点内更新并入委托 state（`_delegation_state`），codeAgent 与 verifier 因此看到最新合并视图（既有行为）。

# 待解决问题

（无）

# 验证预期

- `uv run pytest`（全量）离线通过，重点关注 `tests/test_memory.py`、`tests/test_graph_nodes.py`、`tests/test_code_agent.py`、`tests/test_agent_loop.py`；
- `uv sync` 成功且 `uv.lock` 无变化；
- 手工冒烟（可选，需 API key）：`novagent` CLI 正常跑通 stage3 循环，事件流含 memory 事件但 CLI 不渲染。
