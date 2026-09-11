---
generated_from_state_version: 13
---

# 验证

## 当前结果

- 结果: **已归档**
- 验证情况: **已完成检查，验证结果已确认**
- 目标周期: 2
- 迭代: 1
- 验证器尝试次数: 1
- 完成时间: 2026-09-11T04:04:37.356Z
- 摘要: 十项验收全部满足且有一手证据：提示词常量与 spec 文本程序化比对逐字一致；压缩节点的模型调用、消息替换、状态字段、持久化、截断、事件追加、解析回退与容错均在引用行号核验相符；范围干净（仅 nodes.py 修改加两个新文件），全量 124 项测试由 Verifier 独立重跑离线通过。残余关注点均为 spec 保证范围之外的轻微边界（非 int token limit、仅捕获 OSError 的持久化），不构成验收失败。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: 提示词常量 WHEN 导入 `novagent.prompts.stage4` THEN `CONTEXT_COMPRESSION_PROMPT` 为非空 str AND 以 "You are the context_compressor node in novagent stage 4." 开头 AND 同时含 "summary"、"active_goal"、"completed_work"、"open_todos"、"important_files"、"tool_findings"、"sources"、"next_steps"、"risks" 九个键名与 "Return only JSON with these keys"。 | stage4.py CONTEXT_COMPRESSION_PROMPT 与 spec prompts.stage4 文本逐字一致（程序化 diff），含九键名与 Return only JSON with these keys。 |
| A2 | passed | brief.md | A2: Scenario: 模型调用 WHEN 以含 messages 与任务状态的 state 调用 `context_compressor_node(state, model=FakeModel)` THEN 模型收到的消息恰为 `[SystemMessage, HumanMessage]` AND SystemMessage.content 为 stage4 的 `CONTEXT_COMPRESSION_PROMPT`（同一对象）AND HumanMessage.content 同时包含任务文本、全部旧消息内容与分层 memory JSON（含 `"working_memory"`）。 | nodes.py:669-675 恰以 [SystemMessage(CONTEXT_COMPRESSION_PROMPT), HumanMessage] 调用；human_text 含任务、全部旧消息 transcript 与含 working_memory 的分层 memory JSON。 |
| A3 | passed | brief.md | A3: Scenario: 消息替换 WHEN LLM 返回合法 JSON（九键齐全）THEN 返回的 `messages` 恰含两个元素 AND 第一个是 `RemoveMessage` 且 `id == REMOVE_ALL_MESSAGES` AND 第二个是 `AIMessage` 且 `content` 为截断后的 `summary` 字段。 | 返回 messages=[RemoveMessage(id=REMOVE_ALL_MESSAGES), AIMessage(截断后 summary)]，两元素、RemoveMessage 在前，两个分支的 summary 均经 _short_text 截断。 |
| A4 | passed | brief.md | A4: Scenario: 压缩状态字段 WHEN LLM 返回合法 JSON THEN `context_summary == summary`、`context_should_compress is False` AND `context_token_count` 为正整数且等于对压缩后 summary 的估算 token 数。 | context_summary==summary、context_should_compress=False、context_token_count==_estimate_text_tokens(summary)（max(1,len//4)，空为 0）。 |
| A5 | passed | brief.md | A5: Scenario: 持久化 WHEN 压缩完成 THEN workspace 根下存在 `HISTORY_SUMMARY.md` AND 文件内容含九个字段各自的小节与截断后文本（summary、active_goal、completed_work、open_todos、important_files、tool_findings、sources、next_steps、risks）。 | _persist_history_summary 以 UTF-8 写 runtime.workspace/HISTORY_SUMMARY.md，# History Summary 标题加九个 ## 小节覆盖全部九字段；测试断言九字段文本齐全。 |
| A6 | passed | brief.md | A6: Scenario: 字段截断 WHEN `research_notes` 超过 1600 字符、`agent_handoffs` 超过 6 条、`summary` 超过 1600 字符 THEN 返回的 `research_notes` 长度 ≤ 1600 且以 "..." 结尾 AND `agent_handoffs` 恰保留最近 6 条 AND `context_summary` 长度 ≤ 1600。 | research_notes ≤1600 且以 ... 结尾；agent_handoffs 保序保留最近 6 条；context_summary ≤1600；其余八键各 ≤800（COMPRESSION_DETAIL_LIMIT）。 |
| A7 | passed | brief.md | A7: Scenario: 压缩事件 WHEN state 已有 `compression_events` 且发生压缩 THEN 返回的 `compression_events` 为既有事件追加一条新事件 AND 新事件 `node == "context_compressor"`、`token_count` 等于压缩前 transcript 的估算 token 数、`token_limit` 等于 state 的 `context_token_limit`、`summary` 非空、`created_at` 非空 AND `history_summary` 等于截断后的 summary。 | 恰追加一条事件：node=context_compressor、token_count=formatted transcript 估算、token_limit=int(state 值 or 0)、reason/summary 非空、created_at 为 UTC ISO；history_summary==_short_text(summary,2200)。 |
| A8 | passed | brief.md | A8: Scenario: 解析失败回退 WHEN LLM 返回无法解析为 JSON 的文本 THEN 节点不抛异常 AND 返回的 `messages[0]` 仍为 `RemoveMessage(id=REMOVE_ALL_MESSAGES)` AND `messages[1]` 为非空 `AIMessage`（内容来自既有消息的确定性回退）AND `HISTORY_SUMMARY.md` 仍被写入。 | _parse_verifier_json 对不可解析文本返回 None 不抛异常；回退摘要取既有消息截断拼接、八键置空、RemoveMessage 仍在前、文件仍写入；测试覆盖。 |
| A9 | passed | brief.md | A9: Scenario: 容错 WHEN state 缺少 `runtime` 或 `messages` THEN 节点不抛异常 AND 仍返回完整更新 dict（`messages`/`context_summary`/`context_token_count`/`context_should_compress`/`compression_events` 等键齐全），仅跳过文件持久化。 | messages/runtime 均容错读取（or []/getattr None），transcript 空占位，跳过持久化，仍返回完整 10 键更新 dict；空 state 测试通过。 |
| A10 | passed | brief.md | A10: Scenario: 现有行为不破坏 WHEN 在 change 工作区运行 `uv sync` THEN 成功且无新依赖、lock 一致 AND `uv run pytest` 全部通过（离线），既有 `tests/test_graph_nodes.py`、`tests/test_memory.py`、`tests/test_context_monitor.py` 等覆盖不回归。 | git status 仅 nodes.py 修改、stage4.py 与测试为新增，workflow/state/memory/pyproject/uv.lock 未动；Verifier 第一手运行 uv run pytest -q：124 passed 离线（含 9 项新测试），monitor 的 _estimate_tokens(messages, model) 未被遮蔽。 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv sync（依赖一致性） | sync | . | passed | 0 | 76 ms |
| uv run pytest（全量离线） | run pytest -q | . | passed | 0 | 8089 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

- nodes.py:689 int(state.get('context_token_limit') or 0) 对非数值字符串会抛 ValueError；spec 假定该字段为 int，风险低。
- _persist_history_summary 仅捕获 OSError（nodes.py:638）；非路径型 workspace 可能触发 TypeError，但 RuntimeState.workspace 类型为 Path。
- messages 为空且 LLM 输出不可解析时回退摘要为空字符串（空 AIMessage、token_count 0）；该组合不抛异常但未单测。
- context_compressor_node 按确认 spec 非目标未接入 build_workflow；图路由到压缩器属后续 change。

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 0 | recovery | — | Native Shape artifacts changed | 2026-09-11T03:56:33.584Z |
| 2 | 1 | 1 | pass | — | 十项验收全部满足且有一手证据：提示词常量与 spec 文本程序化比对逐字一致；压缩节点的模型调用、消息替换、状态字段、持久化、截断、事件追加、解析回退与容错均在引用行号核验相符；范围干净（仅 nodes.py 修改加两个新文件），全量 124 项测试由 Verifier 独立重跑离线通过。残余关注点均为 spec 保证范围之外的轻微边界（非 int token limit、仅捕获 OSError 的持久化），不构成验收失败。 | 2026-09-11T04:04:37.356Z |



## 结论

十项验收全部满足且有一手证据：提示词常量与 spec 文本程序化比对逐字一致；压缩节点的模型调用、消息替换、状态字段、持久化、截断、事件追加、解析回退与容错均在引用行号核验相符；范围干净（仅 nodes.py 修改加两个新文件），全量 124 项测试由 Verifier 独立重跑离线通过。残余关注点均为 spec 保证范围之外的轻微边界（非 int token limit、仅捕获 OSError 的持久化），不构成验收失败。
