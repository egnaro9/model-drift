"""Calling models — one small function per provider, each gated on its own API key.

A model is only probed if its key is present in the environment. That's the cost
control: set `OPENAI_API_KEY` and you track OpenAI; leave it unset and that row is
skipped, no spend, no error. Start with one model, add more when you want to fund
them. Everything is `temperature=0` for the most reproducible output a model will
give, and stdlib `urllib` only — no SDKs to pin.

A `mock` provider (deterministic, no key, no network) exists so the whole
pipeline — probe → grade → store → chart — is testable without spending a cent.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

TIMEOUT = 60


@dataclass(frozen=True)
class Model:
    id: str            # the series id in the tracker, e.g. "openai:gpt-4o-mini"
    label: str         # display name
    provider: str      # openai | anthropic | gemini | openai-compatible | mock
    model: str         # the provider's model id
    key_env: str       # env var holding the api key
    base_url: Optional[str] = None  # for openai-compatible providers (Groq, OpenRouter, …)

    @property
    def available(self) -> bool:
        return self.provider == "mock" or bool(os.environ.get(self.key_env, "").strip())


class ProviderError(RuntimeError):
    pass


def _post(url: str, headers: Dict[str, str], body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise ProviderError(f"{url} -> {e.code}: {e.read().decode()[:200]}")
    except urllib.error.URLError as e:
        raise ProviderError(f"{url} unreachable: {e.reason}")


def _openai(m: Model) -> str:
    base = (m.base_url or "https://api.openai.com/v1").rstrip("/")
    key = os.environ[m.key_env]
    data = _post(f"{base}/chat/completions",
                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                 {"model": m.model, "temperature": 0, "messages": [{"role": "user", "content": _PROMPT}]})
    return data["choices"][0]["message"]["content"]


def _anthropic(m: Model) -> str:
    key = os.environ[m.key_env]
    data = _post("https://api.anthropic.com/v1/messages",
                 {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                 {"model": m.model, "max_tokens": 256, "temperature": 0,
                  "messages": [{"role": "user", "content": _PROMPT}]})
    return "".join(b.get("text", "") for b in data.get("content", []))


def _gemini(m: Model) -> str:
    key = os.environ[m.key_env]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m.model}:generateContent?key={key}"
    data = _post(url, {"Content-Type": "application/json"},
                 {"contents": [{"parts": [{"text": _PROMPT}]}],
                  "generationConfig": {"temperature": 0}})
    return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])


# Deterministic mock: knows the suite's right answers, for testing without keys.
# `mock-drifted` deliberately fails two tasks, so regression detection is testable.
_MOCK_ANSWERS = {
    "if-one-word": "blue", "if-json": '{"ok": true}', "if-no-preamble": "144",
    "fact-capital": "Tokyo", "fact-element": "Au", "fact-planet": "Mercury",
    "math-order": "23", "math-percent": "30", "reason-older": "25",
    "fmt-list": "2, 4, 6", "extract-year": "1648", "no-overrefuse": "hello",
}


def _mock(m: Model, task_id: str) -> str:
    ans = _MOCK_ANSWERS.get(task_id, "")
    if m.model == "mock-drifted" and task_id in ("if-json", "math-order"):
        return "I'm not sure I can help with that."  # simulated regression
    return ans


_PROMPT = ""  # set per task by run.py via call()

_PROVIDERS: Dict[str, Callable[[Model], str]] = {
    "openai": _openai, "openai-compatible": _openai,
    "anthropic": _anthropic, "gemini": _gemini,
}


def call(model: Model, prompt: str, task_id: str = "") -> str:
    """Send one prompt to a model, return its text. Raises ProviderError on failure."""
    global _PROMPT
    if model.provider == "mock":
        return _mock(model, task_id)
    _PROMPT = prompt
    fn = _PROVIDERS.get(model.provider)
    if fn is None:
        raise ProviderError(f"unknown provider {model.provider!r}")
    return fn(model)


def load_registry(path: Optional[str] = None) -> List[Model]:
    """Load the model registry (models.json). Bundled default is overridable."""
    from pathlib import Path
    p = Path(path) if path else Path(__file__).parent / "models.json"
    return [Model(**m) for m in json.loads(p.read_text(encoding="utf-8"))]
