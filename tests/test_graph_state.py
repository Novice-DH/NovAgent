"""LangGraph 图共享状态（novagent.graph.state）。"""

import typing
from types import UnionType

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from novagent.core.state import RuntimeState
from novagent.graph.memory import CompressionEvent, LayeredMemory
from novagent.graph.state import (
    AgentHandoff,
    NovGraphState,
    SourceItem,
    TodoItem,
    VerificationCheck,
    VerificationResult,
)


def test_todo_item_annotations():
    assert TodoItem.__annotations__ == {
        "id": str,
        "content": str,
        "status": str,
        "note": str,
    }


def test_verification_result_annotations():
    annotations = VerificationResult.__annotations__
    assert annotations["command"] is str
    assert annotations["ok"] is bool
    assert typing.get_args(annotations["exit_code"]) == (int, type(None))
    assert isinstance(annotations["exit_code"], UnionType)
    assert annotations["stdout"] is str
    assert annotations["stderr"] is str


def test_source_item_annotations():
    assert SourceItem.__total__ is False
    assert list(SourceItem.__annotations__) == ["url", "title", "content", "score"]


def test_agent_handoff_annotations():
    assert AgentHandoff.__total__ is False
    assert list(AgentHandoff.__annotations__) == [
        "from_agent",
        "to_agent",
        "instruction",
        "result",
    ]


def test_compression_event_annotations():
    assert CompressionEvent.__total__ is False
    assert list(CompressionEvent.__annotations__) == [
        "node",
        "reason",
        "token_count",
        "token_limit",
        "summary",
        "created_at",
    ]


def test_layered_memory_annotations():
    assert LayeredMemory.__total__ is False
    assert list(LayeredMemory.__annotations__) == [
        "rules",
        "working_memory",
        "history_summary_store",
    ]


def test_nov_graph_state_fields_and_total():
    assert NovGraphState.__total__ is False
    annotations = NovGraphState.__annotations__
    assert list(annotations) == [
        "task",
        "runtime",
        "messages",
        "plan_summary",
        "todos",
        "acceptance_criteria",
        "verification_commands",
        "verification_results",
        "research_notes",
        "sources",
        "agent_handoffs",
        "code_agent_summary",
        "passed",
        "attempts",
        "max_attempts",
        "final_answer",
        "last_actor_summary",
        "last_error",
        "verification_checks",
        "context_summary",
        "context_token_count",
        "context_token_limit",
        "context_should_compress",
        "context_next_node",
        "compression_events",
        "memory_snapshot",
        "history_summary",
    ]
    assert annotations["task"] is str
    assert annotations["runtime"] is RuntimeState
    assert annotations["plan_summary"] is str
    assert annotations["research_notes"] is str
    assert annotations["code_agent_summary"] is str
    assert typing.get_origin(annotations["todos"]) is list
    assert typing.get_args(annotations["todos"]) == (TodoItem,)
    assert typing.get_args(annotations["acceptance_criteria"]) == (str,)
    assert typing.get_args(annotations["verification_commands"]) == (str,)
    assert typing.get_args(annotations["verification_results"]) == (
        VerificationResult,
    )
    assert typing.get_args(annotations["sources"]) == (SourceItem,)
    assert typing.get_args(annotations["agent_handoffs"]) == (AgentHandoff,)
    assert annotations["passed"] is bool
    assert annotations["attempts"] is int
    assert annotations["max_attempts"] is int
    assert annotations["final_answer"] is str
    assert annotations["last_actor_summary"] is str
    assert annotations["last_error"] is str
    assert typing.get_args(annotations["verification_checks"]) == (VerificationCheck,)
    assert annotations["context_summary"] is str
    assert annotations["context_token_count"] is int
    assert annotations["context_token_limit"] is int
    assert annotations["context_should_compress"] is bool
    assert annotations["context_next_node"] is str
    assert typing.get_args(annotations["compression_events"]) == (CompressionEvent,)
    assert annotations["memory_snapshot"] is LayeredMemory
    assert annotations["history_summary"] is str


def test_messages_uses_add_messages_reducer():
    messages = NovGraphState.__annotations__["messages"]
    inner, reducer = typing.get_args(messages)
    assert typing.get_origin(inner) is list
    assert typing.get_args(inner) == (BaseMessage,)
    assert reducer is add_messages


def test_reducer_and_message_import_origins():
    import langchain_core.messages as core_messages
    import langgraph.graph.message as graph_message

    assert add_messages is graph_message.add_messages
    assert BaseMessage is core_messages.BaseMessage


def test_add_messages_appends_instead_of_overwriting():
    merged = add_messages([SystemMessage("s")], [HumanMessage("hi")])
    assert [message.content for message in merged] == ["s", "hi"]


def test_state_graph_merges_messages():
    builder = StateGraph(NovGraphState)
    builder.add_node(
        "append_user", lambda state: {"messages": [HumanMessage("hi")]}
    )
    builder.add_edge(START, "append_user")
    builder.add_edge("append_user", END)
    graph = builder.compile()

    result = graph.invoke({"messages": [SystemMessage("s")]})

    assert [message.content for message in result["messages"]] == ["s", "hi"]
