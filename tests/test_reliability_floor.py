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

import json

from modeldrift.board import (REL_FLOOR, standings_rows,
                              statuses_from_series, trusted_points)

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


def test_report_consumes_the_floor_rather_than_redefining_it():
    """Three surfaces now, one authority.

    The 2026-08-17 fix moved the floor into Python, but into board.py only. report.py, which
    track.yml actually runs to write RESULTS.md, kept deriving statuses from eval-history,
    which carries no reliability column at all and so cannot apply a floor. The published
    table went on scoring a Google outage as three Gemini regressions for three weeks while
    the chart above it was correct, because nothing pinned the producer to the authority.

    A fourth implementation is the failure mode, so this asserts absence: report.py must
    import the derivation, never define a floor of its own.
    """
    src = (ROOT / "modeldrift" / "report.py").read_text()
    assert not re.search(r"^\s*REL_FLOOR\s*=", src, re.M), (
        "report.py defines its own reliability floor; it must import board.REL_FLOOR")
    assert "statuses_from_series" in src, (
        "report.py must derive statuses through board.statuses_from_series, the single "
        "implementation of the trust floor")
    assert not re.search(r"^\s*statuses\s*=\s*gather\(", src, re.M), (
        "report.py still builds the published statuses from eval-history, which has no "
        "reliability column and therefore cannot apply the floor")


def test_the_floor_has_exactly_one_definition():
    """policy.py is the authority; every other surface imports it.

    board.py held it until 2026-08-30, which forced report.py to either
    restate the value or defer its import, because board imports report. Both
    workarounds are how one source of truth quietly becomes two. board still
    re-exports the name so existing callers keep working."""
    src = (ROOT / "modeldrift" / "policy.py").read_text()
    assert re.search(r"^REL_FLOOR\s*=", src, re.M), "policy.py must define it"
    for mod in ("board.py", "report.py", "run.py"):
        text = (ROOT / "modeldrift" / mod).read_text()
        assert not re.search(r"^\s*REL_FLOOR\s*=\s*[0-9]", text, re.M), (
            f"{mod} defines its own floor; it must import policy.REL_FLOOR")


def test_all_five_surfaces_carry_the_same_floor():
    """The invariant this file exists for, now across every surface.

    Two of these are new. The published table and the metrics the dashboard
    renders from must both state the floor, because a 0.2 bundle is refused
    when any of them disagrees, and the emitted manifest must declare the
    same number so a stranger can reapply it to the committed reliability
    values instead of trusting that it was applied."""
    html = (ROOT / "dashboard" / "index.html").read_text()
    m = re.search(r"const\s+REL_FLOOR\s*=\s*([0-9.]+)\s*;", html)
    assert m, "REL_FLOOR not found in dashboard/index.html"
    assert float(m.group(1)) == REL_FLOOR, "dashboard JS disagrees"

    met = json.loads((ROOT / "dashboard" / "drift_board.json").read_text())
    assert met.get("rel_floor") == REL_FLOOR, (
        "dashboard/drift_board.json disagrees; it is copied into the bundle and "
        "cross-checked there")

    md = (ROOT / "RESULTS.md").read_text()
    assert f"**Reliability floor** is {REL_FLOOR}" in md, (
        "the published table does not state the floor it was derived under")

    vac = ROOT / "vac" / "vac.json"
    if vac.is_file():
        man = json.loads(vac.read_text())
        if man.get("vac_version") == "0.2":
            declared = [c.get("rel_floor") for c in man["results"]["checks"]
                        if c.get("profile") == "modeldrift-board-v1"]
            assert declared and all(d == REL_FLOOR for d in declared), (
                f"the emitted bundle declares {declared}, not {REL_FLOOR}")


def test_a_qualifying_latest_run_is_both_observed_and_standing():
    """When the newest run clears the floor the two facts coincide, which is
    the case that must NOT look special."""
    series = {"m": [_pt("2026-01-01T00:00:00Z", 0.80, 1.0),
                    _pt("2026-01-02T00:00:00Z", 0.90, 1.0)]}
    (row,) = standings_rows(statuses_from_series(series, REGISTRY))
    assert row["when"] == "2026-01-02" and row["acc"] == 0.90
    obs = row["latest_observed"]
    assert obs["when"] == row["when"] and obs["acc"] == row["acc"]
    assert obs["qualified"] is True


def test_a_disqualified_latest_run_is_kept_beside_the_earlier_standing():
    """The collapse stays visible while the standing falls back.

    Publishing only the qualifying standing would erase the outage, which is
    the same defect as scoring it: a reader could not tell a stable model
    from an unreachable one."""
    series = {"m": [_pt("2026-01-01T00:00:00Z", 0.80, 1.0),
                    {"t": "2026-01-02T00:00:00Z", "acc": 0.02,
                     "reliability": 0.03, "acc_spread": 0.6}]}
    (row,) = standings_rows(statuses_from_series(series, REGISTRY))
    assert row["when"] == "2026-01-01" and row["acc"] == 0.80, (
        "the standing must fall back to the last qualifying run")
    obs = row["latest_observed"]
    assert obs["when"] == "2026-01-02" and obs["acc"] == 0.02
    assert obs["reliability"] == 0.03 and obs["acc_spread"] == 0.6
    assert obs["qualified"] is False
