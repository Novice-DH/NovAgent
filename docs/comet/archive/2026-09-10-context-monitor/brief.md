# 目标

在 `src/novagent/graph/nodes.py` 中新增上下文监控节点与路由函数（压缩机制第一步：token 监控）：

1. `context_monitor_node(state) -> dict`：
   - 估算当前 token 数：`token_count = model.get_num_tokens_from_messages(messages + [memory_payload])`；其中 `messages` 为 `state.get("messages")`（`BaseMessage` 列表），`memory_payload` 为携带分层记忆 payload 的消息——内容即 `format_layered_memory_for_prompt(build_layered_memory(state))`（复用 layered-memory change 的产出）；
   - 估算异常时 fallback：`token_count = len(text) // 4`，`text` 为全部参与计数的消息文本拼接；
   - 判断是否需要压缩：`should_compress = token_count > context_token_limit`，`context_token_limit` 取 `state.get("context_token_limit")`，缺失默认 `400000`；
   - `context_next_node` 由上游节点设置（约定：planner 后设 `"verifier"`，verifier 失败后设 `"planner"`）；本节点仅透传：`state.get("context_next_node", "verifier")`；
   - 返回恰为 `{"context_token_count": token_count, "context_should_compress": should_compress, "context_next_node": <透传值>}`。
2. `context_monitor_route(state) -> str`：`state.get("passed")` 为真 → `"final"`；`state.get("context_should_compress")` 为真 → `"context_compressor"`；否则 → `state.get("context_next_node", "verifier")`。

签名约定：`context_monitor_node(state, *, model=None)`——`model` 非 None 时以其 `get_num_tokens_from_messages` 精确估算；`model` 为 None 或估算调用抛出任何异常（含模型无该方法）时，fallback 到字符估算。

# 范围

- 修改 `src/novagent/graph/nodes.py`：
  - 新增 `context_monitor_node(state, *, model=None) -> dict`：
    - `memory_payload = HumanMessage(content=format_layered_memory_for_prompt(build_layered_memory(state)))`（从 `novagent.graph.memory` 导入二者）；
    - 计数输入 = `list(state.get("messages") or []) + [memory_payload]`；
    - `model is not None` 时调用 `model.get_num_tokens_from_messages(<计数输入>)`；`AttributeError`/`TypeError`/`Exception` 一律转入 fallback；
    - fallback：`token_count = len("".join(<每条消息的文本内容>)) // 4`；
    - `limit = state.get("context_token_limit") or 400000`；`should_compress = token_count > limit`；
    - 返回 `{"context_token_count": token_count, "context_should_compress": should_compress, "context_next_node": state.get("context_next_node") or "verifier"}`。
  - 新增 `context_monitor_route(state) -> str`：`passed` → `"final"`；`context_should_compress` → `"context_compressor"`；否则 `context_next_node`（缺失默认 `"verifier"`）。
- 新增 `tests/test_context_monitor.py`（离线测试：注入带/不带 `get_num_tokens_from_messages` 的假模型与抛异常的假模型，覆盖精确估算、fallback、阈值判定、透传、路由优先级、纯函数性）。

# 非目标

- 不接入 `build_workflow`：monitor 不加入图，图拓扑保持 `START → planner → verifier →（verifier_route）final/planner → END`；`context_monitor_route` 返回的 `"context_compressor"` 在本仓库中尚无对应节点（用户确认仅函数层，不接入图）。
- 不修改 `planner_node` / `verifier_node`：`context_next_node` 的"上游设置"（planner 后设 `"verifier"`、verifier 失败后设 `"planner"`）本次仅作为接口约定写入规格，落地属后续接线 change（用户确认）。
- 不实现 `context_compressor` 节点与压缩执行（压缩摘要生成、`HISTORY_SUMMARY.md` 写入、`context_summary`/`compression_events` 的写入逻辑属后续 change）。
- 不修改 `NovGraphState` schema（所需 8 个 context/memory 字段已由 layered-memory change 提供）。
- 不新增运行依赖（`get_num_tokens_from_messages` 来自既有 `langchain-core`；fallback 为纯标准库）。

# 验收示例

- A1: Scenario: 精确估算 WHEN 以含两条 `BaseMessage` 的 `messages` 注入假模型（其 `get_num_tokens_from_messages` 返回固定值 N 并记录入参）调用 `context_monitor_node(state, model=fake)` THEN 返回 dict 恰含 `context_token_count`/`context_should_compress`/`context_next_node` 三键 AND `context_token_count == N` AND 假模型收到的计数输入恰为 `messages + [memory_payload]`（长度 +1）。
- A2: Scenario: memory payload WHEN 检查假模型记录的计数输入最后一项 THEN 其为 `HumanMessage` AND 文本内容可被 `json.loads` 且与 `format_layered_memory_for_prompt(build_layered_memory(state))` 一致。
- A3: Scenario: fallback WHEN `model=None` THEN `context_token_count == len(全部文本拼接) // 4` 且全程未调用 `create_model`、无网络请求 AND WHEN 注入 `get_num_tokens_from_messages` 抛 `RuntimeError` 的假模型 THEN 同样落入 fallback 不抛异常。
- A4: Scenario: 阈值判定 WHEN `token_count` 恰等于 `context_token_limit` THEN `context_should_compress` 为 False AND WHEN 超过（含 state 显式给 limit 或缺失默认 400000） THEN 为 True。
- A5: Scenario: next_node 透传 WHEN state 含 `context_next_node="planner"` THEN 返回透传 `"planner"` AND 缺失时返回 `"verifier"`。
- A6: Scenario: 路由优先级 WHEN 调用 `context_monitor_route` THEN `passed=True` → `"final"`（即使 should_compress 为 True）AND `passed` 假 + `context_should_compress=True` → `"context_compressor"` AND 两者皆假 → `context_next_node` 透传（缺失默认 `"verifier"`）。
- A7: Scenario: 纯函数性 WHEN 调用 `context_monitor_node` THEN 不修改传入 state AND 不写文件、不发起网络请求。
- A8: Scenario: 范围不变 WHEN 在仓库根目录运行 `git diff --stat` THEN `workflow.py`/`state.py`/`memory.py` 无改动 AND `uv run pytest` 全部通过（离线，含新增测试）AND `uv sync` 无新依赖。

# 约束与不变量

- `context_monitor_node` 为确定性节点：不调用模型对话（`invoke`）、无网络、不写文件、不修改 state；`model=None` 时不构造模型（不调用 `create_model`）。
- 阈值语义固定为严格大于：`token_count > limit` 才压缩；`limit` 缺省 400000。
- 返回 dict 契约固定为三键；`context_next_node` 仅透传不自行决策。
- `memory_payload` 内容固定为 `format_layered_memory_for_prompt(build_layered_memory(state))`（复用 layered-memory 产出，不重复实现）。
- 全部测试离线运行（假模型 + 纯函数），不发起真实网络请求，兼容 Python >= 3.10。

# 决策

- D1 `state` 为图状态样 dict：沿用 `planner_node`/`verifier_node`/`build_layered_memory` 既有模式，全部键 `state.get` 容错读取，状态残缺不抛异常。
- D2 `memory_payload` 用 `build_layered_memory` + `format_layered_memory_for_prompt` 构造 `HumanMessage`：伪代码 "messages + [memory_payload]" 中的 memory payload 即分层记忆快照；monitor 是压缩机制对 layered-memory change 产出的首个消费者，复用而非重复实现。
- D3 `model=None` 时直接走字符估算 fallback，不调用 `create_model`：monitor 为确定性监控节点（类比 `final_node` 不接模型），不应依赖 `OPENAI_API_KEY` 配置；`model` 参数供图接线后上游复用已构造模型做精确估算（伪代码主路径 `model.get_num_tokens_from_messages` 兼容）。
- D4 估算异常一律 fallback：伪代码"如果异常，fallback"，含模型无 `get_num_tokens_from_messages` 方法（`AttributeError`）与调用抛错；fallback 文本为计数输入全部消息文本拼接长度整除 4。
- D5 新测试独立成 `tests/test_context_monitor.py`：与 `test_memory.py` 同理，新能力独立成文，不改既有测试文件。
- D6 范围仅函数层，不接入图（用户 2026-09-11 确认）：`context_monitor_route` 已就绪但暂无调用方；`build_workflow` 拓扑不变；`context_next_node` 上游设置约定与 `context_compressor` 压缩器均属后续 change。

# 待解决问题

（无未解决项）

# 验证预期

- `uv sync` 成功且无新依赖、`uv.lock` 一致。
- `uv run pytest` 全部通过（含新增 `tests/test_context_monitor.py`，离线）。
