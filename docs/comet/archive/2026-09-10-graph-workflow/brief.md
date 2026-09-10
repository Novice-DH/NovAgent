# 目标

在 `src/novagent/graph/workflow.py` 中构建可执行的 LangGraph 工作流：`build_workflow()` 组装 `planner → actor → verifier` 主循环（verifier 后按 `verifier_route` 条件边回到 planner 或进入 final），`final_node` 把 passed/failed 状态格式化为 `final_answer` 文本。同时在 `src/novagent/prompts/stage2.py` 中集中提供 LangGraph 工作流（stage2）的四个系统提示：`PLANNER_PROMPT`、`ACTOR_PROMPT`、`VERIFIER_PROMPT`、`FINAL_PROMPT`，并让 `nodes.py` 改为从这里导入，消除重复定义。

# 范围

- 新增 `src/novagent/prompts/__init__.py`（空包文件）与 `src/novagent/prompts/stage2.py`：
  - `PLANNER_PROMPT`：产出计划的系统提示，要求通过 `todo_write` 工具提交计划（延续现 `nodes.py` 中定义的职责与措辞要点）；
  - `ACTOR_PROMPT`：actor 系统提示，以 "You are the actor node in novagent's LangGraph workflow." 开头，约定按当前计划逐步执行工具（workspace 内、用 `todo_update` 汇报步骤进度、结束时给出摘要）；
  - `VERIFIER_PROMPT`：verifier 系统提示，只读核查并要求最终回复单个 JSON `{passed, reason, checks, recommended_next_instruction}`（延续现 `nodes.py` 定义）；
  - `FINAL_PROMPT`：最终总结提示（说明输入为任务、计划与验证结果，输出为面向用户的最终总结）；本 change 中仅作为常量提供并注明预留用途。
- `src/novagent/graph/nodes.py`：
  - `PLANNER_PROMPT`、`VERIFIER_PROMPT` 改为从 `novagent.prompts.stage2` 导入（本地不再定义）；`actor_node` 的系统提示改用 `stage2.ACTOR_PROMPT`（按计划执行的 stage2 版本；`core/agent.py` 及其 `ACTOR_PROMPT`/`stream_agent_events` 保持不动）；
  - 新增 `final_node(state) -> dict`：确定性节点（不调用 LLM）——`passed` 为真时把 `final_answer` 格式化为成功文本（含 attempts 与 verifier 原因），失败时格式化为失败文本（含 attempts 与 `last_error`）。
- 新增 `src/novagent/graph/workflow.py`：
  - `build_workflow(*, model=None)`：`StateGraph(NovGraphState)`，注册 `"planner"`、`"actor"`、`"verifier"`、`"final"` 四个节点（前三个经 `functools.partial` 绑定注入的 `model`，None 时节点内部 `create_model()`）；边：`START → planner → actor → verifier`；`verifier` 经 `verifier_route` 条件边路由 `{"final": "final", "planner": "planner"}`；`final → END`；返回 `graph.compile()`。
- 新增 `tests/test_graph_workflow.py`：
  - 图结构：编译成功、节点集合恰为四节点、START 首边指向 planner；
  - 离线端到端（注入 FakeModel）：一次通过路径（planner→actor→verifier→final，passed=True、final_answer 成功格式、todos 全 completed）；
  - 失败重试路径（验证命令必失败 → verifier 判失败 → 回 planner 修订（HumanMessage 含 last_error）→ 第二轮通过，attempts==2）；
  - `final_node` 通过/失败两种格式化；
  - prompts 常量：四常量非空、内容特征、`nodes.py` 引用与 `stage2` 同一对象。
- 更新 `tests/test_graph_nodes.py`：actor 系统提示断言改为 `stage2.ACTOR_PROMPT`。

# 非目标

- 不改变 `planner_node`/`actor_node`/`verifier_node`/`verifier_route` 的既有语义（仅系统提示来源迁移到 stage2，ACTOR_PROMPT 换为 stage2 版本属本 change 需求）。
- 不修改 `core/agent.py`（`ACTOR_PROMPT`、`stream_agent_events`）与 CLI 行为；stage1 手写循环继续使用 core 的 ACTOR_PROMPT。
- 不提供工作流的 CLI 入口或对外运行命令（图的使用方留给后续 change）。
- 不实现 checkpointing、中断恢复、人机协同、流式 UI 等执行能力。
- `FINAL_PROMPT` 不接入 LLM 调用（final_node 保持确定性），仅按用户要求提供常量。

# 验收示例

- A1: Scenario: 组装四节点工作流 WHEN 调用 `build_workflow()` THEN 返回已编译图 AND 图节点集合恰为 `{"planner", "actor", "verifier", "final"}` AND 从 START 出发的边指向 `"planner"` AND `"final"` 的出边指向 END。
- A2: Scenario: 离线端到端一次通过 WHEN 构造初始状态（task、runtime 指向临时 workspace、max_attempts=3），注入 FakeModel 依次返回（planner 调 `todo_write` 提交计划，验证命令为 `"<python>" -c "print('ok')"`；actor 第一轮 `write_file` 写 `result.txt`、第二轮纯文本结束；verifier 输出 `passed=true` 的 JSON）并调用 `build_workflow(model=fake).invoke(state)` THEN 最终状态 `passed is True`、`final_answer` 为成功格式文本（含 "completed" 与 attempts 数）、todos 全部 `completed`、`attempts == 1` AND FakeModel 共被调用 4 次（1+2+1，证明路径 planner→actor→verifier→final）AND workspace 出现 `result.txt`。
- A3: Scenario: 失败后回 planner 修订再通过 WHEN FakeModel 依次返回（第一轮 planner 提交计划，验证命令为 `"<python>" -c "raise SystemExit(1)"`；actor 纯文本结束；verifier 输出 `passed=false` 且 reason 为 "tests broke" 的 JSON；第二轮 planner 提交修订计划，验证命令为 `"<python>" -c "print('ok')"`；actor 纯文本结束；verifier 输出 `passed=true` 的 JSON）invoke 同一图 THEN 最终 `passed is True`、`attempts == 2` AND 第二轮 planner 收到的 HumanMessage 包含 "tests broke" AND FakeModel 共被调用 6 次（2+1+1 + 1+1）。
- A4: Scenario: final_node 格式化成败 WHEN 以 `{"passed": True, "attempts": 1, "final_answer": "all good"}` 调用 `final_node` THEN 返回更新 `final_answer` 含 "completed"、"1" 与 "all good" AND 以 `{"passed": False, "attempts": 3, "last_error": "boom"}` 调用 THEN 返回更新 `final_answer` 含 "failed"、"3" 与 "boom" AND 两种情况均不包含 `passed` 键（不翻转判定）。
- A5: Scenario: stage2 提示词与引用一致 WHEN 导入 `novagent.prompts.stage2` THEN 四个常量均非空字符串 AND `PLANNER_PROMPT` 含 "todo_write" AND `ACTOR_PROMPT` 以 "You are the actor node in novagent's LangGraph workflow." 开头 AND `VERIFIER_PROMPT` 含 `"passed"` AND `FINAL_PROMPT` 非空 AND `novagent.graph.nodes` 模块级名字 `PLANNER_PROMPT`、`VERIFIER_PROMPT`、`ACTOR_PROMPT` 与 stage2 的对应常量 `is` 同一对象。
- A6: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且 `uv.lock` 一致（无新依赖）AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0 AND `core.agent.ACTOR_PROMPT` 原文不变（`stream_agent_events` 首轮 SystemMessage 仍为其自身）。

# 约束与不变量

- `build_workflow()` 无参调用行为不变于用户伪代码（`model` 为 keyword-only 可选参数，默认 None 时节点内部 `create_model()`）。
- 图拓扑恰为：`START → planner → actor → verifier`；verifier 条件边 `final→"final"`、`planner→"planner"`；`final → END`。
- `final_node` 不调用 LLM、不修改 `passed`，只产出 `final_answer` 文本。
- stage2 常量为 stage2 工作流的唯一权威来源；`nodes.py` 不再本地定义 `PLANNER_PROMPT`/`VERIFIER_PROMPT`，`actor_node` 使用 `stage2.ACTOR_PROMPT`。
- `core/agent.py` 一字不改；stage1（`stream_agent_events`）与 stage2（LangGraph 工作流）的 ACTOR_PROMPT 各自独立。
- 全部测试离线（FakeModel / `sys.executable` 本地命令），兼容 Python >= 3.10。

# 决策

- D1 `build_workflow` 增加 keyword-only `model=None`：用户伪代码签名无参，但离线端到端测试必须注入 FakeModel；None 时完全等价于伪代码行为（节点内部 `create_model()`），无参调用不变。
- D2 `final_node` 定义在 `nodes.py`：节点实现集中一处，`workflow.py` 只负责组装与连线；final 不需要 model 注入。
- D3 `final_node` 为确定性格式化节点，`FINAL_PROMPT` 仅作为常量提供：用户明确"final_node 只是把 passed/failed 状态格式化"，同时明确要求写 FINAL_PROMPT（总结最终结果）；两者并存——FINAL_PROMPT 注明预留给后续 LLM 总结扩展，本 change 不接线（避免确定性节点偷偷引入网络调用）。
- D4 `prompts/stage2.py` 为 stage2 工作流提示词唯一权威来源：`nodes.py` 改为导入而非本地定义；`ACTOR_PROMPT` 提供强调"按计划执行 + todo_update 汇报进度"的 stage2 版本；`core/agent.py` 的 stage1 ACTOR_PROMPT 保持原样，两套工作流各用各的。
- D5 planner/actor/verifier 经 `functools.partial` 绑定 model 后注册：LangGraph 节点只接受 `(state)` 单参 callable，partial 保持节点签名兼容且测试可注入。

# 待解决问题

（无未解决项）

# 验证预期

- `uv sync` 成功且 `uv.lock` 一致（无新依赖）。
- `uv run pytest` 全部通过（含新增 `tests/test_graph_workflow.py`，离线）。
- `uv run novagent --help` 退出码 0（现有行为不受影响）。
