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
