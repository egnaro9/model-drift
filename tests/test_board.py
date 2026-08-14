"""The offline standings derivation: the published board recomputed from the
stored rows, as pure functions — plus the lockstep gates that keep the offline
path and the live (eval-history-backed) path telling the same story.

Two disciplines pinned here, both paid for elsewhere in this repo:

  * every gate is exercised in BOTH directions — a coherence check that was
    never seen red, or a lockstep compare that could not fail, would be exactly
    the vacuous guardrail this portfolio keeps writing field notes about;
  * the lockstep tests run against the real committed artifacts, so a
    divergence between the board's two stores fails CI by name instead of
    quietly publishing two disagreeing tables.
"""
import json
import pathlib

from modeldrift.board import (coherence, results_md_offline, standings_rows,
                              statuses_from_series)
from modeldrift.narrative import narrate
from modeldrift.suite import SUITE, SUITE_VERSION, suite_hash

ROOT = pathlib.Path(__file__).resolve().parents[1]

REG = [
    {"id": "mock:stable", "label": "Mock (stable)", "tier": "mock", "group": "Mock"},
    {"id": "a:up", "label": "Up", "tier": "flagship", "group": "A"},
    {"id": "a:down", "label": "Down", "tier": "mid", "group": "A"},
    {"id": "b:flat", "label": "Flat", "tier": "flagship", "group": "B"},
    {"id": "b:new", "label": "New", "tier": "mini", "group": "B"},
    {"id": "c:ghost", "label": "Ghost", "tier": "mini", "group": "C"},
]


def _pt(t, acc, fails=(), **kw):
    return {"t": t, "acc": acc, "latency_ms": 100.0, "out_chars": 5.0,
            "reliability": 1.0, "refusal_rate": 0.0, "by_kind": {}, "runs": 3,
            "acc_spread": 0.0, "fails": list(fails), **kw}


SERIES = {
    "mock:stable": [_pt("2026-07-01T00:00:00Z", 1.0), _pt("2026-07-02T00:00:00Z", 1.0)],
    "a:up": [_pt("2026-07-01T00:00:00Z", 0.8), _pt("2026-07-02T00:00:00Z", 0.9143)],
    "a:down": [_pt("2026-07-01T00:00:00Z", 0.9), _pt("2026-07-02T00:00:00Z", 0.8, ["if-json"])],
    "b:flat": [_pt("2026-07-01T00:00:00Z", 0.7), _pt("2026-07-02T00:00:00Z", 0.7)],
    "b:new": [_pt("2026-07-02T00:00:00Z", 0.6)],
    # c:ghost has no series at all → no-data
}


def test_verdicts_mirror_the_live_report():
    by = {s.id: s for s in statuses_from_series(SERIES, REG)}
    assert by["a:up"].verdict == "improved" and by["a:up"].delta == round(0.9143 - 0.8, 4)
    assert by["a:down"].verdict == "regressed"
    assert by["b:flat"].verdict == "unchanged" and by["b:flat"].delta == 0.0
    assert by["b:new"].verdict == "baseline" and by["b:new"].delta is None
    assert by["c:ghost"].verdict == "no-data" and by["c:ghost"].latest is None


def test_registry_order_is_row_order():
    assert [s.id for s in statuses_from_series(SERIES, REG)] == [m["id"] for m in REG]


def test_floor_comes_from_the_stored_graded_count():
    """100/graded, from the committed row — the number that was structurally
    unpublishable while it lived only in a dropped API field."""
    series = {"a:up": [_pt("2026-07-01T00:00:00Z", 0.9, graded=35),
                       _pt("2026-07-02T00:00:00Z", 0.92, graded=33)]}
    row = standings_rows(statuses_from_series(series, REG[1:2]))[0]
    assert row["graded"] == 33
    assert row["min_detectable_pts"] == round(100.0 / 33, 3)
    # +2.0 pts on a 33-call run is under the 3.03-pt floor: flagged, so the
    # denominator moving cannot be read as the model moving
    assert row["below_floor"] is True


def test_no_graded_means_no_floor_not_a_guessed_one():
    row = standings_rows(statuses_from_series(SERIES, REG[1:2]))[0]
    assert row["graded"] is None and row["min_detectable_pts"] is None
    assert row["below_floor"] is False


def test_a_real_move_is_not_flagged_below_floor():
    series = {"a:up": [_pt("2026-07-01T00:00:00Z", 0.6, graded=35),
                       _pt("2026-07-02T00:00:00Z", 0.9, graded=35)]}
    row = standings_rows(statuses_from_series(series, REG[1:2]))[0]
    assert row["below_floor"] is False and row["verdict"] == "improved"


# ── coherence: seen clean AND seen red ─────────────────────────────────────

FP = (SUITE_VERSION, suite_hash(), [t.id for t in SUITE])


def test_committed_rows_are_coherent():
    metrics = json.loads((ROOT / "dashboard/metrics.json").read_text(encoding="utf-8"))
    assert coherence(metrics, *FP) == []


def test_synthetic_rows_are_coherent():
    assert coherence({"series": SERIES}, *FP) == []


def test_coherence_fires_on_each_violation():
    cases = {
        "acc": [_pt("2026-07-01T00:00:00Z", 1.5)],
        "precedes": [_pt("2026-07-02T00:00:00Z", 1.0), _pt("2026-07-01T00:00:00Z", 1.0)],
        "outside the suite": [_pt("2026-07-01T00:00:00Z", 0.9, ["not-a-task"])],
        "graded": [_pt("2026-07-01T00:00:00Z", 0.9, graded=0)],
        "graded ": [_pt("2026-07-01T00:00:00Z", 0.9, graded=len(SUITE) + 1)],
        "suite": [_pt("2026-07-01T00:00:00Z", 0.9, suite="2099-01-v9")],
        "suite_hash": [_pt("2026-07-01T00:00:00Z", 0.9, suite_hash="beefbeefbeef")],
        "fails_runs": [_pt("2026-07-01T00:00:00Z", 0.9, ["if-json"],
                           fails_runs=[[], ["math-order"]])],
        "reliability": [_pt("2026-07-01T00:00:00Z", 0.9, reliability=-0.1)],
    }
    for needle, pts in cases.items():
        bad = coherence({"series": {"x:y": pts}}, *FP)
        assert bad and needle.strip() in "\n".join(bad), (needle, bad)


# ── lockstep with the published artifacts, on the real committed data ──────

def _committed():
    metrics = json.loads((ROOT / "dashboard/metrics.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "modeldrift/models.json").read_text(encoding="utf-8"))
    return metrics, registry


def test_committed_results_md_rerenders_from_the_committed_rows():
    """The whole published table — every accuracy, delta, floor, and verdict —
    is a byte-identical function of the stored rows. If this goes red, the
    board's two stores (eval-history, which report.py reads live, and the
    committed metrics file) have diverged: diagnose which one is lying before
    anything else, and never 'fix' it by editing RESULTS.md by hand."""
    metrics, registry = _committed()
    derived = results_md_offline(metrics["series"], registry)
    assert derived == (ROOT / "RESULTS.md").read_text(encoding="utf-8")


def test_committed_narrative_rederives_from_the_committed_rows():
    """Same gate for the generated prose: the committed paragraph must be
    exactly what the claims generator emits from the committed numbers."""
    metrics, registry = _committed()
    regen = json.dumps(narrate(metrics, registry), indent=1) + "\n"
    assert regen == (ROOT / "dashboard/narrative.json").read_text(encoding="utf-8")


def test_the_rerender_gate_can_fail():
    """Liveness of the lockstep gate itself: move one stored point and the
    re-rendered table must change. A compare that stayed green over tampered
    rows would be the vacuous-guardrail failure mode, verbatim."""
    metrics, registry = _committed()
    series = json.loads(json.dumps(metrics["series"]))     # deep copy
    victim = next(m["id"] for m in registry if m["id"] in series
                  and len(series[m["id"]]) >= 2 and m.get("tier") != "mock")
    series[victim][-1]["acc"] = round(1.0 - series[victim][-1]["acc"], 4) or 0.5
    assert results_md_offline(series, registry) != \
        results_md_offline(metrics["series"], registry)
