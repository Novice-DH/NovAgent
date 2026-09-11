"""stage3 LangGraph 工作流组装：planner(supervisor) → 上下文监控/压缩 → verifier 循环。"""

from functools import partial

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from novagent.graph.nodes import (
    context_compressor_node,
    context_compressor_route,
    context_monitor_node,
    context_monitor_route,
    final_node,
    planner_node,
    verifier_node,
)
from novagent.graph.state import NovGraphState


def build_complex_workflow(*, model=None):
    """组装并编译 stage3 工作流图。

    ``model`` 为离线注入的聊天模型；None 时各节点内部调用
    ``create_model()``，行为与无参调用一致。planner 在图上下文中通过
    stream writer 上报协调事件（含受托专家 Agent 的内部事件），每个
    事件复制并补 ``"node": "planner"`` 后进入 custom 流，供
    ``stream_mode="custom"`` 的消费方实时读取；不消费 custom 流的
    场景下写入被静默丢弃。
    """
    graph = StateGraph(NovGraphState)

    def _planner(state):
        stream_writer = get_stream_writer()

        def _writer(event):
            stream_writer({**event, "node": "planner"})

        return planner_node(state, model=model, on_event=_writer)

    graph.add_node("planner", _planner)
    graph.add_node("context_monitor", partial(context_monitor_node, model=model))
    graph.add_node("context_compressor", context_compressor_node)
    graph.add_node("verifier", partial(verifier_node, model=model))
    graph.add_node("final", final_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "context_monitor")
    graph.add_conditional_edges(
        "context_monitor",
        context_monitor_route,
        {
            "context_compressor": "context_compressor",
            "verifier": "verifier",
            "planner": "planner",
            "final": "final",
        },
    )
    graph.add_conditional_edges(
        "context_compressor",
        context_compressor_route,
        {
            "verifier": "verifier",
            "planner": "planner",
            "final": "final",
        },
    )
    graph.add_edge("verifier", "context_monitor")  # 验证后也过 monitor
    graph.add_edge("final", END)
    return graph.compile()
