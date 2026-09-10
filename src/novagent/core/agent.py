"""驱动 stage2 LangGraph 工作流，把图事件解析为统一事件流。"""

from pathlib import Path
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel

from novagent.core.state import RuntimeState
from novagent.graph.workflow import build_workflow


def stream_agent_events(
    task: str,
    *,
    workspace: Path,
    max_attempts: int = 3,
    model: Optional[BaseChatModel] = None,
):
    """运行 planner→actor→verifier 工作流，逐事件产出统一格式 dict。

    每个事件含 ``type`` 与 ``node`` 字段：

    - ``node_output``：某节点完成（``updates`` 流解析），携带该节点的
      关键输出——planner（plan_summary/todos/acceptance_criteria/
      verification_commands）、verifier（passed/reason/
      verification_results/verification_checks）、final（final_answer）；
    - ``ai_message``/``tool_call``/``tool_result``/``final_answer``：
      actor ReAct 循环的内部事件（``custom`` 流实时转发）。

    ``max_attempts`` 是验证重试预算，经 ``verifier_route`` 决定失败后
    回 planner 修订还是进入 final 节点。
    """
    state = RuntimeState(workspace=workspace)
    graph = build_workflow(model=model)
    inputs = {"task": task, "runtime": state, "max_attempts": max_attempts}

    for mode, payload in graph.stream(inputs, stream_mode=["updates", "custom"]):
        if mode == "custom":
            event = dict(payload)
            event.setdefault("node", "actor")
            yield event
            continue
        for node_name, update in payload.items():
            if node_name == "planner":
                yield {
                    "type": "node_output",
                    "node": "planner",
                    "plan_summary": update.get("plan_summary", ""),
                    "todos": update.get("todos", []),
                    "acceptance_criteria": update.get("acceptance_criteria", []),
                    "verification_commands": update.get("verification_commands", []),
                }
            elif node_name == "verifier":
                last_error = update.get("last_error") or ""
                if update.get("passed"):
                    reason = update.get("final_answer", "")
                else:
                    # last_error 由命令失败详情与结论原因拼成；事件层的
                    # reason 只取结论原因，命令详情见 verification_results。
                    reason = last_error.splitlines()[-1] if last_error else ""
                yield {
                    "type": "node_output",
                    "node": "verifier",
                    "passed": update.get("passed", False),
                    "reason": reason,
                    "verification_results": update.get("verification_results", []),
                    "verification_checks": update.get("verification_checks", []),
                }
            elif node_name == "final":
                yield {
                    "type": "node_output",
                    "node": "final",
                    "final_answer": update.get("final_answer", ""),
                }
