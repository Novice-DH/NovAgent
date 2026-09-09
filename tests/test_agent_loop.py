"""手工工具调用循环的离线行为（FakeModel，不发起网络请求）。"""

from langchain_core.messages import AIMessage, ToolMessage

from novagent.cli.app import MAX_ITERATIONS, _run_agent
from novagent.core.state import RuntimeState
from novagent.tools.registry import build_tools


class FakeModel:
    """按序返回预设响应并记录收到的消息。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        return self.responses.pop(0)


def _tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_executes_tool_and_returns_final_answer(state, workspace):
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
    answer = _run_agent(model, build_tools(state), state, "create a note")
    assert answer == "All done."
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "hi"
    last_messages = model.calls[-1]
    tool_message = last_messages[-1]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.tool_call_id == "call_1"
    assert "note.txt" in tool_message.content


def test_tool_error_is_fed_back_not_raised(state):
    model = FakeModel(
        [
            _tool_call("read_file", {"file_path": "missing.txt"}, "call_x"),
            AIMessage(content="Handled."),
        ]
    )
    answer = _run_agent(model, build_tools(state), state, "read something")
    assert answer == "Handled."
    assert model.calls[-1][-1].content.startswith("Error:")


def test_unknown_tool_name_is_reported(state):
    model = FakeModel(
        [
            _tool_call("no_such_tool", {}, "call_u"),
            AIMessage(content="Ok."),
        ]
    )
    answer = _run_agent(model, build_tools(state), state, "whatever")
    assert answer == "Ok."
    assert "unknown tool" in model.calls[-1][-1].content


def test_stops_after_max_iterations(state):
    looping = _tool_call("no_such_tool", {}, "call_loop")
    model = FakeModel([looping] * MAX_ITERATIONS)
    answer = _run_agent(model, build_tools(state), state, "loop forever")
    assert "Stopped after 25" in answer
