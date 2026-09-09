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
- 完成时间: 2026-09-09T19:29:10.902Z
- 摘要: A1-A7 全部通过独立 FakeModel 探针与行为不变性核验，63 测试离线复跑通过，判定 pass。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: planner_node 首次生成计划 WHEN 构造无 todos 的 `NovGraphState`（task 为 "demo task"，runtime 指向临时 workspace），注入 FakeModel（返回调用 `todo_write` 的 tool_call，args 含 plan_summary="plan"、todos 一条 `{id: "t1", content: "step"}`、acceptance_criteria 一条、verification_commands 一条）调用 `planner_node(state, model=fake)` THEN 返回更新的 `plan_summary == "plan"`、`todos` 为一条 TodoItem（id "t1"、status 归一为 "pending"、note 为 ""）、`acceptance_criteria` 与 `verification_commands` 与 args 一致 AND FakeModel 绑定的工具恰为 1 个且名为 `todo_write` AND 首轮消息依次为 SystemMessage（内容为 `PLANNER_PROMPT`）与 HumanMessage（内容含 task 文本）AND 返回更新不含 `passed`/`attempts` 键。 | 探针实证：绑定仅 todo_write；消息 System(PLANNER_PROMPT)+Human 含 task；status 'weird' 归一 'pending'、note ''；更新键不含 passed/attempts；无 tool_call 抛含 todo_write 的 ValueError |
| A2 | passed | brief.md | A2: Scenario: planner_node 按失败修订 WHEN 状态已有 todos 且 `last_error == "boom"`（`verification_results` 含一条 ok=False）调用 `planner_node` THEN 发给模型的 HumanMessage 内容包含 "boom" AND 返回更新为修订后的计划（与本次 tool_call args 一致）AND 首轮仍为 SystemMessage(PLANNER_PROMPT)。 | 探针实证：todos+last_error='boom' 时 HumanMessage 含 'boom' 及失败验证 stderr；首轮仍 System(PLANNER_PROMPT)；返回与修订 args 一致 |
| A3 | passed | brief.md | A3: Scenario: actor_node 运行 ReAct 循环并逐事件产出 WHEN 状态 runtime 指向临时 workspace、注入 FakeModel（第一轮返回 `write_file` 写 `note.txt` 内容 "hi" 的 tool_call，第二轮返回纯文本 "All done."）、以列表收集事件调用 `actor_node(state, model=fake, on_event=events.append)` THEN 事件 `type` 依次为 `ai_message`、`tool_call`、`tool_result`、`ai_message`、`final_answer` AND 返回更新 `messages` 依次为 AIMessage、ToolMessage（tool_call_id 一致、content 为 json.dumps 结果）、AIMessage（content "All done."）AND `last_actor_summary == "All done."` AND workspace 出现 `note.txt` 内容 "hi" AND FakeModel 绑定工具名为 `read_file`、`write_file`、`edit_file`、`grep`、`bash`、`todo_update` 共 6 个。 | 探针实证：事件类型依次 ai_message/tool_call/tool_result/ai_message/final_answer；messages 为 AIMessage/ToolMessage(id=c1,json)/AIMessage('All done.')；note.txt='hi'；last_actor_summary 正确；绑定恰 6 工具 |
| A4 | passed | brief.md | A4: Scenario: actor_node 收集 todo_update WHEN FakeModel 第一轮返回 `todo_update`（args `{todo_id: "t1", status: "completed", note: "done"}`）、第二轮纯文本结束，状态 todos 含 id "t1" 的条目 THEN 返回更新 `todos` 中 t1 的 `status == "completed"` 且 `note == "done"`。 | 探针实证：todo_update {t1,completed,done} 合并进返回 todos；未知 todo_id 'ghost' 被忽略且 todos 不变 |
| A5 | passed | brief.md | A5: Scenario: verifier_node 判定通过 WHEN 状态含 `verification_commands == ["<python> -c \"print('ok')\""]`（<python> 为 `sys.executable`）、todos 两条未完成，FakeModel 只读 agent 第二轮输出合法 JSON `{"passed": true, "reason": "all good", "checks": [{"name": "smoke", "passed": true, "detail": "ok"}], "recommended_next_instruction": "ship it"}` 调用 `verifier_node(state, model=fake)` THEN 返回更新 `passed is True`、`attempts` 为原值 +1、`verification_results` 恰一条且 `ok is True`、`exit_code == 0`、`stdout` 含 "ok"、`stderr == ""`、`verification_checks` 与 LLM checks 一致、`last_error == ""`、`final_answer == "all good"`、todos 全部 `completed` AND FakeModel 绑定工具恰为 `read_file`、`grep` 2 个。 | 探针实证（sys.executable 真跑命令）：passed True、attempts 1→2、结果 ok/exit_code 0/stdout 含 ok/stderr ''、checks 与 LLM 一致、last_error ''、final_answer 'all good'、todos 全 completed、仅绑 read_file+grep |
| A6 | passed | brief.md | A6: Scenario: verifier_node 判定失败并记录错误 WHEN `verification_commands` 含一条必然非零退出的命令，FakeModel 输出 `{"passed": false, "reason": "tests broke", "checks": [{"name": "c1", "passed": false, "detail": "d"}], "recommended_next_instruction": "fix"}` THEN 返回更新 `passed is False`、`attempts` +1、`last_error` 含 "tests broke"、失败命令的 `VerificationResult.ok is False` 且 `exit_code != 0`、todos 中 `in_progress` 条目标为 `blocked` AND 后接调用 `verifier_route(合并后状态)` 返回 `"planner"`。 | 探针实证：passed False、attempts+1、last_error 含 'tests broke'、命令 exit_code 3 ok False、in_progress→blocked、合并后 route='planner'；非法 JSON 判失败并写 'valid JSON' 诊断 |
| A7 | passed | brief.md | A7: Scenario: verifier_route 三分支 WHEN 状态 `{"passed": True, ...}` 返回 `"final"` AND `{"passed": False, "attempts": 3, "max_attempts": 3}` 返回 `"final"` AND `{"passed": False, "attempts": 1, "max_attempts": 3}` 返回 `"planner"` AND 缺省 `max_attempts` 时按默认 3 判断（`attempts=2` → `"planner"`，`attempts=3` → `"final"`）。 | 探针实证五分支：(True)→final；(F,3,3)→final；(F,1,3)→planner；缺省时 attempts=2→planner、3→final（DEFAULT_MAX_ATTEMPTS=3） |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv sync 依赖安装 | sync | . | passed | 0 | 115 ms |
| uv lock --check 锁一致 | lock --check | . | passed | 0 | 68 ms |
| uv run pytest 全量离线测试 | run pytest -q | . | passed | 0 | 9717 ms |
| uv run novagent --help CLI 可用 | run novagent --help | . | passed | 0 | 2723 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

- verifier 复用 core.agent 私有 _execute_tool（跨模块依赖私有符号，语义一致性由复用保证，后续重构 core/agent.py 时需同步）
- verifier 验证命令超时固定 30s 默认值不可配（符合 brief 规定）；超时→exit_code None/ok False 路径经 execute_command TimeoutError 行为与代码走读确认，未做端到端长超时探针

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 1 | pass | — | A1-A7 全部通过独立 FakeModel 探针与行为不变性核验，63 测试离线复跑通过，判定 pass。 | 2026-09-09T19:29:10.902Z |



## 结论

A1-A7 全部通过独立 FakeModel 探针与行为不变性核验，63 测试离线复跑通过，判定 pass。
