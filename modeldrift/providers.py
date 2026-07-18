"""Calling models — one small function per provider, each gated on its own API key.

A model is only probed if its key is present in the environment. That's the cost
control: set `OPENAI_API_KEY` and you track OpenAI; leave it unset and that row is
skipped, no spend, no error. Start with one model, add more when you want to fund
them. stdlib `urllib` only — no SDKs to pin.

**Temperature is per-model, and that matters.** The current flagships reject a
sampling parameter: Claude Opus 4.8 and GPT-5 return a 400 if you send
`temperature`, so a probe that hardcoded `temperature=0` would make every
flagship look 100% broken. Models that accept it are pinned to 0 for
reproducibility; models that reject it set `temperature=None` and it's omitted.

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
    id: str            # the series id in the tracker, e.g. "openai:gpt-5"
    label: str         # display name
    provider: str      # openai | openai-compatible | anthropic | gemini | mock
    model: str         # the provider's model id
    key_env: str       # env var holding the api key
    base_url: Optional[str] = None      # for openai-compatible providers (xAI, Groq, …)
    temperature: Optional[float] = 0.0  # None → omit it (flagships that reject the param)

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


# ── pure request-body builders (tested directly, no network) ──
def openai_body(m: Model, prompt: str) -> dict:
    body = {"model": m.model, "messages": [{"role": "user", "content": prompt}]}
    if m.temperature is not None:
        body["temperature"] = m.temperature
    return body


def anthropic_body(m: Model, prompt: str) -> dict:
    body = {"model": m.model, "max_tokens": 256, "messages": [{"role": "user", "content": prompt}]}
    if m.temperature is not None:
        body["temperature"] = m.temperature
    return body


def gemini_body(m: Model, prompt: str) -> dict:
    cfg = {} if m.temperature is None else {"temperature": m.temperature}
    return {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}


def _openai(m: Model, prompt: str) -> str:
    base = (m.base_url or "https://api.openai.com/v1").rstrip("/")
    key = os.environ[m.key_env].strip()
    data = _post(f"{base}/chat/completions",
                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                 openai_body(m, prompt))
    return data["choices"][0]["message"]["content"]


def _anthropic(m: Model, prompt: str) -> str:
    key = os.environ[m.key_env].strip()
    data = _post("https://api.anthropic.com/v1/messages",
                 {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                 anthropic_body(m, prompt))
    return "".join(b.get("text", "") for b in data.get("content", []))


def _gemini(m: Model, prompt: str) -> str:
    key = os.environ[m.key_env].strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m.model}:generateContent?key={key}"
    data = _post(url, {"Content-Type": "application/json"}, gemini_body(m, prompt))
    return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])


# Deterministic mock: knows the suite's right answers, for testing without keys.
# `mock-drifted` deliberately fails two tasks, so regression detection is testable.
_MOCK_ANSWERS = {
    "if-one-word": "blue", "if-json": '{"ok": true}', "if-no-preamble": "144",
    "fact-capital": "Tokyo", "fact-element": "Au", "fact-planet": "Mercury",
    "math-order": "23", "math-percent": "30", "reason-older": "25",
    "fmt-list": "2, 4, 6", "extract-year": "1648", "no-overrefuse": "hello",
    # hardened tasks (v2)
    "count-r": "3", "sort-numeric": "2, 4, 10, 33", "reverse-str": "dlrow",
    "multi-step-math": "8", "vowel-json": '{"vowels": 5}', "nth-word": "fox",
    "days-feb-2024": "29", "unit-minutes": "150", "logic-syllogism": "yes",
    "compare-decimals": "9.9",
}


def _mock(m: Model, task_id: str) -> str:
    ans = _MOCK_ANSWERS.get(task_id, "")
    if m.model == "mock-drifted" and task_id in ("if-json", "math-order"):
        return "I'm not sure I can help with that."  # simulated regression
    return ans


_PROVIDERS: Dict[str, Callable[[Model, str], str]] = {
    "openai": _openai, "openai-compatible": _openai,
    "anthropic": _anthropic, "gemini": _gemini,
}


def call(model: Model, prompt: str, task_id: str = "") -> str:
    """Send one prompt to a model, return its text. Raises ProviderError on failure."""
    if model.provider == "mock":
        return _mock(model, task_id)
    fn = _PROVIDERS.get(model.provider)
    if fn is None:
        raise ProviderError(f"unknown provider {model.provider!r}")
    return fn(model, prompt)


def load_registry(path: Optional[str] = None) -> List[Model]:
    """Load the model registry (models.json). Bundled default is overridable."""
    from pathlib import Path
    p = Path(path) if path else Path(__file__).parent / "models.json"
    return [Model(**m) for m in json.loads(p.read_text(encoding="utf-8"))]
