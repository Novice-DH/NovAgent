# 目标

把 `src/novagent/core/agent.py` 的 `stream_agent_events` 从手写 ReAct 循环切换为驱动 LangGraph 工作流：调用 `build_workflow().stream(inputs, stream_mode=["updates", "custom"])`，把图事件解析为统一格式的事件流；更新 `src/novagent/cli/app.py`，新增 `--max-attempts` 选项（默认 3），并用节点徽标实时显示每个节点的输出：📋 Planner、🔧 Actor、✅/❌ Verifier、📝 Final。CLI 的默认执行路径由此完整走 planner→actor→verifier 闭环（失败自动回 planner 修订）。

# 范围

- `src/novagent/graph/workflow.py`：actor 节点改为图内包装——执行时调用 `langgraph.config.get_stream_writer()` 并作为 `on_event` 传给 `actor_node`，使 actor 的内部事件进入 LangGraph 的 custom 流（`actor_node` 本身的 `on_event` 接口与语义不变；`invoke()` 下 writer 静默丢弃，已探针验证）。
- `src/novagent/core/agent.py` 重写 `stream_agent_events`：
  - 新签名 `stream_agent_events(task, *, workspace, max_attempts=3, model=None)`（`max_loops` 移除，循环上限由图内部固定）；
  - 构造 `RuntimeState(workspace)`，`inputs = {"task": task, "runtime": state, "max_attempts": max_attempts}`，`build_workflow(model=model)` 后 `.stream(inputs, stream_mode=["updates", "custom"])`；
  - 解析 `(mode, payload)`：`custom` 流转发 actor 内部事件并补 `"node": "actor"`；`updates` 流把节点更新解析为 `{"type": "node_output", "node": ..., ...}` 事件——`planner`（含 `plan_summary`、`todos`、`acceptance_criteria`、`verification_commands`）、`verifier`（含 `passed`、`reason`、`verification_results`、`verification_checks`）、`final`（含 `final_answer`）；`actor` 的节点更新不重复产出（内部事件已实时转发）；
  - 保留模块导出语义：`ACTOR_PROMPT` 不再由本模块定义（stage1 常量随旧循环移除；CLI 与测试改用 `novagent.prompts.stage2`）。
- `src/novagent/cli/app.py`：
  - `run` 命令新增 `--max-attempts: int = 3`（校验 >= 1），透传给 `stream_agent_events`；
  - `_print_event` 按统一事件渲染：
    - `node_output` + `planner` → `📋 Planner` 行 + 计划摘要与 todos 列表；
    - `node=actor` 的 `ai_message`/`tool_call`/`tool_result` → 首次前打印 `🔧 Actor` 标头，随后沿用现有详情渲染；
    - `node_output` + `verifier` → `✅ Verifier`（通过）或 `❌ Verifier`（失败）+ reason + 每条验证命令的退出码结果；
    - `node_output` + `final` → `📝 Final` + 最终回答文本；
    - `node="actor"` 的 `final_answer` 内部事件与 `node_output`+`actor` 忽略（内容已由其他事件覆盖）。
- 测试更新：
  - `tests/test_agent_loop.py` 按新事件语义重写（FakeModel 离线驱动整图）：通过路径事件顺序（planner node_output → actor 内部事件 → verifier node_output → final node_output）、custom 事件带 `node="actor"`、失败回环出现两次 planner node_output 且失败轮有 `❌`（failed verifier node_output）、`max_attempts=1` 时失败后直接进 final（planner 仅一次）、最终 `final_answer` 内容来自 final 节点；
  - `tests/test_cli.py`：fake 流改用统一事件格式并带节点徽标断言（📋/🔧/✅/📝）；fake 断言 `--max-attempts` 默认 3 与显式传值；`--help` 包含 `--max-attempts`。

# 非目标

- 不改变 `planner_node`/`actor_node`/`verifier_node`/`verifier_route`/`final_node`/`build_workflow` 的既有语义与签名（仅 actor 在 workflow.py 的注册包装中桥接 stream writer）。
- 不移除 `novagent.prompts.stage2` 的任何常量；`FINAL_PROMPT` 仍不接线。
- 不增加 checkpointing、并行节点、人机协同等能力。
- 不改变 `create_model` 的环境变量约定与错误信息。
- 不改 `tools/` 与 `graph/state.py`。

# 验收示例

- A1: Scenario: 通过路径的事件序列 WHEN 注入 FakeModel（planner 调 `todo_write` 提交计划、验证命令 `"<python>" -c "print('ok')"`；actor 第一轮 `write_file` 写文件、第二轮纯文本；verifier 输出 `passed=true` JSON）并以临时 workspace 调用 `stream_agent_events(task, workspace=ws, model=fake)` 收集全部事件 THEN 事件依次包含 `node_output`+planner（含 plan_summary 与 todos）、`node="actor"` 的 `ai_message`/`tool_call`/`tool_result`、`node_output`+verifier（passed 为 True）、`node_output`+final，且 `node_output`+final 的 `final_answer` 以 "Task completed" 开头 AND FakeModel 共被调用 4 次 AND 文件落盘。
- A2: Scenario: 失败回环产生两轮节点事件 WHEN FakeModel 依次为（planner 计划带必失败命令 `"<python>" -c "raise SystemExit(1)"`、actor 文本、verifier `passed=false` reason "tests broke"、planner 修订计划带通过命令、actor 文本、verifier `passed=true`）THEN 事件流恰好出现两次 `node_output`+planner AND 失败轮 `node_output`+verifier 的 `passed` 为 False 且 `reason == "tests broke"` AND 最终 `node_output`+final 的 `final_answer` 以 "Task completed" 开头 AND FakeModel 共被调用 6 次。
- A3: Scenario: max_attempts 预算耗尽直接收尾 WHEN FakeModel 提供一轮必失败计划（planner、actor、verifier `passed=false`）且 `stream_agent_events(..., max_attempts=1)` THEN 事件流只有一次 `node_output`+planner AND `node_output`+verifier 的 `passed` 为 False AND `node_output`+final 的 `final_answer` 以 "Task failed" 开头 AND FakeModel 共被调用 3 次（不再回 planner）。
- A4: Scenario: CLI 显示节点徽标与 --max-attempts WHEN 用统一事件格式的 fake 流（planner node_output、actor ai_message/tool_call/tool_result、verifier node_output passed=true、final node_output）monkeypatch 后以 CliRunner 运行 `run "demo task" --workspace <ws> --max-attempts 2` THEN 退出码 0 AND 输出依次包含 "📋 Planner"、"🔧 Actor"、"✅ Verifier"、"📝 Final" 与工具详情、最终回答 AND fake 记录到的 `max_attempts == 2` AND 不带选项运行时 fake 记录到 `max_attempts == 3` AND `--help` 包含 `--max-attempts`。
- A5: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且 `uv.lock` 一致（无新依赖）AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0 AND 缺 `OPENAI_API_KEY` 时 CLI 仍以退出码 1 与清晰错误退出。

# 约束与不变量

- 统一事件格式：每个事件为普通 dict，至少含 `type`；custom 转发事件与节点解析事件均带 `node` 字段（"actor"/"planner"/"verifier"/"final"）。
- `stream_agent_events` 保持生成器（逐事件实时产出）；`model=None` 时经 `build_workflow` 内部 `create_model()`，离线测试可注入。
- CLI 全部输出经 `rich.markup.escape` 转义用户/模型内容；验证命令行与结果逐条显示退出码。
- `planner_node`/`actor_node`/`verifier_node`/`final_node`/`verifier_route`/`build_workflow` 的函数签名与既有测试（`tests/test_graph_nodes.py`、`tests/test_graph_workflow.py`）不受影响。
- 全部测试离线（FakeModel / monkeypatch），兼容 Python >= 3.10。

# 决策

- D1 actor 事件经 `get_stream_writer()` 桥接进 custom 流：在 workflow.py 的 actor 注册包装内（图上下文中）获取 writer 作为 `on_event` 传给 `actor_node`；`actor_node` 接口不变，直接调用与 `invoke()` 场景不受影响（writer 静默丢弃，已探针验证）。
- D2 统一事件格式带 `type` + `node`：custom 转发事件补 `node="actor"`；`updates` 解析为 `type="node_output"` 事件，携带该节点的关键输出字段；`actor` 的节点更新不重复产出（其内部事件已实时转发，避免双重打印）。
- D3 `stream_agent_events` 新签名用 `max_attempts` 替换 `max_loops`：循环轮数上限已是图的内部细节（`DEFAULT_MAX_LOOPS`）；用户可见的新预算是验证重试次数 `max_attempts`（默认 3），与 `verifier_route` 的预算语义对齐。
- D4 CLI 忽略 `node="actor"` 的 `final_answer` 内部事件与 `node_output`+`actor`：其内容与 `🔧 Actor` 详情及最终 `📝 Final` 重复，避免误导性双重输出。
- D5 旧 stage1 常量随旧循环移除：`core.agent.ACTOR_PROMPT` 删除后，stage1 与 stage2 的提示词来源统一为 `novagent.prompts.stage2`；`tests/test_agent_loop.py` 按新事件语义重写而非保留双轨。

# 待解决问题

（无未解决项）

# 验证预期

- `uv sync` 成功且 `uv.lock` 一致（无新依赖）。
- `uv run pytest` 全部通过（重写后的 `tests/test_agent_loop.py`、更新的 `tests/test_cli.py` 及既有全部测试，离线）。
- `uv run novagent --help` 退出码 0 且包含 `--max-attempts`。
