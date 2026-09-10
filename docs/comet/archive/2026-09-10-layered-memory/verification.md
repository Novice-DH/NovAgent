---
generated_from_state_version: 8
---

# 验证

## 当前结果

- 结果: **已归档**
- 验证情况: **已完成检查，验证结果已确认**
- 目标周期: 1
- 迭代: 1
- 验证器尝试次数: 1
- 完成时间: 2026-09-10T23:04:04.771Z
- 摘要: 独立验收通过：A1 规则与 spec.md 原文逐字符一致；A2 三层键集 3/16/8 精确匹配；A3 四种读取情形容错正确；A4-A8 截断/修剪/收敛/round-trip 语义全部符合；A9 八字段 schema 到位且无循环导入；A10 pytest 107 passed 独立复跑确认、依赖与 lock 零变化、无越界改动（nodes/workflow/code_agent/pyproject/uv.lock 均未修改）。纯函数不变量（无模型/网络/写文件/不改 state）与缺失键容错均经代码审读与测试双重验证。Builder 摘要与独立观察一致。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: RULES_LAYER 常量 WHEN 导入 `novagent.graph.memory` THEN `RULES_LAYER` 为 dict 且 `scope == "workspace"`、`storage == "internal"` AND `rules` 为 5 条非空字符串列表，逐条覆盖工作区限定、相对路径约定、上下文外置、三类文件语义（TODO.md/NOTEPAD.md/HISTORY_SUMMARY.md）与"不暴露 memory 写工具"。 | memory.py:44-56 定义 RULES_LAYER，scope=='workspace'、storage=='internal'、rules 为 5 条非空字符串。用 python -c 从 spec.md 代码块 ast.literal_eval 提取英文原文逐字符比对，5 条全部一致（含 'Work inside the current workspace only.' 至 'layered memory is assembled by the runtime.'），未改写。 |
| A2 | passed | brief.md | A2: Scenario: 三层结构 WHEN 以含 task/todos/plan_summary 等键的 state 调用 `build_layered_memory(state)` THEN 返回 dict 恰含 `rules`、`working_memory`、`history_summary_store` 三键 AND `working_memory` 含 node/task/session_id/session_turn/plan_summary/todos/acceptance_criteria/verification_commands/research_notes/sources/agent_handoffs/code_agent_summary/verifier_summary/last_error/attempts/max_attempts 全部键 AND `history_summary_store` 含 history_path/history_exists/history_summary/notepad_path/notepad_exists/notepad/context_summary/compression_events 全部键。 | python -c 断言 build_layered_memory({runtime:None}) 返回键集恰为 {rules, working_memory, history_summary_store}；working_memory 恰 16 键（node/task/session_id/session_turn/plan_summary/todos/acceptance_criteria/verification_commands/research_notes/sources/agent_handoffs/code_agent_summary/verifier_summary/last_error/attempts/max_attempts）；history_summary_store 恰 8 键（history_path/history_exists/history_summary/notepad_path/notepad_exists/notepad/context_summary/compression_events）。tests/test_memory.py:61-96 同样断言。 |
| A3 | passed | brief.md | A3: Scenario: 文件读取 WHEN workspace 存在 NOTEPAD.md 与 HISTORY_SUMMARY.md THEN `read_notepad`/`read_history_summary` 返回 `exists=True` 与文件全文 AND WHEN workspace 不存在这两个文件 THEN 返回 `exists=False`、`content=""` 且不抛异常。 | memory.py:59-78 经 Path.read_text(utf-8) 读取，缺失返回 {'exists': False, 'content': ''} 不抛异常，非 UTF-8/IO 错误经 except (OSError, UnicodeDecodeError) 兜底。uv run pytest -k 'read or notepad...' 9 passed：存在返回 exists=True+全文、缺失目录/None runtime/非 UTF-8 均容错。 |
| A4 | passed | brief.md | A4: Scenario: 截断辅助 WHEN 以超长文本调用 `_short_text(text, limit)` THEN 返回长度不超过 limit 且以 "..." 结尾 AND 短文本原样返回。 | memory.py:81-88 _short_text：len<=limit 原样返回；超长返回 value[:limit-3]+'...'（总长恰为 limit，验证 'x'*50/10 -> 'xxxxxxx...'）；limit<=3 有防御分支。python -c 断言与 tests/test_memory.py:172-182 一致通过。 |
| A5 | passed | brief.md | A5: Scenario: handoffs 修剪 WHEN `agent_handoffs` 超过 6 条 THEN `working_memory["agent_handoffs"]` 恰保留最近 6 条且顺序保持。 | memory.py:91-95 _trim_handoffs 用 list 切片 [-6:]，保留末尾 6 条且顺序保持（9 条输入得 [3,4,5,6,7,8]，测试 8 条得 [2..7]），非 list 返回 []。 |
| A6 | passed | brief.md | A6: Scenario: sources 收敛 WHEN `sources` 含 title/url/content/score THEN `working_memory["sources"]` 每项仅含 `title` 与 `url` 键。 | memory.py:98-111 _norm_sources 每项仅保留 title/url（缺失补 ''），含 content/score 的输入验证输出恰为 [{'title','url'}]，非 list 返回 []。tests/test_memory.py:112-135 断言通过。 |
| A7 | passed | brief.md | A7: Scenario: 压缩历史层 WHEN state 含 `context_summary` 与 `compression_events`（>3 条） THEN `history_summary_store` 反映该 context_summary（≤1600 截断）AND `compression_events` 仅保留最近 3 条。 | memory.py:154-159 context_summary 经 _short_text(...,1600)（9999 字输入验证输出长恰 1600 且以 '...' 结尾）；compression_events 取列表副本 [-3:]，5 条输入验证保留 [n2,n3,n4] 且顺序保持。 |
| A8 | passed | brief.md | A8: Scenario: prompt 格式化 WHEN 调用 `format_layered_memory_for_prompt(memory)` THEN 返回合法 JSON 字符串且 `json.loads` 后与输入相等。 | memory.py:169-171 format_layered_memory_for_prompt 为 json.dumps(memory, ensure_ascii=False)；python -c 与 tests/test_memory.py 验证返回 str、json.loads 后与输入完全相等（含中文内容不被转义）。 |
| A9 | passed | brief.md | A9: Scenario: 状态 schema WHEN 检查 `NovGraphState.__annotations__` THEN 包含 context_summary/context_token_count/context_token_limit/context_should_compress/context_next_node/compression_events/memory_snapshot/history_summary 八个新字段。 | state.py:67-74 新增 8 字段，python -c 验证 NovGraphState.__annotations__ 全部包含且类型正确（str/int/bool/list[CompressionEvent]/LayeredMemory）。无循环导入：memory.py 仅导入 novagent.core.state，全仓 grep 确认 graph.memory 唯一外部导入方为 state.py:9。 |
| A10 | passed | brief.md | A10: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且无新依赖、lock 一致 AND `uv run pytest` 全部通过（离线）。 | 独立复跑 uv run pytest -q -> 107 passed in 6.59s（离线）。git status/diff 确认 pyproject.toml 与 uv.lock 未修改（uv sync 后 lock 一致、无新依赖）；nodes.py/workflow.py/agents/code_agent.py 均未改动，code_agent.build_memory_snapshot 保持原空桩返回（符合 spec 与 D7 不接线要求）。 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv sync（无新依赖、uv.lock 一致） | sync | . | passed | 0 | 99 ms |
| uv run pytest -q（离线全量测试） | run pytest -q | . | passed | 0 | 8798 ms |
| uv run novagent --help（CLI 冒烟） | run novagent --help | . | passed | 0 | 3241 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

- 低风险（不阻塞）：_short_text 在 limit<=3 的退化输入下返回可能短于 3 字符的省略号前缀（如 limit=1 时 '.'），spec 未定义该边界，验收示例不涉及。
- 低风险（不阻塞）：实现用 state.get('max_attempts') or 3，若状态显式设 max_attempts=0 会归一为 3，与 spec 字面 state.get('max_attempts', 3) 在该退化值上有细微差异；无验收项覆盖且语义上 max_attempts=0 无意义。
- 提示：build_layered_memory/rules 目前无运行时写入方与调用方（nodes/workflow 未接线），属 brief D6/D7 明确预期的后续 change 范围。

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 1 | pass | — | 独立验收通过：A1 规则与 spec.md 原文逐字符一致；A2 三层键集 3/16/8 精确匹配；A3 四种读取情形容错正确；A4-A8 截断/修剪/收敛/round-trip 语义全部符合；A9 八字段 schema 到位且无循环导入；A10 pytest 107 passed 独立复跑确认、依赖与 lock 零变化、无越界改动（nodes/workflow/code_agent/pyproject/uv.lock 均未修改）。纯函数不变量（无模型/网络/写文件/不改 state）与缺失键容错均经代码审读与测试双重验证。Builder 摘要与独立观察一致。 | 2026-09-10T23:04:04.771Z |



## 结论

独立验收通过：A1 规则与 spec.md 原文逐字符一致；A2 三层键集 3/16/8 精确匹配；A3 四种读取情形容错正确；A4-A8 截断/修剪/收敛/round-trip 语义全部符合；A9 八字段 schema 到位且无循环导入；A10 pytest 107 passed 独立复跑确认、依赖与 lock 零变化、无越界改动（nodes/workflow/code_agent/pyproject/uv.lock 均未修改）。纯函数不变量（无模型/网络/写文件/不改 state）与缺失键容错均经代码审读与测试双重验证。Builder 摘要与独立观察一致。
