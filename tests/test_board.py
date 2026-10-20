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
import datetime
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



# The store-agreement check below is a MONITOR: it reads two live stores and cannot fail
# on clean data, so it cannot be mutation-tested and a green run proves very little about
# the matching rule itself. The rule is therefore extracted here and exercised directly by
# test_nearest_shared_probe_* with fixtures, which CAN fail on demand.
def _nearest_shared_probe(points, runs, window_s):
    """Pair the newest upstream row with the committed point nearest it in time.

    `points` are committed board points ({"t", "acc"}), `runs` are upstream rows
    ({"created_at", "faithfulness"}) newest first. Returns (point, run, gap_seconds),
    with point None when nothing lands inside `window_s`. gap is None only when there
    was nothing to measure at all.
    """
    def ts(value):
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    points = [p for p in points if isinstance(p, dict) and p.get("t")]
    runs = [r for r in runs if isinstance(r, dict) and r.get("created_at")]
    if not points or not runs:
        return None, None, None
    run = runs[0]
    try:
        t_up = ts(run["created_at"])
    except (TypeError, ValueError):
        return None, None, None
    best, gap = None, None
    for point in points:
        try:
            d = abs((ts(point["t"]) - t_up).total_seconds())
        except (TypeError, ValueError):
            continue
        if gap is None or d < gap:
            best, gap = point, d
    if best is None or gap > window_s:
        return None, run, gap
    return best, run, gap


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
      * upstream ahead of commit  -> match the committed point to the upstream row NEAREST
        IN TIME within 300s, never newest-to-newest and never by calendar date. The probe
        posts to eval-history immediately and the commit lands afterwards, so upstream is
        routinely a day ahead; comparing the two newest rows reports that ordinary lag as a
        store disagreement. A DATE join has the opposite failure: on a day with two probes
        it pairs the board's last with the archive's first, which are different runs.
      * no upstream row inside the window -> that model is recorded in `unmatched` and
        named in the assertion output. It is never dropped silently.
      * failed / sub-floor runs   -> NOT excluded. This compares what each store recorded,
        not what is trustworthy. An outage must appear identically in both; filtering it
        here would hide exactly the disagreement the test exists to find.
    """
    import urllib.error
    import urllib.request

    # eval-history's hosted instance is retired; the upstream store is now its
    # static archive, which has no query string, so filter runs.json here.
    api = "https://erikhill.dev/eval-history"
    metrics, registry = _committed()
    series = metrics["series"]

    def _all_upstream():
        with urllib.request.urlopen(f"{api}/runs.json", timeout=30) as r:
            return json.loads(r.read())

    _cache = {}

    # Matching window; the reasoning for 4h is under ANCHOR ON THE ARCHIVE below.
    _WINDOW_S = 4 * 3600

    def _ts(value):
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    # THE HORIZON. The committed rows are frozen at the commit; the archive is not.
    # Comparing a frozen snapshot with whatever the archive holds TODAY makes the
    # verdict a function of the wall clock: on 2026-10-19 the VAC replay ran this
    # test at d6286ed (board ends 2026-10-05) against an archive that had resumed
    # writing on 2026-10-10, found no shared probe, and failed. When that commit was
    # made the archive was frozen at 2026-08-30 and the frozen-archive branch below
    # skipped instead. Same code, different week, different verdict. So only upstream
    # rows the committed board COULD have seen take part: created no later than that
    # model's newest committed point plus the matching window. Rows written after the
    # commit are not evidence for or against it. At HEAD this only drops archive rows
    # the board has not caught up to yet, and it makes a pinned commit give the same
    # answer next week as on the day it was made (for an append-only archive; a
    # rewritten history still fails, as it should).
    def _horizon(model_id):
        pts = [p for p in (series.get(model_id) or [])
               if isinstance(p, dict) and p.get("t")]
        if not pts:
            return None
        try:
            newest = max(_ts(p["t"]) for p in pts)
        except (TypeError, ValueError):
            return None
        return newest + datetime.timedelta(seconds=_WINDOW_S)

    def upstream_runs(model_id):
        if "rows" not in _cache:
            _cache["rows"] = _all_upstream()
        rows = [x for x in _cache["rows"] if x.get("name") == model_id]
        limit = _horizon(model_id)
        if limit is not None:
            seen = []
            for x in rows:
                try:
                    if _ts(x.get("created_at")) <= limit:
                        seen.append(x)
                except (TypeError, ValueError):
                    continue
            rows = seen
        rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return rows[:10]

    try:
        probe = upstream_runs(registry[0]["id"])
    except Exception as e:                                  # noqa: BLE001 - service, not code
        pytest.skip(f"eval-history unreachable ({type(e).__name__}); store agreement unchecked")
    if not probe and not any(series.get(m["id"]) for m in registry):
        pytest.skip("neither store has any runs yet")

    # ANCHOR ON THE ARCHIVE, THEN MATCH THE NEAREST COMMITTED POINT WITHIN A WINDOW.
    #
    # Two separate defects were here. The join was on calendar DATE, so on any day
    # holding more than one probe it paired the board's LAST point with the archive's
    # FIRST row: two probes of a nondeterministic model, whose disagreement is not a
    # store disagreement. The committed board already holds 5 points on 2026-07-19 and
    # 2 on 2026-07-31, so this was structural; it surfaced on 2026-10-10 when a manual
    # dispatch at 06:41Z and the cron at 15:15Z landed on the same date.
    #
    # The deeper one was the ANCHOR. The old code only ever looked at pts[-1], the
    # board's newest point, and eval-history is the sparser, lagging store: on
    # 2026-10-10 it holds only the 05:53 probe while the board holds both 06:41 and
    # 15:15. Anchored on the board's newest, the 15:15 run has no counterpart and never
    # will, so the check could only fail or skip. Anchored on the archive's newest row,
    # the comparison is the most recent probe BOTH stores actually saw, which is the
    # question this test is asking.
    #
    # THE WINDOW IS NOT INGEST JITTER, which is why 300s was wrong. The board stamps
    # every model with one shared run timestamp (06:41:20Z for all of them) while the
    # archive stamps each model at its own probe moment (05:53:35, 05:56:04, 05:58:40
    # ...). Same probe, two clocks, and the gap grows with the number of models probed
    # serially: ~0.8h on 2026-10-10, median 1.1h across all 927 archive rows. The
    # ceiling is set from the other side: probes run roughly daily, the largest
    # archive-anchored gap in the whole history is 20h, and a window at or above half
    # the probe interval could pair a row with the NEXT day's run. 4h clears the real
    # lag with margin and stays far below 12h. (_WINDOW_S and _ts are defined above
    # upstream_runs, because the horizon filter there needs them on its first call.)

    compared, mismatches, unmatched = 0, [], []
    for m in registry:
        pts = [p for p in (series.get(m["id"]) or []) if isinstance(p, dict) and p.get("t")]
        if not pts:
            continue
        try:
            runs = upstream_runs(m["id"])            # newest first
        except Exception:                                   # noqa: BLE001
            continue
        best, up, gap = _nearest_shared_probe(pts, runs, _WINDOW_S)
        if best is None:
            # SAY SO. "The stores agree" and "nothing was compared" are different
            # results and only one of them is a pass, so an unmatched model is carried
            # to the assertions below instead of vanishing at a bare `continue`.
            if up is not None:
                unmatched.append(
                    f"{m['id']}: newest upstream row {up.get('created_at')} has no "
                    f"committed point within {_WINDOW_S}s"
                    + (f"; nearest is {gap:.0f}s away" if gap is not None else ""))
            continue
        compared += 1
        local, remote = round(best["acc"], 4), round(up["faithfulness"], 4)
        if local != remote:
            mismatches.append(
                f"{m['id']}: committed {best.get('t')} = {local} vs eval-history "
                f"{up.get('created_at')} = {remote} ({gap:.0f}s apart)")

    if not compared:
        # Distinguish "nothing lined up today" from "this can never line up
        # again". eval-history's write path was retired with Render, so the
        # archive is frozen while the committed board advances daily. Every
        # committed date is newer than every upstream one, every model skips,
        # and the guard below fires on every run.
        #
        # It never got the chance to fire. The check first asked the retired
        # host whether it was there, got a 404, and skipped: 57 green runs over
        # 24 days, each printing "207 passed, 1 skipped". A test that CANNOT
        # pass produces the same red
        # as one that just broke and generates none of the urgency, and daily
        # red is how a real failure gets ignored later. The frozen case skips
        # with its reason stated; the guard stays for the ordinary case where
        # a live store simply had no matching row.
        newest_up = max((str(r.get("created_at"))[:10] for r in _cache.get("rows", [])),
                        default="")
        newest_local = max((str(pts[-1].get("t"))[:10]
                            for pts in series.values() if pts), default="")
        if newest_up and newest_local and newest_up < newest_local:
            pytest.skip(
                f"eval-history is a frozen archive: newest upstream run {newest_up}, "
                f"committed board reaches {newest_local}. The write path was retired "
                f"with Render, so there is no second store to agree with. This check "
                f"resumes if a live store is restored.")
    assert compared, (
        "no model could be compared; the agreement check did not actually run.\n  "
        + "\n  ".join(unmatched or ["(no models had committed points at all)"]))
    assert not mismatches, (
        "the two stores disagree on the newest run:\n  " + "\n  ".join(mismatches)
        + ("\n  also unmatched: " + "; ".join(unmatched) if unmatched else ""))


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


def test_rederive_is_a_pure_function_of_the_board(tmp_path):
    """The conflict resolution in track.yml depends on this: RESULTS.md and
    narrative.json must be reproducible from drift_board.json plus the
    registry, with no other input. If that ever stops being true, resolving a
    merge conflict by regenerating would silently drop whatever the extra
    input was."""
    import shutil
    from modeldrift.rederive import rederive
    for name in ("RESULTS.md",):
        shutil.copy(ROOT / name, tmp_path / name)
    (tmp_path / "dashboard").mkdir()
    for name in ("dashboard/drift_board.json", "dashboard/narrative.json"):
        shutil.copy(ROOT / name, tmp_path / name)

    args = (str(tmp_path / "dashboard/drift_board.json"),
            str(ROOT / "modeldrift/models.json"),
            str(tmp_path / "RESULTS.md"),
            str(tmp_path / "dashboard/narrative.json"))
    assert rederive(*args) == [], "committed derived files do not match the board"

    # Corrupt both renderings the way a bad text merge would, and prove a
    # regeneration restores them exactly.
    (tmp_path / "RESULTS.md").write_text("<<<<<<< HEAD\ngarbage\n", encoding="utf-8")
    (tmp_path / "dashboard/narrative.json").write_text("{}\n", encoding="utf-8")
    assert len(rederive(*args)) == 2
    assert (tmp_path / "RESULTS.md").read_text() == (ROOT / "RESULTS.md").read_text()
    assert ((tmp_path / "dashboard/narrative.json").read_text()
            == (ROOT / "dashboard/narrative.json").read_text())


# --- the matching rule, tested directly, no network -------------------------------
#
# The monitor above reads two live stores, so it is green whenever they happen to agree
# and silent about whether the RULE is right. These fixtures are the 2026-10-10 shape
# that put main red, reduced to the smallest thing that reproduces it.

_WINDOW = 4 * 3600

# Board stamps every model with one shared run timestamp; the archive stamps each model
# at its own probe moment, ~45min earlier. Two probes landed on 2026-10-10 and the
# archive only ever received the first.
_TWO_PROBES = [{"t": "2026-10-10T06:41:20Z", "acc": 0.8857},
               {"t": "2026-10-10T15:15:46Z", "acc": 0.9143}]
_ARCHIVE_SAW_THE_FIRST = [{"created_at": "2026-10-10T05:53:35.000000Z", "faithfulness": 0.8857}]


def test_nearest_shared_probe_pairs_the_run_both_stores_saw():
    """The regression that put main red on 2026-10-10.

    A calendar-date join took the board's NEWEST point (15:15, acc 0.9143) and the
    archive's only row (05:53, 0.8857) and called the difference a store disagreement.
    They are two different probes of a nondeterministic model. The 06:41 point is the
    one the archive actually saw, and it agrees exactly.
    """
    point, run, gap = _nearest_shared_probe(_TWO_PROBES, _ARCHIVE_SAW_THE_FIRST, _WINDOW)
    assert point is not None, f"the shared probe was not matched at all (gap {gap})"
    assert point["t"] == "2026-10-10T06:41:20Z", (
        f"paired the wrong probe: {point['t']}. Taking the board's newest point is the "
        f"bug, not the fix.")
    assert round(point["acc"], 4) == round(run["faithfulness"], 4), (
        "the stores agree on this probe; a mismatch here means the pairing is wrong")


def test_nearest_shared_probe_will_not_reach_into_another_days_run():
    """The other side of the window, so it cannot be satisfied by widening it.

    Probes run roughly daily. A window at or past half that interval would happily pair
    an archive row with the NEXT day's committed point and report agreement between two
    runs that have nothing to do with each other.
    """
    far = [{"t": "2026-10-11T15:15:46Z", "acc": 0.9143}]
    point, run, gap = _nearest_shared_probe(far, _ARCHIVE_SAW_THE_FIRST, _WINDOW)
    assert point is None, f"matched across {gap:.0f}s, which is a different day's run"
    assert run is not None and gap is not None, (
        "an unmatched model must still report the row and the distance, or the monitor "
        "cannot name what it failed to compare")


def test_nearest_shared_probe_reports_rather_than_vanishes():
    """A model with no committed points must come back as 'nothing to compare', not as
    a silent success. compared==0 with no explanation is how a skip becomes a pass."""
    assert _nearest_shared_probe([], _ARCHIVE_SAW_THE_FIRST, _WINDOW) == (None, None, None)
    assert _nearest_shared_probe(_TWO_PROBES, [], _WINDOW) == (None, None, None)
