# 目标

在 `src/novagent/graph/workflow.py` 中以 `build_complex_workflow` 直接替换 `build_workflow`：五节点图 planner → context_monitor →（条件路由）→ context_compressor / verifier / planner / final，且 verifier → context_monitor；新增 `context_compressor_node` 占位节点与 `context_compressor_route`；planner/verifier 落地 `context_next_node` 上游设置；`context_monitor_route` 补充预算耗尽判断。`core/agent.py` 切换到新构建函数。

1. `build_complex_workflow(*, model=None)`（唯一构建函数）：
   - 节点注册：`"planner"`（图内包装：`get_stream_writer()` + 事件补 `"node": "planner"`，`partial` 绑定注入 `model`）、`"context_monitor"`（`partial` 绑定注入 `model`）、`"context_compressor"`（直接注册）、`"verifier"`（`partial` 绑定注入 `model`）、`"final"`；
   - 边：`START → "planner"`、`"planner" → "context_monitor"`、`"verifier" → "context_monitor"`、`"final" → END`；
   - `context_monitor` 条件边（`context_monitor_route`）：`{"context_compressor", "verifier", "planner", "final"}` 四目标；
   - `context_compressor` 条件边（`context_compressor_route`）：`{"verifier", "planner", "final"}` 三目标。
2. `context_compressor_node(state) -> dict`：占位节点，返回恰 `{"context_should_compress": False}`；确定性、不接模型、无副作用；真实压缩逻辑属后续 change。
3. `context_compressor_route(state) -> str`：`state.get("context_next_node") or "verifier"`（用户给定 `state.get("context_next_node", "verifier")` 语义；空值回退风格与 monitor 一致）。
4. `context_monitor_route` 增强：在 `passed → "final"` 之后、压缩判定之前插入预算耗尽判断（`attempts >= max_attempts`（缺省 3）`→ "final"`），吸收被移除的 `verifier_route` 终止语义。
5. 上游设置：`planner_node` 每次返回更新恒含 `context_next_node="verifier"`；`verifier_node` 在未通过且 `attempts < max_attempts` 时返回更新含 `context_next_node="planner"`（通过或预算耗尽时不设置该键）。
6. 移除 `build_workflow` 与 `verifier_route`；`core/agent.py` 改用 `build_complex_workflow`。

# 范围

- 修改 `src/novagent/graph/workflow.py`：删除 `build_workflow`，新增 `build_complex_workflow(*, model=None)`（结构如上）；planner 的 stream writer 图内包装与 `partial(model)` 注入模式保持不变。
- 修改 `src/novagent/graph/nodes.py`：
  - 新增 `context_compressor_node(state) -> dict`（占位，返回恰 `{"context_should_compress": False}`）；
  - 新增 `context_compressor_route(state) -> str`；
  - `context_monitor_route` 插入预算耗尽 → `"final"`；
  - `planner_node` 返回更新恒含 `context_next_node="verifier"`；
  - `verifier_node` 失败且预算未尽时返回更新含 `context_next_node="planner"`；
  - 删除 `verifier_route`。
- 修改 `src/novagent/core/agent.py`：导入并调用 `build_complex_workflow`（模块 docstring 中的路由描述同步更新）；`context_monitor`/`context_compressor` 的 updates 无对应解析分支、不产生事件（现状自然行为，不加分支）。
- 测试：
  - `tests/test_graph_workflow.py` 更新：结构断言改为五节点与四/三目标条件边；端到端改经 `build_complex_workflow`；
  - `tests/test_graph_nodes.py` 更新：移除 `verifier_route` 断言；新增 planner/verifier 的 `context_next_node` 断言、compressor 节点与路由断言；
  - `tests/test_context_monitor.py` 扩展：新增 monitor 路由预算耗尽 → `"final"` 覆盖（含优先级位置）；
  - `tests/test_agent_loop.py` 适配：端到端语义保持（通过路径、失败回环、预算耗尽），改由新图驱动。
- 更新完整目标规格 `specs/novagent/spec.md`。

# 非目标

- 不实现真实压缩逻辑（压缩摘要生成、`messages` 裁剪、`context_summary`/`compression_events`/`history_summary` 写入）——属后续 change。
- 不修改 `NovGraphState` schema 与 `novagent.graph.memory`。
- 不新增运行依赖。
- 不修改 CLI 渲染：`context_monitor`/`context_compressor` 的 `node_output` 不产生统一事件、不被 CLI 渲染。

# 验收示例

- A1: Scenario: 图结构与编译 WHEN 调用 `build_complex_workflow()` THEN 编译成功 AND 节点集合恰为 `{"planner", "context_monitor", "context_compressor", "verifier", "final"}` AND 边含 `START→planner`、`planner→context_monitor`、`verifier→context_monitor`、`final→END` AND `context_monitor` 条件路由目标恰为 `{"context_compressor", "verifier", "planner", "final"}` AND `context_compressor` 条件路由目标恰为 `{"verifier", "planner", "final"}`。
- A2: Scenario: 替换完整 WHEN 检查仓库 THEN `novagent.graph.workflow` 不再提供 `build_workflow` AND `novagent.graph.nodes` 不再提供 `verifier_route` AND `core/agent.py` 调用 `build_complex_workflow` AND `uv run pytest` 全部通过（离线）AND `uv sync` 无新依赖。
- A3: Scenario: compressor 占位 WHEN 调用 `context_compressor_node(state)` THEN 返回恰 `{"context_should_compress": False}` AND 不修改传入 state AND 不调用模型对话与 `create_model`、无网络、不写文件。
- A4: Scenario: compressor 路由 WHEN 调用 `context_compressor_route` THEN `context_next_node="planner"` → `"planner"` AND `="verifier"` → `"verifier"` AND `="final"` → `"final"` AND 缺失 → `"verifier"`。
- A5: Scenario: monitor 路由预算耗尽 WHEN `passed` 假 AND `attempts >= max_attempts` THEN 返回 `"final"`（即使 `context_should_compress` 为真）。
- A6: Scenario: monitor 路由优先级保持 WHEN 调用 `context_monitor_route` THEN `passed=True` → `"final"`（即使应压缩或预算耗尽）AND `passed` 假 + 预算未尽 + `should_compress=True` → `"context_compressor"` AND `passed` 假 + 预算未尽 + 未压缩 → `context_next_node` 透传（缺失默认 `"verifier"`）。
- A7: Scenario: planner 上游设置 WHEN `planner_node` 完成返回 THEN 更新 dict 含 `context_next_node="verifier"`。
- A8: Scenario: verifier 上游设置 WHEN `verifier_node` 判定失败且 `attempts < max_attempts` THEN 更新 dict 含 `context_next_node="planner"` AND 判定通过时更新 dict 不含该键。
- A9: Scenario: 成功端到端 WHEN 离线 FakeModel 驱动 `build_complex_workflow(model=fake)` 成功路径（planner 发布计划→verifier 通过）THEN 执行序列为 planner→context_monitor→verifier→context_monitor→final AND `final_answer` 以 `"Task completed"` 开头 AND planner 协调事件仍带 `node="planner"` 进入 custom 流。
- A10: Scenario: 失败重试端到端 WHEN verifier 首轮判定失败（预算未尽）THEN 图回到 planner 修订并再次 verifier，最终通过进入 final AND 全程不抛 `GraphRecursionError`。
- A11: Scenario: 预算耗尽端到端 WHEN `max_attempts=1` 且 verifier 判定失败 THEN 经 context_monitor 进入 final AND `final_answer` 含 `"Task failed"`。
- A12: Scenario: 压缩分支端到端 WHEN 注入极低 `context_token_limit`（如 1）使 `context_should_compress=True` THEN planner→context_monitor→context_compressor→（`context_next_node="verifier"`）→verifier 正常继续 AND compressor 执行后 state 的 `context_should_compress` 为 False。

# 约束与不变量

- 新图必须保持既有循环语义：通过 → final；预算耗尽 → final；失败且预算未尽 → planner 重试。
- 路由优先级固定：`passed` ＞ 预算耗尽 ＞ `should_compress` ＞ `context_next_node` 透传。
- `context_monitor`/`context_compressor` 条件边的映射键与用户给定结构逐字一致。
- `context_compressor_node` 为确定性占位节点：不调用模型对话（`invoke`）、不构造模型（不调用 `create_model`）、无网络、不写文件、不修改传入 state。
- planner 的 stream writer 图内包装与 `partial(model)` 注入模式保持；`model=None` 时全部节点离线可运行。
- 全部测试离线运行（FakeModel + 纯函数），不发起真实网络请求，兼容 Python >= 3.10。

# 决策

- D1 直接替换（用户选定）：`build_complex_workflow` 成为唯一构建函数，`build_workflow` 与 `verifier_route` 移除，`core/agent.py` 与测试同步切换；生产图立即走 monitor/compressor 循环。
- D2 上游设置一并落地（用户选定）：planner 规划后设 `"verifier"`，verifier 失败且预算未尽设 `"planner"`；不设置则失败后退化为 verifier 原地重试、丢失重新规划语义。monitor 透传与缺失回退 `"verifier"` 保持既有实现不变。
- D3 压缩器占位（用户选定）：仅返回 `{"context_should_compress": False}` 清除压缩标记，防止 compressor 分支在后续 monitor 轮次重复触发；真实压缩属后续 change（延续分层推进：数据层→监控→接线→压缩器）。
- D4 monitor 路由吸收预算判断：`verifier → context_monitor` 无条件边替代原 verifier 条件边后，预算耗尽终止语义必须由 `context_monitor_route` 承担，否则既有"预算耗尽 → final"行为回归（且失败路径在无上游设置时可能原地循环直至 `GraphRecursionError`）。
- D5 `context_compressor_route` 采用 `state.get("context_next_node") or "verifier"`：与 `context_monitor_node`/`_route` 的空值回退风格一致，等价覆盖用户给定默认值语义（`planner`/`verifier` 写入值恒非空）。
- D6 CLI 与统一事件流不感知新节点：`core/agent.py` 解析分支仅 planner/verifier/final，`context_monitor`/`context_compressor` 的 updates 自然跳过，不加渲染分支。

# 待解决问题

（无 `[blocking]` 项：图接入方式、上游设置、压缩器深度均已由用户确认。）

# 验证预期

- `uv sync` 成功且无新依赖、`uv.lock` 一致。
- `uv run pytest` 全部通过（离线，含更新后的 `test_graph_workflow.py`、`test_graph_nodes.py`、`test_context_monitor.py`、`test_agent_loop.py`）。
