"""Minimal OpenAI client for the generator. Reads OPENAI_API_KEY from .env."""
from __future__ import annotations

import os
from typing import Any

DEFAULT_MODEL = os.environ.get("DYNAMIC_COMPARATOR_MODEL", "gpt-5-mini")


def call_llm(messages: list[dict[str, Any]], response_format: dict,
             model: str | None = None) -> str:
    """llm(messages, response_format) -> raw JSON text."""
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set (expected in .env)")

    client = OpenAI()
    response = client.chat.completions.create(
        model=model or os.environ.get("DYNAMIC_COMPARATOR_MODEL", DEFAULT_MODEL),
        messages=messages,
        response_format=response_format,
        reasoning_effort="low",
    )
    return response.choices[0].message.content or ""
