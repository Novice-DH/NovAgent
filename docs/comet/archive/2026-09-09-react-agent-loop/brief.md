# 目标

在 `src/novagent/core/agent.py` 实现可逐事件产出的 ReAct 循环 `stream_agent_events(task, *, workspace, max_loops=10)`，并以模块常量 `ACTOR_PROMPT` 作为 actor 系统提示；CLI（`src/novagent/cli/app.py`）改为消费该事件流，用 rich 实时打印每个事件，替代现有的内联工具调用循环。

# 范围

- 新增 `src/novagent/core/agent.py`：
  - 模块常量 `ACTOR_PROMPT`，逐字使用用户提供的原文（以 "You are the actor node in novagent's ReAct workflow." 开头，含 FileWriteTool/FileReadTool/FileEditTool/BashTool 使用规则与结尾摘要要求）。
  - 生成器函数 `stream_agent_events(task, *, workspace, max_loops=10, model=None)`，按用户给定伪代码执行：
    1. 创建 `RuntimeState(workspace)`；
    2. 构建消息列表 `SystemMessage(ACTOR_PROMPT)` + `HumanMessage(task)`；
    3. `model.bind_tools(build_tools(state))`；
    4. 最多 `max_loops` 轮：`response = model.invoke(messages)` 后 `messages.append(response)` 并 yield `{"type": "ai_message", "content": ...}`；无 tool_calls 则 break；否则对每个 tool_call 依次 yield `{"type": "tool_call", "name": ..., "args": ...}`、执行工具、append `ToolMessage(content=json.dumps(result), tool_call_id=...)`、yield `{"type": "tool_result", "name": ..., "result": ...}`；
    5. 结束时 yield `{"type": "final_answer", "content": last_ai_content}`。
  - `model=None` 时内部调用 `create_model()`；工具执行异常与未知工具名均转为 `Error: ...` 文本回传模型（延续现有语义），不向调用方抛出。
- 改写 `src/novagent/cli/app.py`：移除内联 `_run_agent`、`_tool_system_prompt`、`MAX_ITERATIONS`，`run` 命令改为调用 `stream_agent_events` 并用 `rich.Console` 实时打印事件：`tool_call` → 工具名与参数；`tool_result` → 结果；`final_answer` → 最终回答；`ai_message` → 内容。
- `pyproject.toml` 运行依赖新增 `rich`，并同步 `uv.lock`。
- `tests/test_agent_loop.py` 改写为针对 `stream_agent_events` 的离线 FakeModel 测试；`tests/test_cli.py` 补充 rich 事件打印的离线验证。

# 非目标

- 不引入 LangGraph、langchain-agents 等现成执行器，循环保持手写。
- 不改变五个工具（read_file/write_file/edit_file/grep/bash）的行为与 `build_tools` 注册方式。
- 不增加多 Agent、记忆、token 级流式输出、并行工具执行等能力。
- 不改变 `create_model` 的环境变量约定与错误信息。

# 验收示例

- A1: Scenario: ReAct 循环产出完整事件序列 WHEN 以临时 workspace 和注入的 FakeModel（第一轮返回 `write_file` 写 `note.txt` 内容 `"hi"` 的 tool_call，第二轮返回纯文本 `"All done."`）调用 `stream_agent_events("create a note", workspace=ws, model=fake)` THEN 事件 `type` 依次为 `ai_message`、`tool_call`、`tool_result`、`ai_message`、`final_answer` AND `tool_call` 事件 name 为 `write_file` 且 args 为 `{"file_path": "note.txt", "content": "hi"}` AND `final_answer` 事件 content 为 `"All done."` AND workspace 中出现 `note.txt` 且内容为 `"hi"` AND 第二轮发给模型的消息最后一条是 `ToolMessage`，其 `tool_call_id` 等于 tool_call 的 id，content 为 `json.dumps` 后的结果。
- A2: Scenario: 消息构建使用 ACTOR_PROMPT WHEN 检查 FakeModel 收到的第一轮消息 THEN 依次为 SystemMessage 与 HumanMessage AND SystemMessage.content 等于 `novagent.core.agent.ACTOR_PROMPT` AND HumanMessage.content 等于传入的 task AND `ACTOR_PROMPT` 以 "You are the actor node in novagent's ReAct workflow." 开头。
- A3: Scenario: 工具异常转为错误回传 WHEN FakeModel 第一轮请求 `read_file`（目标文件不存在），第二轮返回 `"Handled."` THEN 调用 `stream_agent_events` 不抛出异常 AND `tool_result` 事件 result 以 `"Error:"` 开头 AND 第二轮消息最后一条 `ToolMessage.content` 以 `"Error:"` 开头。
- A4: Scenario: 未知工具名回传错误 WHEN FakeModel 第一轮请求未注册的 `no_such_tool`，第二轮返回 `"Ok."` THEN `tool_result` 事件 result 包含 `"unknown tool"` AND 流程以 `final_answer` 事件正常结束。
- A5: Scenario: max_loops 限制模型调用轮数 WHEN FakeModel 每轮都返回 tool_call 且以 `max_loops=3` 调用 `stream_agent_events` THEN 模型恰好被调用 3 次 AND 生成器仍产出 `final_answer` 事件。
- A6: Scenario: CLI 用 rich 实时打印事件 WHEN 将 `novagent.cli.app` 依赖的模型与事件流替换为假实现（monkeypatch），使 `stream_agent_events` 依次产出 `tool_call`（`bash`，`{"command": "echo hi"}`）、`tool_result`（`"hi"`）、`final_answer`（`"Done."`）后用 CliRunner 运行 `run "demo task" --workspace <临时目录>` THEN 退出码 0 AND 输出按顺序包含工具名 `bash`、命令参数 `echo hi`、结果 `hi` 与最终回答 `Done.`。

# 约束与不变量

- 事件为普通 dict，值均可 JSON 序列化；生成器边执行边 yield，消费方可在事件发生时实时收到。
- 工具异常与未知工具名不抛出到调用方，统一转为 `Error: ...` 文本进入 ToolMessage 与 `tool_result` 事件。
- `ToolMessage.content` 一律用 `json.dumps(result)` 序列化（伪代码要求）；`tool_result` 事件携带工具原始返回字符串便于展示。
- `final_answer` 的 content 为最后一轮 AI 消息文本；达到 `max_loops` 上限仍未自然结束时同样产出 `final_answer`。
- 全部测试离线运行（FakeModel / monkeypatch），不发真实网络请求；兼容 Python >= 3.10。

# 决策

- D1 用 `stream_agent_events` 完全替代 `cli.app` 的内联循环 `_run_agent`/`_tool_system_prompt`/`MAX_ITERATIONS`：用户明确要求 CLI 层调用 `stream_agent_events`，保留两套循环会产生死代码与双重维护。
- D2 `stream_agent_events` 增加可选 keyword-only 参数 `model=None`（为 None 时内部 `create_model()`）：不改变用户给定签名的调用方式，同时支持离线注入 FakeModel 测试；CLI 显式创建模型传入，保留现有配置错误处理。
- D3 `ai_message` 事件也在 CLI 打印内容：用户要求"用 rich 实时打印每个事件"。
- D4 显式新增 `rich` 运行依赖：虽然 typer 生态常见 rich，但项目未声明，显式声明保证可用与可复现。

# 待解决问题

（无未解决项）

# 验证预期

- `uv run pytest` 全部通过（离线）。
- `uv sync` 后 `uv run novagent --help` 退出码 0。
- 可选人工冒烟：配置 `OPENAI_API_KEY` 后运行真实任务，观察 rich 实时输出工具调用、结果与最终回答。
