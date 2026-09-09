# 目标

使用 uv 初始化并管理名为 `novagent` 的 Python 项目（src layout，包位于 `src/novagent/`），提供基于 typer 的 CLI 命令 `novagent`，实现一组受工作区约束的文件/搜索/命令工具（LangChain `StructuredTool`），并通过 `langchain_openai.ChatOpenAI` 驱动手工实现的工具调用（ToolCall）循环，在指定 workspace 内完成用户任务。

# 范围

- uv 项目管理：`pyproject.toml`（项目名 `novagent`，src layout）、`uv.lock`、`.venv`；依赖为 `langchain-openai`、`typer`、`python-dotenv`；开发依赖为 `pytest`。
- 包结构（与用户给定结构一致）：
  - `src/novagent/__init__.py`、`src/novagent/__main__.py`
  - `src/novagent/core/__init__.py`、`core/state.py`（`RuntimeState` 数据类，含 `workspace: Path`）、`core/paths.py`（工作区路径安全工具）
  - `src/novagent/tools/__init__.py`、`tools/registry.py`（`build_tools(state)`）、`tools/file_tools.py`（`FileReadTool`/`FileWriteTool`/`FileEditTool`）、`tools/grep_tool.py`（`GrepTool`）、`tools/bash_tool.py`（`BashTool`）
  - `src/novagent/providers/__init__.py`、`providers/openai_provider.py`（`create_model()`）
  - `src/novagent/cli/__init__.py`、`cli/app.py`（typer 入口）
- `tests/` 目录：pytest 用例，覆盖路径安全、文件工具语义、grep 参数、bash 超时与 cwd、build_tools 注册、create_model 环境变量读取、CLI workspace 自动创建。

# 非目标

- 不引入 langgraph 或其他 agent 编排框架；工具调用循环在本项目内手工实现。
- 不实现流式输出、多轮会话历史持久化、会话恢复或断点续跑。
- 不在自动化验收中发起真实 LLM 网络调用（无 API key 的环境必须可全部验证）。
- 不发布到 PyPI，不配置 CI/CD，不添加 ruff/mypy 等额外工具链。

# 验收示例

- Scenario: uv 环境与 CLI 入口
  WHEN 在仓库根目录运行 `uv sync`
  THEN 依赖安装成功并生成 `uv.lock`
  AND `uv run novagent --help` 退出码为 0，帮助文本包含位置参数 `task` 和选项 `--workspace`
- Scenario: 工具注册
  WHEN 以临时目录为 workspace 构造 `RuntimeState` 并调用 `build_tools(state)`
  THEN 返回 5 个 `StructuredTool`，名称依次为 `read_file`、`write_file`、`edit_file`、`grep`、`bash`
- Scenario: 文件工具路径安全与读写改语义
  WHEN `FileReadTool` 读取 workspace 内的文本文件
  THEN 返回文件内容，`offset`/`limit` 可截取指定行范围
  AND 传入解析后逃逸出 workspace 的 `file_path`（如 `../x.txt` 或外部绝对路径）时报错且不产生读取/写入
  AND `FileWriteTool` 可在 workspace 内创建含父目录的新文件并覆写已有文件
  AND `FileEditTool` 将唯一匹配的 `old_text` 替换为 `new_text`
  AND `old_text` 无匹配或多处匹配时报错且文件内容保持不变
- Scenario: grep 与 bash 工具
  WHEN `GrepTool` 以正则 `pattern` 搜索 workspace
  THEN 按 `glob` 过滤文件、按 `ignore_case` 决定大小写敏感、最多返回 `head_limit` 条 `相对路径:行号:行内容` 形式的匹配
  AND `GrepTool` 的 `path` 逃逸出 workspace 时报错
  AND `BashTool` 以 workspace 为工作目录执行 `command` 并返回含退出码的输出
  AND 超过 `timeout_seconds` 的命令被终止并报超时错误
- Scenario: 模型工厂
  WHEN 目录 `.env` 中配置 `OPENAI_API_KEY` 后调用 `create_model()`
  THEN 返回 `langchain_openai.ChatOpenAI` 实例，其 api_key 来自 `.env`
  AND 缺少 `OPENAI_API_KEY` 时报清晰的配置错误而非 ImportError/AttributeError
- Scenario: CLI 任务执行与 workspace 自动创建
  WHEN 运行 `uv run novagent "整理文件" --workspace <不存在的目录>`
  THEN 该目录（含父目录）被自动创建
  AND 在缺少 `OPENAI_API_KEY` 的环境中以清晰错误信息退出而非未捕获异常崩溃

# 约束与不变量

- 所有工具（read/write/edit/grep/bash 的路径类参数）操作必须限制在 `RuntimeState.workspace` 内：先解析（含 `..` 与符号链接）再校验，逃逸一律报错。
- `FileEditTool` 只替换唯一匹配；多处匹配视为错误，绝不部分替换。
- `BashTool` 子进程的 cwd 必须是 workspace，且有超时控制。
- `create_model()` 的 `OPENAI_API_KEY` 从项目根 `.env`（python-dotenv）或进程环境读取；密钥不得写入代码或被 pytest 输出泄露。
- 工具函数返回字符串结果（供模型消费）；校验失败以异常形式报错。

# 决策

- 工具命名采用小写下划线：`read_file`、`write_file`、`edit_file`、`grep`、`bash`（与类名 FileReadTool 等一一对应）。
- 依赖保持最小集：`langchain-openai`（含 langchain-core）、`typer`、`python-dotenv`；不引入完整 `langchain` 发行包与 langgraph。
- `create_model()` 环境变量约定：`OPENAI_API_KEY`（必需）、`OPENAI_MODEL`（可选，默认 `gpt-4o-mini`）、`OPENAI_BASE_URL`（可选）。
- CLI 默认 workspace 为当前目录下的 `workspace/`，不存在时自动创建（`--workspace` 可覆盖）；agent 循环最大迭代次数默认 25。
- 新增 `tests/` 目录承载 pytest 验收测试，不占用用户给定的 `src/` 结构。
- `requires-python >= 3.10`；本机使用已安装的 CPython 3.13 创建虚拟环境。

# 待解决问题

（无 `[blocking]` 项）

# 验证预期

- 全部验收以离线方式验证：`uv sync`、`uv run novagent --help`、`uv run pytest`（或 `uv run python -m pytest`）。
- 不需要真实 API key；涉及 `create_model()` 的用例通过临时写入 `.env` 或 monkeypatch 环境变量验证。
- Windows（Git Bash）与本仓库为验证环境；路径安全用例必须覆盖 `..` 与绝对路径逃逸两种形态。
