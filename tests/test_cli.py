"""CLI 入口：帮助文本、workspace 自动创建与缺 key 错误。"""

from typer.testing import CliRunner

from novagent.cli.app import app

runner = CliRunner()


def _output(result):
    text = result.output
    try:
        text += result.stderr
    except (ValueError, AttributeError):
        pass
    return text


def test_help_lists_task_argument_and_workspace_option():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    text = _output(result).lower()
    assert "task" in text
    assert "--workspace" in text


def test_creates_missing_workspace_then_fails_cleanly_without_key(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "fresh" / "ws"
    result = runner.invoke(
        app,
        ["tidy the files", "--workspace", str(target)],
        env={"OPENAI_API_KEY": ""},
    )
    assert target.exists()
    assert result.exit_code == 1
    assert "OPENAI_API_KEY" in _output(result)


def test_default_workspace_is_created(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["tidy the files"], env={"OPENAI_API_KEY": ""})
    assert (tmp_path / "workspace").exists()
    assert result.exit_code == 1


def test_rich_prints_tool_call_result_and_final_answer(tmp_path, monkeypatch):
    from novagent.cli import app as app_module

    def fake_stream(task, *, workspace, model=None, max_loops=10):
        yield {"type": "ai_message", "content": "Let me check."}
        yield {"type": "tool_call", "name": "bash", "args": {"command": "echo hi"}}
        yield {"type": "tool_result", "name": "bash", "result": "hi"}
        yield {"type": "final_answer", "content": "Done."}

    monkeypatch.setattr(app_module, "create_model", lambda: object())
    monkeypatch.setattr(app_module, "stream_agent_events", fake_stream)
    result = runner.invoke(
        app, ["demo task", "--workspace", str(tmp_path / "ws")]
    )
    assert result.exit_code == 0
    text = _output(result)
    assert "Let me check." in text
    pos_bash = text.index("bash")
    pos_args = text.index("echo hi")
    pos_result = text.index("hi", pos_args + len("echo hi"))
    pos_final = text.index("Done.")
    assert 0 <= pos_bash < pos_args < pos_result < pos_final
