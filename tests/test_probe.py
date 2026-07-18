"""The probe and its graders, on the deterministic mock — no keys, no network.

A drift tracker is only trustworthy if the *grader* is trustworthy: a scored run
must depend on the model's answer and nothing else. These pin that — the graders
pass and fail the right things, a clean model scores 1.0, and a model that returns
wrong answers is caught (not silently averaged away).
"""
from modeldrift.providers import Model
from modeldrift.run import per_kind, probe
from modeldrift.suite import SUITE, suite_hash

STABLE = Model("mock:stable", "Mock", "mock", "mock", "NONE")
DRIFTED = Model("mock:drifted", "Mock (drifted)", "mock", "mock-drifted", "NONE")


def test_a_correct_model_scores_perfectly():
    r = probe(STABLE)
    assert r["metrics"]["faithfulness"] == 1.0
    assert r["metrics"]["flagged_cases"] == 0.0
    assert r["metrics"]["n_cases"] == len(SUITE)


def test_a_drifted_model_is_caught_not_averaged_away():
    """mock-drifted fails exactly two tasks (if-json, math-order)."""
    r = probe(DRIFTED)
    assert r["metrics"]["faithfulness"] < 1.0
    flagged = [c for c in r["cases"] if c["flagged"]]
    ids = {c["q"].split("]")[0].lstrip("[") for c in flagged}
    assert ids == {"if-json", "math-order"}


def test_score_drop_is_exactly_the_two_failures():
    stable, drifted = probe(STABLE), probe(DRIFTED)
    n = len(SUITE)
    assert round(stable["metrics"]["faithfulness"] - drifted["metrics"]["faithfulness"], 4) == round(2 / n, 4)


def test_per_kind_breakdown_localises_the_regression():
    """The value of the tracker: not just 'it dropped' but 'instruction-following
    and arithmetic dropped' — the two kinds the drifted tasks belong to."""
    by = per_kind(probe(DRIFTED))
    assert by["instruction-following"] < 1.0   # if-json failed
    assert by["arithmetic"] < 1.0              # math-order failed
    assert by["factual-recall"] == 1.0         # untouched


def test_graders_are_strict_about_form():
    from modeldrift.suite import SUITE as S
    tasks = {t.id: t for t in S}
    assert tasks["if-one-word"].grade("blue") and not tasks["if-one-word"].grade("the sky is blue")
    assert tasks["if-json"].grade('{"ok": true}') and not tasks["if-json"].grade('sure: {"ok": true}')
    assert tasks["math-order"].grade("23") and tasks["math-order"].grade("The answer is 23.")
    assert not tasks["math-order"].grade("35")   # 3+4*5, not (3+4)*5
    assert tasks["fmt-list"].grade("2, 4, 6") and not tasks["fmt-list"].grade("2, 4, 6, 8")


def test_suite_hash_is_stable():
    assert suite_hash() == suite_hash() and len(suite_hash()) == 12


def test_run_shape_is_eval_history_compatible():
    r = probe(STABLE)
    assert set(r["metrics"]) >= {"faithfulness", "precision@k", "recall@k", "citation_rate",
                                 "flagged_cases", "n_cases"}
    assert all({"q", "answer", "scores", "flagged"} <= set(c) for c in r["cases"])


def test_probe_measures_latency_and_verbosity():
    r = probe(STABLE)
    assert r["_latency_ms"] is not None and r["_latency_ms"] >= 0
    assert r["_out_chars"] is not None and r["_out_chars"] > 0


def test_metrics_file_accumulates_and_skips_total_failures(tmp_path):
    import json
    from modeldrift.run import update_metrics_file
    r = probe(STABLE)
    f = tmp_path / "metrics.json"
    update_metrics_file(str(f), [r], "2026-07-18T00:00:00Z")
    d = json.loads(f.read_text())
    assert set(d["series"]["mock:stable"][0]) == {"t", "acc", "latency_ms", "out_chars"}
    update_metrics_file(str(f), [r], "2026-07-25T00:00:00Z")          # appends
    assert len(json.loads(f.read_text())["series"]["mock:stable"]) == 2
    failed = {**r, "run": "x:broken", "_latency_ms": None, "_out_chars": None}
    update_metrics_file(str(f), [failed], "2026-07-26T00:00:00Z")     # skipped
    assert "x:broken" not in json.loads(f.read_text())["series"]
