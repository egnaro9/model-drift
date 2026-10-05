"""flips.py must not score an outage as instability.

Before 2026-10-05 this module compared RAW consecutive points. A provider outage read
as every task breaking at once and then recovering, and 268 of the board's 895 recorded
flips were manufactured that way by 19 untrusted points, every one on a Gemini model.
board.py had the filter two files away and said why in a comment; this module never
called it.
"""
from __future__ import annotations

from modeldrift.flips import analyze, flips_for_model
from modeldrift.policy import REL_FLOOR, trusted_points


def _pt(day, fails, rel=1.0, graded=35):
    return {"t": f"2026-09-{day:02d}T00:00:00Z", "fails": list(fails),
            "reliability": rel, "graded": graded, "acc": (graded - len(fails)) / graded}


OUT = _pt(12, [f"task-{i}" for i in range(30)], rel=0.03)   # the provider was down


def test_an_outage_manufactures_no_flips():
    """Steady, outage, steady. The old code counted 60 flips here: 30 tasks breaking
    into the outage and 30 recovering out of it."""
    pts = [_pt(11, ["a"]), OUT, _pt(13, ["a"])]
    assert sum(r["flips"] for r in flips_for_model(trusted_points(pts))) == 0


def test_analyze_drops_the_outage_without_being_asked():
    """The filter has to live inside analyze. A caller who forgets is the bug that was
    shipped, and every caller forgot because there was nothing to remember."""
    series = {"google:gemini-3.5-flash": [_pt(11, ["a"]), OUT, _pt(13, ["a"])]}
    a = analyze(series)
    assert sum(r["flips"] for k in ("repeat_offenders", "one_offs")
               for r in a.get(k, [])) == 0


def test_a_real_flip_still_registers():
    """The mirror. A filter that suppressed everything would be the opposite defect and
    would look identical from the outside: a quiet detector."""
    series = {"xai:grok-4-fast": [_pt(11, ["a"]), _pt(12, ["a", "b"]), _pt(13, ["a"])]}
    a = analyze(series)
    flips = {r["task"]: r["flips"] for k in ("repeat_offenders", "one_offs")
             for r in a.get(k, [])}
    assert flips.get("b") == 2, flips


def test_an_outage_does_not_raise_a_probe_alarm():
    """The cross-provider path reads the same points. Three providers down on one day
    is an outage, not an accusation against the probe."""
    day = [_pt(12, [f"task-{i}" for i in range(30)], rel=0.03)]
    series = {f"{p}:m": list(day) for p in ("openai", "anthropic", "google")}
    assert not analyze(series).get("probe_alarms")


def test_one_definition_of_trusted_points():
    """It moved to policy.py when flips became a second consumer. Two copies of a
    predicate that must agree is the shape this repository keeps finding."""
    from modeldrift import board, policy
    assert board.trusted_points is policy.trusted_points
    assert policy.REL_FLOOR == REL_FLOOR
