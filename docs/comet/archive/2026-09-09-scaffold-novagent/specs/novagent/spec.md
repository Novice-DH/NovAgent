# novagent 完整目标规格

本规格描述 change 归档后 `novagent` 项目的完整行为。项目由 uv 管理，src layout，包名 `novagent`。

## 项目与依赖

- `pyproject.toml`：`name = "novagent"`，src layout（`[tool.uv]`/hatch 构建后端指向 `src/novagent`），`requires-python >= 3.10`，控制台脚本 `novagent = novagent.cli.app:main`。
- 运行依赖：`langchain-openai`、`typer`、`python-dotenv`。开发依赖：`pytest`。
- `uv.lock` 存在且与 `pyproject.toml` 一致；`uv sync` 可在新环境完成安装。
- 包结构：

```text
src/novagent/
├── __init__.py
├── __main__.py
├── core/
│   ├── __init__.py
│   ├── state.py
│   └── paths.py
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
  1. 解析并自动创建 workspace（`parents=True, exist_ok=True`）；
  2. 构造 `RuntimeState`，调用 `create_model()`，`build_tools(state)` 后 `bind_tools`；
  3. 工具调用循环：系统提示说明可用工具与 workspace，追加用户任务后调用模型；若返回 `tool_calls` 则逐个执行并回填 `ToolMessage`（工具异常转为错误文本消息），再次调用模型；无 `tool_calls` 时输出最终回答并结束；最大迭代 25 次，达到上限输出提示并退出；
  4. `OPENAI_API_KEY` 缺失等配置错误以清晰错误信息退出（非零退出码），不打印未捕获 traceback；
- `python -m novagent` 与控制台脚本 `novagent` 行为一致（`__main__.py` 调用 `cli.app`）。

## tests

- `tests/` 使用 pytest 覆盖：路径安全（`..` 与绝对路径逃逸）、三个文件工具语义（含多匹配报错且文件不变）、grep 参数行为、bash 的 cwd 与超时、`build_tools` 返回 5 个工具及命名、`create_model` 读取 `.env` 与缺 key 报错、CLI workspace 自动创建与缺 key 清晰报错（typer CliRunner）；
- 全部测试离线运行，不发起真实网络请求。
