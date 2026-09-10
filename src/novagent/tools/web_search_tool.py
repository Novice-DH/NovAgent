"""Tavily 联网搜索工具。

不依赖 ``RuntimeState``/workspace，可独立使用；``tavily`` 仅在本模块导入。
工具返回普通 dict（可 JSON 序列化），错误（缺 key、网络/API 异常）不抛出，
由调用方按 ``ok`` 字段处理。
"""

import os

from dotenv import find_dotenv, load_dotenv
from langchain_core.tools import StructuredTool
from tavily import TavilyClient


def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web with the Tavily Search API.

    Args:
        query: The search query text.
        max_results: Maximum number of results to return.

    Returns:
        A JSON-serializable dict. On success:
        ``{"ok": True, "query": ..., "answer": ..., "results":
        [{"title", "url", "content", "score"}, ...]}``. When
        ``TAVILY_API_KEY`` is missing or the search fails:
        ``{"ok": False, "query": ..., "error": ...}`` — no exception is
        raised and no network request is made without a key.
    """
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return {"ok": False, "query": query, "error": "missing TAVILY_API_KEY"}
    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=max_results, include_answer=True)
    except Exception as exc:  # noqa: BLE001 - 错误以结构化 dict 回传调用方
        return {"ok": False, "query": query, "error": str(exc)}
    results = [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "content": str(item.get("content") or ""),
            "score": float(item.get("score") or 0.0),
        }
        for item in response.get("results") or []
    ]
    return {
        "ok": True,
        "query": query,
        "answer": str(response.get("answer") or ""),
        "results": results,
    }


WebSearchTool = StructuredTool.from_function(web_search, name="web_search")
