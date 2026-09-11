# 目标

在 `src/novagent/graph/nodes.py` 新增 `context_compressor_node`：用 LLM 把当前消息历史压缩为结构化 JSON 摘要（保留任务目标、计划、已完成工作、重要文件、工具发现、来源、下一步与风险），用 `RemoveMessage(id=REMOVE_ALL_MESSAGES)` 清空旧消息并以一条 `AIMessage(content=summary)` 作为新的上下文起点，把结构化摘要持久化到 workspace 根的 `HISTORY_SUMMARY.md`，对返回的状态字段做 `_short_text` 截断，并追加一条 `CompressionEvent`。

同时在 `src/novagent/prompts/stage4.py` 新增常量 `CONTEXT_COMPRESSION_PROMPT`（逐字采用用户给定英文原文），要求 LLM 只返回含 `summary`、`active_goal`、`completed_work`、`open_todos`、`important_files`、`tool_findings`、`sources`、`next_steps`、`risks` 九个键的 JSON。

该节点是已归档 context-monitor change 路由目标 `"context_compressor"` 的落地：`context_monitor_route` 在 `context_should_compress` 为真时指向本节点；本 change 为 `context_summary`、`context_token_count`、`context_should_compress`、`compression_events`、`history_summary` 等 schema 字段接入压缩写入方。

# 范围

- 新增 `src/novagent/prompts/stage4.py`：模块常量 `CONTEXT_COMPRESSION_PROMPT`（非空英文字符串，逐字用户给定原文，含 "Return only JSON with these keys" 与九个键名）。
- 修改 `src/novagent/graph/nodes.py`，新增 `context_compressor_node(state, *, model=None) -> dict`：
  1. `model=None` 时内部 `create_model()`（与 planner/verifier 一致，支持离线注入 FakeModel）；
  2. 组装分层 memory 快照：`build_layered_memory(state, node="context_compressor")` + `format_layered_memory_for_prompt`；
  3. 组装消息文本：把 `state.get("messages")` 逐条格式化为 `序号. [type] content` 的 transcript；
  4. 调用 `model.invoke([SystemMessage(CONTEXT_COMPRESSION_PROMPT), HumanMessage(task + transcript + memory JSON)])`；
  5. 解析响应为 JSON（复用既有 `_parse_verifier_json`，容忍代码围栏）：取九个键（缺失补 `""`）；解析失败时走确定性回退——`summary` 取既有消息内容的截断拼接，其余字段为空，节点不抛异常；
  6. 各字段用 `_short_text` 截断：`summary` ≤ 1600（`CONTEXT_SUMMARY_LIMIT`）、其余八个字段各 ≤ 800；
  7. 返回更新 dict：
     - `"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), AIMessage(content=summary)]`；
     - `"context_summary": summary`、`"context_should_compress": False`（刚压缩过，避免监控环路立即再次触发）；
     - `"context_token_count": <压缩后估算 token 数>`（估算函数 `_estimate_text_tokens(text) = max(1, len(text)//4)`，空文本为 0，不引入 tiktoken 等新依赖；命名区别于 monitor 的 `_estimate_tokens(messages, model)`）；
     - `"research_notes"`（≤1600）、`"agent_handoffs"`（最近 6 条）、`"sources"`（仅 title/url）、`"code_agent_summary"`（≤1000）等既有上下文字段的截断版；
     - `"history_summary": _short_text(summary, 2200)`；
     - `"compression_events": [...既有事件, 新事件]`，新事件为 `CompressionEvent`：`node="context_compressor"`、`reason`、`token_count=<压缩前 transcript 估算 token 数>`、`token_limit=<state 的 context_token_limit，缺失为 0>`、`summary=<截断后摘要>`、`created_at=<UTC ISO 时间>`；
  8. 持久化：把九个截断后的字段写成 Markdown 写入 `runtime.workspace / "HISTORY_SUMMARY.md"`（UTF-8，各字段独立小节标题）；`runtime` 缺失或写入失败时跳过持久化，不影响返回值（容错，不抛异常）。
- 新增 `tests/test_context_compressor.py`（FakeModel 离线测试，不发起网络请求）。

# 非目标

- 不把 `context_compressor_node` 接入 `build_workflow`：不新增节点注册、边或路由改造；monitor 与 compressor 的图接线（含 `context_monitor_route`/压缩路由的真实调用方）属后续接线 change（沿用 context-monitor change D6 的函数层交付先例；用户伪代码仅含节点函数与提示词）。
- 不修改 `planner_node`/`verifier_node`/`final_node`/`verifier_route`/`context_monitor_node`/`context_monitor_route` 与既有图行为。
- 不修改 `code_agent.build_memory_snapshot` 预留接口（仍返回空字符串）。
- 不引入新的运行依赖（token 数为字符估算，不用 tiktoken）。
- 不实现 TODO.md / NOTEPAD.md 的写入。

# 验收示例

- A1: Scenario: 提示词常量 WHEN 导入 `novagent.prompts.stage4` THEN `CONTEXT_COMPRESSION_PROMPT` 为非空 str AND 以 "You are the context_compressor node in novagent stage 4." 开头 AND 同时含 "summary"、"active_goal"、"completed_work"、"open_todos"、"important_files"、"tool_findings"、"sources"、"next_steps"、"risks" 九个键名与 "Return only JSON with these keys"。
- A2: Scenario: 模型调用 WHEN 以含 messages 与任务状态的 state 调用 `context_compressor_node(state, model=FakeModel)` THEN 模型收到的消息恰为 `[SystemMessage, HumanMessage]` AND SystemMessage.content 为 stage4 的 `CONTEXT_COMPRESSION_PROMPT`（同一对象）AND HumanMessage.content 同时包含任务文本、全部旧消息内容与分层 memory JSON（含 `"working_memory"`）。
- A3: Scenario: 消息替换 WHEN LLM 返回合法 JSON（九键齐全）THEN 返回的 `messages` 恰含两个元素 AND 第一个是 `RemoveMessage` 且 `id == REMOVE_ALL_MESSAGES` AND 第二个是 `AIMessage` 且 `content` 为截断后的 `summary` 字段。
- A4: Scenario: 压缩状态字段 WHEN LLM 返回合法 JSON THEN `context_summary == summary`、`context_should_compress is False` AND `context_token_count` 为正整数且等于对压缩后 summary 的估算 token 数。
- A5: Scenario: 持久化 WHEN 压缩完成 THEN workspace 根下存在 `HISTORY_SUMMARY.md` AND 文件内容含九个字段各自的小节与截断后文本（summary、active_goal、completed_work、open_todos、important_files、tool_findings、sources、next_steps、risks）。
- A6: Scenario: 字段截断 WHEN `research_notes` 超过 1600 字符、`agent_handoffs` 超过 6 条、`summary` 超过 1600 字符 THEN 返回的 `research_notes` 长度 ≤ 1600 且以 "..." 结尾 AND `agent_handoffs` 恰保留最近 6 条 AND `context_summary` 长度 ≤ 1600。
- A7: Scenario: 压缩事件 WHEN state 已有 `compression_events` 且发生压缩 THEN 返回的 `compression_events` 为既有事件追加一条新事件 AND 新事件 `node == "context_compressor"`、`token_count` 等于压缩前 transcript 的估算 token 数、`token_limit` 等于 state 的 `context_token_limit`、`summary` 非空、`created_at` 非空 AND `history_summary` 等于截断后的 summary。
- A8: Scenario: 解析失败回退 WHEN LLM 返回无法解析为 JSON 的文本 THEN 节点不抛异常 AND 返回的 `messages[0]` 仍为 `RemoveMessage(id=REMOVE_ALL_MESSAGES)` AND `messages[1]` 为非空 `AIMessage`（内容来自既有消息的确定性回退）AND `HISTORY_SUMMARY.md` 仍被写入。
- A9: Scenario: 容错 WHEN state 缺少 `runtime` 或 `messages` THEN 节点不抛异常 AND 仍返回完整更新 dict（`messages`/`context_summary`/`context_token_count`/`context_should_compress`/`compression_events` 等键齐全），仅跳过文件持久化。
- A10: Scenario: 现有行为不破坏 WHEN 在 change 工作区运行 `uv sync` THEN 成功且无新依赖、lock 一致 AND `uv run pytest` 全部通过（离线），既有 `tests/test_graph_nodes.py`、`tests/test_memory.py`、`tests/test_context_monitor.py` 等覆盖不回归。

# 约束与不变量

- `context_compressor_node` 与 LangGraph 节点签名兼容：第一个位置参数为状态 dict，返回普通 dict 更新；`model=None` 时内部 `create_model()`。
- 消息替换必须用 `RemoveMessage(id=REMOVE_ALL_MESSAGES)`（从 `langgraph.graph.message` 导入）+ 单条 `AIMessage`，适配 `messages` 通道的 `add_messages` reducer。
- 全部截断使用 `novagent.graph.memory._short_text`；`agent_handoffs` 用 `_trim_handoffs`、`sources` 用 `_norm_sources`，与既有上限一致（research_notes 1600 / code_agent_summary 1000 / history_summary 2200 / context_summary 1600 / 其余八个压缩字段 800）。
- 解析 LLM 响应复用 `_parse_verifier_json`（容忍代码围栏与前后杂文本）；任何解析/持久化失败都不允许让节点抛异常。
- 提示词 `CONTEXT_COMPRESSION_PROMPT` 逐字采用用户给定英文原文，不改写、不翻译。
- 全部测试离线运行（FakeModel + 临时 workspace），不发起网络请求，兼容 Python >= 3.10。

# 决策

- D1 独立 change 承载（用户 2026-09-11 选择 worktree 隔离创建 `context-compressor`）：context-monitor 归档后 monitor 节点与 `context_monitor_route` 就绪，本 change 落地其 `"context_compressor"` 路由目标；与 layered-memory（数据层）→ context-monitor（监控）→ context-compressor（压缩执行）的分阶段路线一致。
- D2 不接入 `build_workflow`：用户伪代码只定义节点函数与提示词，返回 dict 不含 `context_next_node`；monitor+compressor 的图接线属后续 change，本节点以可独立测试的函数交付（与 context-monitor D6"仅函数层"先例一致）。
- D3 `AIMessage.content` 只放 `summary` 字段：用户伪代码为 `AIMessage(summary)`；九键完整结构持久化进 `HISTORY_SUMMARY.md`，恢复上下文走文件读取（`read_history_summary`）而非消息流。
- D4 `HISTORY_SUMMARY.md` 写 Markdown 小节（`# History Summary` + 各字段 `##` 小节）：文件为 `.md` 且被 `read_history_summary` 以文本读回注入 prompt，Markdown 可读性优于裸 JSON；内容用截断后的九字段。
- D5 token 数为字符估算 `_estimate_text_tokens(text) = max(1, len(text)//4)`（空文本为 0）：项目约束不新增运行依赖（无 tiktoken）；`context_token_count` 记录压缩后估算值，事件 `token_count` 记录压缩前 transcript 估算值，形成前后对比；命名区别于 monitor 已占用的 `_estimate_tokens(messages, model)`。
- D6 解析失败走确定性回退（不抛异常）：`summary` 回退为既有消息内容的截断拼接、其余八键为空，压缩与持久化流程照常完成——节点崩溃会中断整图，与 memory 模块"状态残缺不抛异常"的容错哲学一致。
- D7 `runtime` 缺失或写文件失败时跳过持久化：文件名固定于 workspace 根（与 `read_history_summary` 对称），无 runtime 的纯函数调用场景（部分单测）仍可获得完整返回值。
- D8 截断除 `summary` 外的八个字段各 ≤ 800：用户伪代码要求"截断各字段的文本长度（_short_text）"但未给上限；800 字符足够承载 resume 所需要点且防 HISTORY_SUMMARY.md 膨胀（`_short_text` 复用自 memory.py，上限以模块常量表达）。
- D9 事件 `created_at` 使用 `datetime.now(timezone.utc).isoformat()`：`CompressionEvent` 预留字段首次有压缩写入方；时间取真实 UTC 时间戳，测试只断言非空与结构。
- D10 其余截断返回字段取 `research_notes`/`agent_handoffs`/`sources`/`code_agent_summary`：用户伪代码点名前两者并以"其他截断字段"兜底；这四个正是 planner 循环中持续累积的上下文字段，压缩点一并收敛语义最完整。
- D11 压缩后 `context_should_compress` 置 False（用户伪代码明确）：与 monitor 的严格大于判定配合，避免压缩后残留 True 导致路由环路；`context_token_count` 同步刷新为压缩后估算值。

# 待解决问题

（无未解决项）

# 验证预期

- `uv sync` 成功且无新依赖、`uv.lock` 一致。
- `uv run pytest` 全部通过（含新增 `tests/test_context_compressor.py`，离线）。
