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
