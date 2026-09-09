"""core.agent ReAct 循环的离线行为（FakeModel，不发起网络请求）。"""

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from novagent.core.agent import ACTOR_PROMPT, stream_agent_events


class FakeModel:
    """按序返回预设响应并记录收到的消息。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        return self.responses.pop(0)


def _tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_emits_full_event_sequence_and_writes_file(workspace):
    model = FakeModel(
        [
            _tool_call(
                "write_file",
                {"file_path": "note.txt", "content": "hi"},
                "call_1",
            ),
            AIMessage(content="All done."),
        ]
    )
    events = list(
        stream_agent_events("create a note", workspace=workspace, model=model)
    )
    assert [event["type"] for event in events] == [
        "ai_message",
        "tool_call",
        "tool_result",
        "ai_message",
        "final_answer",
    ]
    assert events[1] == {
        "type": "tool_call",
        "name": "write_file",
        "args": {"file_path": "note.txt", "content": "hi"},
    }
    assert events[-1] == {"type": "final_answer", "content": "All done."}
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "hi"
    tool_message = model.calls[-1][-1]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.tool_call_id == "call_1"
    assert tool_message.content == json.dumps(events[2]["result"])


def test_builds_messages_from_actor_prompt(workspace):
    model = FakeModel([AIMessage(content="done")])
    list(stream_agent_events("do it", workspace=workspace, model=model))
    system_message, human_message = model.calls[0]
    assert isinstance(system_message, SystemMessage)
    assert system_message.content == ACTOR_PROMPT
    assert isinstance(human_message, HumanMessage)
    assert human_message.content == "do it"
    assert ACTOR_PROMPT.startswith(
        "You are the actor node in novagent's ReAct workflow."
    )
    assert model.bound_tools is not None
    assert [tool.name for tool in model.bound_tools] == [
        "read_file",
        "write_file",
        "edit_file",
        "grep",
        "bash",
    ]


def test_tool_error_is_fed_back_not_raised(workspace):
    model = FakeModel(
        [
            _tool_call("read_file", {"file_path": "missing.txt"}, "call_x"),
            AIMessage(content="Handled."),
        ]
    )
    events = list(
        stream_agent_events("read something", workspace=workspace, model=model)
    )
    tool_result = events[2]
    assert tool_result["type"] == "tool_result"
    assert tool_result["name"] == "read_file"
    assert tool_result["result"].startswith("Error:")
    tool_message = model.calls[-1][-1]
    assert tool_message.content.startswith('"Error:')
    assert json.loads(tool_message.content).startswith("Error:")


def test_unknown_tool_name_is_reported(workspace):
    model = FakeModel(
        [
            _tool_call("no_such_tool", {}, "call_u"),
            AIMessage(content="Ok."),
        ]
    )
    events = list(
        stream_agent_events("whatever", workspace=workspace, model=model)
    )
    assert "unknown tool" in events[2]["result"]
    assert events[-1] == {"type": "final_answer", "content": "Ok."}
    assert "unknown tool" in json.loads(model.calls[-1][-1].content)


def test_stops_after_max_loops(workspace):
    looping = _tool_call("no_such_tool", {}, "call_loop")
    model = FakeModel([looping] * 3)
    events = list(
        stream_agent_events(
            "loop forever", workspace=workspace, model=model, max_loops=3
        )
    )
    assert len(model.calls) == 3
    assert events[-1]["type"] == "final_answer"
