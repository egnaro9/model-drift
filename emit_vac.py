"""Emit the drift board's derivation layer as a CLOSED VAC bundle (vac-protocol
SPEC v0.1, profile modeldrift-board-v1): `vac/` = `vac.json` plus byte-copies of
exactly the seven artifacts the manifest lists, nothing else.

The claim is deliberately narrow: every PUBLISHED number is a deterministic,
clock-free, byte-identical function of the COMMITTED per-run rows — grading and
aggregation replay over stored artifacts, never reproduction of the live model
responses (those are nondeterministic by construction and stay historical).

Unlike evalmut's emitter this one runs no battery. The inputs are the repo's own
committed artifacts — dashboard/metrics.json (the stored rows), models.json (the
registry), dashboard/narrative.json and RESULTS.md (the two published derived
views) — and everything else is DERIVED from them by issuer code before anything
is written:

  * the standings re-render: RESULTS.md rebuilt entirely from the last two
    stored points per series and byte-compared against the committed file —
    REFUSED on mismatch, because a divergence means the board's two stores
    (eval-history, which report.py reads live, and the committed rows) disagree
    and a bundle must never notarize that;
  * the narrative regen, byte-compared the same way;
  * the per-task flip / probe-alarm analysis, frozen here for the first time;
  * the per-point coherence gate over every stored row;
  * the suite fingerprint, recomputed from modeldrift/suite.py;
  * the min-detectable-regression floor — 100 / graded calls, a pure function
    of task counts that had never been published from any stored artifact.

The stamp comes from git history with the fleet's dirty-tree refusal; sha256s
come from the just-derived bytes; no clock is read anywhere, so re-emission is
byte-identical and CI can re-run the emitter at the stamped commit and demand
`diff -r` silence (regenerate-and-diff in the same job — this repo has been
burned twice by second-workflow publish paths).

`python3 emit_vac.py` — stdlib-only, offline, no model calls. Exits nonzero
only on a real refusal.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from modeldrift import board  # noqa: E402
from modeldrift.flips import analyze  # noqa: E402
from modeldrift.narrative import narrate  # noqa: E402
from modeldrift.suite import SUITE, SUITE_VERSION, suite_hash  # noqa: E402

ISSUER = "egnaro9/model-drift"

# Committed inputs the derivations read: bundle basename -> repo home. The
# bundle copies each under its basename, so basenames must stay unique.
INPUTS = {
    "metrics.json": "dashboard/metrics.json",
    "models.json": "modeldrift/models.json",
    "narrative.json": "dashboard/narrative.json",
    "RESULTS.md": "RESULTS.md",
}

# Every path whose bytes can change the emitted bundle. tests/ and prose are
# deliberately excluded: a commit that cannot move the bundle must not move the
# stamp (the fleet discipline — the bundle lands in a follow-up commit touching
# only vac/, and CI re-runs the emitter at the stamp expecting byte-identity,
# stamp included). NOTE the difference from evalmut: the daily standings commit
# touches metrics.json, which IS an input here — so data commits move the
# stamp, and a bundle is always a frozen snapshot of one standings commit.
CODE_PATHS = ("modeldrift", "pyproject.toml", "emit_vac.py",
              "dashboard/metrics.json", "dashboard/narrative.json", "RESULTS.md")

# The only paths allowed to be dirty when stamping: the emitter's own output.
OUTPUT_PATHS = ("vac/",)


def stamp_code_commit(repo: pathlib.Path = ROOT) -> str:
    """The publication stamp, with the fleet's two refusals: dirty tree,
    no code commit."""
    # -uall: porcelain collapses a fully-untracked directory to one `?? dir/`
    # line, which would defeat the exact-path allowlist below in both
    # directions (output dirt misread as code dirt, or code dirt hidden
    # inside an output directory). List every file individually.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "-uall"], cwd=repo,
        capture_output=True, text=True, check=True).stdout.splitlines()
    outside = [ln for ln in dirty if not ln[3:].startswith(OUTPUT_PATHS)]
    if outside:
        raise RuntimeError(
            "refusing to stamp a dirty tree — the stamped commit must "
            "contain the exact code and data that produced this bundle. "
            "Commit first:\n" + "\n".join(outside))
    commit = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--abbrev=7", "--", *CODE_PATHS],
        cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    if not commit:
        raise RuntimeError("git log returned no code commit; cannot stamp")
    return commit


def read_inputs(root: pathlib.Path = ROOT) -> dict[str, bytes]:
    return {name: (root / home).read_bytes() for name, home in INPUTS.items()}


def derive(inputs: dict[str, bytes]) -> tuple[dict[str, bytes], dict]:
    """({derived basename: bytes}, the declared numbers) — a pure function of
    the input bytes. Every number is recomputed from the rows, never read from
    a published aggregate, so the manifest can never declare what a verifier
    would not re-earn. Raises rather than emits when the inputs are incoherent
    or the committed derived views are not what the code re-derives."""
    metrics = json.loads(inputs["metrics.json"])
    registry = json.loads(inputs["models.json"])
    series = metrics.get("series") or {}

    fp = {"suite_version": SUITE_VERSION, "suite_hash": suite_hash(),
          "tasks": len(SUITE), "task_ids": [t.id for t in SUITE]}

    bad = board.coherence(metrics, fp["suite_version"], fp["suite_hash"],
                          fp["task_ids"])
    # The null control, enforced: a mock point below 100% or with a recorded
    # failure means the pipeline moved, not a model — nothing derived from
    # rows like that deserves a manifest.
    bad += [f"{mid}[{i}]: the deterministic control moved "
            f"(acc {p.get('acc')!r}, fails {p.get('fails')!r})"
            for mid, pts in series.items() if mid.startswith("mock:")
            for i, p in enumerate(pts)
            if p.get("acc") != 1.0 or (p.get("fails") or [])]
    if bad:
        raise RuntimeError("refusing to bundle incoherent stored rows:\n"
                           + "\n".join(bad))

    blurb = narrate(metrics, registry)
    if (json.dumps(blurb, indent=1) + "\n").encode() != inputs["narrative.json"]:
        raise RuntimeError(
            "dashboard/narrative.json is not what narrate() re-derives from "
            "the committed rows — regenerate it (python3 -m "
            "modeldrift.narrative), commit, and re-run")
    if board.results_md_offline(series, registry).encode() != inputs["RESULTS.md"]:
        raise RuntimeError(
            "RESULTS.md does not re-render from the committed rows — either it "
            "went stale, or eval-history (its live source) and "
            "dashboard/metrics.json have diverged. Diagnose before bundling; "
            "a bundle must never notarize a board whose two stores disagree")

    rows = board.standings_rows(board.statuses_from_series(series, registry))
    floor_full = round(100.0 / fp["tasks"], 3)
    standings = {"suite_version": fp["suite_version"],
                 "suite_hash": fp["suite_hash"],
                 "min_detectable_pts_full_grade": floor_full,
                 "rows": rows}
    flips = analyze(series)

    derived = {
        "standings.json": (json.dumps(standings, indent=1) + "\n").encode(),
        "flips.json": (json.dumps(flips, indent=1, sort_keys=True) + "\n").encode(),
        "suite-fingerprint.json": (json.dumps(fp, indent=1) + "\n").encode(),
    }
    verdicts = {v: sum(1 for r in rows if r["verdict"] == v)
                for v in ("regressed", "improved", "unchanged", "baseline", "no-data")}
    numbers = {
        "rows": len(rows),
        "regressed": verdicts["regressed"], "improved": verdicts["improved"],
        "unchanged": verdicts["unchanged"], "baseline": verdicts["baseline"],
        "no_data": verdicts["no-data"],
        "series": len(series),
        "points": sum(len(p) for p in series.values()),
        "tasks": fp["tasks"],
        "min_detectable_pts_full_grade": floor_full,
        "probe_alarms": len(flips["probe_alarms"]),
        "repeat_offenders": len(flips["repeat_offenders"]),
        "one_offs": len(flips["one_offs"]),
        "models_with_enough_history": flips["models_with_enough_history"],
        "claims_fired": blurb["claims_fired"],
    }
    return derived, numbers


def build_manifest(files: dict[str, bytes], numbers: dict, commit: str) -> str:
    """The vac.json text — a pure function of the artifact bytes and the
    stamped commit."""
    n = numbers
    metrics = json.loads(files["metrics.json"])
    # newest stored row's stamp — data-derived; no clock is read anywhere here
    snapshot = max((p.get("t") or "" for pts in (metrics.get("series") or {}).values()
                    for p in pts), default="")
    manifest = {
        "vac_version": "0.1",
        "claim": {
            "capability": (
                "the public drift board's derivation layer recomputes "
                "deterministically and byte-identically offline from the "
                f"repo-committed per-run rows: the standings table ({n['rows']} "
                "rows — accuracy, delta vs previous run, verdict, and the "
                "min-detectable-regression floor 100/graded-calls), the "
                f"generated narrative paragraph ({n['claims_fired']} claims "
                "fired), and the per-task flip / probe-alarm analysis "
                f"({n['repeat_offenders']} repeat offenders, {n['probe_alarms']} "
                f"probe alarms), under frozen suite {SUITE_VERSION} "
                f"({n['tasks']} tasks, mechanical graders only, no LLM judge)"),
            "scope": (
                "exactly the committed artifacts at the stamped commit: "
                f"dashboard/metrics.json ({n['series']} series, {n['points']} "
                "stored rows) joined to modeldrift/models.json under suite "
                f"{SUITE_VERSION}; grading/aggregation replay over stored "
                "artifacts only — offline, stdlib-only, no network, no model "
                "calls, no clock"),
            "limitations": [
                "the model responses are HISTORICAL: replay re-earns every "
                "derivation (standings, narrative, flips, floors) from the "
                "stored rows, never the measurements — the rows were written "
                "by the same scheduled job that made the model calls, and the "
                "live probes are nondeterministic by construction (no tracked "
                "model accepts temperature=0; a documented 9-point spread "
                "across 3 identical runs), so no part of this claim covers "
                "reproducing a model's answers",
                "the eval-history database (full per-task prompts and answers) "
                "is a mutable external store outside this bundle: "
                "corroborating, never load-bearing — no bundled number "
                "depends on it",
                "RESULTS.md's generator reads the live eval-history API; this "
                "bundle proves the committed table re-renders byte-identically "
                "from the committed rows (the emitter refuses to bundle "
                "otherwise), not that the generator ran; the two stores skip "
                "failed probes under slightly different rules, and a future "
                "divergence fails that gate by design",
                "stored rows that predate per-point emission of `graded` "
                "carry no per-run floor: their min_detectable_pts is null and "
                "the standings' Min-detectable column prints '—' for them; "
                "the suite-level floor 100/tasks = "
                f"{n['min_detectable_pts_full_grade']} pts is the finest this "
                "instrument can ever resolve, and per-run floors appear as "
                "points carry `graded`",
                "per-task failure identity in `fails` is the "
                "median-representative sample's; the other samples' "
                "identities land in `fails_runs` only from this code commit "
                "on — earlier points keep only their spread (acc_spread)",
                "rows that predate per-point suite stamping carry no "
                "`suite`/`suite_hash` field; for those rows the single-suite "
                "claim rests on the repo history of the frozen suite file, "
                "not on a per-row stamp",
                "byte-identity of the derived artifacts depends on CPython's "
                "shortest-roundtrip float formatting (see replay.expected for "
                "the versions it was verified under); the pytest suite is the "
                "semantic backstop",
            ],
        },
        "subject": {
            "kind": "suite-archetype",
            "id": "model-drift public board — the derivation layer over "
                  "dashboard/metrics.json",
            "version": {"suite_version": SUITE_VERSION,
                        "suite_hash": suite_hash(),
                        "board_commit": commit},
        },
        "protocol": {
            "issuer": ISSUER,
            "issuer_commit": commit,
            "task": "drift standings board over the frozen probe suite: "
                    "standings, narrative, and flip analysis derived from the "
                    "committed per-run rows",
            "hashes": {
                "suite_hash": suite_hash(),
                "metrics_sha256": hashlib.sha256(files["metrics.json"]).hexdigest(),
                "registry_sha256": hashlib.sha256(files["models.json"]).hexdigest(),
            },
            "grading": (
                "deterministic end to end: the stored rows were graded by the "
                "frozen suite's mechanical graders (exact / substring / regex "
                "/ numeric compare — no LLM judge), and every bundled number "
                "is a pure, clock-free function of those committed rows — "
                "standings from the last two stored points per series "
                "(verdict thresholds at ±1e-9, delta rounded to 4 places), "
                "min-detectable floor = 100/graded, flip analysis from the "
                "stored per-task failure identities, narrative from the "
                "claims generator; byte-identical on re-emission"),
            "control_policy": (
                "the mock:stable series is the live null control: a "
                "deterministic fixture probed through the identical pipeline "
                "every scheduled run, committed beside the real series, and "
                "excluded from the narrative (by registry tier) and the flip "
                "analysis (by id) — the emitter refuses to bundle any control "
                "point below 100% or carrying a failure, because a moved "
                "control indicts the harness, not the models"),
        },
        "evidence": [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items()) if name != "vac.json"
        ],
        "results": {
            "summary": {
                "standings": {k: n[k] for k in
                              ("rows", "regressed", "improved", "unchanged",
                               "baseline", "no_data")},
                "stored_rows": {"series": n["series"], "points": n["points"]},
                "suite": {"tasks": n["tasks"],
                          "min_detectable_pts_full_grade":
                              n["min_detectable_pts_full_grade"]},
                "flips": {k: n[k] for k in
                          ("probe_alarms", "repeat_offenders", "one_offs",
                           "models_with_enough_history")},
                "narrative": {"claims_fired": n["claims_fired"]},
            },
            "checks": [
                {"profile": "modeldrift-board-v1",
                 "metrics": "metrics.json",
                 "registry": "models.json",
                 "standings": "standings.json",
                 "flips": "flips.json",
                 "narrative": "narrative.json",
                 "results_md": "RESULTS.md",
                 "fingerprint": "suite-fingerprint.json",
                 "expect": n},
            ],
        },
        "replay": {
            "issuer_commit": commit,
            "commands": [
                f"git clone https://github.com/{ISSUER} issuer",
                f"git -C issuer checkout {commit}",
                "( cd issuer && python3 emit_vac.py )",
                "for f in RESULTS.md flips.json metrics.json models.json "
                "narrative.json standings.json suite-fingerprint.json "
                "vac.json; do cmp issuer/vac/$f $f || exit 1; done",
                "python3 -m venv v && v/bin/pip install -q -e 'issuer[dev]' "
                "&& v/bin/pytest -q issuer",
            ],
            "expected": (
                "every command exits 0 and every cmp stays silent: the emitter "
                "re-derives the whole bundle offline from the rows committed "
                "at the stamped commit — no network, no model calls, no clock "
                "— byte-identical to this one (commands run from the bundle "
                "directory), and the full test suite passes. Requires CPython "
                ">= 3.11; the committed narrative.json was produced under CI's "
                "3.12 and this bundle was cut and byte-verified against it "
                "under 3.14 — repo CI re-emits at the stamped commit under "
                "3.12 and diffs"),
        },
        # Seed fields for a registry MONITOR entry — additive, non-normative
        # in SPEC v0.1 (unknown keys are permitted and carry no meaning).
        "monitor": {
            "cadence": "daily — track.yml cron '17 8 * * *'",
            "snapshot": snapshot,
            "freshness_gate": (
                "a registry entry seeded from this bundle MUST fail red — "
                "never skip — when it cannot fetch dashboard/metrics.json "
                "from the issuer's main, or when the newest stored row is "
                "older than 3x the cadence; 'checked and fresh' and 'never "
                "checked' must be distinguishable outcomes (this repo has "
                "already shipped three distinct stale-publish mechanisms)"),
            "supersession": (
                "each refresh cuts a NEW closed bundle at the new standings "
                "commit and supersedes this entry — the monitored claim is a "
                "chain of frozen snapshots, never an edited one"),
        },
    }
    return json.dumps(manifest, indent=1) + "\n"


def build_bundle(inputs: dict[str, bytes], commit: str) -> dict[str, bytes]:
    """{basename: bytes} for the whole closed bundle, vac.json included — a
    pure function of the input bytes and the stamp."""
    derived, numbers = derive(inputs)
    files = {**inputs, **derived}
    files["vac.json"] = build_manifest(files, numbers, commit).encode()
    return files


def write_bundle(files: dict[str, bytes], bundle: pathlib.Path) -> None:
    bundle.mkdir(exist_ok=True)
    # the bundle is CLOSED: refuse to publish around an unexpected rider
    for stale in bundle.iterdir():
        if stale.name not in files:
            raise RuntimeError(f"unexpected file in the closed bundle: {stale}")
    for name, data in files.items():
        (bundle / name).write_bytes(data)


def emit() -> None:
    commit = stamp_code_commit()
    files = build_bundle(read_inputs(), commit)
    write_bundle(files, ROOT / "vac")
    print(f"stamped {commit}; wrote {len(files) - 1} artifacts + vac/vac.json")


if __name__ == "__main__":
    emit()
