"""create_model 的环境变量与 .env 读取。"""

import pytest
from langchain_openai import ChatOpenAI

from novagent.providers.openai_provider import create_model


def _clean_key_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)


def test_reads_api_key_from_dotenv(tmp_path, monkeypatch):
    _clean_key_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-from-dotenv\n", encoding="utf-8")
    model = create_model()
    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_key.get_secret_value() == "sk-from-dotenv"
    assert model.model_name == "gpt-4o-mini"


def test_honors_openai_model_override(tmp_path, monkeypatch):
    _clean_key_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=sk-from-dotenv\nOPENAI_MODEL=custom-model\n",
        encoding="utf-8",
    )
    model = create_model()
    assert model.model_name == "custom-model"


def test_missing_api_key_raises_clear_error(tmp_path, monkeypatch):
    _clean_key_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        create_model()
