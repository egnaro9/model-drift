"""draft.yml's confirm gate, exercised with a stubbed probe.

WHY THIS FILE EXISTS. The gate decides whether a finding becomes a pull request, and
it decides by calling a live model. That makes it the one piece of this pipeline that
cannot be tested by running it for real in CI, and therefore the piece most likely to
rot unnoticed. It is extracted from the workflow YAML rather than copied, so an edit to
the workflow is an edit to what these tests run.

The property that matters is FAIL CLOSED: a probe that errors, lacks a key, or returns
too few usable runs must stop the draft. A confirm that could not run has not confirmed,
and the opposite reading is the defect this repository exists to catch.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import types

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _gate_source() -> str:
    d = yaml.safe_load((ROOT / ".github/workflows/draft.yml").read_text())
    step = next(s for s in d["jobs"]["draft"]["steps"]
                if s.get("name", "").startswith("Confirm the finding"))
    inner = step["run"].split("<<'PY'", 1)[1].rsplit("PY", 1)[0]
    return "\n".join(l[10:] if l.startswith(" " * 10) else l for l in inner.split("\n"))


def _run(tmp_path, items, probe, available=True):
    out, summ = tmp_path / "out.txt", tmp_path / "sum.md"
    out.write_text(""); summ.write_text("")
    os.environ.update(CONFIRMABLE=json.dumps(items), GITHUB_OUTPUT=str(out),
                      GITHUB_STEP_SUMMARY=str(summ))

    class M:
        def __init__(self, i): self.id, self.available = i, available

    prov = types.ModuleType("modeldrift.providers")
    prov.load_registry = lambda *a, **k: [M(i["model"]) for i in items] or [M("x")]
    runm = types.ModuleType("modeldrift.run")
    runm.probe_repeated = probe
    saved = {k: sys.modules.get(k) for k in ("modeldrift.providers", "modeldrift.run")}
    sys.modules["modeldrift.providers"], sys.modules["modeldrift.run"] = prov, runm
    try:
        try:
            exec(compile(_gate_source(), "gate", "exec"), {"__name__": "__main__"})
        except SystemExit:
            pass
    finally:
        for k, v in saved.items():
            if v is None: sys.modules.pop(k, None)
            else: sys.modules[k] = v
    return dict(l.split("=", 1) for l in out.read_text().split("\n") if "=" in l)


ITEM = [{"model": "xai:grok-4-fast", "move_pts": 8.57}]

def _probe(runs=3, spread=0.02):
    return lambda m, n: {"_runs": runs, "_acc_spread": spread}


def test_move_larger_than_the_fresh_spread_survives(tmp_path):
    assert _run(tmp_path, ITEM, _probe(spread=0.02))["survived"] == "true"


def test_move_inside_the_fresh_spread_is_dropped(tmp_path):
    """The grok-4-fast case: 8.57 against a measured 12.00 is one bounce."""
    assert _run(tmp_path, ITEM, _probe(spread=0.12))["survived"] == "false"


def test_a_probe_that_raises_stops_the_draft(tmp_path):
    def boom(m, n): raise RuntimeError("provider 500")
    assert _run(tmp_path, ITEM, boom)["survived"] == "false"


def test_too_few_usable_runs_stops_the_draft(tmp_path):
    """One run cannot produce a spread, so it cannot confirm anything."""
    assert _run(tmp_path, ITEM, _probe(runs=1, spread=0.0))["survived"] == "false"


def test_a_missing_spread_stops_the_draft(tmp_path):
    assert _run(tmp_path, ITEM, _probe(spread=None))["survived"] == "false"


def test_a_model_without_a_key_stops_the_draft(tmp_path):
    assert _run(tmp_path, ITEM, _probe(), available=False)["survived"] == "false"


def test_nothing_confirmable_proceeds_but_is_marked(tmp_path):
    """A task flip cannot be settled by re-measuring accuracy. It goes forward, and
    the PR body has to say it was never tested."""
    got = _run(tmp_path, [], _probe())
    assert got["survived"] == "true"
    assert got["confirmed"] == "none"


def test_a_move_equal_to_the_spread_is_dropped(tmp_path):
    """EXCEED the spread, not merely reach it. This repository already fixed exactly
    this boundary once, in clears_floor: "a move equal to the smallest move the run can
    print is not a finding". The first version of this gate used `move > spread` and
    nothing tested it, so flipping it to `>=` passed the whole suite."""
    item = [{"model": "xai:grok-4-fast", "move_pts": 5.0}]
    assert _run(tmp_path, item, _probe(spread=0.05))["survived"] == "false"


def test_the_pr_step_is_actually_gated_on_the_confirm_result():
    """THE wiring fact, and the first version of this file did not check it. Deleting
    the gate from the PR step's `if` passed every test here: the gate computed a verdict
    that nothing consulted, which is the same shape as a check whose result is ignored.
    """
    d = yaml.safe_load((ROOT / ".github/workflows/draft.yml").read_text())
    pr = next(s for s in d["jobs"]["draft"]["steps"]
              if s.get("name", "").startswith("Open a pull request"))
    assert "steps.confirm.outputs.survived == 'true'" in pr["if"], (
        f"the PR step's condition is {pr['if']!r} and does not consult the confirm "
        "gate, so a finding that failed its probe would still open a pull request")


def test_the_pr_body_distinguishes_confirmed_from_unconfirmed():
    """The gate may pass something untested, so the artifact a human reads must say
    which it is. Asserting a word appears somewhere in the file is nearly unfalsifiable,
    so this checks the BRANCH: both arms must exist and both must be reachable from the
    confirmed output."""
    d = yaml.safe_load((ROOT / ".github/workflows/draft.yml").read_text())
    pr = next(s for s in d["jobs"]["draft"]["steps"]
              if s.get("name", "").startswith("Open a pull request"))
    run = pr["run"]
    assert 'steps.confirm.outputs.confirmed }}" = "none"' in run, "no branch on the result"
    head, _, tail = run.partition('= "none" ]; then')
    then_arm, _, else_arm = tail.partition("else")
    assert "UNCONFIRMED" in then_arm, "the untested arm does not say it was untested"
    assert "CONFIRMED" in else_arm and "re-probed" in else_arm, (
        "the confirmed arm does not say what was done")
