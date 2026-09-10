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
- 完成时间: 2026-09-10T12:22:33.095Z
- 摘要: A1-A6 全部通过：图拓扑、双路径端到端、final_node 格式化、stage2 常量唯一来源与 core 零改动均经独立探针证实。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: 组装四节点工作流 WHEN 调用 `build_workflow()` THEN 返回已编译图 AND 图节点集合恰为 `{"planner", "actor", "verifier", "final"}` AND 从 START 出发的边指向 `"planner"` AND `"final"` 的出边指向 END。 | 探针实测 build_workflow() 编译成功，nodes={__start__,planner,actor,verifier,final}，边 __start__→planner、planner→actor、actor→verifier、final→__end__、verifier 条件边 {final:final,planner:planner}，签名 keyword-only model=None |
| A2 | passed | brief.md | A2: Scenario: 离线端到端一次通过 WHEN 构造初始状态（task、runtime 指向临时 workspace、max_attempts=3），注入 FakeModel 依次返回（planner 调 `todo_write` 提交计划，验证命令为 `"<python>" -c "print('ok')"`；actor 第一轮 `write_file` 写 `result.txt`、第二轮纯文本结束；verifier 输出 `passed=true` 的 JSON）并调用 `build_workflow(model=fake).invoke(state)` THEN 最终状态 `passed is True`、`final_answer` 为成功格式文本（含 "completed" 与 attempts 数）、todos 全部 `completed`、`attempts == 1` AND FakeModel 共被调用 4 次（1+2+1，证明路径 planner→actor→verifier→final）AND workspace 出现 `result.txt`。 | FakeModel 端到端实测 passed=True、attempts=1、模型调用恰 4 次（1+2+1，bindings 首工具依次 todo_write/read_file/read_file）、final_answer 含 completed/1/all good、todos 全 completed、result.txt 写出 |
| A3 | passed | brief.md | A3: Scenario: 失败后回 planner 修订再通过 WHEN FakeModel 依次返回（第一轮 planner 提交计划，验证命令为 `"<python>" -c "raise SystemExit(1)"`；actor 纯文本结束；verifier 输出 `passed=false` 且 reason 为 "tests broke" 的 JSON；第二轮 planner 提交修订计划，验证命令为 `"<python>" -c "print('ok')"`；actor 纯文本结束；verifier 输出 `passed=true` 的 JSON）invoke 同一图 THEN 最终 `passed is True`、`attempts == 2` AND 第二轮 planner 收到的 HumanMessage 包含 "tests broke" AND FakeModel 共被调用 6 次（2+1+1 + 1+1）。 | 失败重试路径实测 attempts=2、FakeModel 调用 6 次（2+1+1+1+1）、第二轮 planner 消息为 HumanMessage 且含 'tests broke' |
| A4 | passed | brief.md | A4: Scenario: final_node 格式化成败 WHEN 以 `{"passed": True, "attempts": 1, "final_answer": "all good"}` 调用 `final_node` THEN 返回更新 `final_answer` 含 "completed"、"1" 与 "all good" AND 以 `{"passed": False, "attempts": 3, "last_error": "boom"}` 调用 THEN 返回更新 `final_answer` 含 "failed"、"3" 与 "boom" AND 两种情况均不包含 `passed` 键（不翻转判定）。 | final_node 成功返回 'Task completed in 1 attempt(s). all good'，失败返回 'Task failed after 3 attempt(s). Last error: boom'，两种返回键均仅 final_answer，不翻转 passed |
| A5 | passed | brief.md | A5: Scenario: stage2 提示词与引用一致 WHEN 导入 `novagent.prompts.stage2` THEN 四个常量均非空字符串 AND `PLANNER_PROMPT` 含 "todo_write" AND `ACTOR_PROMPT` 以 "You are the actor node in novagent's LangGraph workflow." 开头 AND `VERIFIER_PROMPT` 含 `"passed"` AND `FINAL_PROMPT` 非空 AND `novagent.graph.nodes` 模块级名字 `PLANNER_PROMPT`、`VERIFIER_PROMPT`、`ACTOR_PROMPT` 与 stage2 的对应常量 `is` 同一对象。 | 四常量非空，PLANNER_PROMPT 含 todo_write，ACTOR_PROMPT 以指定句开头，VERIFIER_PROMPT 含 "passed"；graph.nodes.PLANNER/VERIFIER/ACTOR_PROMPT 与 stage2 对应常量 is 同一对象；FINAL_PROMPT grep 仅 stage2.py 定义与测试引用，无运行时调用 |
| A6 | passed | brief.md | A6: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且 `uv.lock` 一致（无新依赖）AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0 AND `core.agent.ACTOR_PROMPT` 原文不变（`stream_agent_events` 首轮 SystemMessage 仍为其自身）。 | 独立复跑 pytest 69 passed、novagent --help exit 0；git diff core/agent.py 为空，core ACTOR_PROMPT 仍以 ReAct workflow 开头（agent.py:14）；pyproject.toml/uv.lock 零 diff，无新依赖 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv sync 依赖安装 | sync | . | passed | 0 | 72 ms |
| uv lock --check 锁一致 | lock --check | . | passed | 0 | 55 ms |
| uv run pytest 全量离线测试 | run pytest -q | . | passed | 0 | 7687 ms |
| uv run novagent --help CLI 可用 | run novagent --help | . | passed | 0 | 2514 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

_未报告风险。_

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 1 | pass | — | A1-A6 全部通过：图拓扑、双路径端到端、final_node 格式化、stage2 常量唯一来源与 core 零改动均经独立探针证实。 | 2026-09-10T12:22:33.095Z |



## 结论

A1-A6 全部通过：图拓扑、双路径端到端、final_node 格式化、stage2 常量唯一来源与 core 零改动均经独立探针证实。
