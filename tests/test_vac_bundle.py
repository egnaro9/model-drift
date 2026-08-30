"""The VAC bundle held to the board's own standard: every gate proven in both
directions. Freshness — the committed vac/ re-derives byte-identically from
its own evidence copies at its own stamp, twice over. Liveness — a tampered
stored row changes the re-emitted bundle, a cooked narrative or standings
table is refused outright, incoherent rows and a moved null control are
refused, a rider file cannot ship inside the closed bundle, and the stamp's
refusals fire on a throwaway repo. A refusal that was never seen red would be
exactly the vacuous guardrail this portfolio keeps writing field notes about.

These tests read the bundle's OWN byte-copies, not the live dashboard files:
the board moves daily and the bundle is a frozen snapshot of one standings
commit, so verifying it against HEAD data would rot within a day while
verifying it against itself holds forever (CI separately re-emits at the
stamped commit and diffs).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import emit_vac  # noqa: E402


@pytest.fixture(scope="module")
def bundle_inputs():
    return {name: (ROOT / "vac" / name).read_bytes() for name in emit_vac.INPUTS}


def committed_stamp() -> str:
    man = json.loads((ROOT / "vac/vac.json").read_text(encoding="utf-8"))
    return man["protocol"]["issuer_commit"]


# ── freshness: rebuild from the bundle's own bytes → byte-identical ────────

def test_bundle_is_byte_stable(bundle_inputs):
    assert emit_vac.build_bundle(bundle_inputs, "abc1234") == \
        emit_vac.build_bundle(bundle_inputs, "abc1234")


def test_committed_bundle_is_closed_and_derived(bundle_inputs):
    """vac/ holds byte-copies of exactly the four inputs, the three derived
    artifacts, and a manifest that is a pure function of those bytes and the
    stamped commit — a re-authored number, a stale copy, or a smuggled file
    all fail."""
    rebuilt = emit_vac.build_bundle(bundle_inputs, committed_stamp())
    assert sorted(p.name for p in (ROOT / "vac").iterdir()) == sorted(rebuilt)
    for name, data in rebuilt.items():
        assert (ROOT / "vac" / name).read_bytes() == data, (
            f"vac/{name}: committed bytes are not what the code re-derives — "
            "run `python3 emit_vac.py` and commit the diff")
    man = json.loads(rebuilt["vac.json"])
    assert sorted(e["path"] for e in man["evidence"]) == \
        sorted(n for n in rebuilt if n != "vac.json")
    for e in man["evidence"]:
        assert hashlib.sha256(rebuilt[e["path"]]).hexdigest() == e["sha256"]
    # limitations are load-bearing in SPEC v0.1: an empty list is an invalid bundle
    assert man["claim"]["limitations"]
    assert man["replay"]["issuer_commit"] == man["protocol"]["issuer_commit"]


def test_declared_numbers_are_recomputed_not_read(bundle_inputs):
    """Every expect number re-earns from the artifact bytes: standings row
    verdict counts, stored-row totals, flip counts, the suite floor."""
    man = json.loads((ROOT / "vac/vac.json").read_text(encoding="utf-8"))
    expect = man["results"]["checks"][0]["expect"]
    standings = json.loads((ROOT / "vac/standings.json").read_text(encoding="utf-8"))
    series = json.loads(bundle_inputs["drift_board.json"])["series"]
    fp = json.loads((ROOT / "vac/suite-fingerprint.json").read_text(encoding="utf-8"))
    nar = json.loads(bundle_inputs["narrative.json"])
    assert expect["rows"] == len(standings["rows"])
    for verdict, key in (("regressed", "regressed"), ("improved", "improved"),
                         ("unchanged", "unchanged"), ("baseline", "baseline"),
                         ("no-data", "no_data")):
        assert expect[key] == sum(1 for r in standings["rows"]
                                  if r["verdict"] == verdict)
    assert expect["series"] == len(series)
    assert expect["points"] == sum(len(p) for p in series.values())
    assert expect["tasks"] == fp["tasks"] == len(fp["task_ids"])
    assert expect["min_detectable_pts_full_grade"] == round(100.0 / fp["tasks"], 3)
    assert expect["claims_fired"] == nar["claims_fired"] == len(nar["sentences"])


# ── liveness: a tampered artifact cannot survive re-derivation ─────────────

def test_tampered_old_row_changes_the_bundle(bundle_inputs):
    """Add a failure to an OLD stored point — invisible to the narrative and
    the standings (both read only the newest points) but not to the flip
    analysis or the sha256 pins: the re-emitted bundle must differ, so the
    CI diff gate fires on the cooked file."""
    metrics = json.loads(bundle_inputs["drift_board.json"])
    victim = next(mid for mid, pts in metrics["series"].items()
                  if not mid.startswith("mock:") and len(pts) >= 3
                  and "if-json" not in (pts[0].get("fails") or []))
    metrics["series"][victim][0].setdefault("fails", []).append("if-json")
    tampered = {**bundle_inputs,
                "drift_board.json": (json.dumps(metrics, indent=1)).encode()}
    honest = emit_vac.build_bundle(bundle_inputs, "abc1234")
    cooked = emit_vac.build_bundle(tampered, "abc1234")
    assert cooked["flips.json"] != honest["flips.json"]
    h, c = (json.loads(b["vac.json"]) for b in (honest, cooked))
    assert [e["sha256"] for e in h["evidence"]] != \
        [e["sha256"] for e in c["evidence"]]


def test_cooked_narrative_is_refused(bundle_inputs):
    cooked = {**bundle_inputs,
              "narrative.json": bundle_inputs["narrative.json"] + b"\n"}
    with pytest.raises(RuntimeError, match="narrative"):
        emit_vac.build_bundle(cooked, "abc1234")


def test_cooked_standings_are_refused(bundle_inputs):
    cooked = {**bundle_inputs, "RESULTS.md": bundle_inputs["RESULTS.md"] + b"\n"}
    with pytest.raises(RuntimeError, match="RESULTS.md"):
        emit_vac.build_bundle(cooked, "abc1234")


def test_incoherent_rows_are_refused(bundle_inputs):
    metrics = json.loads(bundle_inputs["drift_board.json"])
    mid = next(m for m in metrics["series"] if not m.startswith("mock:"))
    metrics["series"][mid][-1]["acc"] = 1.5
    cooked = {**bundle_inputs, "drift_board.json": json.dumps(metrics).encode()}
    with pytest.raises(RuntimeError, match="incoherent"):
        emit_vac.build_bundle(cooked, "abc1234")


def test_a_moved_null_control_is_refused(bundle_inputs):
    metrics = json.loads(bundle_inputs["drift_board.json"])
    metrics["series"]["mock:stable"][0]["acc"] = 0.97
    cooked = {**bundle_inputs, "drift_board.json": json.dumps(metrics).encode()}
    with pytest.raises(RuntimeError, match="control moved"):
        emit_vac.build_bundle(cooked, "abc1234")


def test_bundle_refuses_a_rider(tmp_path):
    dest = tmp_path / "vac"
    dest.mkdir()
    (dest / "rider.txt").write_text("smuggled\n")
    with pytest.raises(RuntimeError, match="unexpected file"):
        emit_vac.write_bundle({"vac.json": b"{}"}, dest)


# ── the stamp's refusals, live on a throwaway repo ─────────────────────────

def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def toy_repo(tmp_path):
    repo = tmp_path / "r"
    (repo / "modeldrift").mkdir(parents=True)
    (repo / "modeldrift" / "core.py").write_text("x = 1\n")
    (repo / "dashboard").mkdir()
    (repo / "dashboard" / "drift_board.json").write_text("{}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "code+data")
    return repo


def test_stamp_refuses_a_dirty_tree(toy_repo):
    (toy_repo / "modeldrift" / "core.py").write_text("x = 2\n")
    with pytest.raises(RuntimeError, match="refusing to stamp"):
        emit_vac.stamp_code_commit(toy_repo)


def test_stamp_ignores_bundle_dirt_and_follows_inputs(toy_repo):
    stamp = emit_vac.stamp_code_commit(toy_repo)
    # the emitter's own output may be dirty (it is what is being emitted)
    (toy_repo / "vac").mkdir()
    (toy_repo / "vac" / "vac.json").write_text("{}\n")
    assert emit_vac.stamp_code_commit(toy_repo) == stamp
    # a bundle-only commit must NOT move the stamp: CI re-runs the emitter at
    # the stamped commit expecting byte-identity, stamp included
    _git(toy_repo, "add", ".")
    _git(toy_repo, "commit", "-qm", "bundle")
    assert emit_vac.stamp_code_commit(toy_repo) == stamp
    # a data commit MUST move it — the daily standings commit changes the
    # rows the claim is about, so a bundle is always a snapshot of one
    # standings commit (this is where the emitter differs from evalmut's)
    (toy_repo / "dashboard" / "drift_board.json").write_text('{"updated": "x"}\n')
    _git(toy_repo, "add", ".")
    _git(toy_repo, "commit", "-qm", "data")
    assert emit_vac.stamp_code_commit(toy_repo) != stamp
