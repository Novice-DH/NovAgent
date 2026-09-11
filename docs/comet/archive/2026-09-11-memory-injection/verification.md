---
generated_from_state_version: 10
---

# 验证

## 当前结果

- 结果: **已归档**
- 验证情况: **已完成检查，验证结果已确认**
- 目标周期: 1
- 迭代: 1
- 验证器尝试次数: 1
- 完成时间: 2026-09-11T03:56:35.591Z
- 摘要: memory-injection 候选 e664dc8 九项验收全部通过：memory_event 形状、planner/codeAgent/verifier 记忆注入与事件序、build_memory_snapshot 移除、searchAgent 与既有行为均符合规格，110 个离线测试全绿。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: memory_event 形状 WHEN 调用 `memory_event(memory, node="planner")` THEN 返回 dict 恰为 `{"type": "memory", "node": "planner", "memory": <传入的同一 memory>}` AND 缺省 node 时为 `"graph"`。 | memory.py:174-176 返回恰为 {type,node,memory}；python -c 验证缺省 node=graph 且 memory 为同一对象；test_memory.py:293-298 通过 |
| A2 | passed | brief.md | A2: Scenario: planner 注入 WHEN 以 FakeModel 分别驱动 `planner_node` 的首轮（无 todos）与修订（todos + `last_error`）输入 THEN 捕获的首条 HumanMessage 分别以首轮指令文本（`Task: ...`）与修订文本（含 `Last error:` 与失败验证）开头 AND 消息包含 `format_layered_memory_for_prompt(memory)` 的完整 JSON，`json.loads` 后 `working_memory.node == "planner"` 且 `working_memory.task` 与 state 一致。 | nodes.py:45-70/122-124/251-254；独立 FakeModel 驱动首轮 Task: 开头、修订含 Last error: 与 fail.cmd，末尾 JSON 解析 node=planner task 一致；test_graph_nodes.py:97-144 通过 |
| A3 | passed | brief.md | A3: Scenario: planner memory 事件 WHEN 以 FakeModel 驱动 `planner_node` 并收集 `on_event` 事件 THEN 第一条事件为 `{"type": "memory", "node": "planner", "memory": <三层结构>}` 且先于任何 `ai_message`。 | nodes.py:122-124 先于所有事件；test_graph_nodes.py:147-161 events[0] 为 memory 且后随 ai_message；test_agent_loop.py:104-114 首条 planner 事件为 memory |
| A4 | passed | brief.md | A4: Scenario: codeAgent 注入 WHEN 以 FakeModel 驱动 `run_code_agent` THEN 捕获的首条 HumanMessage 含 Task/Instruction/Session context 段 AND 含分层记忆 JSON（解析后 `working_memory.node == "codeAgent"`）AND 不包含 `(no memory snapshot)`。 | code_agent.py:52-64/125-129；独立驱动含 Task/Instruction/Session context、无 (no memory snapshot)、JSON node=codeAgent；grep 零残留；test_code_agent.py:65-89 通过 |
| A5 | passed | brief.md | A5: Scenario: codeAgent memory 事件 WHEN 以 FakeModel 驱动 `run_code_agent` 并以列表收集 `writer` THEN 第一条事件为 memory 事件（解析后 `working_memory.node == "codeAgent"`）AND 同一事件位于返回 `tool_events` 首位。 | code_agent.py:135-141 emit 首发 memory 事件；独立驱动 writer 首事件与 tool_events[0] 同一；test_code_agent.py:92-106 通过 |
| A6 | passed | brief.md | A6: Scenario: verifier 注入 WHEN 以 FakeModel 驱动 `verifier_node` THEN 捕获的首条 HumanMessage 含既有验收文本（Task / Plan summary / Acceptance criteria / Verification commands）AND 含分层记忆 JSON（解析后 `working_memory.node == "verifier"`）AND `verifier_node` 签名不变（无事件参数）。 | nodes.py:307-322/325/338-341；inspect 确认签名 (state,*,model=None) 无事件参数；独立驱动验收文本齐全且 JSON node=verifier；test_graph_nodes.py:391-423 通过 |
| A7 | passed | brief.md | A7: Scenario: 预留接口移除 WHEN 检查 `novagent.agents.code_agent` 模块 THEN 不存在 `build_memory_snapshot` 属性。 | python -c hasattr 为 False；grep src/ 零匹配；test_code_agent.py:254-256 通过 |
| A8 | passed | brief.md | A8: Scenario: searchAgent 保持 WHEN 以 FakeModel 驱动 `run_search_agent` THEN 其首条 HumanMessage 不包含分层记忆 JSON（行为与现状一致）。 | search_agent.py 在 diff 中未改动；test_search_agent.py:125-126 断言无 Layered memory: 通过 |
| A9 | passed | brief.md | A9: Scenario: 既有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且无新增依赖、`uv.lock` 不变 AND `uv run pytest` 全部通过（离线）。 | pyproject/uv.lock diff 为空、工作树干净；独立复跑 uv run pytest -q 得 110 passed（6.18s 离线）；uv sync 由 Runtime 验 exit 0 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv sync 依赖安装 | sync | . | passed | 0 | 77 ms |
| uv.lock 无未提交变更 | status --porcelain -- uv.lock | . | passed | 0 | 49 ms |
| 全量离线测试 uv run pytest | run pytest -q | . | passed | 0 | 7895 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

- _format_failed_verification 与 _planner_input 失败验证过滤假定 verification_results 项为 dict，非 dict 项抛 AttributeError（基线既有语义，非本次引入）
- 受托 codeAgent 的 memory 事件经 workflow 桥接顶层 node 统一为 planner，Agent 身份仅由 memory.working_memory.node 区分（符合 spec 约定）

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 1 | pass | — | memory-injection 候选 e664dc8 九项验收全部通过：memory_event 形状、planner/codeAgent/verifier 记忆注入与事件序、build_memory_snapshot 移除、searchAgent 与既有行为均符合规格，110 个离线测试全绿。 | 2026-09-11T03:56:35.591Z |



## 结论

memory-injection 候选 e664dc8 九项验收全部通过：memory_event 形状、planner/codeAgent/verifier 记忆注入与事件序、build_memory_snapshot 移除、searchAgent 与既有行为均符合规格，110 个离线测试全绿。
