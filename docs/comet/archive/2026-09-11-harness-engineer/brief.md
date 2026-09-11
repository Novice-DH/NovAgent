# 目标

实现项目篇阶段五「引入 Harness Engineer」：给 novagent 加上 Harness Engineering 的三大安全网与可观测性措施——

1. **人类在环审批**：高风险 shell 命令（依赖安装、网络下载、长驻服务）在执行前经风险分类，按 `inline` / `auto` / `deny` 三种模式分流，`inline` 由人类确认后执行；
2. **Checkpoint 检查点**：运行过程中按 `light` / `strict` / `off` 三级保存检查点（元数据 + 人类可读恢复指南 + git 快照，strict 额外保存完整图状态与事件日志），中断后可恢复；
3. **Trace 链路追踪**：按 `on` / `off` 记录每次运行的完整事件日志与统计（节点访问、工具调用、审批、检查点、交接数），产出 `trace.json` / `events.jsonl` / `timeline.md`。

三者统一集成进 `stream_agent_events` 主循环与 typer CLI。

# 范围

## 来源覆盖（Source coverage）

需求来源：用户随请求提供的《项目篇规划 - 副本.md》（仓库根，untracked，用户明确声明该文档不计入项目资产、不得提交）。全文 2642 行已完整读取（分两次读入，无不可访问单元），覆盖状态 `complete`。用户当前请求只取其中「阶段五：引入 Harness Engineer」（第 1554–2056 行）；其余章节归类如下，不进入本 change 范围。

| 来源单元 | 位置 | 状态 | 去向 |
| --- | --- | --- | --- |
| U1 阶段五设计目标（三措施总述） | L1556–1563 | complete | 目标；Spec 全部小节 |
| U2 架构-审批机制（分流图、RISK_PATTERNS、三模式） | L1566–1608 | complete | Spec core.approval / tools.bash_tool；A1–A8 |
| U3 架构-Checkpoint（目录结构、三级模式、恢复流程） | L1610–1633 | complete | Spec core.checkpoint；A10–A14 |
| U4 架构-Trace（目录结构、统计 JSON） | L1635–1669 | complete | Spec core.trace；A15–A16 |
| U5 演示效果（审批提示、checkpoint、resume） | L1671–1711 | complete | 归类为示例场景；行为映射进 A9/A10/A17 |
| U6 讲解要点 | L1713–1719 | complete | 背景说明，非可执行 |
| U7 核心代码（approval/classify、_resolve_approval、run_bash、CheckpointManager.save、agent.py 集成） | L1721–1823 | complete | Spec 各模块（按本仓库既有约定适配，见决策 D1–D3） |
| U8 Vibe Coding Prompt Step 1–6（含 10 条 RISK_PATTERNS 全文、CheckpointManager/load_resume_inputs/resume_command/build_recovery_markdown、TraceRecorder 全规格、agent 集成签名、CLI 参数表、测试运行方式） | L1826–2055 | complete | Spec 的权威实现规格；各验收项 |
| 其余章节（阶段一～四已实现并归档；阶段六 TUI/Session；总结、拍摄建议、Vibe 使用指南） | 其余行 | complete | 阶段一～四为既有基线（superseded by 已归档 change）；阶段六与文档性内容为非目标 |

来源无 `[blocking]` 单元：所有可执行单元均映射到 Spec 与验收 ID；源文档与本仓库现状的差异（函数签名、返回类型、CLI 形态）以适配决策记录在「决策」，不构成歧义。

## 实现范围

- 新增 `src/novagent/core/approval.py`：`RISK_PATTERNS`（源文档 10 条正则）、`classify_command_risk`、`ApprovalRequest` / `ApprovalDecision`、`VALID_APPROVAL_MODES`、`normalize_approval_mode`。
- 修改 `src/novagent/core/state.py`：`RuntimeState` 新增 `approval_mode`（默认 `"inline"`）、`approval_handler`（默认 `None`）、`checkpoint_mode`（默认 `"light"`）、`trace_mode`（默认 `"on"`）、`trace_id`（默认 `None`）、`approval_log`（默认空列表）。
- 修改 `src/novagent/tools/bash_tool.py`：`bash()` 执行前经 `_resolve_approval(state, command)` 分流——安全命令直接执行；`auto` 放行并标记；`deny`（或 `inline` 无 handler）拒绝且不执行；`inline` 调用 `state.approval_handler(request)` 等待决策；每次风险分流追加 `state.approval_log`。
- 新增 `src/novagent/core/checkpoint.py`：`CheckpointManager`（`save` / `load_resume_inputs`）、`normalize_checkpoint_mode`、`resume_command`、`build_recovery_markdown`；检查点目录 `workspace/.novagent/checkpoints/`，三级模式 `light` / `strict` / `off`。
- 新增 `src/novagent/core/trace.py`：`TraceRecorder`（`start` / `record_custom_event` / `record_graph_update` / `end`）、`normalize_trace_mode`；追踪目录 `workspace/.novagent/traces/{trace_id}/`，两级模式 `on` / `off`。
- 修改 `src/novagent/core/agent.py`：`stream_agent_events` 新增 `approval_mode` / `approval_handler` / `checkpoint_mode` / `trace_mode` / `resume_workspace` 参数；创建 CheckpointManager 与 TraceRecorder；在启动、每个图节点更新后、失败的 tool_result、正常结束、KeyboardInterrupt 时保存检查点；全程记录 trace；支持 `--resume` 恢复路径。
- 修改 `src/novagent/cli/app.py`：`run` 命令新增 `--approval-mode` / `--checkpoint-mode` / `--trace-mode` / `--resume`；`task` 参数改为可选（`--resume` 时可省略，从检查点读取）；`inline` 审批的终端确认 handler（rich 提示 + y/n 输入）；checkpoint 与中断信息的终端渲染。
- 更新测试（全部离线：FakeModel / monkeypatch / 临时 workspace，不发起网络请求）：新增 `tests/test_approval.py`、`tests/test_checkpoint.py`、`tests/test_trace.py`；更新 `tests/test_bash_tool.py`、`tests/test_agent_loop.py`、`tests/test_cli.py`。

# 非目标

- 不实现阶段六（Claw 交互层）：不做 Textual TUI、`tui/approval.py` 审批弹窗、intent router、chat responder、多轮 session（`core/session.py`）、`build_entry_workflow`；审批交互仅做 CLI 终端提示。
- 不实现 `run_bash` 自由函数与 `_looks_dangerous` 危险命令拦截、`_handle_tail_command` 特殊命令处理（源文档「最终形态」描述，本仓库从未实现，也不属于本阶段三措施）。
- 审批只挂在 BashTool：不拦截 verifier 的 `_run_verification_commands`（planner 验证命令的直执行路径）与 `execute_command` 的其他直接调用方。
- 不修改图结构（`workflow.py`）、图节点（`nodes.py`）、提示词常量、既有事件 schema；只新增 `checkpoint_saved` 事件类型。
- 不新增运行依赖（git 快照经 `subprocess` 调用系统 git，不可用时降级记录 `git_error`，不失败）。
- 全部自动化验收离线运行（FakeModel + 临时 workspace），不发起真实 LLM/网络调用；无 API key 环境必须可全部验证。
- 不把参考文档《项目篇规划 - 副本.md》提交进仓库。

# 验收示例

- A1: Scenario: 风险命令分类 WHEN 对 10 类风险模式（pip install、uv add、uv sync、uv pip install、npm install、pnpm install、yarn install、yarn add、curl/wget、uvicorn、python -m http.server）各构造命令调用 `classify_command_risk` THEN 全部返回非 None 的风险原因字符串 AND 复合命令 `echo ok && pip install flask` 命中 AND 匹配不区分大小写 AND 安全命令（`echo hi`、`python app.py`）返回 None。
- A2: Scenario: 审批模式归一 WHEN 调用 `normalize_approval_mode` 传入 `None`、`""`、`"bogus"` THEN 一律返回 `"inline"` AND 传入 `inline`/`auto`/`deny` 原样返回 AND `VALID_APPROVAL_MODES == {"inline", "auto", "deny"}`。
- A3: Scenario: 审批数据类 WHEN 构造 `ApprovalRequest(command=..., risk_reason=...)` THEN `id` 以 `"approval-"` 开头、`tool_name == "BashTool"` AND `ApprovalDecision(approved=True)` 的 `reason` 默认为空字符串。
- A4: Scenario: auto 模式放行 WHEN RuntimeState 为 `approval_mode="auto"` 且以 monkeypatch 的 `execute_command` 驱动 bash 工具执行 `pip install flask` THEN 底层执行被调用且返回文本含 `requires_approval: True` 与 `approved: True` AND `state.approval_log` 追加一条含 `command`、`risk_reason`、`mode=="auto"`、`approved is True` 的记录。
- A5: Scenario: deny 模式拒绝 WHEN `approval_mode="deny"` 驱动 bash 工具执行风险命令 THEN 底层执行不被调用 AND 返回文本含 `human approval required` 与风险原因。
- A6: Scenario: inline 批准 WHEN `approval_mode="inline"`、handler 记录收到的请求并返回 `ApprovalDecision(approved=True)` THEN handler 恰被调用一次且请求的 `command`/`risk_reason`/`tool_name` 正确 AND 底层执行被调用；handler 返回裸 `True` 时行为相同。
- A7: Scenario: inline 拒绝 WHEN handler 返回 `ApprovalDecision(approved=False)` 或裸 `False` THEN 底层执行不被调用 AND 返回文本含 `human rejected` AND 安全命令不触发 handler。
- A8: Scenario: inline 无 handler WHEN `approval_mode="inline"` 且 `approval_handler` 为 None THEN 风险命令被拒绝（等同 deny）且不执行。
- A9: Scenario: CLI 参数与恢复入口 WHEN `novagent run --help` THEN 帮助文本包含 `--approval-mode`（含 inline/auto/deny）、`--checkpoint-mode`（含 light/strict/off）、`--trace-mode`（含 on/off）、`--resume` AND 无 `--resume` 且省略 task 时以非零退出码报错 AND `--resume` 指向无检查点的目录时干净报错（非零退出、错误含 resume 路径）。
- A10: Scenario: light 检查点 WHEN 以 light 模式对含文件的临时 workspace 调用 `CheckpointManager.save(state, status="running", latest_node="planner")` THEN `checkpoint.json` 与 `RECOVERY.md` 生成 AND `checkpoint.json` 含 `task`、`status`、`latest_node` AND `RECOVERY.md` 含 `resume_command(workspace)` 的命令文本（`novagent run --resume ...`）AND 返回事件 `type=="checkpoint_saved"`。
- A11: Scenario: off 模式不落盘 WHEN checkpoint 模式为 off THEN `save` 返回 None 且不创建 `.novagent/checkpoints` 目录。
- A12: Scenario: strict 附加产物 WHEN strict 模式带 `event` 调用 `save` THEN 额外生成 `state.json` 与 `events.jsonl` AND `events.jsonl` 每次调用追加一行 JSON。
- A13: Scenario: git 快照与恢复 WHEN save 后修改 workspace 内已有文件再 `load_resume_inputs` THEN 文件内容恢复为快照时内容 AND git 不可用（monkeypatch 抛错）时 `save` 不抛异常且 `checkpoint.json` 记录非空 `git_error`。
- A14: Scenario: 恢复输入重建 WHEN `load_resume_inputs` 读取存在检查点的 workspace THEN 返回的 inputs 含检查点中的 `task` 与 `attempts` AND 无检查点时抛 `FileNotFoundError`。
- A15: Scenario: trace 记录与统计 WHEN 以 on 模式依次 `start`、记录 custom 事件（tool_call、失败 tool_result、handoff、checkpoint_saved）、图节点更新并 `end` THEN `trace.json`/`events.jsonl`/`timeline.md` 生成 AND `node_visits`/`tool_calls`/`failed_tool_calls`/`handoff_count`/`checkpoint_count` 与输入一致 AND `approval_count` 等于 `runtime.approval_log` 中风险分流条数 AND `trace.json` 含 `timeline_head`（≤20 条）、`timeline_tail`（≤80 条）与 `timeline_omitted` AND `timeline.md` 含事件行文本。
- A16: Scenario: trace off WHEN trace 模式为 off THEN 各 record 方法为 no-op 且不创建 `.novagent/traces` 目录。
- A17: Scenario: 端到端集成 WHEN 以 FakeModel 驱动 `stream_agent_events`（light + trace on）跑通完整工作流 THEN 事件流出现 `checkpoint_saved` 事件 AND 结束后 `checkpoint.json` 的 `status=="finished"`、`trace.json` 的 `status=="finished"` 且 `checkpoint_count>0`、`node_visits` 非空 AND RuntimeState 上的审批配置对 codeAgent 的 bash 工具生效（FakeModel 发起风险 bash 调用时被审批分流）。
- A18: Scenario: 中断保存 WHEN FakeModel 在流中途抛出 `KeyboardInterrupt` THEN `checkpoint.json` 与 `trace.json` 的 `status=="interrupted"` AND 异常向上传播给调用方。
- A19: Scenario: 既有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且无新增依赖、`uv.lock` 不变 AND `uv run pytest` 全部通过（离线）。

# 约束与不变量

- 审批拒绝与审批等待不得执行命令：`deny` 与未批准路径在 `execute_command` 之前返回。
- 检查点与 trace 的任何单点失败（git 缺失、JSON 写入异常、tokenizer 不可用等）不中断工作流：降级记录后继续。
- `approval_handler` 为同步可调用对象，运行于工具调用线程；CLI 的 inline handler 阻塞等待用户输入，y/yes 批准、n/no 拒绝（不区分大小写），EOF 视为拒绝。
- 检查点目录（`.novagent/checkpoints`）与 trace 目录（`.novagent/traces`）位于 workspace 内；git 影子仓库只读写该目录，不污染 workspace 用户文件、不在 workspace 创建 `.git`。
- 统一事件流向后兼容：既有事件类型的语义与相对顺序不变；新增 `checkpoint_saved` 事件（含 `mode`、`status`、`latest_node`、`path`）。
- resume 语义 = 恢复 workspace 文件到快照 + 重建 inputs（task/attempts，strict 另含 messages）+ 重新运行工作流；不是逐节点精确续跑。
- 全部测试离线运行（FakeModel + monkeypatch + 临时 workspace），兼容 Python >= 3.10。

# 决策

- D1 源文档的 `run_bash(state, ...)` 自由函数与 dict 返回值适配为本仓库既有约定：保留 `create_bash_tool(state)` 工厂与字符串返回值；审批分流实现在 `bash()` 闭包内，结构化审批信息经新增的 `RuntimeState.approval_log` 暴露（工具返回文本附带 `requires_approval`/`approved` 标记行），不改变事件层 `tool_result.result` 为字符串的既有 schema。
- D2 resume 的 CLI 形态适配：源文档为 `novagent --resume <workspace>`，本仓库为 typer 单命令 `run`，故定为 `novagent run [task] --resume <workspace>`；task 省略时取检查点中的 task，显式给出时覆盖。`--resume` 与 `--workspace` 同时给出且指向不同目录时报错退出。
- D3 git 快照采用检查点目录内的影子仓库（`git --git-dir=<checkpoints>/.git --work-tree=<workspace>`），对应源文档目录结构中 checkpoints 下的 `.git/` 条目；首次 save 时 `git init`。恢复经同配置的 `git checkout` 完成。
- D4 审批默认 `inline`、检查点默认 `light`、trace 默认 `on`（源文档明确）；`normalize_approval_mode` 对无效值回落 `inline`，`normalize_checkpoint_mode`/`normalize_trace_mode` 同构回落各自默认。
- D5 `approval_count` 语义 = 风险分流总次数（含 auto 自动放行），取自 `runtime.approval_log` 长度；`failed_tool_calls` 的判定规则 = tool_result 文本以 `Error` 开头，或首行为 `exit_code: <n>` 且 n≠0（确定性规则，兼容字符串结果 schema）。
- D6 strict 的图状态序列化：`messages` 经 langchain `messages_to_dict`/`messages_from_dict` 往返，其余可 JSON 字段原样；`runtime` 不序列化，恢复时按 workspace 重建。light 模式不保存消息，恢复 inputs 只含 task/attempts。
- D7 检查点保存时机：run 启动（`started`/`resumed`）、每个图节点 updates 事件后、失败的 tool_result（custom 流）、正常结束（`finished`）、KeyboardInterrupt（`interrupted`）；trace 的 `checkpoint_count` 只统计 `checkpoint_saved` 事件。
- D8 审批同样作用于 verifier 的 bash 工具（verifier 经 `create_bash_tool(runtime)` 构造工具，配置随 RuntimeState 生效）；planner 验证命令直执行路径不经过审批（非 BashTool 路径）。
- D9 `trace_id` 生成规则：`runtime.trace_id` 非空时直接使用，否则取 `uuid4().hex[:8]` 并回写 `runtime.trace_id`（与 `ApprovalRequest.id` 的短 id 风格一致）。

# 待解决问题

（无 `[blocking]` 项。）

# 验证预期

- `uv run pytest` 全部通过（离线，FakeModel + 临时 workspace + monkeypatch，无 API key 环境可运行）。
- `uv sync` 无新增运行依赖，`uv.lock` 不变。
- 手工冒烟（可选，需 API key）：`novagent run "..." --approval-mode inline --checkpoint-mode light --trace-mode on` 触发审批提示、`.novagent/checkpoints/` 与 `.novagent/traces/` 产物；Ctrl+C 后 `novagent run --resume <workspace>` 可恢复。
