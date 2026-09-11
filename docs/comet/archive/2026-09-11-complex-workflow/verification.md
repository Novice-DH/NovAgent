---
generated_from_state_version: 11
---

# 验证

## 当前结果

- 结果: **已归档**
- 验证情况: **已完成检查，验证结果已确认**
- 目标周期: 2
- 迭代: 1
- 验证器尝试次数: 1
- 完成时间: 2026-09-11T04:40:11.769Z
- 摘要: 本轮实现与 brief/spec 高度一致：build_complex_workflow 五节点图、条件边映射逐字匹配四/三目标集，monitor 路由优先级（passed＞预算耗尽＞should_compress＞透传）在 nodes.py:539-546 正确落地，compressor 占位为纯函数，planner/verifier 上游设置按约定写入 context_next_node，verifier_route 与 build_workflow 已彻底移除且无残留引用。planner stream writer 桥接（custom 流 node="planner"）未回归。本人独立重跑 uv run pytest -q 得 127 passed，A1–A12 均有源码行号与测试断言双重证据支持。仅存在三项非阻塞风险：agent.py 遗留陈旧文案（范围外）、大 max_attempts 的递归上限理论风险、占位压缩器逐轮重复触发的无害行为。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: 图结构与编译 WHEN 调用 `build_complex_workflow()` THEN 编译成功 AND 节点集合恰为 `{"planner", "context_monitor", "context_compressor", "verifier", "final"}` AND 边含 `START→planner`、`planner→context_monitor`、`verifier→context_monitor`、`final→END` AND `context_monitor` 条件路由目标恰为 `{"context_compressor", "verifier", "planner", "final"}` AND `context_compressor` 条件路由目标恰为 `{"verifier", "planner", "final"}`。 | workflow.py:40-68 注册恰五节点（planner/context_monitor/context_compressor/verifier/final）并含 START→planner、planner→context_monitor、verifier→context_monitor（workflow.py:67）、final→END（workflow.py:68）；context_monitor 条件边映射恰四目标、context_compressor 恰三目标（workflow.py:48-66）；test_graph_workflow.py:83-115 断言节点集合与条件路由目标集一致，测试通过。 |
| A2 | passed | brief.md | A2: Scenario: 替换完整 WHEN 检查仓库 THEN `novagent.graph.workflow` 不再提供 `build_workflow` AND `novagent.graph.nodes` 不再提供 `verifier_route` AND `core/agent.py` 调用 `build_complex_workflow` AND `uv run pytest` 全部通过（离线）AND `uv sync` 无新依赖。 | grep 全仓仅剩负向断言引用（test_graph_workflow.py:119-120、test_graph_nodes.py:354），workflow.py:20 仅提供 build_complex_workflow；nodes.py 中 verifier_route 已删除（git diff 确认）；core/agent.py:9,34 调用 build_complex_workflow；本人重跑 uv run pytest -q 得 127 passed（6.37s，离线）；git status 显示 pyproject.toml/uv.lock 无改动且 Runtime 已验证 uv lock --check 退出码 0，无新依赖。 |
| A3 | passed | brief.md | A3: Scenario: compressor 占位 WHEN 调用 `context_compressor_node(state)` THEN 返回恰 `{"context_should_compress": False}` AND 不修改传入 state AND 不调用模型对话与 `create_model`、无网络、不写文件。 | nodes.py:549-555 context_compressor_node 仅返回 {"context_should_compress": False}，函数体无模型调用、无 create_model、无网络/文件操作、不触碰传入 state；test_context_monitor.py:188-196 以 _forbidden_create_model monkeypatch + state 快照比对验证纯函数性，测试通过。 |
| A4 | passed | brief.md | A4: Scenario: compressor 路由 WHEN 调用 `context_compressor_route` THEN `context_next_node="planner"` → `"planner"` AND `="verifier"` → `"verifier"` AND `="final"` → `"final"` AND 缺失 → `"verifier"`。 | nodes.py:558-560 为 state.get("context_next_node") or DEFAULT_CONTEXT_NEXT_NODE（="verifier"，nodes.py:33），符合 brief D5 空值回退语义；test_context_monitor.py:199-212 覆盖 planner/verifier/final 透传与缺失回退四取值，测试通过。 |
| A5 | passed | brief.md | A5: Scenario: monitor 路由预算耗尽 WHEN `passed` 假 AND `attempts >= max_attempts` THEN 返回 `"final"`（即使 `context_should_compress` 为真）。 | nodes.py:541-543 在 passed 判断之后、should_compress 判断之前插入 attempts >= max_attempts（缺省 3，nodes.py:31）→ "final"；test_context_monitor.py:146-157 在 passed 假、attempts=3>=max_attempts=3 且 context_should_compress=True 时断言返回 "final"，测试通过。 |
| A6 | passed | brief.md | A6: Scenario: monitor 路由优先级保持 WHEN 调用 `context_monitor_route` THEN `passed=True` → `"final"`（即使应压缩或预算耗尽）AND `passed` 假 + 预算未尽 + `should_compress=True` → `"context_compressor"` AND `passed` 假 + 预算未尽 + 未压缩 → `context_next_node` 透传（缺失默认 `"verifier"`）。 | nodes.py:539-546 优先级依次为 passed→final、预算耗尽→final、should_compress→context_compressor、否则 context_next_node 透传（缺失 "verifier"）；test_context_monitor.py:121-185 分别断言 passed=True 压过预算与压缩（attempts=5>3）、预算未尽+压缩→context_compressor（attempts=2<3）、未压缩→透传 planner/缺失回退 verifier，测试通过。 |
| A7 | passed | brief.md | A7: Scenario: planner 上游设置 WHEN `planner_node` 完成返回 THEN 更新 dict 含 `context_next_node="verifier"`。 | nodes.py:77-78 将 updates 初始化为 {"context_next_node": "verifier"} 且 nodes.py:290 恒返回该 dict，故每次 planner_node 返回必含该键；test_graph_nodes.py:147 与 326（update == {"context_next_node": "verifier"}）断言成立，测试通过。 |
| A8 | passed | brief.md | A8: Scenario: verifier 上游设置 WHEN `verifier_node` 判定失败且 `attempts < max_attempts` THEN 更新 dict 含 `context_next_node="planner"` AND 判定通过时更新 dict 不含该键。 | nodes.py:366-368 仅在 not passed 且 attempts < max_attempts 时写入 context_next_node="planner"；test_graph_nodes.py:384-401（失败且 attempts 自增后 1<3 → 含 "planner"）、378（通过时键不存在）、404-420（attempts=2 自增到 3 预算耗尽时键不存在）断言成立，测试通过。 |
| A9 | passed | brief.md | A9: Scenario: 成功端到端 WHEN 离线 FakeModel 驱动 `build_complex_workflow(model=fake)` 成功路径（planner 发布计划→verifier 通过）THEN 执行序列为 planner→context_monitor→verifier→context_monitor→final AND `final_answer` 以 `"Task completed"` 开头 AND planner 协调事件仍带 `node="planner"` 进入 custom 流。 | test_graph_workflow.py:170-190 断言 updates 序列恰为 planner→context_monitor→verifier→context_monitor→final；final_node 格式（nodes.py:489）保证 final_answer 以 "Task completed" 开头，test_agent_loop.py:129 显式断言 startswith("Task completed")；planner stream writer 桥接未回归：workflow.py:32-38 图内 get_stream_writer 包装补 "node": "planner"，test_agent_loop.py:100-109 断言 custom 流事件带 node="planner" 且含 handoff，测试通过。 |
| A10 | passed | brief.md | A10: Scenario: 失败重试端到端 WHEN verifier 首轮判定失败（预算未尽）THEN 图回到 planner 修订并再次 verifier，最终通过进入 final AND 全程不抛 `GraphRecursionError`。 | test_graph_workflow.py:193-216 verifier 首轮失败（FAIL_JSON）后经 context_monitor 路由回 planner（context_next_node="planner"），修订消息含 "tests broke"，attempts=2 最终通过，graph.invoke 全程无 GraphRecursionError；test_agent_loop.py:135-167 断言两次 planner node_output，测试通过。 |
| A11 | passed | brief.md | A11: Scenario: 预算耗尽端到端 WHEN `max_attempts=1` 且 verifier 判定失败 THEN 经 context_monitor 进入 final AND `final_answer` 含 `"Task failed"`。 | test_graph_workflow.py:219-240 max_attempts=1 且 verifier 失败时 updates 序列仍为 planner→context_monitor→verifier→context_monitor→final（预算耗尽由第二个 monitor 路由承担）；test_agent_loop.py:170-193 断言 final_answer 以 "Task failed" 开头且含 "tests broke"，测试通过。 |
| A12 | passed | brief.md | A12: Scenario: 压缩分支端到端 WHEN 注入极低 `context_token_limit`（如 1）使 `context_should_compress=True` THEN planner→context_monitor→context_compressor→（`context_next_node="verifier"`）→verifier 正常继续 AND compressor 执行后 state 的 `context_should_compress` 为 False。 | test_graph_workflow.py:243-276 注入 context_token_limit=1 触发压缩，updates 序列恰为 planner→context_monitor→context_compressor→verifier→context_monitor→final 且 compressor 更新恰 {"context_should_compress": False}（state 标记被清除）；compressor 后经 context_compressor_route 按 planner 预设的 context_next_node="verifier" 回 verifier 正常继续，测试通过。 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv lock --check 锁一致（无新依赖） | lock --check | . | passed | 0 | 67 ms |
| uv run pytest 全量离线测试 | run pytest -q | . | passed | 0 | 8043 ms |
| uv run novagent --help CLI 冒烟 | run novagent --help | . | passed | 0 | 2667 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

- core/agent.py:1 与 19 仍有改动前遗留的陈旧 docstring（"stage2 LangGraph 工作流"、"planner→actor→verifier"），line 40 setdefault("node", "actor") 回退分支在新图中为死代码（planner writer 恒补 node="planner"）；均属交接说明中声明的范围外既有文案，不影响行为。
- 大 max_attempts 下理论上可能触及 LangGraph 默认 recursion_limit=25：每轮 planner→monitor→verifier→monitor 约 4 个超步（含持续压缩约 5 个），无压缩 max_attempts>=7 或持续压缩 max_attempts>=5 时存在 GraphRecursionError 风险（默认 3 不受影响），与 Builder known_limits 一致。
- 占位压缩器不改变 token 估算，后续 monitor 每轮会重新置 context_should_compress=True，verifier 失败且预算未尽时 compressor 节点会逐轮重复执行；因 attempts 单调递增且清标记设计保证最终终止，行为无害，但真实压缩 change 落地时需注意。

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 0 | recovery | — | Native Shape artifacts changed | 2026-09-11T04:32:07.743Z |
| 2 | 1 | 1 | pass | — | 本轮实现与 brief/spec 高度一致：build_complex_workflow 五节点图、条件边映射逐字匹配四/三目标集，monitor 路由优先级（passed＞预算耗尽＞should_compress＞透传）在 nodes.py:539-546 正确落地，compressor 占位为纯函数，planner/verifier 上游设置按约定写入 context_next_node，verifier_route 与 build_workflow 已彻底移除且无残留引用。planner stream writer 桥接（custom 流 node="planner"）未回归。本人独立重跑 uv run pytest -q 得 127 passed，A1–A12 均有源码行号与测试断言双重证据支持。仅存在三项非阻塞风险：agent.py 遗留陈旧文案（范围外）、大 max_attempts 的递归上限理论风险、占位压缩器逐轮重复触发的无害行为。 | 2026-09-11T04:40:11.769Z |



## 结论

本轮实现与 brief/spec 高度一致：build_complex_workflow 五节点图、条件边映射逐字匹配四/三目标集，monitor 路由优先级（passed＞预算耗尽＞should_compress＞透传）在 nodes.py:539-546 正确落地，compressor 占位为纯函数，planner/verifier 上游设置按约定写入 context_next_node，verifier_route 与 build_workflow 已彻底移除且无残留引用。planner stream writer 桥接（custom 流 node="planner"）未回归。本人独立重跑 uv run pytest -q 得 127 passed，A1–A12 均有源码行号与测试断言双重证据支持。仅存在三项非阻塞风险：agent.py 遗留陈旧文案（范围外）、大 max_attempts 的递归上限理论风险、占位压缩器逐轮重复触发的无害行为。
