# 目标

在 `src/novagent/tools/web_search_tool.py` 中实现联网搜索工具 `WebSearchTool`（基于 tavily-python 的 `TavilyClient.search()`），并在 `src/novagent/agents/search_agent.py` 中实现独立的搜索专家 Agent：`run_search_agent(state, instruction, *, writer=None, max_loops=4)` 以手写 ReAct 循环驱动模型调用 `WebSearchTool` 完成事实研究，经 `writer` 实时写出 `tool_call`/`search_results` 事件，返回研究摘要、查询与来源列表。

# 范围

- 新增 `src/novagent/agents/__init__.py`（空包文件）与 `src/novagent/agents/search_agent.py`：
  - 模块常量 `SEARCH_AGENT_PROMPT`：逐字使用用户给定的英文系统提示（"You are searchAgent, a focused research specialist." 开头；唯一外部能力是 WebSearchTool；优先官方/百科来源；输出简洁研究摘要与来源 URL 列表；不写文件、不产出应用代码）；
  - `run_search_agent(state, instruction, *, writer=None, max_loops=4, model=None) -> dict`：创建/注入 model 并 `bind_tools([WebSearchTool])`（唯一绑定工具）；消息为 `SystemMessage(SEARCH_AGENT_PROMPT)` + `HumanMessage(task + instruction + research_notes)`；手写 ReAct 循环最多 `max_loops` 轮（无 tool_calls 提前结束）；每轮提取 tool_calls 执行 WebSearchTool，结果以 `ToolMessage(json.dumps(result))` 回传；收集 `queries`（每次搜索的 query）与 `sources`（成功结果的 url，去重保序）；执行前后经 `writer` 发 `tool_call`/`search_results` 事件并收集进 `tool_events`；返回 `{ok: True, summary, queries, sources, messages, tool_events}`。
- 新增 `src/novagent/tools/web_search_tool.py`：
  - 模块级 `WebSearchTool`（StructuredTool，工具名 `web_search`，args：`query: str`、`max_results: int = 5`）；
  - 执行：先 `load_dotenv(find_dotenv(usecwd=True))` 再读 `TAVILY_API_KEY`（与 `create_model` 一致）；缺失时返回 `{ok: False, query, error: "missing TAVILY_API_KEY"}`，不构造客户端、不发起网络请求；有 key 时 `TavilyClient(api_key=...).search(query, max_results=max_results, include_answer=True)`；成功返回 `{ok: True, query, answer, results: [{title, url, content, score}]}`（四键归一化）；异常不外泄，返回 `{ok: False, query, error}`。
- `pyproject.toml`：运行依赖新增 `tavily-python`（`uv.lock` 同步）。
- 新增 `tests/test_web_search_tool.py` 与 `tests/test_search_agent.py`（全部离线：monkeypatch 环境变量与 fake `TavilyClient`，FakeModel 驱动 Agent）。

# 非目标

- 不把 `run_search_agent` 接入 LangGraph 工作流（planner/actor/verifier/final 节点与 `build_workflow` 不变），不修改 `NovGraphState` schema（不新增 `research_notes` 通道；state 由调用方按需提供）。
- 不改动既有五个工具、`build_tools`/`build_read_only_tools` 注册表与 `create_model` 的环境变量约定。
- 不实现网页抓取/爬取、结果缓存、多查询并行；仅 Tavily `search()` API。
- 不提供 CLI 入口，不引入研究笔记的持久化机制。
- 不引入 langchain-agents 等现成执行器，循环保持手写。

# 验收示例

- A1: Scenario: 缺少 API key 的降级 WHEN 未设置 `TAVILY_API_KEY` 时 invoke `WebSearchTool`（query 任意）THEN 返回 dict `ok is False` 且 `error == "missing TAVILY_API_KEY"` 且携带传入 query AND 全程不发起网络请求、不抛异常。
- A2: Scenario: 正常搜索返回 WHEN 设置 `TAVILY_API_KEY` 且注入 fake `TavilyClient`（返回 answer 与多条 results）后 invoke `WebSearchTool` THEN 返回 `ok is True` 的 dict 且 `query` 透传、`answer` 为 API answer、`results` 每项恰含 `title/url/content/score` 四键（API 缺键补空值）AND fake 的 search 收到 `max_results` 透传。
- A3: Scenario: 搜索异常降级 WHEN fake `TavilyClient.search` 抛异常 THEN `WebSearchTool` 返回 `ok is False` 且 `error` 非空且携带 query AND 不抛异常。
- A4: Scenario: ReAct 循环与返回结构 WHEN 以 `state={"task": ..., "research_notes": ...}`、instruction 与收集型 writer 注入 FakeModel（第一轮返回 `web_search` tool_call，第二轮纯文本）调用 `run_search_agent` THEN 返回 `ok is True` 且 `summary` 为最后 AI 文本 AND `queries` 含所发查询 AND `sources` 为结果 url（去重保序）AND `messages` 依次为 AIMessage（带 tool_call）、ToolMessage（内容为合法 JSON）、AIMessage（纯文本）AND `tool_events` 依次含 `tool_call` 与 `search_results` 事件且 writer 收到同一批事件。
- A5: Scenario: 消息构造 WHEN 调用 `run_search_agent` THEN 发给模型的首条消息为 SystemMessage 且内容即 `SEARCH_AGENT_PROMPT` AND 第二条 HumanMessage 同时包含 task、instruction 与已有研究笔记文本。
- A6: Scenario: 循环边界 WHEN FakeModel 每轮都返回 tool_call 且 `max_loops=2` THEN 模型恰被调用 2 次后返回 AND WHEN FakeModel 第一轮即返回纯文本 THEN 模型只被调用 1 次（提前结束）。
- A7: Scenario: 提示词常量 WHEN 导入 `novagent.agents.search_agent` THEN `SEARCH_AGENT_PROMPT` 以 "You are searchAgent, a focused research specialist." 开头 AND 含 "WebSearchTool" AND 含 "Do not write files or produce application code."。
- A8: Scenario: 现有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且 lock 与 pyproject 一致（新增 tavily-python）AND `uv run pytest` 全部通过（离线）AND `uv run novagent --help` 退出码 0。

# 约束与不变量

- `SEARCH_AGENT_PROMPT` 逐字使用用户给定英文原文，不改写、不翻译。
- `run_search_agent` 对用户给定签名 `run_search_agent(state, instruction, *, writer=None, max_loops=4)` 完全兼容；`model` 为追加的 keyword-only 可选参数（None 时内部 `create_model()`）。
- `WebSearchTool` 是 `run_search_agent` 绑定的唯一工具；`WebSearchTool` 不进入 `build_tools`/`build_read_only_tools` 注册表。
- 返回 dict 契约固定为 `{ok: True, summary, queries, sources, messages, tool_events}`；配置错误（如缺 `OPENAI_API_KEY`）由 `create_model` 抛异常，不经 `ok` 表达。
- 缺 `TAVILY_API_KEY` 时工具返回结构化错误 dict（error 恰为 "missing TAVILY_API_KEY"），不抛异常、不发起网络请求。
- `tavily` 仅在 `tools/web_search_tool.py` 中导入，不向其他模块扩散。
- 全部测试离线运行（FakeModel / fake TavilyClient / monkeypatch 环境变量），不发起真实网络请求，兼容 Python >= 3.10。

# 决策

- D1 `run_search_agent` 追加 keyword-only `model=None`：用户伪代码签名无 model 参数，但项目不变量要求测试全部离线；沿用 `graph-workflow` change 的 D1 先例（None 时行为与伪代码完全一致，内部 `create_model()`），用户给定调用方式不变。
- D2 `WebSearchTool` 实现为模块级 `StructuredTool`、工具名 `web_search`：`bind_tools` 需要 LangChain 工具对象；工具名字符串沿用项目小写下划线惯例（read_file/grep/bash），Python 侧导出名保持用户指定的 `WebSearchTool`。
- D3 `SEARCH_AGENT_PROMPT` 定义在 `agents/search_agent.py`：常量职责专属该 Agent；`prompts/stage2.py` 保持 stage2 LangGraph 工作流专用，用户未要求放入 prompts 包。
- D4 `state` 语义：图状态样 dict-like 映射，读取 `state.get("task", "")` 与 `state.get("research_notes", "")`（均可缺失）；不修改 `NovGraphState`（把搜索 Agent 接入工作流属后续 change）。
- D5 事件 schema：`tool_call` 事件与 `actor_node` 现有约定一致（`name` + `args`），搜索执行后补发 `search_results` 事件（`name: "web_search"`、`query`、完整 `result` dict）；伪代码第 3 步的 "answers" 由 `search_results` 事件的 `result.answer` 承载，返回 dict 按伪代码第 4 步原样（不含独立 answers 键）。
- D6 工具失败语义：Tavily 异常与模型幻觉调用未知工具都转为 `{"ok": False, "error": ...}` dict 回传模型（沿用 `_execute_tool` 错误回传约定），不中断循环。
- D7 新增运行依赖 `tavily-python`：用户明确要求调用其 `TavilyClient.search()`；`tavily` 仅在 `web_search_tool.py` 导入。

# 待解决问题

（无未解决项）

# 验证预期

- `uv sync` 成功，`uv.lock` 与 `pyproject.toml` 一致（新增 tavily-python）。
- `uv run pytest` 全部通过（含新增 `tests/test_web_search_tool.py`、`tests/test_search_agent.py`，离线）。
- `uv run novagent --help` 退出码 0（现有行为不受影响）。
