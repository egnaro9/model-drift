import pytest
"""Request-body construction — the part that must be right or a flagship 400s.

Claude Opus 4.8 and GPT-5 reject a `temperature` parameter. If the probe sent one
anyway, every flagship call would error and the model would read as 100% broken —
a fake regression. These pin that temperature is omitted when a model declares
`temperature=None`, and sent when it doesn't.
"""
from modeldrift.providers import Model, _safe, anthropic_body, gemini_body, load_registry, openai_body

FLAGSHIP = Model("x:flag", "Flag", "openai", "gpt-5", "K", temperature=None)
MINI = Model("x:mini", "Mini", "openai", "gpt-4o-mini", "K")  # default temp 0.0


def test_openai_omits_temperature_for_param_strict_flagships():
    assert "temperature" not in openai_body(FLAGSHIP, "hi")
    assert openai_body(MINI, "hi")["temperature"] == 0.0


def test_anthropic_omits_temperature_when_none():
    opus = Model("a:opus", "Opus", "anthropic", "claude-opus-4-8", "K", temperature=None)
    haiku = Model("a:haiku", "Haiku", "anthropic", "claude-haiku-4-5", "K")
    assert "temperature" not in anthropic_body(opus, "hi")
    assert anthropic_body(haiku, "hi")["temperature"] == 0.0
    assert anthropic_body(opus, "hi")["max_tokens"] == 256   # still bounded


def test_gemini_temperature_is_conditional():
    pro = Model("g:pro", "Pro", "gemini", "gemini-2.5-pro", "K")
    assert gemini_body(pro, "hi")["generationConfig"]["temperature"] == 0.0
    off = Model("g:x", "X", "gemini", "gemini-2.5-pro", "K", temperature=None)
    assert gemini_body(off, "hi")["generationConfig"] == {}


def test_registry_parses_flagships_with_null_temperature():
    reg = {m.id: m for m in load_registry()}
    # every known param-strict model must load with temperature omitted
    for pid in ("openai:gpt-5", "openai:gpt-5-mini", "openai:gpt-5-nano",
                "anthropic:claude-fable-5", "anthropic:claude-opus-4-8", "anthropic:claude-sonnet-5"):
        assert reg[pid].temperature is None, pid
    # a mini that accepts the param keeps the deterministic default
    assert reg["openai:gpt-4o-mini"].temperature == 0.0
    # tier depth per big-four provider (only where a real model exists — no padding)
    expected = {"openai:": 4, "anthropic:": 4, "google:": 3, "xai:": 3}
    for prefix, n in expected.items():
        assert sum(1 for k in reg if k.startswith(prefix)) == n, prefix
    # Grok routes through the OpenAI-compatible path with xAI's base url
    assert reg["xai:grok-4.5"].provider == "openai-compatible"
    assert reg["xai:grok-4.5"].base_url == "https://api.x.ai/v1"


def test_every_real_model_is_key_gated():
    for m in load_registry():
        if m.provider != "mock":
            assert m.key_env and m.key_env != "NONE"


def test_a_socket_timeout_becomes_a_provider_error(monkeypatch):
    """A bare TimeoutError is not a URLError. It used to escape every handler,
    sail past probe()'s `except ProviderError`, and kill the run - losing every
    model already measured because one endpoint was slow."""
    import urllib.request
    from modeldrift import providers

    def slow(*a, **k):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(urllib.request, "urlopen", slow)
    with pytest.raises(providers.ProviderError) as e:
        providers._post("https://example.test/v1", {}, {"x": 1})
    assert "TimeoutError" in str(e.value)


def test_a_malformed_json_body_becomes_a_provider_error(monkeypatch):
    import io, urllib.request
    from modeldrift import providers

    class R:
        def read(self): return b"<html>gateway timeout</html>"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R())
    with pytest.raises(providers.ProviderError):
        providers._post("https://example.test/v1", {}, {"x": 1})


def _http_error(code, body=b"{}", retry_after=None):
    import email.message, io, urllib.error
    hdrs = email.message.Message()
    if retry_after is not None:
        hdrs["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("https://x.test/v1", code, "err", hdrs, io.BytesIO(body))


class _OK:
    def read(self): return b'{"ok": true}'
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_post_retries_a_429_then_succeeds(monkeypatch):
    """A rate limit (429) is transient — Groq's free tier throws it constantly.
    The probe must retry, not record a 0% 'regression'."""
    import urllib.request
    from modeldrift import providers
    calls = {"n": 0}

    def flaky(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, b'{"error":"rate limit"}', retry_after=0)
        return _OK()

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)
    assert providers._post("https://x.test/v1", {}, {"a": 1}) == {"ok": True}
    assert calls["n"] == 2   # errored once, retried, succeeded


def test_post_does_not_retry_a_deterministic_400(monkeypatch):
    """A 400 (e.g. a flagship rejecting `temperature`) is deterministic — retrying
    just burns the run. Only 429/5xx are retried."""
    import urllib.request
    from modeldrift import providers
    calls = {"n": 0}

    def bad(req, timeout=None):
        calls["n"] += 1
        raise _http_error(400, b'{"error":"temperature unsupported"}')

    monkeypatch.setattr(urllib.request, "urlopen", bad)
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)
    with pytest.raises(providers.ProviderError):
        providers._post("https://x.test/v1", {}, {"a": 1})
    assert calls["n"] == 1   # not retried


def test_a_rate_capped_host_is_throttled(monkeypatch):
    """Two back-to-back calls to a capped host (Groq) must space themselves;
    an uncapped host never waits."""
    from modeldrift import providers
    slept = []
    monkeypatch.setattr(providers.time, "sleep", lambda s: slept.append(s))
    providers._last_call.clear()
    groq = "https://api.groq.com/openai/v1/chat/completions"
    providers._throttle(groq)
    providers._throttle(groq)          # immediately again → must wait
    assert slept and slept[-1] > 0
    slept.clear()
    providers._throttle("https://api.openai.com/v1/chat/completions")
    assert slept == []                 # uncapped host never sleeps


# ── _safe: the credential scrub that guards public Actions logs ──────────
# This existed with ZERO tests. It is interpolated into every ProviderError in
# the module and this repo's Actions logs are public, so a regression here
# publishes a live key on the next failure. The neighbouring lesson is that
# masking is exact-match and a truncated key slips past it, so the scrub itself
# is the only thing standing between a careless `?key=` and a public log.


def test_safe_redacts_every_secret_param_name_it_claims_to():
    for name in ("key", "api_key", "access_token", "token"):
        url = f"https://api.example.com/v1/models?{name}=AIzaSyREAL_SECRET_VALUE"
        out = _safe(url)
        assert "AIzaSyREAL_SECRET_VALUE" not in out, name
        assert out.endswith(f"{name}=REDACTED"), name


def test_safe_redacts_a_secret_that_is_not_the_first_parameter():
    """The `&` branch of the alternation. A key is rarely the first param."""
    out = _safe("https://api.example.com/v1/models?alt=json&key=SECRET123&pretty=true")
    assert "SECRET123" not in out
    assert "alt=json" in out and "pretty=true" in out
    assert "key=REDACTED" in out


def test_safe_stops_at_the_parameter_boundary_and_keeps_the_rest_of_the_url():
    """A scrub that ate the remaining query string would be a different bug:
    the error message is what a human reads to debug the failure."""
    out = _safe("https://api.example.com/v1/x?key=SECRET&model=gpt-5&n=2")
    assert out == "https://api.example.com/v1/x?key=REDACTED&model=gpt-5&n=2"


def test_safe_leaves_a_url_with_no_secret_untouched():
    url = "https://api.example.com/v1/models?model=claude-opus-4-8"
    assert _safe(url) == url


def test_safe_redacts_two_secrets_in_one_url():
    out = _safe("https://x.test/a?key=AAA&token=BBB")
    assert "AAA" not in out and "BBB" not in out
    assert out.count("REDACTED") == 2


def test_safe_does_not_cover_unhyphenated_or_header_style_names():
    """Documents the REAL boundary rather than implying total coverage.

    The pattern lists four parameter names. `apikey` (no separator) is not one of
    them, so it survives. This is not a request to widen the regex blindly; it is
    here so the limit is visible to the next person, and so widening it later
    turns this assertion red on purpose instead of silently.
    """
    assert "STILL_VISIBLE" in _safe("https://x.test/a?apikey=STILL_VISIBLE")
