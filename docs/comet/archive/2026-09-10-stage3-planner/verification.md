---
generated_from_state_version: 13
---

# 验证

## 当前结果

- 结果: **已归档**
- 验证情况: **已完成检查，验证结果已确认**
- 目标周期: 3
- 迭代: 1
- 验证器尝试次数: 1
- 完成时间: 2026-09-10T19:05:04.240Z
- 摘要: 13 项验收全部通过：提示词逐字一致、planner 恰 3 工具与手写 ReAct 循环、委托语义（handoff 先行、状态合并、model 透传）、三节点拓扑、离线端到端与 verifier 4 工具绑定均与 brief/规格吻合，Runtime 四项命令检查全绿且 registry.py/CLI/core.agent 未改。仅有测试覆盖粒度层面的等价性说明，不构成失败项。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: stage3 提示词与导入 WHEN 导入 `novagent.prompts.stage3` THEN `PLANNER_PROMPT` 以 "You are the planner/supervisor node in novagent stage 3." 开头、含 "TodoWriteTool"、"CallSearchAgentTool"、"CallCodeAgentTool"、"Always call TodoWriteTool before delegating new work." 且以 "End with a concise supervisor summary after the needed specialist calls." 结尾 AND `novagent.graph.nodes.PLANNER_PROMPT` 与 stage3 常量为同一对象 AND `novagent.prompts.stage2` 不再有 `PLANNER_PROMPT`/`ACTOR_PROMPT`/`VERIFIER_PROMPT` 属性、仍有 `FINAL_PROMPT`。 | stage3.py PLANNER_PROMPT 与规格原文逐行一致（开头句/三工具名/Always 句/结尾句齐全，尾部换行为惯例）；nodes 以 from-import 持有同一对象且有 is 断言；stage2 仅余 FINAL_PROMPT 并有属性缺失断言。 |
| A2 | passed | brief.md | A12: Scenario: verifier 提示词与工具集 WHEN 导入 `novagent.prompts.stage3` THEN `VERIFIER_PROMPT` 以 "You are verifier, a model-based reviewer node." 开头、含 "NotepadReadTool"、"search the web"、"Run the provided verification commands when they are relevant." 且以 "an empty string when passed" 结尾 AND `novagent.graph.nodes.VERIFIER_PROMPT` 与 stage3 常量为同一对象 AND `verifier_node` 绑定工具名序列恰为 `["read_file", "grep", "bash", "web_search"]`。 | nodes.py:198-203 恰绑定 todo_write/call_search_agent/call_code_agent，test_planner_binds_three_tools 精确断言名字序列。 |
| A3 | passed | brief.md | A2: Scenario: planner 工具绑定 WHEN 注入 FakeModel 调用 `planner_node` THEN FakeModel 绑定的工具名序列恰为 `["todo_write", "call_search_agent", "call_code_agent"]`。 | handoff 事件先于受托内部事件（测试断言索引先后）、research_notes 空行追加、sources 按 url 去重保序、handoffs 恰一条、node=planner 标注经 workflow 桥接断言、model 透传与合并视图已实现。 |
| A4 | passed | brief.md | A3: Scenario: 委托搜索 WHEN FakeModel 依次返回 `todo_write` 计划、`call_search_agent`（注入 fake TavilyClient 返回带 title/url 的结果）、纯文本结束 THEN 返回更新含计划四字段、`research_notes`（agent summary）、`sources`（`SourceItem` 列表，url/title/content/score 且按 url 去重保序）、`agent_handoffs` 恰含一条 `{"from_agent": "planner", "to_agent": "searchAgent", "instruction", "result"}` AND 事件序列中 `handoff` 事件先于受托 agent 的内部事件 AND 全程事件带 `node="planner"`（经 writer 收集断言）。 | 受托循环真实写文件、todo_update 迁移至 completed（起点 pending 与验收所述 in_progress 走同一无条件覆盖路径，属等价）、todos/code_agent_summary/agent_handoffs/messages 并入均被精确断言。 |
| A5 | passed | brief.md | A4: Scenario: 委托实现 WHEN FakeModel 依次返回 `todo_write`、`call_code_agent`（state 含 runtime 指向临时 workspace 与 todos）、纯文本 THEN 受托循环真实写文件并迁移 todo（in_progress→completed）AND 返回更新 `todos` 为委托后状态、`code_agent_summary` 为 agent summary、`agent_handoffs` 含 to `codeAgent` 记录、`messages` 并入委托新增 AIMessage/ToolMessage。 | SourceItem/AgentHandoff 均 total=False 且四字段精确，NovGraphState 含 research_notes/sources/agent_handoffs/code_agent_summary，test_graph_state.py 逐一断言。 |
| A6 | passed | brief.md | A5: Scenario: 数据结构与状态字段 WHEN 导入 `novagent.graph.state` THEN 存在 `SourceItem`（url/title/content/score）与 `AgentHandoff`（from_agent/to_agent/instruction/result）且均为 `total=False` AND `NovGraphState` 含 `research_notes`/`sources`/`agent_handoffs`/`code_agent_summary` 字段。 | 编译图节点恰为 planner/verifier/final（__start__ 为框架注入伪节点）加 START→planner、planner→verifier、final→END；verifier 条件映射 {final, planner} 由源码与失败回环/预算耗尽行为测试共同验证。 |
| A7 | passed | brief.md | A6: Scenario: 图拓扑 WHEN 调用 `build_workflow()` THEN 编译图节点集合恰为 `{"planner", "verifier", "final"}` AND `START` 出边指向 planner AND planner 出边指向 verifier AND verifier 条件边路由 `{"final", "planner"}` AND final 出边指向 END。 | 端到端恰 6 次模型调用、passed is True、成功格式 final_answer、code_agent_summary/agent_handoffs 写入、result.txt 落盘；e2e 中 todo 完成经 verifier 归一化达成（显式迁移由 A4 单测覆盖），THEN 结果全部满足。 |
| A8 | passed | brief.md | A7: Scenario: 离线端到端 WHEN 初始 state（task、runtime、max_attempts=3、verification command 为 `"<python>" -c "print('ok')"`）注入 FakeModel（planner 轮 1 `todo_write`、轮 2 `call_code_agent` 写 `result.txt` 并完成 todo、轮 3 纯文本；verifier 输出 `passed=true` JSON）并 `build_workflow(model=fake).invoke(state)` THEN 最终 `passed is True`、`final_answer` 成功格式、`code_agent_summary` 与 `agent_handoffs` 已写入、workspace 出现 `result.txt`。 | 修订分支 HumanMessage 含 Last error 与 Failed verifications 明细，测试断言 last_error 与失败命令均在消息中。 |
| A9 | passed | brief.md | A8: Scenario: 修订路径 WHEN 构造 `todos` 非空且 `last_error` 非空的 state 调用 `planner_node` THEN 发给模型的 HumanMessage 包含 `last_error` 与失败验证信息。 | graph.nodes 无 actor_node 属性、图中无 actor 节点且被测试断言；cli 渲染分支与 core/agent.py setdefault 为 spec 声明保留项，不算残留。 |
| A10 | passed | brief.md | A9: Scenario: actor 移除 WHEN 导入 `novagent.graph.nodes` 与 `novagent.graph.workflow` THEN 无 `actor_node` 属性、`build_workflow()` 图中无 `"actor"` 节点。 | 首轮纯文本恰 1 次调用且返回空更新，max_loops=2 时恰 2 次调用，与 nodes.py 手写 ReAct 的 break/range 实现一致。 |
| A11 | passed | brief.md | A10: Scenario: 循环边界 WHEN FakeModel 第一轮即纯文本 THEN 模型只被调用 1 次 AND WHEN 每轮都返回 tool_call 且 `max_loops=2` THEN 恰调用 2 次。 | Runtime 登记 uv sync/uv lock --check/pytest（90 passed）/novagent --help 全部 exit 0，且两提交未触及 pyproject.toml/uv.lock。 |
| A12 | passed | brief.md | A11: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且无新依赖、lock 一致 AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0。 | VERIFIER_PROMPT 与原文逐行一致（含跨行 search the web 与结尾句），nodes 持同一对象，绑定序列恰 [read_file, grep, bash, web_search] 被单测与 e2e 双重断言。 |
| A13 | passed | brief.md | A13: Scenario: verifier 绑定与降级 WHEN 注入 FakeModel 调用 `verifier_node`（state 含 runtime 与 verification_commands）THEN 绑定工具名序列恰为 `["read_file", "grep", "bash", "web_search"]` AND HumanMessage 含计划、验收标准与验证命令 AND 全部测试离线（web_search 在测试环境不发起真实请求）。 | 绑定 4 工具被精确断言，HumanMessage 模板含计划/验收标准/验证命令三段（源码核实），web_search 离线由 fake TavilyClient fixture 与离线 pytest 保证，registry.py 不在提交 diff 中确认未改。 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv sync 依赖安装 | sync | . | passed | 0 | 70 ms |
| uv lock --check 锁一致 | lock --check | . | passed | 0 | 56 ms |
| uv run pytest 全量离线测试 | run pytest -q | . | passed | 0 | 7980 ms |
| uv run novagent --help 退出码 0 | run novagent --help | . | passed | 0 | 2562 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

- 测试对 PLANNER_PROMPT 的 contains/endswith（TodoWriteTool、CallCodeAgentTool、Always 句、结尾句）未逐一断言，本次由 Verifier 直接比对源码与规格引用确认一致；后续若改动提示词，现有测试可能无法拦截全部字面变化
- A13 的 HumanMessage 断言仅覆盖验收标准段（done），计划摘要与验证命令段未显式断言（模板结构已核实包含）
- A7 端到端脚本中 codeAgent 未显式调用 todo_update，todo 完成依赖 verifier 归一化；显式 in_progress→completed 迁移仅由 A4 单测覆盖
- cli/app.py 模块 docstring 仍写 planner→actor→verifier 工作流，属陈旧文案；CLI 为本 change 零修改范围，不影响验收

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 0 | recovery | — | Native Shape artifacts changed | 2026-09-10T18:07:08.642Z |
| 2 | 0 | 0 | recovery | — | Native confirmed acceptance criteria changed | 2026-09-10T18:37:54.801Z |
| 3 | 1 | 1 | pass | — | 13 项验收全部通过：提示词逐字一致、planner 恰 3 工具与手写 ReAct 循环、委托语义（handoff 先行、状态合并、model 透传）、三节点拓扑、离线端到端与 verifier 4 工具绑定均与 brief/规格吻合，Runtime 四项命令检查全绿且 registry.py/CLI/core.agent 未改。仅有测试覆盖粒度层面的等价性说明，不构成失败项。 | 2026-09-10T19:05:04.240Z |



## 结论

13 项验收全部通过：提示词逐字一致、planner 恰 3 工具与手写 ReAct 循环、委托语义（handoff 先行、状态合并、model 透传）、三节点拓扑、离线端到端与 verifier 4 工具绑定均与 brief/规格吻合，Runtime 四项命令检查全绿且 registry.py/CLI/core.agent 未改。仅有测试覆盖粒度层面的等价性说明，不构成失败项。
