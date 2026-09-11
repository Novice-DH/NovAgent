"""上下文监控节点（context_monitor_node / context_monitor_route）离线单元测试。"""

import json

from langchain_core.messages import AIMessage, HumanMessage

import novagent.graph.nodes as graph_nodes
from novagent.graph.memory import (
    build_layered_memory,
    format_layered_memory_for_prompt,
)
from novagent.graph.nodes import context_monitor_node, context_monitor_route


class CountingModel:
    """get_num_tokens_from_messages 返回固定值并记录入参。"""

    def __init__(self, token_count):
        self.token_count = token_count
        self.calls = []

    def get_num_tokens_from_messages(self, messages):
        self.calls.append(list(messages))
        return self.token_count


class ExplodingModel:
    """估算调用始终抛错，触发 fallback。"""

    def get_num_tokens_from_messages(self, messages):
        raise RuntimeError("tokenizer unavailable")


def _state(**overrides):
    state = {
        "messages": [HumanMessage("hello"), AIMessage("world")],
        "task": "demo task",
    }
    state.update(overrides)
    return state


def _payload_text(state):
    return format_layered_memory_for_prompt(build_layered_memory(state))


def _forbidden_create_model(*args, **kwargs):
    raise AssertionError("context_monitor_node must not call create_model")


def test_exact_estimation_with_model():
    model = CountingModel(123)
    state = _state()

    result = context_monitor_node(state, model=model)

    assert set(result.keys()) == {
        "context_token_count",
        "context_should_compress",
        "context_next_node",
    }
    assert result["context_token_count"] == 123
    counted = model.calls[0]
    assert len(counted) == 3
    assert counted[:2] == state["messages"]
    payload = counted[2]
    assert isinstance(payload, HumanMessage)
    assert json.loads(payload.content) == json.loads(_payload_text(state))


def test_fallback_without_model(monkeypatch):
    monkeypatch.setattr(graph_nodes, "create_model", _forbidden_create_model)
    state = _state()

    result = context_monitor_node(state, model=None)

    total_text = "hello" + "world" + _payload_text(state)
    assert result["context_token_count"] == len(total_text) // 4
    assert result["context_should_compress"] is False
    assert result["context_next_node"] == "verifier"


def test_fallback_on_model_exception(monkeypatch):
    monkeypatch.setattr(graph_nodes, "create_model", _forbidden_create_model)
    state = _state()

    result = context_monitor_node(state, model=ExplodingModel())

    total_text = "hello" + "world" + _payload_text(state)
    assert result["context_token_count"] == len(total_text) // 4


def test_threshold_comparison():
    state = _state(context_token_limit=1000)

    equal = context_monitor_node(state, model=CountingModel(1000))
    assert equal["context_should_compress"] is False

    above = context_monitor_node(state, model=CountingModel(1001))
    assert above["context_should_compress"] is True


def test_threshold_default_limit():
    below = context_monitor_node(_state(), model=CountingModel(400_000))
    assert below["context_should_compress"] is False

    above = context_monitor_node(_state(), model=CountingModel(400_001))
    assert above["context_should_compress"] is True


def test_next_node_passthrough():
    explicit = context_monitor_node(
        _state(context_next_node="planner"), model=CountingModel(1)
    )
    assert explicit["context_next_node"] == "planner"

    missing = context_monitor_node(_state(), model=CountingModel(1))
    assert missing["context_next_node"] == "verifier"


def test_route_priority():
    assert (
        context_monitor_route(_state(passed=True, context_should_compress=True))
        == "final"
    )
    assert (
        context_monitor_route(_state(passed=False, context_should_compress=True))
        == "context_compressor"
    )
    assert (
        context_monitor_route(
            _state(
                passed=False,
                context_should_compress=False,
                context_next_node="planner",
            )
        )
        == "planner"
    )
    assert (
        context_monitor_route(_state(passed=False, context_should_compress=False))
        == "verifier"
    )


def test_does_not_mutate_state(monkeypatch):
    monkeypatch.setattr(graph_nodes, "create_model", _forbidden_create_model)
    state = _state(context_token_limit=10, context_next_node="planner")
    snapshot = json.dumps(state, sort_keys=True, default=str)

    context_monitor_node(state, model=CountingModel(5))
    context_monitor_node(state, model=None)

    assert json.dumps(state, sort_keys=True, default=str) == snapshot
