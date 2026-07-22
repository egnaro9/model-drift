"""The model-identity check — pure logic, plus attest()/CLI on the mock.

No keys, no network. The check exists to catch a silently-swapped backend: the
config asks for model X, the provider serves model Y. These pin that the
comparison flags a real swap, tolerates a provider's dated/versioned id, and
never false-alarms on an id it simply couldn't read.
"""
import pytest

from modeldrift import identity as ident
from modeldrift.identity import Identity, _consistent, check, served_model_id
from modeldrift.providers import Model

STABLE = Model("mock:stable", "Mock", "mock", "mock", "NONE")
GPT5 = Model("openai:gpt-5", "GPT-5", "openai", "gpt-5", "OPENAI_API_KEY")
OPUS = Model("anthropic:claude-opus-4-8", "Opus", "anthropic", "claude-opus-4-8", "ANTHROPIC_API_KEY")
GEMINI = Model("google:gemini-3.1-pro", "Gemini", "gemini", "gemini-3.1-pro-preview", "GEMINI_API_KEY")


# ── served_model_id: where each provider carries the id ──────────────────
def test_served_id_read_per_provider_shape():
    assert served_model_id("openai", {"model": "gpt-5-2025-08-01"}) == "gpt-5-2025-08-01"
    assert served_model_id("openai-compatible", {"model": "grok-4.5"}) == "grok-4.5"
    assert served_model_id("anthropic", {"model": "claude-opus-4-8-20260514"}) == "claude-opus-4-8-20260514"
    # Gemini uses modelVersion, with `model` as a fallback if a future response carries it
    assert served_model_id("gemini", {"modelVersion": "gemini-3.1-pro-preview"}) == "gemini-3.1-pro-preview"
    assert served_model_id("gemini", {"model": "gemini-3.5-flash"}) == "gemini-3.5-flash"


def test_served_id_is_none_when_absent_or_blank():
    assert served_model_id("openai", {}) is None
    assert served_model_id("openai", {"model": "   "}) is None
    assert served_model_id("openai", {"model": None}) is None
    assert served_model_id("mystery-provider", {"model": "x"}) is None


# ── _consistent: tolerate version suffixes, reject a real swap ────────────
def test_exact_and_dated_variants_are_consistent():
    assert _consistent("gpt-5", "gpt-5")
    assert _consistent("gpt-4o", "gpt-4o-2024-08-06")            # provider appends a date
    assert _consistent("claude-opus-4-8", "claude-opus-4-8-20260514")
    assert _consistent("grok-4-fast-non-reasoning", "grok-4-fast")  # provider returns the base
    assert _consistent("GPT-5", "gpt-5")                          # case-insensitive


def test_a_bare_prefix_is_not_a_match():
    # The whole point: gpt-4 must NOT wave through gpt-4o (the next char is a
    # letter, not a version separator) — that would hide the downgrade.
    assert not _consistent("gpt-4", "gpt-4o")
    assert not _consistent("gpt-5", "gpt-5x")
    assert not _consistent("gpt-5", "gpt-4o-mini")
    assert not _consistent("claude-opus-4-8", "claude-haiku-4-5")


# ── check(): assemble an Identity from a response ────────────────────────
def test_check_match_on_dated_id():
    i = check(GPT5, {"model": "gpt-5-2025-08-01", "choices": []})
    assert i.verified and i.ok and i.status == "match"
    assert i.requested == "gpt-5" and i.served == "gpt-5-2025-08-01"


def test_check_flags_a_swapped_backend():
    i = check(GPT5, {"model": "gpt-4o-mini"})
    assert i.verified and not i.ok and i.status == "MISMATCH"
    assert i.model_id == "openai:gpt-5" and i.served == "gpt-4o-mini"


def test_check_anthropic_and_gemini_shapes():
    assert check(OPUS, {"model": "claude-opus-4-8-20260514"}).status == "match"
    assert check(GEMINI, {"modelVersion": "gemini-3.1-pro-preview"}).status == "match"


def test_unverified_when_provider_does_not_echo_an_id():
    i = check(GPT5, {"choices": [{"message": {"content": "ok"}}]})
    assert not i.verified and i.ok and i.status == "unverified"   # can't tell != wrong


# ── attest(): one call, mock needs no key/network ────────────────────────
def test_attest_mock_matches_itself():
    i = ident.attest(STABLE)
    assert i.status == "match" and i.served == "mock"


def test_attest_flags_a_swap(monkeypatch):
    monkeypatch.setattr(ident, "call_raw", lambda m, p: {"model": "gpt-4o-mini"})
    assert ident.attest(GPT5).status == "MISMATCH"


def test_attest_propagates_a_call_failure(monkeypatch):
    from modeldrift.providers import ProviderError

    def boom(m, p):
        raise ProviderError("429: slow down")

    monkeypatch.setattr(ident, "call_raw", boom)
    with pytest.raises(ProviderError):
        ident.attest(GPT5)   # a failed call is a reliability problem, not a mismatch


@pytest.fixture
def only_mock_available(monkeypatch):
    """Make availability deterministic regardless of the CI environment's keys:
    clear every provider key so the mock is the only available model and no test
    below can accidentally hit a live provider."""
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_attest_registry_covers_only_available_models(only_mock_available):
    # Only the mock is available, so it's the one attested here — the rest are
    # skipped exactly like the probe skips them for lack of a key.
    results = ident.attest_registry()
    assert [r.model_id for r in results] == ["mock:stable"]
    assert results[0].status == "match"


# ── CLI: exit code gates CI ──────────────────────────────────────────────
def test_cli_clean_registry_exits_zero(only_mock_available):
    assert ident.main([]) == 0


def test_cli_exits_nonzero_on_mismatch(only_mock_available, monkeypatch):
    monkeypatch.setattr(ident, "call_raw", lambda m, p: {"model": "some-other-backend"})
    assert ident.main([]) == 1   # mock served "some-other-backend" != "mock"


def test_cli_strict_flag_fails_on_unverified(only_mock_available, monkeypatch):
    monkeypatch.setattr(ident, "call_raw", lambda m, p: {})   # nothing echoed
    assert ident.main([]) == 0            # unverified is tolerated by default
    assert ident.main(["--strict"]) == 1  # and gated under --strict
