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
- 完成时间: 2026-09-10T23:32:11.498Z
- 摘要: 独立验收通过：context_monitor_node/context_monitor_route 实现与 brief A1-A8 及 spec graph.nodes 段逐条一致——三键返回契约、计数输入 messages+[HumanMessage(layered-memory JSON)]、异常一律字符 fallback（//4）、严格大于阈值（默认 400000）、next_node 纯透传、路由优先级 passed>compress>next_node；节点为确定性纯函数（哨兵验证不调 create_model、无 invoke/写文件/网络、不改 state），novagent.graph.memory 不反向导入 nodes 无循环导入。git diff 证实 nodes.py 纯新增 49 行、范围文件零改动；uv run pytest 115 passed（复跑）、uv sync 无新依赖。Builder 复核摘要与独立观察无矛盾。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: 精确估算 WHEN 以含两条 `BaseMessage` 的 `messages` 注入假模型（其 `get_num_tokens_from_messages` 返回固定值 N 并记录入参）调用 `context_monitor_node(state, model=fake)` THEN 返回 dict 恰含 `context_token_count`/`context_should_compress`/`context_next_node` 三键 AND `context_token_count == N` AND 假模型收到的计数输入恰为 `messages + [memory_payload]`（长度 +1）。 | nodes.py:526 构造 counted = list(state.get("messages") or []) + [memory_payload]，nodes.py:508 经 _estimate_tokens 调用 model.get_num_tokens_from_messages(counted)。测试 test_exact_estimation_with_model（tests/test_context_monitor.py:51-68）断言恰三键、context_token_count==123（模型返回值）、计数输入长度 3（=messages+1）且前两项与 state["messages"] 相同。另用 python -c 独立注入 CountingModel 复核：set(result)=={三键}、token_count==模型返回值、入参长度==len(messages)+1，全部成立。 |
| A2 | passed | brief.md | A2: Scenario: memory payload WHEN 检查假模型记录的计数输入最后一项 THEN 其为 `HumanMessage` AND 文本内容可被 `json.loads` 且与 `format_layered_memory_for_prompt(build_layered_memory(state))` 一致。 | nodes.py:18-21 从 novagent.graph.memory 导入二者，nodes.py:523-525 memory_payload=HumanMessage(content=format_layered_memory_for_prompt(build_layered_memory(state)))。测试第 66-68 行断言末项 isinstance HumanMessage 且 json.loads(content)==json.loads(_payload_text(state))；memory.py:169-171 证实该函数为确定性 json.dumps，json.loads 可解析且内容等价。独立 python 断言同样通过。 |
| A3 | passed | brief.md | A3: Scenario: fallback WHEN `model=None` THEN `context_token_count == len(全部文本拼接) // 4` 且全程未调用 `create_model`、无网络请求 AND WHEN 注入 `get_num_tokens_from_messages` 抛 `RuntimeError` 的假模型 THEN 同样落入 fallback 不抛异常。 | nodes.py:504-512：model 为 None 跳过精确估算；任何异常被 except Exception 捕获后落入 len(text)//4，text 经 _response_text（str 原样/非 str str()，nodes.py:55-57）顺序拼接，与 spec 一致。测试 test_fallback_without_model（71-80 行）与 test_fallback_on_model_exception（83-90 行，RuntimeError）覆盖，且两测试 monkeypatch create_model 为抛 AssertionError 哨兵。独立复算 fallback 值 == len('hello'+'world'+payload)//4 且哨兵零调用，通过。 |
| A4 | passed | brief.md | A4: Scenario: 阈值判定 WHEN `token_count` 恰等于 `context_token_limit` THEN `context_should_compress` 为 False AND WHEN 超过（含 state 显式给 limit 或缺失默认 400000） THEN 为 True。 | nodes.py:529-532：limit = state.get("context_token_limit") or DEFAULT_CONTEXT_TOKEN_LIMIT(=400_000, nodes.py:32)；should_compress = token_count > limit 严格大于。测试 test_threshold_comparison（93-100 行：1000==limit→False、1001→True）与 test_threshold_default_limit（103-108 行：400000→False、400001→True）。独立断言四种情形全部复现，通过。 |
| A5 | passed | brief.md | A5: Scenario: next_node 透传 WHEN state 含 `context_next_node="planner"` THEN 返回透传 `"planner"` AND 缺失时返回 `"verifier"`。 | nodes.py:533-534：context_next_node = state.get("context_next_node") or DEFAULT_CONTEXT_NEXT_NODE(="verifier", nodes.py:33)，仅透传不自行决策。测试 test_next_node_passthrough（111-118 行："planner" 透传、缺失默认 "verifier"）。独立断言两分支成立，通过。 |
| A6 | passed | brief.md | A6: Scenario: 路由优先级 WHEN 调用 `context_monitor_route` THEN `passed=True` → `"final"`（即使 should_compress 为 True）AND `passed` 假 + `context_should_compress=True` → `"context_compressor"` AND 两者皆假 → `context_next_node` 透传（缺失默认 `"verifier"`）。 | nodes.py:538-544：passed→"final"；context_should_compress→"context_compressor"；否则 next_node or "verifier"。测试 test_route_priority（121-143 行）覆盖四分支含 passed=True+should_compress=True→"final"。独立断言四分支（含缺失默认 "verifier"）全部成立，通过。 |
| A7 | passed | brief.md | A7: Scenario: 纯函数性 WHEN 调用 `context_monitor_node` THEN 不修改传入 state AND 不写文件、不发起网络请求。 | 代码审读：context_monitor_node（nodes.py:515-535）无 invoke、无文件写入、无网络调用（grep requests/httpx/urlopen/.write(/write_text 于 nodes.py/memory.py/测试文件零匹配）；其依赖 build_layered_memory 仅经 memory.py:59-66 Path.read_text 只读 workspace 文件。测试 test_does_not_mutate_state（146-154 行）以 JSON 快照验证 state 不变并挂 create_model 哨兵。独立用哨兵+快照+inspect.getsource 断言（无 '.invoke('/'open('，哨兵零触发）全部通过。 |
| A8 | passed | brief.md | A8: Scenario: 范围不变 WHEN 在仓库根目录运行 `git diff --stat` THEN `workflow.py`/`state.py`/`memory.py` 无改动 AND `uv run pytest` 全部通过（离线，含新增测试）AND `uv sync` 无新依赖。 | git diff --stat 仅 src/novagent/graph/nodes.py 49 insertions(+) 0 deletions，三个 hunk 均为纯新增（memory 导入块、两常量、文件末尾追加函数），planner_node/verifier_node/final_node/verifier_route 既有行零改动；git diff --stat 对 workflow.py/state.py/graph state/memory.py/core state/pyproject.toml/uv.lock 为空。复跑 uv run pytest -q 得 115 passed（含新增 8 项，离线）；uv sync 由 Runtime 验证 exit 0 无安装变更，且 pyproject.toml/uv.lock 无 diff 佐证无新依赖。 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv sync（无新依赖、uv.lock 一致） | sync | . | passed | 0 | 73 ms |
| uv run pytest -q（离线全量测试） | run pytest -q | . | passed | 0 | 7987 ms |
| uv run novagent --help（CLI 冒烟） | run novagent --help | . | passed | 0 | 2766 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

- A2 测试用 json.loads 后比较而非原始字符串全等：因 format_layered_memory_for_prompt 为确定性 json.dumps，两者等价，风险可忽略
- limit 读取用 or 默认：state 显式给 context_token_limit=0 会落到默认 400000——与 brief 伪代码 "or 400000" 语义一致，非缺陷
- context_monitor_route 的 "context_compressor" 目标节点尚不存在：brief 非目标明确本 change 仅函数层不接图，属预期

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 1 | pass | — | 独立验收通过：context_monitor_node/context_monitor_route 实现与 brief A1-A8 及 spec graph.nodes 段逐条一致——三键返回契约、计数输入 messages+[HumanMessage(layered-memory JSON)]、异常一律字符 fallback（//4）、严格大于阈值（默认 400000）、next_node 纯透传、路由优先级 passed>compress>next_node；节点为确定性纯函数（哨兵验证不调 create_model、无 invoke/写文件/网络、不改 state），novagent.graph.memory 不反向导入 nodes 无循环导入。git diff 证实 nodes.py 纯新增 49 行、范围文件零改动；uv run pytest 115 passed（复跑）、uv sync 无新依赖。Builder 复核摘要与独立观察无矛盾。 | 2026-09-10T23:32:11.498Z |



## 结论

独立验收通过：context_monitor_node/context_monitor_route 实现与 brief A1-A8 及 spec graph.nodes 段逐条一致——三键返回契约、计数输入 messages+[HumanMessage(layered-memory JSON)]、异常一律字符 fallback（//4）、严格大于阈值（默认 400000）、next_node 纯透传、路由优先级 passed>compress>next_node；节点为确定性纯函数（哨兵验证不调 create_model、无 invoke/写文件/网络、不改 state），novagent.graph.memory 不反向导入 nodes 无循环导入。git diff 证实 nodes.py 纯新增 49 行、范围文件零改动；uv run pytest 115 passed（复跑）、uv sync 无新依赖。Builder 复核摘要与独立观察无矛盾。
