"""The reliability floor must live in Python, fire, and match the dashboard.

Regression test for a real defect found 2026-08-17: REL_FLOOR existed only in
dashboard/index.html JavaScript. board.py wrote RESULTS.md without it, so a
Google provider outage published as three Gemini "regressions" (-37.1 and
-94.3 pts) while the chart directly above those rows correctly excluded the
same points. The rule was documented in README.md and enforced in one surface
out of two.
"""
import re
from pathlib import Path

from modeldrift.board import REL_FLOOR, statuses_from_series, trusted_points

ROOT = Path(__file__).resolve().parents[1]

REGISTRY = [{"id": "m", "label": "M"}]


def _pt(t, acc, rel):
    return {"t": t, "acc": acc, "reliability": rel}


def test_floor_drops_the_outage_point():
    """A healthy run then an outage must not read as a regression."""
    series = {"m": [_pt("2026-08-01T00:00:00Z", 0.80, 1.0),
                    _pt("2026-08-02T00:00:00Z", 0.029, 0.0286)]}
    (s,) = statuses_from_series(series, REGISTRY)
    assert s.verdict != "regressed", (
        "an outage point (reliability 0.0286) was scored as accuracy; "
        "this is exactly the RESULTS.md bug")
    assert s.latest == 0.80, "the last trusted accuracy should survive"


def test_floor_actually_fires():
    """Liveness: the filter must remove something, not pass everything through.

    Without this the test above would still pass if trusted_points became the
    identity function.
    """
    pts = [_pt("t1", 1.0, 1.0), _pt("t2", 0.0, 0.01)]
    assert len(trusted_points(pts)) == 1, "floor did not exclude the low-reliability point"


def test_boundary_is_inclusive():
    assert len(trusted_points([_pt("t", 0.5, REL_FLOOR)])) == 1
    assert len(trusted_points([_pt("t", 0.5, REL_FLOOR - 1e-9)])) == 0


def test_missing_reliability_is_kept():
    """Rows predating per-point reliability must not be silently dropped."""
    assert len(trusted_points([{"t": "t", "acc": 0.7}])) == 1
    assert len(trusted_points([{"t": "t", "acc": 0.7, "reliability": None}])) == 1


def test_all_points_below_floor_reads_as_no_data():
    series = {"m": [_pt("t1", 0.02, 0.02), _pt("t2", 0.03, 0.03)]}
    (s,) = statuses_from_series(series, REGISTRY)
    assert s.verdict == "no-data"
    assert s.latest is None


def test_python_and_dashboard_floors_agree():
    """The two surfaces must not drift apart again."""
    html = (ROOT / "dashboard" / "index.html").read_text()
    m = re.search(r"const\s+REL_FLOOR\s*=\s*([0-9.]+)\s*;", html)
    assert m, "REL_FLOOR not found in dashboard/index.html"
    assert float(m.group(1)) == REL_FLOOR, (
        f"dashboard JS floor {m.group(1)} != Python REL_FLOOR {REL_FLOOR}")
