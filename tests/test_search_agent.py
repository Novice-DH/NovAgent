"""search_agent 的离线行为（FakeModel + fake TavilyClient，不发起网络请求）。"""

import json

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from novagent.agents.search_agent import SEARCH_AGENT_PROMPT, run_search_agent


class FakeModel:
    """按序返回预设响应并记录收到的消息与绑定工具。"""

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


def test_prompt_constant():
    assert SEARCH_AGENT_PROMPT.startswith(
        "You are searchAgent, a focused research specialist."
    )
    assert "WebSearchTool" in SEARCH_AGENT_PROMPT
    assert "Do not write files or produce application code." in SEARCH_AGENT_PROMPT


def test_react_loop_collects_queries_sources_and_events():
    FakeTavilyClient.responses.append(
        {
            "answer": "LangGraph is a framework.",
            "results": [
                {"title": "Docs", "url": "https://example.com/docs", "score": 0.9},
                {"title": "Wiki", "url": "https://example.com/wiki", "score": 0.8},
            ],
        }
    )
    model = FakeModel(
        [
            _tool_call(
                "web_search", {"query": "langgraph docs", "max_results": 5}, "call_1"
            ),
            AIMessage(content="Research summary: docs at example.com."),
        ]
    )
    events = []
    state = {"task": "research LangGraph", "research_notes": "prior notes about X"}

    result = run_search_agent(
        state, "find official docs", writer=events.append, model=model
    )

    assert result["ok"] is True
    assert result["summary"] == "Research summary: docs at example.com."
    assert result["queries"] == ["langgraph docs"]
    assert result["sources"] == ["https://example.com/docs", "https://example.com/wiki"]
    assert [type(message).__name__ for message in result["messages"]] == [
        "AIMessage",
        "ToolMessage",
        "AIMessage",
    ]
    tool_message = result["messages"][1]
    assert tool_message.tool_call_id == "call_1"
    payload = json.loads(tool_message.content)
    assert payload["ok"] is True
    assert payload["query"] == "langgraph docs"
    assert payload["answer"] == "LangGraph is a framework."
    assert [event["type"] for event in result["tool_events"]] == [
        "tool_call",
        "search_results",
    ]
    assert result["tool_events"][0] == {
        "type": "tool_call",
        "name": "web_search",
        "args": {"query": "langgraph docs", "max_results": 5},
    }
    assert result["tool_events"][1]["result"] == payload
    assert events == result["tool_events"]
    assert [tool.name for tool in model.bound_tools] == ["web_search"]

    system_message, human_message = model.calls[0]
    assert isinstance(system_message, SystemMessage)
    assert system_message.content == SEARCH_AGENT_PROMPT
    assert "research LangGraph" in human_message.content
    assert "find official docs" in human_message.content
    assert "prior notes about X" in human_message.content


def test_missing_research_notes_is_labelled():
    FakeTavilyClient.responses.append({"answer": "", "results": []})
    model = FakeModel([AIMessage(content="nothing to search.")])

    result = run_search_agent({"task": "t"}, "i", model=model)

    human_message = model.calls[0][1]
    assert "(no research notes yet)" in human_message.content
    assert result["queries"] == []
    assert result["sources"] == []
    assert result["tool_events"] == []


def test_sources_dedupe_and_keep_order():
    FakeTavilyClient.responses = [
        {
            "answer": "",
            "results": [
                {"title": "A", "url": "https://example.com/a", "score": 0.9},
                {"title": "B", "url": "https://example.com/b", "score": 0.8},
                {"title": "A again", "url": "https://example.com/a", "score": 0.7},
            ],
        },
        {
            "answer": "",
            "results": [{"title": "B2", "url": "https://example.com/b", "score": 0.6}],
        },
    ]
    model = FakeModel(
        [
            _tool_call("web_search", {"query": "q1"}, "c1"),
            _tool_call("web_search", {"query": "q2"}, "c2"),
            AIMessage(content="done"),
        ]
    )

    result = run_search_agent({}, "i", model=model)

    assert result["queries"] == ["q1", "q2"]
    assert result["sources"] == ["https://example.com/a", "https://example.com/b"]


def test_loop_stops_without_tool_calls():
    model = FakeModel([AIMessage(content="no search needed")])

    result = run_search_agent({"task": "t"}, "i", model=model)

    assert len(model.calls) == 1
    assert result["summary"] == "no search needed"


def test_loop_respects_max_loops():
    FakeTavilyClient.responses = [
        {"answer": "", "results": [{"url": f"https://example.com/{i}"}]}
        for i in range(5)
    ]
    model = FakeModel(
        [
            _tool_call("web_search", {"query": f"q{i}"}, f"c{i}")
            for i in range(5)
        ]
    )

    result = run_search_agent({}, "i", model=model, max_loops=2)

    assert len(model.calls) == 2
    assert result["queries"] == ["q0", "q1"]
    assert result["sources"] == ["https://example.com/0", "https://example.com/1"]


def test_unknown_tool_returns_error_without_execution():
    model = FakeModel(
        [
            _tool_call(
                "write_file", {"file_path": "x.txt", "content": "y"}, "c1"
            ),
            AIMessage(content="ok"),
        ]
    )

    result = run_search_agent({}, "i", model=model)

    payload = json.loads(result["messages"][1].content)
    assert payload["ok"] is False
    assert "unknown tool" in payload["error"]
    assert result["queries"] == []


def test_search_failure_still_records_query_and_event(monkeypatch):
    # 真实 WebSearchTool 走缺 key 分支：失败调用也记录 query 并发 search_results
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(
        "novagent.tools.web_search_tool.load_dotenv", lambda *a, **k: False
    )
    model = FakeModel(
        [
            _tool_call("web_search", {"query": "failing query"}, "c1"),
            AIMessage(content="search failed, reporting."),
        ]
    )
    events = []

    result = run_search_agent({"task": "t"}, "i", writer=events.append, model=model)

    assert result["queries"] == ["failing query"]
    assert result["sources"] == []
    assert [event["type"] for event in result["tool_events"]] == [
        "tool_call",
        "search_results",
    ]
    payload = result["tool_events"][1]["result"]
    assert payload["ok"] is False
    assert payload["error"] == "missing TAVILY_API_KEY"
    assert events == result["tool_events"]
