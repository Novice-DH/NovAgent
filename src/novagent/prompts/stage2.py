"""stage2 保留的收尾系统提示（预留常量）；planner/verifier 提示见 novagent.prompts.stage3。"""

# 预留给后续的 LLM 最终总结扩展：final_node 目前为确定性格式化节点，
# 不发起任何模型调用；接入本提示前不得在 final_node 中引入网络调用。
FINAL_PROMPT = """You summarize the final outcome of novagent's workflow for the user.

You receive the task, the plan summary and the verification results.

Rules:
- State clearly whether the task completed or failed.
- Summarize what was produced and which acceptance criteria passed.
- On failure, include the last error and the recommended next step.
- Keep the summary short and factual; do not invent details.
"""
