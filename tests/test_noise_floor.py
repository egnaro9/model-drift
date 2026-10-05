"""A move must clear the model's own spread, not just the arithmetic floor.

These two were conflated until 2026-09-23. The arithmetic floor asks what the
smallest difference ONE run can print is, given its denominator. The noise
floor asks how far the SAME model moves between runs of the identical frozen
suite. Only the second decides whether a move means anything, and on grok-4.3
it was three times larger.
"""
import pytest
from modeldrift.report import (ModelStatus, min_detectable_change, noise_floor,
                               reportable_threshold)


def test_noise_floor_is_the_median_in_points():
    assert noise_floor([0.02, 0.04, 0.06]) == 4.0


def test_noise_floor_ignores_an_outage_sized_outlier():
    """grok-4.5's worst recorded spread is 91.43 points and its median is 1.43.
    Taking the max would suppress every finding on any model that ever had a
    bad morning."""
    assert noise_floor([0.0, 0.0143, 0.0, 0.9143, 0.0143]) < 2.0


def test_noise_floor_is_none_when_nothing_recorded():
    assert noise_floor([None, None]) is None
    assert noise_floor([]) is None


def test_threshold_takes_the_LARGER_of_the_two():
    assert reportable_threshold(35, 5.72) == pytest.approx(5.72)
    assert reportable_threshold(35, 0.0) == pytest.approx(100 / 35)


def test_threshold_falls_back_when_no_spread_is_known():
    """Older runs predate acc_spread. They keep the old behaviour rather than
    becoming unreportable."""
    assert reportable_threshold(35, None) == pytest.approx(100 / 35)


def test_the_retired_grok_finding_would_no_longer_be_reported():
    """The regression test for the whole change.

    2026-09-23: a 4.30 point move was drafted as a regression against an
    arithmetic floor of 2.94. Three confirming probes put grok-4.3's own spread
    at 8.57 points, and its recent median at 5.72. The finding was retired.
    """
    move = 4.30
    assert move >= min_detectable_change(34), "it did clear the arithmetic floor"
    assert move < reportable_threshold(34, 5.72), "and it must NOT clear both"


def test_a_stable_model_keeps_full_sensitivity():
    """The mirror. A threshold that suppresses everything is not a fix.

    gpt-5's median spread is 0.00, so its threshold stays at the arithmetic
    floor and a 3 point move is still reported.
    """
    assert 3.0 >= reportable_threshold(35, 0.0)


def test_a_move_larger_than_both_floors_still_reports():
    assert 9.0 >= reportable_threshold(34, 5.72)


def test_status_carries_the_spread_so_findings_can_see_it():
    s = ModelStatus("x", "X", 0.9, -0.043, "regressed", "2026-09-23", 34, noise_pts=5.72)
    assert reportable_threshold(s.graded, s.noise_pts) == pytest.approx(5.72)


# ── the WIRING, not just the function ─────────────────────────────────────
# The tests above all pass with findings.py passing None for the spread, which
# means they prove nothing about whether the detector actually consults it.

from modeldrift.findings import regressions_and_recoveries


def _status(**kw):
    base = dict(id="xai:grok-4.3", label="Grok 4.3", latest=0.9143, delta=-0.0428,
                verdict="regressed", when="2026-09-23", graded=34)
    base.update(kw)
    return ModelStatus(**base)


def test_findings_SUPPRESSES_a_move_inside_the_model_spread():
    """The end-to-end case. 4.28 points clears the arithmetic floor of 2.94 and
    must still not be drafted, because this model moves 5.72 on its own."""
    out = regressions_and_recoveries([_status(noise_pts=5.72)])
    assert out == [], "a move smaller than the model's own spread was drafted as a finding"


def test_findings_REPORTS_the_same_move_on_a_stable_model():
    """Same delta, same denominator, quiet model. It must still come through,
    or the fix is just a mute button."""
    out = regressions_and_recoveries([_status(noise_pts=0.0)])
    assert len(out) == 1
    assert out[0].kind == "regression"


def test_findings_still_reports_a_move_larger_than_the_spread():
    out = regressions_and_recoveries([_status(delta=-0.09, noise_pts=5.72)])
    assert len(out) == 1


def test_findings_falls_back_when_the_spread_is_unknown():
    """Runs predating acc_spread keep the old behaviour."""
    out = regressions_and_recoveries([_status(noise_pts=None)])
    assert len(out) == 1


# ---- the boundary: a move must EXCEED the floor, not land on it ----
# Added 2026-09-28. `move_pts < floor` admitted single-item flips, and three drafts
# (Opus 4.8, GPT-OSS 20B, Gemini 3.5 Flash) each reported one item moving as a
# regression whose evidence claimed it was larger than the run could print.

from modeldrift.report import clears_floor


def one_item(graded: int, passed: int) -> float:
    """move_pts for one graded item flipping, by the same route findings.py uses."""
    return abs(passed / graded - (passed - 1) / graded) * 100


def test_the_real_board_row_that_shipped_a_false_draft():
    """The exact numbers from dashboard/drift_board.json on 2026-09-28, which my first
    attempt at this fix did NOT suppress. The board rounds acc to 4 dp, so the move
    arrives as 2.860 rather than 2.857142, a full 0.003 ABOVE the exact floor. Any
    fix that compares points at full precision passes this through."""
    move = abs(0.8857 - 0.9143) * 100          # stored 31/35 and 32/35
    assert move > min_detectable_change(35), "the stored move really is above the floor"
    assert not clears_floor(move, min_detectable_change(35))


def test_one_item_flip_never_clears_the_arithmetic_floor():
    """The whole bug. One item is the smallest move possible, so it cannot be
    evidence that a move was larger than the smallest move possible."""
    for passed in range(1, 36):
        move = one_item(35, passed)
        assert not clears_floor(move, min_detectable_change(35)), (
            f"{passed}/35 vs {passed-1}/35 reported a one-item flip")


def test_the_old_comparison_would_have_admitted_these():
    """Guards the regression. A bare `>` disagrees with itself on float noise: the
    same physical event passes at 32/35 and fails at 30/35."""
    floor = min_detectable_change(35)
    assert one_item(35, 32) > floor, "32/35 slipped past a bare >"
    assert one_item(35, 30) < floor, "30/35 was caught by a bare >, same event"
    for passed in (30, 32):
        assert not clears_floor(one_item(35, passed), floor)


def test_two_items_still_clears():
    move = abs(33 / 35 - 31 / 35) * 100
    assert clears_floor(move, min_detectable_change(35))


def test_the_boundary_holds_across_denominators():
    for graded in (7, 20, 33, 35, 100, 159):
        floor = min_detectable_change(graded)
        assert not clears_floor(one_item(graded, graded), floor), f"graded={graded}"
        two = abs(graded / graded - (graded - 2) / graded) * 100
        assert clears_floor(two, floor), f"graded={graded} suppressed a two-item move"


def test_a_move_equal_to_the_measured_spread_is_suppressed():
    """Equal to the model's own run-to-run spread is not distinguishable from
    sampling it again, so it is not reportable either."""
    assert not clears_floor(8.57, reportable_threshold(35, 8.57))
    # 8.58 is NOT enough: one stored unit on each acc is worth 0.01 pts, so a move
    # that beats the spread by 0.01 has not beaten it at this precision.
    assert not clears_floor(8.58, reportable_threshold(35, 8.57))
    assert clears_floor(8.60, reportable_threshold(35, 8.57))


def test_unknown_floor_still_reports():
    """A row predating graded_total must not be silently suppressed; the evidence
    line says the floor is UNKNOWN instead."""
    assert clears_floor(2.0, None) is True


# ----------------------------------------- pooled_noise_floor, added 2026-10-05
#
# The median-of-daily-spreads floor is built from three-run estimates, and three runs
# does not estimate this quantity: grok-4-fast measured 2.86 points of spread on
# 2026-09-29 and 8.58 on 2026-10-03, same model, same frozen suite. These tests pin the
# pooled estimator and, more importantly, pin that it can never LOWER a floor.

def _pt(graded, fails_per_run):
    return {"graded": graded, "runs": len(fails_per_run), "fails_runs": fails_per_run}


def test_pooled_floor_is_none_below_the_minimum_sample():
    """Fewer than MIN_POOLED_RUNS runs is not an estimate, and returning a number
    anyway would be the whole defect this function exists to fix, one layer in."""
    from modeldrift.report import pooled_noise_floor, MIN_POOLED_RUNS
    pts = [_pt(35, [[], ["a"]])]                       # 2 runs
    assert pooled_noise_floor(pts) is None
    assert MIN_POOLED_RUNS >= 6


def test_pooled_floor_sees_spread_that_daily_medians_hide():
    """Every DAY is internally consistent, so every per-day spread is 0 and the median
    floor is 0. The model still moves between days. The pooled band sees it."""
    import statistics
    from modeldrift.report import noise_floor, pooled_noise_floor
    pts = ([_pt(35, [[], [], []]) for _ in range(5)] +          # 3 days at 100%
           [_pt(35, [["a"]*7]*3) for _ in range(5)])            # 3 days at 80%
    assert noise_floor([0.0] * 10) == 0.0
    pooled = pooled_noise_floor(pts)
    assert pooled is not None and pooled > 10, pooled


def test_pooled_floor_is_a_band_not_a_range():
    """max - min grows with n by construction, so it would credit the estimator for
    nothing but a bigger sample. One extreme run must not set the floor on its own."""
    from modeldrift.report import pooled_noise_floor
    steady = [_pt(35, [[], [], []]) for _ in range(9)]
    with_outlier = steady + [_pt(35, [["x"] * 35])]      # one run at 0%
    assert pooled_noise_floor(steady) == 0.0
    assert pooled_noise_floor(with_outlier) < 50.0


def test_board_floor_never_falls_below_the_median_floor():
    """THE property the whole change rests on, driven through board.py itself.

    The first version of this test computed max() on its own values and asserted the
    result, which is a test of the `max` builtin. Replacing board.py's
    `max(_med, _pooled)` with plain `_pooled` passed all 368 tests. A test that cannot
    fail is the defect this repository exists to catch, so it has to drive the real
    line: a series where the pooled band is NARROWER than the median floor, where
    taking the pooled value alone would silently lower the gate.
    """
    from modeldrift.board import statuses_from_series
    from modeldrift.report import noise_floor, pooled_noise_floor
    # THE REALISTIC WAY THE TWO DISAGREE, and it is not contrived. The two estimators
    # read different subsets: noise_floor needs `acc_spread`, pooled_noise_floor needs
    # `fails_runs`. Older rows predate per-point run emission and carry the first
    # without the second, which board.py's own docstring already notes. So a history of
    # noisy days with no per-run detail, plus a few recent quiet days that have it,
    # leaves the median high and the pooled band near zero.
    pts = []
    for i in range(7):                      # noisy, spread recorded, no per-run detail
        pts.append({"acc": 30 / 35, "acc_spread": 5 / 35, "reliability": 1.0,
                    "graded": 35, "t": f"2026-09-{i + 10:02d}T00:00:00Z"})
    for i in range(3):                      # quiet, and the only days pooled can see
        q = _pt(35, [[], [], []])
        q.update(acc=1.0, acc_spread=0.0, reliability=1.0,
                 t=f"2026-09-{i + 17:02d}T00:00:00Z")
        pts.append(q)
    med, pooled = noise_floor([p["acc_spread"] for p in pts]), pooled_noise_floor(pts)
    assert pooled is not None and pooled < med, (
        f"fixture does not exercise the property: pooled={pooled} med={med}")

    st = statuses_from_series({"m:x": pts}, [{"id": "m:x", "label": "m"}])
    assert st[0].noise_pts == med, (
        f"board lowered the floor to {st[0].noise_pts}; the median was {med}. "
        "max(median, pooled) is what keeps this change from creating false positives.")


def test_board_raises_the_floor_when_the_pooled_band_is_wider():
    """The mirror, and it was missing. Dropping pooled_noise_floor from board.py
    entirely passed all 368 tests, so nothing held the benefit of this change, only its
    safety. This is the grok-4-fast shape: every DAY internally consistent, so every
    per-day spread is 0 and the median floor is 0, while the model moves between days.
    """
    from modeldrift.board import statuses_from_series
    from modeldrift.report import noise_floor, pooled_noise_floor
    pts = []
    for i in range(5):                       # five days pinned at 100%
        q = _pt(35, [[], [], []])
        q.update(acc=1.0, acc_spread=0.0, reliability=1.0,
                 t=f"2026-09-{i + 10:02d}T00:00:00Z")
        pts.append(q)
    for i in range(5):                       # five days pinned at 80%, still spread 0
        q = _pt(35, [["x"] * 7] * 3)
        q.update(acc=28 / 35, acc_spread=0.0, reliability=1.0,
                 t=f"2026-09-{i + 15:02d}T00:00:00Z")
        pts.append(q)

    med, pooled = noise_floor([p["acc_spread"] for p in pts]), pooled_noise_floor(pts)
    assert med == 0.0, f"fixture broken: median should be 0, got {med}"
    assert pooled is not None and pooled > 10, (
        f"fixture does not exercise the property: pooled={pooled}")

    st = statuses_from_series({"m:x": pts}, [{"id": "m:x", "label": "m"}])
    assert st[0].noise_pts == pooled, (
        f"board reported {st[0].noise_pts}; the pooled band was {pooled} and the median "
        "was 0. Without pooled the gate would compare a real 20-point move against a "
        "floor of 2.86 and draft it, which is what this change exists to stop.")
