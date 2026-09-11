"""graph.nodes 的 stage3 supervisor 行为（FakeModel，不发起网络请求）。"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from novagent.core.state import RuntimeState
from novagent.graph import nodes as graph_nodes
from novagent.graph.nodes import (
    PLANNER_PROMPT,
    planner_node,
    verifier_node,
)
from novagent.prompts import stage2, stage3


class FakeModel:
    """按序返回预设响应并记录调用与绑定工具。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        return self.responses.pop(0)


class FakeTavilyClient:
    """返回预设 Tavily search 响应。"""

    responses: list

    def __init__(self, api_key=None):
        self.api_key = api_key

    def search(self, query, **kwargs):
        return type(self).responses.pop(0)


@pytest.fixture(autouse=True)
def offline_tavily(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr(
        "novagent.tools.web_search_tool.load_dotenv", lambda *a, **k: False
    )
    FakeTavilyClient.responses = []
    monkeypatch.setattr(
        "novagent.tools.web_search_tool.TavilyClient", FakeTavilyClient
    )


def _tool_call(name, args, call_id):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
    )


def _state(workspace, **overrides):
    state = {"task": "demo task", "runtime": RuntimeState(workspace=workspace)}
    state.update(overrides)
    return state


def _plan_args():
    return {
        "plan_summary": "plan",
        "todos": [{"id": "t1", "content": "step"}],
        "acceptance_criteria": ["result exists"],
        "verification_commands": ["python -c 'pass'"],
    }


def test_planner_binds_three_tools(workspace):
    model = FakeModel([AIMessage(content="nothing to do.")])

    planner_node(_state(workspace), model=model)

    assert [tool.name for tool in model.bound_tools] == [
        "todo_write",
        "call_search_agent",
        "call_code_agent",
    ]


def test_planner_message_construction_first_run(workspace):
    model = FakeModel([AIMessage(content="done.")])

    planner_node(_state(workspace), model=model)

    system_message, human_message = model.calls[0]
    assert isinstance(system_message, SystemMessage)
    assert system_message.content == PLANNER_PROMPT
    assert PLANNER_PROMPT is stage3.PLANNER_PROMPT
    assert "demo task" in human_message.content
    assert "todo_write" in human_message.content


def test_planner_message_construction_revise(workspace):
    model = FakeModel([AIMessage(content="revised.")])
    state = _state(
        workspace,
        todos=[{"id": "t1", "content": "old", "status": "in_progress", "note": ""}],
        last_error="boom",
        verification_results=[
            {
                "command": "fail.cmd",
                "ok": False,
                "exit_code": 1,
                "stdout": "",
                "stderr": "boom detail",
            }
        ],
    )

    planner_node(state, model=model)

    system_message, human_message = model.calls[0]
    assert system_message.content == PLANNER_PROMPT
    assert isinstance(human_message, HumanMessage)
    assert "boom" in human_message.content
    assert "fail.cmd" in human_message.content


def test_planner_publishes_plan(workspace):
    events = []
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args(), "c1"),
            AIMessage(content="Plan is ready."),
        ]
    )

    update = planner_node(
        _state(workspace),
        model=model,
        on_event=events.append,
    )

    assert update["plan_summary"] == "plan"
    assert update["context_next_node"] == "verifier"
    assert update["todos"] == [
        {"id": "t1", "content": "step", "status": "pending", "note": ""}
    ]
    assert update["acceptance_criteria"] == ["result exists"]
    assert update["verification_commands"] == ["python -c 'pass'"]
    assert [event["type"] for event in events] == [
        "ai_message",
        "tool_call",
        "tool_result",
        "ai_message",
    ]
    assert events[0] == {"type": "ai_message", "content": ""}


def test_planner_delegates_search(workspace, monkeypatch):
    FakeTavilyClient.responses.append(
        {
            "answer": "LangGraph is a framework.",
            "results": [
                {
                    "title": "Docs",
                    "url": "https://example.com/docs",
                    "content": "official docs",
                    "score": 0.9,
                },
                {"url": "https://example.com/docs"},
            ],
        }
    )
    events = []
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args(), "c1"),
            _tool_call(
                "call_search_agent",
                {"instruction": "research LangGraph"},
                "c2",
            ),
            # 受托 searchAgent 内部：发起 web_search 后总结
            _tool_call("web_search", {"query": "LangGraph"}, "s1"),
            AIMessage(content="LangGraph is a framework."),
            # planner 第三轮：纯文本结束
            AIMessage(content="Research done, plan ready."),
        ]
    )

    update = planner_node(
        _state(workspace),
        model=model,
        on_event=events.append,
    )

    assert update["research_notes"] == "LangGraph is a framework."
    assert update["sources"] == [
        {
            "url": "https://example.com/docs",
            "title": "Docs",
            "content": "official docs",
            "score": 0.9,
        }
    ]
    (handoff,) = update["agent_handoffs"]
    assert handoff["from_agent"] == "planner"
    assert handoff["to_agent"] == "searchAgent"
    assert handoff["instruction"] == "research LangGraph"
    assert handoff["result"] == "LangGraph is a framework."

    event_types = [event["type"] for event in events]
    assert event_types.count("handoff") == 1
    handoff_index = event_types.index("handoff")
    assert events[handoff_index] == {
        "type": "handoff",
        "from": "planner",
        "to": "searchAgent",
        "instruction": "research LangGraph",
    }
    # handoff 先于受托 agent 的内部事件（其 ai_message/tool_call）
    first_search_event = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "tool_call" and event.get("name") == "web_search"
    )
    assert handoff_index < first_search_event
    assert "web_search" in [event.get("name") for event in events if event.get("type") == "tool_call"]
    # planner 自己的工具调用也有 tool_call/tool_result 事件
    assert ("tool_call", "call_search_agent") in [
        (event["type"], event.get("name")) for event in events
    ]


def test_planner_delegates_code_agent(workspace):
    events = []
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args(), "c1"),
            _tool_call(
                "call_code_agent",
                {"instruction": "write result.txt"},
                "c2",
            ),
            # 受托 codeAgent 内部：写文件、汇报 todo、总结
            _tool_call(
                "write_file", {"file_path": "result.txt", "content": "done"}, "k1"
            ),
            _tool_call(
                "todo_update", {"todo_id": "t1", "status": "completed"}, "k2"
            ),
            AIMessage(content="Implementation finished."),
            # planner 第三轮：纯文本结束
            AIMessage(content="Supervisor summary."),
        ]
    )
    state = _state(
        workspace,
        todos=[{"id": "t1", "content": "step", "status": "pending", "note": ""}],
    )

    update = planner_node(
        state,
        model=model,
        on_event=events.append,
    )

    assert (workspace / "result.txt").exists()
    assert update["code_agent_summary"]
    assert all(todo["status"] == "completed" for todo in update["todos"])
    assert update["todos"] != []
    (handoff,) = update["agent_handoffs"]
    assert handoff["to_agent"] == "codeAgent"
    assert handoff["result"] == update["code_agent_summary"]
    assert [type(message).__name__ for message in update["messages"]] == [
        "AIMessage",
        "ToolMessage",
        "AIMessage",
        "ToolMessage",
        "AIMessage",
    ]
    event_types = [event["type"] for event in events]
    assert event_types.count("handoff") == 1
    handoff_index = event_types.index("handoff")
    assert events[handoff_index]["to"] == "codeAgent"
    inner_todo_updates = [
        event
        for event in events
        if event.get("type") == "tool_call" and event.get("name") == "todo_update"
    ]
    assert inner_todo_updates, "受托 codeAgent 的内部事件应透传"


def test_planner_chains_todos_into_code_delegation(workspace):
    """先发布计划再委托时，受托 codeAgent 应看到计划 todos 并可更新它们。"""
    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args(), "c1"),
            _tool_call(
                "call_code_agent",
                {"instruction": "finish t1"},
                "c2",
            ),
            _tool_call(
                "todo_update", {"todo_id": "t1", "status": "completed"}, "k1"
            ),
            AIMessage(content="t1 done."),
            AIMessage(content="done."),
        ]
    )

    update = planner_node(_state(workspace), model=model)

    assert update["todos"] == [
        {"id": "t1", "content": "step", "status": "completed", "note": ""}
    ]


def test_planner_loop_boundaries(workspace):
    model = FakeModel([AIMessage(content="nothing to do.")])
    update = planner_node(_state(workspace), model=model)
    assert len(model.calls) == 1
    assert update == {"context_next_node": "verifier"}

    model = FakeModel(
        [
            _tool_call("todo_write", _plan_args(), f"c{i}") for i in range(5)
        ]
    )
    update = planner_node(_state(workspace), model=model, max_loops=2)
    assert len(model.calls) == 2
    assert update["plan_summary"] == "plan"


def test_actor_node_is_removed_and_prompts_migrated():
    assert not hasattr(graph_nodes, "actor_node")
    assert not hasattr(stage2, "PLANNER_PROMPT")
    assert not hasattr(stage2, "ACTOR_PROMPT")
    assert not hasattr(stage2, "VERIFIER_PROMPT")
    assert stage2.FINAL_PROMPT
    assert graph_nodes.VERIFIER_PROMPT is stage3.VERIFIER_PROMPT
    assert graph_nodes.VERIFIER_PROMPT.startswith(
        "You are verifier, a model-based reviewer node."
    )
    assert "NotepadReadTool" in graph_nodes.VERIFIER_PROMPT
    # 原文中 "search the web" 跨行折行，折叠空白后断言
    assert "search the web" in " ".join(graph_nodes.VERIFIER_PROMPT.split())
    assert graph_nodes.VERIFIER_PROMPT.rstrip("\n").endswith(
        "an empty string when passed"
    )
    assert "verifier_route" not in dir(graph_nodes)


def test_verifier_binds_four_tools(workspace):
    verdict = json.dumps(
        {
            "passed": True,
            "reason": "ok",
            "checks": [],
            "recommended_next_instruction": "",
        }
    )
    model = FakeModel([AIMessage(content=verdict)])
    state = _state(workspace, acceptance_criteria=["done"])

    update = verifier_node(state, model=model)

    assert [tool.name for tool in model.bound_tools] == [
        "read_file",
        "grep",
        "bash",
        "web_search",
    ]
    assert update["passed"] is True
    assert "context_next_node" not in update
    system_message, human_message = model.calls[0]
    assert system_message.content == stage3.VERIFIER_PROMPT
    assert "done" in human_message.content


def test_verifier_sets_context_next_node_on_failure(workspace):
    verdict = json.dumps(
        {
            "passed": False,
            "reason": "broken",
            "checks": [],
            "recommended_next_instruction": "fix it",
        }
    )

    update = verifier_node(
        _state(workspace, attempts=0, max_attempts=3),
        model=FakeModel([AIMessage(content=verdict)]),
    )

    assert update["passed"] is False
    assert update["attempts"] == 1
    assert update["context_next_node"] == "planner"


def test_verifier_omits_context_next_node_when_budget_exhausted(workspace):
    verdict = json.dumps(
        {
            "passed": False,
            "reason": "broken",
            "checks": [],
            "recommended_next_instruction": "fix it",
        }
    )

    update = verifier_node(
        _state(workspace, attempts=2, max_attempts=3),
        model=FakeModel([AIMessage(content=verdict)]),
    )

    assert update["attempts"] == 3
    assert "context_next_node" not in update
