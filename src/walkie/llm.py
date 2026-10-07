"""Single local-Ollama client for the whole app (airgap: best-effort only)."""

from __future__ import annotations

import json

import ollama

from walkie import config
from walkie.log import get_logger

log = get_logger("llm")


def complete(
    prompt: str,
    *,
    max_tokens: int = 300,
    temperature: float = 0.3,
    host: str | None = None,
    model: str | None = None,
) -> str | None:
    """One chat completion; returns None when the model is unreachable."""
    if host is None or model is None:
        default_host, default_model = config.load_ollama_config()
        host = host or default_host
        model = model or default_model
    try:
        response = ollama.Client(host=host).chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": temperature, "num_predict": max_tokens},
        )
    except Exception as exc:  # noqa: BLE001 - local LLM is best-effort
        log.info(f"ollama unavailable ({exc})")
        return None
    return _response_text(response)


def complete_json(prompt: str, **kwargs: object) -> dict | None:
    """Completion + JSON extraction; None on unreachable model or bad reply."""
    text = complete(prompt, **kwargs)  # type: ignore[arg-type]
    return extract_json(text) if text else None


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of an LLM reply."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _response_text(response: object) -> str | None:
    message = getattr(response, "message", None)
    text = getattr(message, "content", None)
    if not text and isinstance(response, dict):
        text = response.get("message", {}).get("content")
    return text.strip() if text else None
