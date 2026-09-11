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
- 完成时间: 2026-09-11T18:27:27.660Z
- 摘要: 独立验收通过：全量测试 195 passed（Verifier 重跑），10 条 RISK_PATTERNS、三模式审批分流（拒绝路径确证不调用 execute_command）、checkpoint 三级与 git 影子仓库恢复、trace 统计与 head/tail 截断、CLI 四个新选项及错误路径均经代码审读与直接命令执行证实。改动范围与交接一致，无 pyproject/uv.lock 变更，参考文档保持未跟踪。19/19 项 passed，无阻塞。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1: Scenario: 风险命令分类 WHEN 对 10 类风险模式（pip install、uv add、uv sync、uv pip install、npm install、pnpm install、yarn install、yarn add、curl/wget、uvicorn、python -m http.server）各构造命令调用 `classify_command_risk` THEN 全部返回非 None 的风险原因字符串 AND 复合命令 `echo ok && pip install flask` 命中 AND 匹配不区分大小写 AND 安全命令（`echo hi`、`python app.py`）返回 None。 | 独立运行 classify_command_risk：11 类风险命令全部命中、复合与大小写命中、安全命令返回 None；RISK_PATTERNS（approval.py L15-35）与 spec 10 条正则逐字符一致；tests/test_approval.py::test_risk_patterns_match_expected_reasons 等 13 例参数化通过 |
| A2 | passed | brief.md | A2: Scenario: 审批模式归一 WHEN 调用 `normalize_approval_mode` 传入 `None`、`""`、`"bogus"` THEN 一律返回 `"inline"` AND 传入 `inline`/`auto`/`deny` 原样返回 AND `VALID_APPROVAL_MODES == {"inline", "auto", "deny"}`。 | 独立验证 normalize_approval_mode(None/""/"bogus")=="inline"、三合法值原样返回、VALID_APPROVAL_MODES=={inline,auto,deny}；test_normalize_approval_mode_falls_back_to_inline 通过 |
| A3 | passed | brief.md | A3: Scenario: 审批数据类 WHEN 构造 `ApprovalRequest(command=..., risk_reason=...)` THEN `id` 以 `"approval-"` 开头、`tool_name == "BashTool"` AND `ApprovalDecision(approved=True)` 的 `reason` 默认为空字符串。 | 独立验证 ApprovalRequest.id 以 approval- 开头且 tool_name=="BashTool"、ApprovalDecision(approved=True).reason==""；test_approval_dataclasses 另校验 id 长度=approval-+8 |
| A4 | passed | brief.md | A4: Scenario: auto 模式放行 WHEN RuntimeState 为 `approval_mode="auto"` 且以 monkeypatch 的 `execute_command` 驱动 bash 工具执行 `pip install flask` THEN 底层执行被调用且返回文本含 `requires_approval: True` 与 `approved: True` AND `state.approval_log` 追加一条含 `command`、`risk_reason`、`mode=="auto"`、`approved is True` 的记录。 | tests/test_approval.py::test_auto_mode_executes_risky_command_and_marks_result：monkeypatch 的 execute_command 被调用、输出含 requires_approval: True/approved: True、approval_log 含 command/risk_reason/mode=auto/approved is True |
| A5 | passed | brief.md | A5: Scenario: deny 模式拒绝 WHEN `approval_mode="deny"` 驱动 bash 工具执行风险命令 THEN 底层执行不被调用 AND 返回文本含 `human approval required` 与风险原因。 | test_deny_mode_blocks_execution：execute_command.calls==[] 且输出含 human approval required 与风险原因；代码路径 bash_tool.py 在执行前返回 |
| A6 | passed | brief.md | A6: Scenario: inline 批准 WHEN `approval_mode="inline"`、handler 记录收到的请求并返回 `ApprovalDecision(approved=True)` THEN handler 恰被调用一次且请求的 `command`/`risk_reason`/`tool_name` 正确 AND 底层执行被调用；handler 返回裸 `True` 时行为相同。 | test_inline_approved_calls_handler_once_then_executes 验证 handler 恰调一次且请求字段正确后执行；test_inline_accepts_bare_boolean_decisions 验证裸 True 行为相同 |
| A7 | passed | brief.md | A7: Scenario: inline 拒绝 WHEN handler 返回 `ApprovalDecision(approved=False)` 或裸 `False` THEN 底层执行不被调用 AND 返回文本含 `human rejected` AND 安全命令不触发 handler。 | test_inline_rejected_blocks_execution：不执行且输出含 human rejected；test_safe_command_bypasses_handler_and_log 用抛异常 handler 证明安全命令不触发 handler |
| A8 | passed | brief.md | A8: Scenario: inline 无 handler WHEN `approval_mode="inline"` 且 `approval_handler` 为 None THEN 风险命令被拒绝（等同 deny）且不执行。 | test_inline_without_handler_denies_like_deny：inline 无 handler 时不执行并返回 human approval required |
| A9 | passed | brief.md | A9: Scenario: CLI 参数与恢复入口 WHEN `novagent run --help` THEN 帮助文本包含 `--approval-mode`（含 inline/auto/deny）、`--checkpoint-mode`（含 light/strict/off）、`--trace-mode`（含 on/off）、`--resume` AND 无 `--resume` 且省略 task 时以非零退出码报错 AND `--resume` 指向无检查点的目录时干净报错（非零退出、错误含 resume 路径）。 | 实际运行 uv run novagent run --help 含 --approval-mode(inline/auto/deny)/--checkpoint-mode(light/strict/off)/--trace-mode(on/off)/--resume；无 task 退出码 2（实测）；--resume 指向空目录退出码 1 且错误含路径（实测）；tests/test_cli.py 同步覆盖 |
| A10 | passed | brief.md | A10: Scenario: light 检查点 WHEN 以 light 模式对含文件的临时 workspace 调用 `CheckpointManager.save(state, status="running", latest_node="planner")` THEN `checkpoint.json` 与 `RECOVERY.md` 生成 AND `checkpoint.json` 含 `task`、`status`、`latest_node` AND `RECOVERY.md` 含 `resume_command(workspace)` 的命令文本（`novagent run --resume ...`）AND 返回事件 `type=="checkpoint_saved"`。 | tests/test_checkpoint.py::test_light_save_writes_metadata_and_recovery：checkpoint.json+RECOVERY.md 生成、含 task/status/latest_node、RECOVERY.md 含 resume_command 文本、返回 type==checkpoint_saved 事件 |
| A11 | passed | brief.md | A11: Scenario: off 模式不落盘 WHEN checkpoint 模式为 off THEN `save` 返回 None 且不创建 `.novagent/checkpoints` 目录。 | test_off_mode_writes_nothing：save 返回 None 且 .novagent/checkpoints 目录未创建；checkpoint.py off 早退 |
| A12 | passed | brief.md | A12: Scenario: strict 附加产物 WHEN strict 模式带 `event` 调用 `save` THEN 额外生成 `state.json` 与 `events.jsonl` AND `events.jsonl` 每次调用追加一行 JSON。 | test_strict_mode_writes_state_and_appends_events：两次调用 events.jsonl 恰两行 JSON、state.json 生成；无 event 调用不触碰事件日志亦被覆盖 |
| A13 | passed | brief.md | A13: Scenario: git 快照与恢复 WHEN save 后修改 workspace 内已有文件再 `load_resume_inputs` THEN 文件内容恢复为快照时内容 AND git 不可用（monkeypatch 抛错）时 `save` 不抛异常且 `checkpoint.json` 记录非空 `git_error`。 | test_git_snapshot_restores_files_on_resume：save 后改文件再 load_resume_inputs 内容恢复为 v1；test_git_failure_is_degraded_not_raised：_run_git 抛错时 save 不抛且 git_error 非空 |
| A14 | passed | brief.md | A14: Scenario: 恢复输入重建 WHEN `load_resume_inputs` 读取存在检查点的 workspace THEN 返回的 inputs 含检查点中的 `task` 与 `attempts` AND 无检查点时抛 `FileNotFoundError`。 | test_git_snapshot_restores_files_on_resume 断言 inputs 含检查点 task/attempts；test_load_resume_inputs_without_checkpoint_raises 抛 FileNotFoundError |
| A15 | passed | brief.md | A15: Scenario: trace 记录与统计 WHEN 以 on 模式依次 `start`、记录 custom 事件（tool_call、失败 tool_result、handoff、checkpoint_saved）、图节点更新并 `end` THEN `trace.json`/`events.jsonl`/`timeline.md` 生成 AND `node_visits`/`tool_calls`/`failed_tool_calls`/`handoff_count`/`checkpoint_count` 与输入一致 AND `approval_count` 等于 `runtime.approval_log` 中风险分流条数 AND `trace.json` 含 `timeline_head`（≤20 条）、`timeline_tail`（≤80 条）与 `timeline_omitted` AND `timeline.md` 含事件行文本。 | test_trace_records_stats_and_files：三产物生成、各计数与输入一致、approval_count==approval_log 条数、timeline_head<=20/tail<=80 且 timeline.md 含事件行；test_timeline_head_tail_truncation 验证 152 行截断为 20/80/52 |
| A16 | passed | brief.md | A16: Scenario: trace off WHEN trace 模式为 off THEN 各 record 方法为 no-op 且不创建 `.novagent/traces` 目录。 | test_off_mode_is_noop：各 record 方法后计数为 0、timeline 为空且 .novagent/traces 未创建 |
| A17 | passed | brief.md | A17: Scenario: 端到端集成 WHEN 以 FakeModel 驱动 `stream_agent_events`（light + trace on）跑通完整工作流 THEN 事件流出现 `checkpoint_saved` 事件 AND 结束后 `checkpoint.json` 的 `status=="finished"`、`trace.json` 的 `status=="finished"` 且 `checkpoint_count>0`、`node_visits` 非空 AND RuntimeState 上的审批配置对 codeAgent 的 bash 工具生效（FakeModel 发起风险 bash 调用时被审批分流）。 | tests/test_agent_loop.py::test_checkpoint_and_trace_integrated_in_stream：事件流含 checkpoint_saved、checkpoint.json/trace.json status==finished、checkpoint_count>=1、node_visits 含 planner/verifier/final；test_approval_config_flows_through_delegated_code_agent 证明 deny 配置对 codeAgent 的 bash 生效 |
| A18 | passed | brief.md | A18: Scenario: 中断保存 WHEN FakeModel 在流中途抛出 `KeyboardInterrupt` THEN `checkpoint.json` 与 `trace.json` 的 `status=="interrupted"` AND 异常向上传播给调用方。 | test_keyboard_interrupt_saves_interrupted_checkpoint：KeyboardInterrupt 向上传播且两文件 status==interrupted；test_consumer_close_persists_interrupted_state 覆盖 GeneratorExit 路径 |
| A19 | passed | brief.md | A19: Scenario: 既有行为不破坏 WHEN 在仓库根目录运行 `uv sync` THEN 成功且无新增依赖、`uv.lock` 不变 AND `uv run pytest` 全部通过（离线）。 | Verifier 本人运行 uv run pytest -q 得 195 passed (17.05s)；uv sync exit 0 且 pyproject.toml/uv.lock 前后 porcelain 均为空；《项目篇规划 - 副本.md》保持 untracked |

## 检查

_没有记录 Runtime 检查。_

## 阻塞项

_无。_

## 风险与跳过的工作

- checkpoint/trace 落盘失败静默降级（吞 OSError 不告警），符合规格的单点失败不中断约束，但生产环境可能掩盖磁盘问题
- CLI 帮助文本中长描述在窄终端被 rich 截断显示（选项值仍在完整输出中，测试按全量文本断言通过）

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 1 | pass | — | 独立验收通过：全量测试 195 passed（Verifier 重跑），10 条 RISK_PATTERNS、三模式审批分流（拒绝路径确证不调用 execute_command）、checkpoint 三级与 git 影子仓库恢复、trace 统计与 head/tail 截断、CLI 四个新选项及错误路径均经代码审读与直接命令执行证实。改动范围与交接一致，无 pyproject/uv.lock 变更，参考文档保持未跟踪。19/19 项 passed，无阻塞。 | 2026-09-11T18:27:27.660Z |



## 结论

独立验收通过：全量测试 195 passed（Verifier 重跑），10 条 RISK_PATTERNS、三模式审批分流（拒绝路径确证不调用 execute_command）、checkpoint 三级与 git 影子仓库恢复、trace 统计与 head/tail 截断、CLI 四个新选项及错误路径均经代码审读与直接命令执行证实。改动范围与交接一致，无 pyproject/uv.lock 变更，参考文档保持未跟踪。19/19 项 passed，无阻塞。
