"""OpenAI 模型工厂。"""

import os

from dotenv import find_dotenv, load_dotenv
from langchain_openai import ChatOpenAI

DEFAULT_MODEL = "gpt-4o-mini"


def create_model() -> ChatOpenAI:
    """从 ``.env`` 或进程环境读取配置并创建 :class:`ChatOpenAI`。

    环境变量：``OPENAI_API_KEY``（必需）、``OPENAI_MODEL``（可选，
    默认 ``gpt-4o-mini``）、``OPENAI_BASE_URL``（可选）。
    """
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. Add OPENAI_API_KEY=sk-... to your "
            ".env file or export it in your shell, then retry."
        )
    kwargs: dict = {
        "model": os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        "api_key": api_key,
        "temperature": 0,
    }
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)
