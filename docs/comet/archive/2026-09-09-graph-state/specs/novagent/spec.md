# novagent 完整目标规格

本规格描述 change 归档后 `novagent` 项目的完整行为。项目由 uv 管理，src layout，包名 `novagent`。

## 项目与依赖

- `pyproject.toml`：`name = "novagent"`，src layout（uv_build 后端指向 `src/novagent`），`requires-python >= 3.10`，控制台脚本 `novagent = novagent.cli.app:main`。
- 运行依赖：`langchain-openai`、`typer`、`python-dotenv`、`rich`、`langgraph`。开发依赖：`pytest`。
- `uv.lock` 存在且与 `pyproject.toml` 一致；`uv sync` 可在新环境完成安装；锁中不引入完整 `langchain` 发行包。
- 包结构：

```text
src/novagent/
├── __init__.py
├── __main__.py
├── core/
│   ├── __init__.py
│   ├── agent.py
│   ├── state.py
│   └── paths.py
├── graph/
│   ├── __init__.py
│   └── state.py
├── tools/
│   ├── __init__.py
│   ├── registry.py
│   ├── file_tools.py
│   ├── grep_tool.py
│   └── bash_tool.py
├── providers/
│   ├── __init__.py
│   └── openai_provider.py
└── cli/
    ├── __init__.py
    └── app.py
```

## core.state — RuntimeState

- `@dataclass RuntimeState`，字段 `workspace: Path`。
- 构造时可将相对路径规范化为绝对路径；`workspace` 是所有工具的根约束。

## core.paths — 工作区路径工具

- 提供 `resolve_in_workspace(state, raw_path) -> Path`：
  1. 以 `workspace` 为基准解析相对路径（支持子目录如 `sub/dir/file.txt`）；
  2. `Path.resolve()` 归一化 `..`、`.` 与符号链接；
  3. 解析结果不在 `workspace.resolve()` 内时抛出 `ValueError`，错误信息包含被拒绝的路径；
  4. workspace 本身不存在时不隐式创建，由调用方（CLI/写工具）决定创建。

## core.agent — ReAct 循环与事件流

- 模块常量 `ACTOR_PROMPT`，为 actor 节点系统提示，内容以 "You are the actor node in novagent's ReAct workflow." 开头，约定：只用 FileWriteTool 新建文件、编辑已有文件前先用 FileReadTool 读取、聚焦修改用 FileEditTool、用 BashTool 运行命令并验证结果；BashTool 已在 workspace 内运行，使用相对路径而非 "cd /workspace"；结束时给出已改动文件与已运行命令的简洁摘要。
- `stream_agent_events(task, *, workspace, max_loops=10, model=None)` 为生成器，逐步产出普通 dict 事件，类型为 `ai_message`、`tool_call`、`tool_result`、`final_answer`：
  1. 创建 `RuntimeState(workspace)`，构建 `tools = build_tools(state)`；
  2. `model` 为 None 时调用 `create_model()` 创建；随后 `agent = model.bind_tools(tools)`；
  3. 消息列表初始化为 `[SystemMessage(ACTOR_PROMPT), HumanMessage(task)]`；
  4. 最多循环 `max_loops` 次：`response = agent.invoke(messages)`；`messages.append(response)`；yield `{"type": "ai_message", "content": <response 文本内容>}`；
     - `response.tool_calls` 为空时 break；
     - 否则对每个 tool_call 依次：yield `{"type": "tool_call", "name": ..., "args": ...}`；执行工具并把结果字符串经 `json.dumps` 序列化后构造 `ToolMessage(tool_call_id=<call id>)` append 到消息列表；yield `{"type": "tool_result", "name": ..., "result": <工具原始返回字符串>}`；
  5. 循环结束（自然结束或 break）后 yield `{"type": "final_answer", "content": <最后一轮 AI 消息文本>}`。
- 工具执行语义：
  - 未知工具名：不抛出，结果为包含 `unknown tool` 的错误文本；
  - 工具抛出异常：不向调用方传播，结果为 `Error: <异常信息>` 文本；
  - 两种错误文本同样进入 `ToolMessage` 与 `tool_result` 事件，供模型下一轮修正。
- 达到 `max_loops` 上限仍未出现无 tool_calls 的响应时，循环停止并照常产出 `final_answer`（内容为最后一轮 AI 消息文本）。

## graph.state — LangGraph 图共享状态

模块 `novagent.graph.state` 定义 LangGraph 图的共享状态类型，均为 `typing.TypedDict`：

- `TodoItem(TypedDict)`，字段与类型：
  - `id: str`
  - `content: str`
  - `status: str` —— 注释标注取值 `"pending" | "in_progress" | "completed" | "blocked"`
  - `note: str`
- `VerificationResult(TypedDict)`，字段与类型：
  - `command: str`
  - `ok: bool`
  - `exit_code: int | None`
  - `stdout: str`
  - `stderr: str`
- `NovGraphState(TypedDict, total=False)`，字段与类型：
  - `task: str`
  - `runtime: RuntimeState`（`novagent.core.state.RuntimeState`，直接复用，不复制）
  - `messages: Annotated[list[BaseMessage], add_messages]`
  - `plan_summary: str`
  - `todos: list[TodoItem]`
  - `acceptance_criteria: list[str]`
  - `verification_commands: list[str]`
  - `verification_results: list[VerificationResult]`
  - `passed: bool`
  - `attempts: int`
  - `max_attempts: int`
  - `final_answer: str`

导入约定：

- `add_messages` 从 langgraph 导入（`langgraph.graph.message` 或 langgraph 公开顶层）；
- `BaseMessage` 从 `langchain_core.messages` 导入；
- `RuntimeState` 从 `novagent.core.state` 导入。

行为约定：

- `NovGraphState` 所有字段可选（`total=False`），图可以部分状态启动与更新；
- `messages` 通道使用 `add_messages` reducer：图执行中对 `messages` 的更新按 LangGraph 语义追加/合并（如按消息 ID 去重更新），而不是整体覆盖；
- 其余字段为默认覆盖语义的普通通道；
- 本模块只定义状态类型，不组装 StateGraph、不定义节点与边。

## tools.file_tools

三个工具均为闭包工厂，接收 `RuntimeState`，内部通过 `resolve_in_workspace` 校验后执行：

- `FileReadTool` → `read_file(file_path: str, offset: int = 1, limit: int | None = None) -> str`
  - 读取 UTF-8 文本，返回内容；`offset` 为起始行（1-based），`limit` 为最多返回行数；
  - 文件不存在、是目录或逃逸 workspace 时报错。
- `FileWriteTool` → `write_file(file_path: str, content: str) -> str`
  - 创建含缺失父目录的目标文件或整体覆写；成功返回确认信息；
  - 逃逸 workspace 时报错。
- `FileEditTool` → `edit_file(file_path: str, old_text: str, new_text: str) -> str`
  - `old_text` 必须在文件中恰好出现一次，替换后写回，返回确认信息；
  - 出现 0 次或多次时报错且文件内容保持不变；
  - 文件不存在或逃逸 workspace 时报错。

## tools.grep_tool — GrepTool

`grep(pattern: str, path: str = ".", glob: str = "**/*", head_limit: int = 20, ignore_case: bool = False) -> str`

- 在 `path`（必须位于 workspace 内，逃逸报错）下递归遍历匹配 `glob` 的文件；
- 按行应用 `re` 正则，`ignore_case=True` 时忽略大小写；
- 命中行以 `相对路径:行号:行内容` 输出，最多 `head_limit` 条；
- 跳过无法按 UTF-8 解码的二进制文件与超大小文件，不因个别文件失败中断；
- 无匹配返回提示信息；非法正则报错。

## tools.bash_tool — BashTool

`bash(command: str, timeout_seconds: float = 30) -> str`

- 以 `RuntimeState.workspace` 为 cwd 执行 shell 命令，返回包含退出码、stdout、stderr 的文本；
- 超过 `timeout_seconds` 终止子进程并报超时错误；
- 非零退出码不抛异常，正常返回输出并标注退出码。

## tools.registry — build_tools

- `build_tools(state: RuntimeState) -> list[StructuredTool]`；
- 依次注册 `read_file`、`write_file`、`edit_file`、`grep`、`bash` 五个工具，args schema 由函数签名自动推导；
- 返回列表可直接用于 `model.bind_tools(tools)`。

## providers.openai_provider — create_model

- `create_model() -> ChatOpenAI`：
  1. `load_dotenv()` 加载项目根 `.env`；
  2. 读取 `OPENAI_API_KEY`，缺失时抛出说明配置方法的 `ValueError`；
  3. `OPENAI_MODEL` 可选，默认 `gpt-4o-mini`；`OPENAI_BASE_URL` 可选，设置时传入 `base_url`；
  4. 返回 `langchain_openai.ChatOpenAI` 实例。

## cli.app — novagent 命令

- `novagent <task> --workspace <path>`：`task` 为位置参数；`--workspace` 默认 `<cwd>/workspace`；
- 执行流程：
  1. 解析并自动创建 workspace（`parents=True, exist_ok=True`），打印 workspace 路径；
  2. 调用 `create_model()`；`OPENAI_API_KEY` 缺失等配置错误以清晰错误信息退出（非零退出码），不打印未捕获 traceback；
  3. 调用 `core.agent.stream_agent_events(task, workspace=..., model=...)` 消费事件流，用 `rich.Console` 实时打印每个事件：
     - `ai_message` → 打印 AI 文本内容；
     - `tool_call` → 打印工具名与参数；
     - `tool_result` → 打印工具结果；
     - `final_answer` → 打印最终回答；
- `python -m novagent` 与控制台脚本 `novagent` 行为一致（`__main__.py` 调用 `cli.app`）。
- CLI 不保留独立的内联工具调用循环；循环逻辑唯一来源于 `core.agent.stream_agent_events`。

## tests

- `tests/` 使用 pytest 覆盖：路径安全（`..` 与绝对路径逃逸）、三个文件工具语义（含多匹配报错且文件不变）、grep 参数行为、bash 的 cwd 与超时、`build_tools` 返回 5 个工具及命名、`create_model` 读取 `.env` 与缺 key 报错、CLI workspace 自动创建与缺 key 清晰报错（typer CliRunner）；
- `tests/test_agent_loop.py` 以 FakeModel 离线覆盖 `stream_agent_events`：事件序列与顺序、`ACTOR_PROMPT` 与首轮消息构建、`ToolMessage` 的 `tool_call_id` 与 `json.dumps` 内容、工具异常与未知工具名回传错误文本、`max_loops` 限制模型调用次数且仍产出 `final_answer`；
- `tests/test_graph_state.py` 离线覆盖 LangGraph 共享状态：三个 TypedDict 存在且字段注解逐一正确、`NovGraphState` 的 `total` 为 False、`messages` 注解为 `Annotated[list[BaseMessage], add_messages]` 且导入来源正确、`add_messages` 合并语义（直接调用追加 + 最小 StateGraph 端到端消息拼接不覆盖）；
- CLI 测试以 monkeypatch 假事件流离线验证 rich 打印包含工具名、参数、结果与最终回答；
- 全部测试离线运行，不发起真实网络请求。
