# 目标

在 `src/novagent/graph/memory.py` 中实现三层 Memory 系统（Context Engineering）：

1. **Rules Layer（固定规则层）**：模块常量 `RULES_LAYER`（含 `scope="workspace"`、`storage="internal"` 与 5 条固定规则：仅在工作区内工作、相对路径不加 workspace/ 前缀、持久任务上下文尽量脱离消息记录、TODO.md=工作计划态 / NOTEPAD.md=持久笔记 / HISTORY_SUMMARY.md=压缩历史、不向 Agent 暴露 memory 写工具而由 runtime 组装分层记忆）。
2. **Working Memory（当前任务状态层）**：`build_layered_memory(state, *, node="graph") -> dict` 从状态与 workspace 文件组装 `working_memory`（node、task、session_id、session_turn、plan_summary、todos、acceptance_criteria、verification_commands、research_notes(≤1600)、sources(仅 title/url)、agent_handoffs(最近 6 条)、code_agent_summary(≤1000)、verifier_summary(≤1000)、last_error(≤1400)、attempts、max_attempts）。
3. **History Summary Store（压缩历史层）**：同一 `build_layered_memory` 返回值包含 `history_summary_store`（HISTORY_SUMMARY.md 读取与 `history_summary`(≤2200)、NOTEPAD.md 读取与 `notepad`(≤1800)、`context_summary`(≤1600)、`compression_events`(最近 3 条)），返回结构为 `{"rules", "working_memory", "history_summary_store"}`。

关键辅助函数：`_short_text(text, limit)`（超长截断并以 "..." 结尾）、`_trim_handoffs(handoffs)`（保留最近 6 条）、`format_layered_memory_for_prompt(memory)`（`json.dumps` 格式化）。

同时在 `NovGraphState` 新增字段：`context_summary: str`、`context_token_count: int`、`context_token_limit: int`、`context_should_compress: bool`、`context_next_node: str`、`compression_events: list[CompressionEvent]`、`memory_snapshot: LayeredMemory`、`history_summary: str`。

# 范围

- 新增 `src/novagent/graph/memory.py`：
  - 常量 `RULES_LAYER`：按上述 5 条固定规则的字典；
  - 文件读取辅助 `read_notepad(runtime)` / `read_history_summary(runtime)`：分别读取 workspace 根下的 `NOTEPAD.md` / `HISTORY_SUMMARY.md`，返回 `{"exists": bool, "content": str}`（文件缺失时 `exists=False`、`content=""`，不抛异常）；
  - 内部辅助 `_short_text` / `_trim_handoffs` / `_norm_sources`（sources 仅保留 title/url）；
  - `build_layered_memory(state, *, node="graph") -> dict`：组装 rules / working_memory / history_summary_store 三层；缺失键一律容错读取（`state.get(...)`）；`session_id`/`session_turn`/`verifier_summary` 等当前 schema 尚不存在的键按缺失占位处理；
  - `format_layered_memory_for_prompt(memory) -> str`：`json.dumps(memory, ensure_ascii=False)`。
  - 类型 `CompressionEvent`、`LayeredMemory`（TypedDict，供 `NovGraphState` 引用）。
- 修改 `src/novagent/graph/state.py`：`NovGraphState` 新增 `context_summary`、`context_token_count`、`context_token_limit`、`context_should_compress`、`context_next_node`、`compression_events`、`memory_snapshot`、`history_summary` 字段；新增 `CompressionEvent` / `LayeredMemory` 类型引用。
- 新增 `tests/test_memory.py`（纯函数离线测试，不调用模型、不发起网络请求）。

# 非目标

- 不实现压缩机制的执行逻辑：token 计数、`context_should_compress` 判定、压缩摘要生成、`HISTORY_SUMMARY.md` 写入、`context_next_node` 路由均不在本次（用户确认仅数据层）；本次新增的 `context_*`/`compression_events`/`history_summary` 状态字段为压缩机制预留 schema，尚无写入方属预期。
- 不把 `build_layered_memory` 接入运行时：不修改 `nodes.py`/`workflow.py`/`code_agent.py`，planner/verifier 提示词注入与 `code_agent.build_memory_snapshot` 真实化由后续 change 处理（用户确认仅交付模块；该预留接口本 change 后仍返回空字符串）。
- 不实现 notepad 写工具（`NotepadAppendTool`/`NotepadReadTool`），本 change 对 NOTEPAD.md 只读不写。
- 不引入 TODO.md 的读写实现（RULES_LAYER 规则文字提及 TODO.md，但不实现其文件读写）。
- 不新增运行依赖。

# 验收示例

- A1: Scenario: RULES_LAYER 常量 WHEN 导入 `novagent.graph.memory` THEN `RULES_LAYER` 为 dict 且 `scope == "workspace"`、`storage == "internal"` AND `rules` 为 5 条非空字符串列表，逐条覆盖工作区限定、相对路径约定、上下文外置、三类文件语义（TODO.md/NOTEPAD.md/HISTORY_SUMMARY.md）与"不暴露 memory 写工具"。
- A2: Scenario: 三层结构 WHEN 以含 task/todos/plan_summary 等键的 state 调用 `build_layered_memory(state)` THEN 返回 dict 恰含 `rules`、`working_memory`、`history_summary_store` 三键 AND `working_memory` 含 node/task/session_id/session_turn/plan_summary/todos/acceptance_criteria/verification_commands/research_notes/sources/agent_handoffs/code_agent_summary/verifier_summary/last_error/attempts/max_attempts 全部键 AND `history_summary_store` 含 history_path/history_exists/history_summary/notepad_path/notepad_exists/notepad/context_summary/compression_events 全部键。
- A3: Scenario: 文件读取 WHEN workspace 存在 NOTEPAD.md 与 HISTORY_SUMMARY.md THEN `read_notepad`/`read_history_summary` 返回 `exists=True` 与文件全文 AND WHEN workspace 不存在这两个文件 THEN 返回 `exists=False`、`content=""` 且不抛异常。
- A4: Scenario: 截断辅助 WHEN 以超长文本调用 `_short_text(text, limit)` THEN 返回长度不超过 limit 且以 "..." 结尾 AND 短文本原样返回。
- A5: Scenario: handoffs 修剪 WHEN `agent_handoffs` 超过 6 条 THEN `working_memory["agent_handoffs"]` 恰保留最近 6 条且顺序保持。
- A6: Scenario: sources 收敛 WHEN `sources` 含 title/url/content/score THEN `working_memory["sources"]` 每项仅含 `title` 与 `url` 键。
- A7: Scenario: 压缩历史层 WHEN state 含 `context_summary` 与 `compression_events`（>3 条） THEN `history_summary_store` 反映该 context_summary（≤1600 截断）AND `compression_events` 仅保留最近 3 条。
- A8: Scenario: prompt 格式化 WHEN 调用 `format_layered_memory_for_prompt(memory)` THEN 返回合法 JSON 字符串且 `json.loads` 后与输入相等。
- A9: Scenario: 状态 schema WHEN 检查 `NovGraphState.__annotations__` THEN 包含 context_summary/context_token_count/context_token_limit/context_should_compress/context_next_node/compression_events/memory_snapshot/history_summary 八个新字段。
- A10: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且无新依赖、lock 一致 AND `uv run pytest` 全部通过（离线）。

# 约束与不变量

- `build_layered_memory` 为纯组装函数：不调用模型、无网络、不写文件；缺失键一律容错（`state.get`），不因状态残缺抛异常。
- 文本截断上限固定：research_notes 1600 / code_agent_summary 1000 / verifier_summary 1000 / last_error 1400 / history_summary 2200 / notepad 1800 / context_summary 1600；handoffs 最近 6 条；compression_events 最近 3 条。
- `RULES_LAYER` 规则文字逐字采用用户给定 5 条（英文原文），不改写。
- 返回结构契约固定为 `{"rules": ..., "working_memory": ..., "history_summary_store": ...}`。
- 全部测试离线运行（临时 workspace + 纯函数），不发起网络请求，兼容 Python >= 3.10。

# 决策

- D1 `state` 为图状态样 dict：沿用 `actor_node`/`run_code_agent` 既有模式（state 为 dict、经 `state["runtime"]` 取 RuntimeState）；`build_layered_memory` 同样从 dict 状态容错读键。
- D2 `read_notepad`/`read_history_summary` 定义在 `memory.py` 内：用户伪代码直接调用二者，而仓库当前无任何 notepad/历史读取实现（code-agent change D5 明确其属于本 memory 阶段）；二者读取 workspace 根下的 `NOTEPAD.md`/`HISTORY_SUMMARY.md`，返回 `{"exists", "content"}`。
- D3 `session_id`/`session_turn`/`verifier_summary` 以 `state.get` 缺失占位处理：用户新增字段清单未含这些 schema 字段，本 change 不为其扩 schema（沿用 code-agent change D6 的先例）。
- D4 `CompressionEvent`/`LayeredMemory` 定义为 TypedDict：`NovGraphState` 现有风格全部为 TypedDict；`memory_snapshot: LayeredMemory` 直接复用该类型。
- D5 无新增依赖：组装与截断均为标准库可完成。
- D6 压缩执行逻辑不在本次范围（用户 2026-09-11 确认"仅数据层"）：本 change 交付三层 Memory 数据层 + `NovGraphState` 字段定义；`context_*`/`compression_events` 字段作为压缩机制预留 schema，token 监控、压缩摘要与历史写入、路由属后续图接线 change。
- D7 分层记忆暂不接入运行时（用户 2026-09-11 确认"仅交付模块"）：不改 `nodes.py`/`workflow.py`/`code_agent.py`，现有图行为完全不变；运行时注入由后续 change 处理，与 RULES_LAYER "layered memory is assembled by the runtime" 的语义一致。
- D8 `history_summary` 取自 `read_history_summary` 的文件内容：用户伪代码中 `history_summary` 紧跟 `history = read_history_summary(runtime)` 且未标注其他来源，取 `history.get("content", "")` 最贴近原文；`NovGraphState.history_summary` 字段本次同为 schema 预留（无写入方）。
- D9 `session_id`/`session_turn`/`verifier_summary` 缺失占位：`NovGraphState` 现无这些字段，用户新增字段清单亦未含；以 `state.get(...)` 缺省值处理（`""`/`0`），沿用 code-agent change D6 先例，不为其扩 schema。
- D10 `_short_text` 保证结果总长不超过 `limit` 且超长时以 "..." 结尾：截断含省略号，向调用方提供确定的上界保证。
- D11 `format_layered_memory_for_prompt` 使用 `json.dumps(memory, ensure_ascii=False)`：输出用于 prompt，中文内容不转义可读性更好；JSON 语义不变。

# 待解决问题

（无未解决项）

# 验证预期

- `uv sync` 成功且无新依赖、`uv.lock` 一致。
- `uv run pytest` 全部通过（含新增 `tests/test_memory.py`，离线）。
