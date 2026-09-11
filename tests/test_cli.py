"""CLI 入口：帮助文本、--max-attempts、workspace 自动创建、节点徽标渲染。"""

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


def test_help_lists_task_max_attempts_and_workspace():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    text = _output(result).lower()
    assert "task" in text
    assert "--workspace" in text
    assert "--max-attempts" in text


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


def _fake_stream(recorded):
    """构造统一事件格式的假事件流，记录收到的 max_attempts。"""

    def fake_stream(task, *, workspace, max_attempts=3, model=None):
        recorded.append(max_attempts)
        yield {
            "type": "node_output",
            "node": "planner",
            "plan_summary": "write a note",
            "todos": [{"id": "t1", "content": "write note", "status": "pending", "note": ""}],
            "acceptance_criteria": ["note exists"],
            "verification_commands": ["echo check"],
        }
        yield {"type": "ai_message", "node": "actor", "content": "Let me check."}
        yield {
            "type": "memory",
            "node": "planner",
            "memory": {
                "rules": {"scope": "workspace"},
                "working_memory": {"node": "planner", "task": "demo task"},
                "history_summary_store": {},
            },
        }
        yield {
            "type": "tool_call",
            "node": "actor",
            "name": "bash",
            "args": {"command": "echo hi"},
        }
        yield {"type": "tool_result", "node": "actor", "name": "bash", "result": "hi"}
        yield {
            "type": "node_output",
            "node": "verifier",
            "passed": True,
            "reason": "all good",
            "verification_results": [{"command": "echo check", "ok": True, "exit_code": 0}],
            "verification_checks": [],
        }
        yield {
            "type": "node_output",
            "node": "final",
            "final_answer": "Task completed in 1 attempt(s). all good",
        }

    return fake_stream


def test_rich_prints_node_badges_in_order(tmp_path, monkeypatch):
    from novagent.cli import app as app_module

    recorded = []
    monkeypatch.setattr(app_module, "create_model", lambda: object())
    monkeypatch.setattr(
        app_module, "stream_agent_events", _fake_stream(recorded)
    )
    result = runner.invoke(
        app,
        ["demo task", "--workspace", str(tmp_path / "ws"), "--max-attempts", "2"],
    )
    assert result.exit_code == 0
    text = _output(result)

    assert recorded == [2]
    assert "📋 Planner" in text
    assert "🔧 Actor" in text
    assert "✅ Verifier" in text
    assert "📝 Final" in text
    assert "write a note" in text
    assert "write note" in text
    pos_bash = text.index("bash")
    pos_args = text.index("echo hi")
    pos_result = text.index("hi", pos_args + len("echo hi"))
    pos_final = text.index("Task completed in 1 attempt(s). all good")
    assert 0 <= pos_bash < pos_args < pos_result < pos_final
    assert "❌" not in text
    assert "exit 0" in text
    # memory 事件当前不渲染：记忆内容不出现在 CLI 输出
    assert "working_memory" not in text


def test_max_attempts_defaults_to_three(tmp_path, monkeypatch):
    from novagent.cli import app as app_module

    recorded = []
    monkeypatch.setattr(app_module, "create_model", lambda: object())
    monkeypatch.setattr(
        app_module, "stream_agent_events", _fake_stream(recorded)
    )
    result = runner.invoke(app, ["demo task", "--workspace", str(tmp_path / "ws")])
    assert result.exit_code == 0
    assert recorded == [3]


def test_failed_verifier_shows_cross_badge(tmp_path, monkeypatch):
    from novagent.cli import app as app_module

    def fake_stream(task, *, workspace, max_attempts=3, model=None):
        yield {
            "type": "node_output",
            "node": "planner",
            "plan_summary": "p",
            "todos": [],
            "acceptance_criteria": [],
            "verification_commands": [],
        }
        yield {
            "type": "node_output",
            "node": "verifier",
            "passed": False,
            "reason": "tests broke",
            "verification_results": [
                {"command": "echo bad", "ok": False, "exit_code": 3}
            ],
            "verification_checks": [],
        }
        yield {
            "type": "node_output",
            "node": "final",
            "final_answer": "Task failed after 1 attempt(s).\nLast error: tests broke",
        }

    monkeypatch.setattr(app_module, "create_model", lambda: object())
    monkeypatch.setattr(app_module, "stream_agent_events", fake_stream)
    result = runner.invoke(app, ["demo task", "--workspace", str(tmp_path / "ws")])
    assert result.exit_code == 0
    text = _output(result)
    assert "❌ Verifier" in text
    assert "tests broke" in text
    assert "exit 3" in text
    assert "Task failed after 1 attempt(s)." in text
