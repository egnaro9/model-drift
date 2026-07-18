"""Request-body construction — the part that must be right or a flagship 400s.

Claude Opus 4.8 and GPT-5 reject a `temperature` parameter. If the probe sent one
anyway, every flagship call would error and the model would read as 100% broken —
a fake regression. These pin that temperature is omitted when a model declares
`temperature=None`, and sent when it doesn't.
"""
from modeldrift.providers import Model, anthropic_body, gemini_body, load_registry, openai_body

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
