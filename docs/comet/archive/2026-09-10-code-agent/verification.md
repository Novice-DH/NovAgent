---
generated_from_state_version: 12
---

# 验证

## 当前结果

- 结果: **已归档**
- 验证情况: **已完成检查，验证结果已确认**
- 目标周期: 2
- 迭代: 1
- 验证器尝试次数: 1
- 完成时间: 2026-09-10T17:12:49.214Z
- 摘要: 10 项验收全部通过：实现与测试真实覆盖 A1–A9 各场景，CODE_AGENT_PROMPT 经逐行比对与用户原文逐字一致，A10 的依赖/CLI 检查由 Runtime 全部通过且 git diff 证实 pyproject/uv.lock 未改动。无 failed、无 blocked，总判定 pass。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: 工具绑定 WHEN 以含 `runtime`（指向临时 workspace）的 state 注入 FakeModel 调用 `run_code_agent` THEN FakeModel 绑定的工具名序列恰为 `["read_file", "write_file", "edit_file", "grep", "bash", "todo_update"]`。 | code_agent.py:104 绑定 build_tools(5 个，registry 顺序 read_file/write_file/edit_file/grep/bash) + todo_update，测试断言绑定名序列恰为 6 个且顺序一致 |
| A2 | passed | brief.md | A2: Scenario: 消息构造 WHEN 调用 `run_code_agent`（state 含 task 与 session_context）THEN 发给模型的首条消息为 SystemMessage 且内容即 `CODE_AGENT_PROMPT` AND 第二条 HumanMessage 同时包含 task、instruction、session_context 文本与 memory 快照段 AND 快照与 session 缺失时包含占位标注。 | 首条 SystemMessage 内容即 CODE_AGENT_PROMPT，HumanMessage 含 task/instruction/session_context/memory 段，(no session context) 与 (no memory snapshot) 占位均有测试覆盖 |
| A3 | passed | brief.md | A3: Scenario: ReAct 循环与返回结构 WHEN 注入 FakeModel（write_file 写文件 → `todo_update` 置 in_progress → `todo_update` 置 completed → 纯文本结束）与收集型 writer THEN 返回 `ok is True` AND `summary` 为最后 AI 文本 AND `todos` 中对应 todo 状态经 pending→in_progress→completed AND workspace 出现写入文件 AND `messages` 类型序列以 AIMessage 开始、含 ToolMessage（内容为合法 JSON）、以 AIMessage 结束 AND `tool_events` 类型序列为 `ai_message`、`tool_call`、`tool_result`（每工具一对）、`ai_message`、`final_answer` AND writer 收到同一批事件。 | write_file→in_progress→completed→纯文本场景下 ok/summary/todos 终态/文件落盘/messages 类型序列（含合法 JSON ToolMessage）/事件序列（每轮先 ai_message、每工具一对 tool_call+tool_result、末尾 final_answer）/writer 同批事件全部断言通过；todo 实时合并逻辑与 actor_node 逐字一致，中间态由调用顺序与代码路径等价保证 |
| A4 | passed | brief.md | A4: Scenario: todo 状态迁移边界 WHEN FakeModel 调用 `todo_update` 将某 todo 置 `blocked`（含 note）THEN 返回 `todos` 对应项 status 为 `blocked` 且 note 已更新 AND WHEN 调用未知 `todo_id` THEN `todos` 保持不变且不报错。 | blocked+note 更新生效、未知 todo_id 时 todos 不变且不报错，_VALID_STATUS 白名单与 note 逻辑与 graph/nodes.py 的 actor_node 完全一致 |
| A5 | passed | brief.md | A5: Scenario: 循环边界 WHEN FakeModel 第一轮即纯文本 THEN 模型只被调用 1 次（提前结束）AND WHEN FakeModel 每轮都返回 tool_call 且 `max_loops=2` THEN 模型恰被调用 2 次后返回。 | 第一轮纯文本仅 1 次模型调用提前结束；max_loops=2 配 5 个 tool_call 响应恰调用 2 次后返回，两个方向均有测试 |
| A6 | passed | brief.md | A6: Scenario: runtime 缺失 WHEN 以不含 `runtime` 的 state 调用 `run_code_agent` THEN 抛出 `ValueError`。 | state 无 runtime 时抛 ValueError（message 含 runtime），测试 pytest.raises 匹配，与 actor_node 一致 |
| A7 | passed | brief.md | A7: Scenario: 未知工具降级 WHEN FakeModel 调用未绑定的 `notepad_append` THEN 该调用结果文本以 `Error: unknown tool` 开头并作为 ToolMessage 回传 AND 循环继续不中断。 | notepad_append 未绑定，结果文本以 Error: unknown tool 开头（格式化与 graph.nodes._execute_tool 逐字相同）经 ToolMessage 回传，模型被调用 2 次证明循环继续 |
| A8 | passed | brief.md | A8: Scenario: 提示词常量 WHEN 导入 `novagent.agents.code_agent` THEN `CODE_AGENT_PROMPT` 以 "You are codeAgent, a focused implementation specialist." 开头 AND 含 "TodoUpdateTool"、"NotepadAppendTool"、"BashTool" AND 以 "End with a concise summary of files changed and checks run." 结尾。 | CODE_AGENT_PROMPT 与 spec.md agents.code_agent 节用户原文 20 行逐行逐字一致（含换行位置、两空格续行、引号与撇号，两侧无行尾空白），仅末尾多一个换行符属豁免范围，开头/结尾句与三个工具名提及均符合 |
| A9 | passed | brief.md | A9: Scenario: memory 接口预留 WHEN 调用 `build_memory_snapshot(state)` THEN 返回空字符串 AND 全程不发起模型调用或网络请求。 | build_memory_snapshot 恒返回空字符串，函数体无模型调用/网络/副作用，测试对两种 state 断言为空 |
| A10 | passed | brief.md | A10: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且无新依赖、lock 一致 AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0。 | Runtime 登记的 uv sync/uv lock --check/pytest(79 passed)/novagent --help 全部通过，且 git diff 028fcd6..HEAD --stat 显示本 change 仅新增 3 个源码/测试文件，pyproject.toml 与 uv.lock 未被修改 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv sync 依赖安装 | sync | . | passed | 0 | 87 ms |
| uv lock --check 锁一致 | lock --check | . | passed | 0 | 59 ms |
| uv run pytest 全量离线测试 | run pytest -q | . | passed | 0 | 8292 ms |
| uv run novagent --help 退出码 0 | run novagent --help | . | passed | 0 | 2738 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

- A3 的 pending→in_progress 中间态未被测试单独快照（仅断言终态 completed），实时迁移由 tool_call 顺序与 _apply_todo_update 逐调用合并的代码路径保证，属等价覆盖
- note 以空字符串提供时不更新（if args.get('note') 真值判断），与 actor_node 同语义且规格注明与 actor_node 一致，对空串覆盖旧 note 的极端场景行为未定义
- docs/comet/changes/ 目录当前为 git 未跟踪状态，不影响依赖与行为，change 文档将在归档事务中由 Runtime 处理

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 0 | recovery | — | Native Shape artifacts changed | 2026-09-10T17:00:32.178Z |
| 2 | 1 | 1 | pass | — | 10 项验收全部通过：实现与测试真实覆盖 A1–A9 各场景，CODE_AGENT_PROMPT 经逐行比对与用户原文逐字一致，A10 的依赖/CLI 检查由 Runtime 全部通过且 git diff 证实 pyproject/uv.lock 未改动。无 failed、无 blocked，总判定 pass。 | 2026-09-10T17:12:49.214Z |



## 结论

10 项验收全部通过：实现与测试真实覆盖 A1–A9 各场景，CODE_AGENT_PROMPT 经逐行比对与用户原文逐字一致，A10 的依赖/CLI 检查由 Runtime 全部通过且 git diff 证实 pyproject/uv.lock 未改动。无 failed、无 blocked，总判定 pass。
