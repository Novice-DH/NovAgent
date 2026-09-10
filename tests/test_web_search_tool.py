"""web_search_tool 的离线行为（monkeypatch 环境变量与 fake TavilyClient）。"""

import pytest

from novagent.tools.web_search_tool import WebSearchTool


class FakeTavilyClient:
    """记录构造参数与 search 调用，返回预设响应。"""

    instances: list
    responses: list

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.search_calls = []
        type(self).instances.append(self)

    def search(self, query, **kwargs):
        self.search_calls.append((query, kwargs))
        return type(self).responses.pop(0)


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    # load_dotenv 桩掉，避免本机 .env 干扰用例的确定性
    monkeypatch.setattr(
        "novagent.tools.web_search_tool.load_dotenv", lambda *a, **k: False
    )
    FakeTavilyClient.instances = []
    FakeTavilyClient.responses = []
    monkeypatch.setattr(
        "novagent.tools.web_search_tool.TavilyClient", FakeTavilyClient
    )
    return FakeTavilyClient


def test_tool_name_and_schema():
    assert WebSearchTool.name == "web_search"
    assert set(WebSearchTool.args_schema.model_fields) == {"query", "max_results"}


def test_missing_api_key_returns_structured_error(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(
        "novagent.tools.web_search_tool.load_dotenv", lambda *a, **k: False
    )

    result = WebSearchTool.invoke({"query": "langgraph", "max_results": 3})

    assert result["ok"] is False
    assert result["error"] == "missing TAVILY_API_KEY"
    assert result["query"] == "langgraph"


def test_successful_search_normalizes_results(fake_client):
    fake_client.responses.append(
        {
            "answer": "Tavily answer",
            "results": [
                {
                    "title": "Doc",
                    "url": "https://example.com/a",
                    "content": "text",
                    "score": 0.9,
                },
                {"url": "https://example.com/b"},
            ],
        }
    )

    result = WebSearchTool.invoke({"query": "langgraph", "max_results": 2})

    assert result["ok"] is True
    assert result["query"] == "langgraph"
    assert result["answer"] == "Tavily answer"
    assert result["results"] == [
        {
            "title": "Doc",
            "url": "https://example.com/a",
            "content": "text",
            "score": 0.9,
        },
        {"title": "", "url": "https://example.com/b", "content": "", "score": 0.0},
    ]
    (client,) = fake_client.instances
    assert client.api_key == "tvly-test"
    assert client.search_calls == [("langgraph", {"max_results": 2, "include_answer": True})]


def test_search_exception_returns_error_dict(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr(
        "novagent.tools.web_search_tool.load_dotenv", lambda *a, **k: False
    )

    class BoomClient:
        def __init__(self, api_key=None):
            self.api_key = api_key

        def search(self, query, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr("novagent.tools.web_search_tool.TavilyClient", BoomClient)

    result = WebSearchTool.invoke({"query": "q"})

    assert result["ok"] is False
    assert result["query"] == "q"
    assert "network down" in result["error"]
