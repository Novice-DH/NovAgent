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
- 完成时间: 2026-09-10T15:58:41.285Z
- 摘要: 8 项验收全部通过：工具与搜索 Agent 的实现、离线测试、依赖与包结构均与 brief/spec 一致，A1/A7 等逐字级要求经直接比对确认无偏差，仅存在两处验收范围外的极小鲁棒性风险。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: 缺少 API key 的降级 WHEN 未设置 `TAVILY_API_KEY` 时 invoke `WebSearchTool`（query 任意）THEN 返回 dict `ok is False` 且 `error == "missing TAVILY_API_KEY"` 且携带传入 query AND 全程不发起网络请求、不抛异常。 | web_search_tool.py 缺 key 分支返回 error 恰为 "missing TAVILY_API_KEY" 且不构造客户端不发网络请求，测试精确断言 error 字符串与 query 透传 |
| A2 | passed | brief.md | A2: Scenario: 正常搜索返回 WHEN 设置 `TAVILY_API_KEY` 且注入 fake `TavilyClient`（返回 answer 与多条 results）后 invoke `WebSearchTool` THEN 返回 `ok is True` 的 dict 且 `query` 透传、`answer` 为 API answer、`results` 每项恰含 `title/url/content/score` 四键（API 缺键补空值）AND fake 的 search 收到 `max_results` 透传。 | 结果归一化为恰含 title/url/content/score 四键（缺键补 ""/0.0），测试断言整 dict 相等且 fake 收到 max_results=2 与 include_answer=True 透传 |
| A3 | passed | brief.md | A3: Scenario: 搜索异常降级 WHEN fake `TavilyClient.search` 抛异常 THEN `WebSearchTool` 返回 `ok is False` 且 `error` 非空且携带 query AND 不抛异常。 | 客户端构造与 search 异常均被捕获转为 {ok: False, query, error}，BoomClient 测试断言不抛异常且 error 含原始异常信息 |
| A4 | passed | brief.md | A4: Scenario: ReAct 循环与返回结构 WHEN 以 `state={"task": ..., "research_notes": ...}`、instruction 与收集型 writer 注入 FakeModel（第一轮返回 `web_search` tool_call，第二轮纯文本）调用 `run_search_agent` THEN 返回 `ok is True` 且 `summary` 为最后 AI 文本 AND `queries` 含所发查询 AND `sources` 为结果 url（去重保序）AND `messages` 依次为 AIMessage（带 tool_call）、ToolMessage（内容为合法 JSON）、AIMessage（纯文本）AND `tool_events` 依次含 `tool_call` 与 `search_results` 事件且 writer 收到同一批事件。 | 返回 dict 恰为 {ok, summary, queries, sources, messages, tool_events} 六键，测试断言消息序列 AIMessage/ToolMessage(合法JSON)/AIMessage、事件依次为 tool_call 与 search_results 且 writer 收到同一批事件 |
| A5 | passed | brief.md | A5: Scenario: 消息构造 WHEN 调用 `run_search_agent` THEN 发给模型的首条消息为 SystemMessage 且内容即 `SEARCH_AGENT_PROMPT` AND 第二条 HumanMessage 同时包含 task、instruction 与已有研究笔记文本。 | 首条消息为 SystemMessage(SEARCH_AGENT_PROMPT)，HumanMessage 同时包含 task、instruction 与 research_notes（缺失时标注 no research notes yet），均有测试断言 |
| A6 | passed | brief.md | A6: Scenario: 循环边界 WHEN FakeModel 每轮都返回 tool_call 且 `max_loops=2` THEN 模型恰被调用 2 次后返回 AND WHEN FakeModel 第一轮即返回纯文本 THEN 模型只被调用 1 次（提前结束）。 | range(max_loops) 加无 tool_calls 即 break，测试覆盖每轮 tool_call 时 max_loops=2 恰调用 2 次与首轮纯文本仅调用 1 次两个方向 |
| A7 | passed | brief.md | A7: Scenario: 提示词常量 WHEN 导入 `novagent.agents.search_agent` THEN `SEARCH_AGENT_PROMPT` 以 "You are searchAgent, a focused research specialist." 开头 AND 含 "WebSearchTool" AND 含 "Do not write files or produce application code."。 | SEARCH_AGENT_PROMPT 与 brief 原文逐行比对逐字一致：开头句、WebSearchTool、Do not write files or produce application code. 均在 |
| A8 | passed | brief.md | A8: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且 lock 与 pyproject 一致（新增 tavily-python）AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0。 | pyproject 新增 tavily-python>=0.5.0 且 uv.lock 含 tavily-python 0.8.1 一致；WebSearchTool 未进 registry、tavily 导入不扩散、agents/__init__.py 为空包；Runtime 命令检查（pytest 81 passed、--help exit 0）全部通过 |

## 检查

| 检查 | 命令 | 工作目录 | 状态 | 退出码 | 耗时 |
| --- | --- | --- | --- | ---: | ---: |
| uv sync 依赖安装 | sync | . | passed | 0 | 70 ms |
| uv lock --check 锁一致 | lock --check | . | passed | 0 | 59 ms |
| uv run pytest 全量离线测试 | run pytest -q | . | passed | 0 | 8109 ms |
| uv run novagent --help 退出码 0 | run novagent --help | . | passed | 0 | 2507 ms |

## 阻塞项

_无。_

## 风险与跳过的工作

- 未知工具名的调用也会发出 search_results 事件且 name 为未知工具名（规格字面写 name 为 web_search），A4 场景（web_search）行为完全一致，属验收范围外的极小偏差
- 结果归一化中 float(item.get("score")) 位于 try 块之外，若 Tavily 返回非数值 score 字符串会抛出 ValueError 外泄；规格仅要求缺键补空值，畸形值不在验收范围

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 1 | pass | — | 8 项验收全部通过：工具与搜索 Agent 的实现、离线测试、依赖与包结构均与 brief/spec 一致，A1/A7 等逐字级要求经直接比对确认无偏差，仅存在两处验收范围外的极小鲁棒性风险。 | 2026-09-10T15:58:41.285Z |



## 结论

8 项验收全部通过：工具与搜索 Agent 的实现、离线测试、依赖与包结构均与 brief/spec 一致，A1/A7 等逐字级要求经直接比对确认无偏差，仅存在两处验收范围外的极小鲁棒性风险。
