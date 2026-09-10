"""stage2 LangGraph 工作流组装：planner → actor → verifier 循环。"""

from functools import partial
from typing import Optional

from langgraph.graph import END, START, StateGraph

from novagent.graph.nodes import (
    actor_node,
    final_node,
    planner_node,
    verifier_node,
    verifier_route,
)
from novagent.graph.state import NovGraphState


def build_workflow(*, model=None):
    """组装并编译 stage2 工作流图。

    ``model`` 为离线注入的聊天模型；None 时各节点内部调用
    ``create_model()``，行为与无参调用一致。
    """
    graph = StateGraph(NovGraphState)
    graph.add_node("planner", partial(planner_node, model=model))
    graph.add_node("actor", partial(actor_node, model=model))
    graph.add_node("verifier", partial(verifier_node, model=model))
    graph.add_node("final", final_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "actor")
    graph.add_edge("actor", "verifier")
    graph.add_conditional_edges(
        "verifier",
        verifier_route,
        {
            "final": "final",
            "planner": "planner",
        },
    )
    graph.add_edge("final", END)
    return graph.compile()
