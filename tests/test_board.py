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
import pytest
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
    metrics = json.loads((ROOT / "dashboard/drift_board.json").read_text(encoding="utf-8"))
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
    metrics = json.loads((ROOT / "dashboard/drift_board.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "modeldrift/models.json").read_text(encoding="utf-8"))
    return metrics, registry


def test_committed_results_md_rerenders_from_the_committed_rows():
    """RESULTS.md on disk is exactly what the renderer emits from the stored rows.

    This no longer cross-checks two stores. It used to, by accident: report.py built the
    published table from eval-history while this rebuilt it from the committed rows, so a
    disagreement showed up as a Markdown diff. That coincidence was also the bug's hiding
    place, because eval-history has no reliability column and could not apply the trust
    floor, so the two sides were never comparable in the first place. report.py now renders
    through this same derivation, which makes this a staleness check: the committed file
    matches the current code. The store agreement it used to imply is asserted directly by
    test_eval_history_agrees_with_the_committed_series below.

    Never 'fix' a failure here by editing RESULTS.md by hand; re-run the producer."""
    metrics, registry = _committed()
    derived = results_md_offline(metrics["series"], registry)
    assert derived == (ROOT / "RESULTS.md").read_text(encoding="utf-8")


def test_eval_history_agrees_with_the_committed_series():
    """The upstream evaluation record and the committed rows describe the same runs.

    The real invariant behind the old Markdown comparison. run.py posts each probe to
    eval-history and writes the same numbers into dashboard/drift_board.json; if those two
    stores disagree, one of them is lying and every published figure is suspect.

    Handling, stated rather than implied:
      * eval-history unreachable  -> skip. A repo test cannot assert a third-party service
        is up. This is a real gap: the check does not run when the service is down, so it
        is a companion to CI-side validation, not a substitute for it.
      * model absent upstream     -> skip that model (newly added, never probed).
      * model absent locally      -> skip that model.
      * upstream ahead of commit  -> compare like-for-like by run DATE, never newest-to-newest.
        The probe posts to eval-history immediately and the commit lands afterwards, so
        upstream is routinely a day ahead. Comparing the two newest rows reports that
        ordinary lag as a store disagreement, which is a false alarm, not a defect.
      * no upstream run for the committed date -> skip that model.
      * failed / sub-floor runs   -> NOT excluded. This compares what each store recorded,
        not what is trustworthy. An outage must appear identically in both; filtering it
        here would hide exactly the disagreement the test exists to find.
    """
    import urllib.error
    import urllib.request
    from urllib.parse import quote

    api = "https://eval-history.onrender.com"
    metrics, registry = _committed()
    series = metrics["series"]

    def upstream_runs(model_id):
        url = f"{api}/runs?name={quote(model_id)}&limit=10"
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())

    try:
        probe = upstream_runs(registry[0]["id"])
    except Exception as e:                                  # noqa: BLE001 - service, not code
        pytest.skip(f"eval-history unreachable ({type(e).__name__}); store agreement unchecked")
    if not probe and not any(series.get(m["id"]) for m in registry):
        pytest.skip("neither store has any runs yet")

    compared, mismatches = 0, []
    for m in registry:
        pts = series.get(m["id"]) or []
        if not pts:
            continue
        try:
            runs = upstream_runs(m["id"])
        except Exception:                                   # noqa: BLE001
            continue
        day = str(pts[-1].get("t"))[:10]
        up = next((r for r in runs if str(r.get("created_at"))[:10] == day), None)
        if up is None:
            continue
        compared += 1
        local, remote = round(pts[-1]["acc"], 4), round(up["faithfulness"], 4)
        if local != remote:
            mismatches.append(
                f"{m['id']} on {day}: committed {local} vs eval-history {remote}")

    assert compared, "no model could be compared; the agreement check did not actually run"
    assert not mismatches, (
        "the two stores disagree on the newest run:\n  " + "\n  ".join(mismatches))


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
