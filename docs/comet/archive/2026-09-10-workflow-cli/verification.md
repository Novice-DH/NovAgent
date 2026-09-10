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
- 完成时间: 2026-09-10T12:50:41.109Z
- 摘要: A1-A5 全部经独立探针复核通过：事件流语义、失败回环与预算耗尽、CLI 徽标渲染与 --max-attempts、范围外零改动均与 brief/spec 一致。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: 通过路径的事件序列 WHEN 注入 FakeModel（planner 调 `todo_write` 提交计划、验证命令 `"<python>" -c "print('ok')"`；actor 第一轮 `write_file` 写文件、第二轮纯文本；verifier 输出 `passed=true` JSON）并以临时 workspace 调用 `stream_agent_events(task, workspace=ws, model=fake)` 收集全部事件 THEN 事件依次包含 `node_output`+planner（含 plan_summary 与 todos）、`node="actor"` 的 `ai_message`/`tool_call`/`tool_result`、`node_output`+verifier（passed 为 True）、`node_output`+final，且 `node_output`+final 的 `final_answer` 以 "Task completed" 开头 AND FakeModel 共被调用 4 次 AND 文件落盘。 | 探针实测事件序 [(node_output,planner),(ai_message,actor),(tool_call,actor),(tool_result,actor),(ai_message,actor),(final_answer,actor),(node_output,verifier),(node_output,final)]，verifier passed=True，final_answer='Task completed in 1 attempt(s). all good'，调用 4 次，文件落盘内容正确 |
| A2 | passed | brief.md | A2: Scenario: 失败回环产生两轮节点事件 WHEN FakeModel 依次为（planner 计划带必失败命令 `"<python>" -c "raise SystemExit(1)"`、actor 文本、verifier `passed=false` reason "tests broke"、planner 修订计划带通过命令、actor 文本、verifier `passed=true`）THEN 事件流恰好出现两次 `node_output`+planner AND 失败轮 `node_output`+verifier 的 `passed` 为 False 且 `reason == "tests broke"` AND 最终 `node_output`+final 的 `final_answer` 以 "Task completed" 开头 AND FakeModel 共被调用 6 次。 | 探针实测恰好 2 次 planner node_output；失败轮 verifier passed=False 且 reason=='tests broke'（exit_code=1）；调用 6 次；最终 final_answer 以 Task completed 开头 |
| A3 | passed | brief.md | A3: Scenario: max_attempts 预算耗尽直接收尾 WHEN FakeModel 提供一轮必失败计划（planner、actor、verifier `passed=false`）且 `stream_agent_events(..., max_attempts=1)` THEN 事件流只有一次 `node_output`+planner AND `node_output`+verifier 的 `passed` 为 False AND `node_output`+final 的 `final_answer` 以 "Task failed" 开头 AND FakeModel 共被调用 3 次（不再回 planner）。 | max_attempts=1 探针实测仅 1 次 planner node_output，verifier passed=False，final_answer 以 'Task failed after 1 attempt(s).' 开头（含 tests broke），调用 3 次未回环 |
| A4 | passed | brief.md | A4: Scenario: CLI 显示节点徽标与 --max-attempts WHEN 用统一事件格式的 fake 流（planner node_output、actor ai_message/tool_call/tool_result、verifier node_output passed=true、final node_output）monkeypatch 后以 CliRunner 运行 `run "demo task" --workspace <ws> --max-attempts 2` THEN 退出码 0 AND 输出依次包含 "📋 Planner"、"🔧 Actor"、"✅ Verifier"、"📝 Final" 与工具详情、最终回答 AND fake 记录到的 `max_attempts == 2` AND 不带选项运行时 fake 记录到 `max_attempts == 3` AND `--help` 包含 `--max-attempts`。 | CliRunner 探针：退出码 0，📋/🔧/✅/📝 位置严格递增，工具详情 bash/echo hi/exit 0 齐全；--max-attempts 显式记录 [2]、缺省记录 [3]；--help 含 --max-attempts 且退出码 0 |
| A5 | passed | brief.md | A5: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且 `uv.lock` 一致（无新依赖）AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0 AND 缺 `OPENAI_API_KEY` 时 CLI 仍以退出码 1 与清晰错误退出。 | git diff 证实 tools/、graph/state.py、prompts/ 无改动；nodes.py 的 _execute_tool 与 HEAD 原 core.agent 实现逐行一致；独立复跑 uv lock --check OK、pytest 69 passed、novagent --help 退出 0，缺 OPENAI_API_KEY 时退出码 1 且报 Configuration error 清晰信息 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv sync 依赖安装 | sync | . | passed | 0 | 73 ms |
| uv lock --check 锁一致 | lock --check | . | passed | 0 | 59 ms |
| uv run pytest 全量离线测试 | run pytest -q | . | passed | 0 | 8132 ms |
| uv run novagent --help 含 --max-attempts | run novagent --help | . | passed | 0 | 2483 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

- verifier 命令超时（exit_code=None）时 CLI 显示 'failed to run' 而非具体退出码，属渲染降级非缺陷
- tests/test_graph_workflow.py 删除 stage1 ACTOR_PROMPT 旧测试，为 D5 移除常量的必要连带改动，节点语义测试未受影响

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 1 | pass | — | A1-A5 全部经独立探针复核通过：事件流语义、失败回环与预算耗尽、CLI 徽标渲染与 --max-attempts、范围外零改动均与 brief/spec 一致。 | 2026-09-10T12:50:41.109Z |



## 结论

A1-A5 全部经独立探针复核通过：事件流语义、失败回环与预算耗尽、CLI 徽标渲染与 --max-attempts、范围外零改动均与 brief/spec 一致。
