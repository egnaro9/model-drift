"""Prepaid credentials (auto-reload off) run until the balance is spent.

When that happens the provider refuses every call. That is a budget decision,
not a model result and not an outage, so the board must say "paused" — never
"regressed", never a stale "unchanged" — and the probe must not go red daily.
"""
import json
from pathlib import Path

from modeldrift import run as R
from modeldrift.board import statuses_from_series
from modeldrift.providers import Model, ProviderError
from modeldrift.report import regressions, results_md

REG = json.loads((Path(__file__).resolve().parent.parent / "modeldrift" / "models.json")
                 .read_text(encoding="utf-8"))


def pt(day, acc=0.9):
    return {"t": f"2026-11-{day:02d}T08:17:00Z", "acc": acc, "reliability": 1.0, "graded": 35}


def test_registry_declares_funding_for_every_credential():
    by = {}
    for m in REG:
        by.setdefault(m["key_env"], set()).add(m.get("funding"))
    assert by["OPENAI_API_KEY"] == {"prepaid"}
    assert by["GEMINI_API_KEY"] == {"prepaid"}
    assert by["XAI_API_KEY"] == {"prepaid"}
    assert by["ANTHROPIC_API_KEY"] == {"auto-reload"}
    assert by["GROQ_API_KEY"] == {"free"}


def test_a_prepaid_model_that_stopped_reporting_is_paused_not_stale():
    reg = [{"id": "a", "label": "A", "funding": "prepaid"},
           {"id": "b", "label": "B", "funding": "auto-reload"}]
    series = {"a": [pt(19), pt(20, 0.8)], "b": [pt(19), pt(20), pt(21)]}
    a, b = statuses_from_series(series, reg)
    assert a.verdict == "paused" and a.delta is None and a.latest == 0.8
    assert b.verdict == "unchanged"
    assert regressions([a, b]) == []
    assert "⏸ paused (prepaid credit, last run 2026-11-20)" in results_md([a, b])


def test_an_auto_reload_model_that_stopped_reporting_is_not_called_paused():
    reg = [{"id": "a", "label": "A", "funding": "auto-reload"},
           {"id": "b", "label": "B", "funding": "free"}]
    series = {"a": [pt(19), pt(20)], "b": [pt(19), pt(20), pt(21)]}
    assert statuses_from_series(series, reg)[0].verdict != "paused"


def test_a_prepaid_model_still_reporting_is_scored_normally():
    reg = [{"id": "a", "label": "A", "funding": "prepaid"}]
    assert statuses_from_series({"a": [pt(20), pt(21, 0.8)]}, reg)[0].verdict == "regressed"


def _run(monkeypatch, tmp_path, models, dark):
    monkeypatch.setattr(R, "load_registry", lambda *_a, **_k: models)
    def probe(m, runs):
        n = len(R.SUITE) if m.id in dark else 0
        return {"metrics": {"faithfulness": 0.0, "graded_total": 0 if n else 35},
                "_latency_ms": None, "_out_chars": None, "_acc_spread": 0.0,
                "_errors": n, "_first_error": "402 insufficient credit" if n else None}
    monkeypatch.setattr(R, "probe_repeated", probe)
    monkeypatch.setattr(R, "per_kind", lambda r: {})
    monkeypatch.setattr(R, "update_metrics_file", lambda *a, **k: None)
    for m in models:
        monkeypatch.setenv(m.key_env, "test-key")
    for k in ("DATABASE_URL", "EVAL_HISTORY_WRITE_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("sys.argv", ["run", "--metrics", str(tmp_path / "m.json"),
                                     "--narrative", str(tmp_path / "n.json")])
    return R.main()


def _m(i, env, funding):
    return Model(i, i, "openai", i, env, funding=funding)


def test_spent_prepaid_credential_does_not_fail_the_job(monkeypatch, tmp_path, capsys):
    ms = [_m("x1", "XAI_API_KEY", "prepaid"), _m("c1", "ANTHROPIC_API_KEY", "auto-reload")]
    assert _run(monkeypatch, tmp_path, ms, {"x1"}) == 0
    assert "PAUSED — prepaid credit exhausted" in capsys.readouterr().out


def test_dark_auto_reload_credential_still_fails_the_job(monkeypatch, tmp_path):
    ms = [_m("x1", "XAI_API_KEY", "prepaid"), _m("c1", "ANTHROPIC_API_KEY", "auto-reload")]
    assert _run(monkeypatch, tmp_path, ms, {"x1", "c1"}) == 1
