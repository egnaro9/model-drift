"""Recompute the published board from the stored rows — pure, offline, no API.

`report.py` writes RESULTS.md from the live eval-history API, which means the
generator itself cannot be replayed by a stranger: the API is a mutable store on
someone else's disk. But every number it publishes is *also* derivable from the
repo-committed rows in `dashboard/metrics.json` — the last two stored points of
a series are exactly the "latest vs previous" comparison the API answers. This
module is that derivation: the same standings, recomputed as a pure function of
the committed file, so the published table can be re-earned offline.

Two functions matter:

  * `statuses_from_series` — mirrors `report.status_for` point-for-point over
    the stored rows. It must stay in lockstep with the live path; the byte
    compare of `results_md_offline` against the committed RESULTS.md (enforced
    by emit_vac.py and tests) is the gate that catches drift between the two.
    The stores skip failed probes under slightly different rules (eval-history
    drops only total failures; the metrics file drops latency-less runs), so a
    divergence is possible — and must fail red, never be papered over.
  * `coherence` — the per-point invariants a stored row must satisfy before any
    claim is derived from it. Returns violations, never raises: "checked and
    clean" is an empty list, distinguishable from never having checked.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .report import ModelStatus, min_detectable_change, results_md


REL_FLOOR = 0.5
"""Accuracy points from runs below this aggregate reliability are not scored.

A rate limit, timeout or provider outage makes a call *absent*, not *wrong*.
Scoring it 0 publishes the provider's bad morning as the model getting dumber.
The Reliability metric keeps these points, because reliability genuinely did
drop and that is the true signal. Keyed on aggregate reliability, never on
"a call failed": a blanket drop-on-failure would inflate accuracy on exactly
the hardest tasks. See docs/a-rate-limit-not-a-regression.md.

This constant is the single source of truth. dashboard/index.html carries the
same 0.5 for its client-side charts; tests/test_reliability_floor.py pins the
two together so they cannot drift apart again. They did drift once: the floor
lived only in the dashboard JS, so RESULTS.md published a Google outage as
three Gemini regressions (-37.1 and -94.3 pts) while the chart above it
correctly showed nothing.
"""


def trusted_points(pts: Sequence[dict]) -> List[dict]:
    """The accuracy-bearing subset of a series: reliability missing or >= floor."""
    return [p for p in pts
            if p.get("reliability") is None or p["reliability"] >= REL_FLOOR]


def statuses_from_series(series: Dict[str, List[dict]],
                         registry: Sequence[dict]) -> List[ModelStatus]:
    """One ModelStatus per registry entry, in registry order, from stored rows.

    Verdict semantics are report.status_for's, verbatim: no points → no-data,
    one point → baseline, else the delta between the last two points with the
    same ±1e-9 thresholds. `graded` comes from the newest point (null on rows
    that predate per-point emission), same as report's metrics join.

    Points below REL_FLOOR are dropped first, so an outage reads as no-data or
    a stale-but-honest number rather than a regression.
    """
    out = []
    for m in registry:
        label = m.get("label") or m["id"]
        pts = trusted_points(series.get(m["id"]) or [])
        if not pts:
            out.append(ModelStatus(m["id"], label, None, None, "no-data", None, None))
            continue
        last = pts[-1]
        g = last.get("graded")
        graded = int(g) if g else None
        when = (last.get("t") or "")[:10] or None
        if len(pts) < 2:
            out.append(ModelStatus(m["id"], label, last["acc"], None, "baseline",
                                   when, graded))
            continue
        delta = round(last["acc"] - pts[-2]["acc"], 4)
        verdict = ("regressed" if delta < -1e-9
                   else "improved" if delta > 1e-9 else "unchanged")
        out.append(ModelStatus(m["id"], label, last["acc"], delta, verdict, when, graded))
    return out


def standings_rows(statuses: Sequence[ModelStatus]) -> List[dict]:
    """The standings as data: every column of the published table plus the
    floor it is measured against. `min_detectable_pts` = round(100/graded, 3);
    `below_floor` uses the unrounded floor with results_md's exact inequality,
    so the flag here is the flag the table prints."""
    rows = []
    for s in statuses:
        floor = min_detectable_change(s.graded)
        rows.append({
            "id": s.id, "label": s.label, "when": s.when,
            "acc": s.latest, "delta": s.delta, "verdict": s.verdict,
            "graded": s.graded,
            "min_detectable_pts": round(floor, 3) if floor is not None else None,
            "below_floor": (floor is not None and s.delta is not None
                            and 1e-9 < abs(s.delta * 100) < floor),
        })
    return rows


def results_md_offline(series: Dict[str, List[dict]],
                       registry: Sequence[dict]) -> str:
    """The published RESULTS.md, re-rendered entirely from the stored rows —
    same renderer, offline statuses. Byte-identical to the committed file
    whenever the two stores agree; the emitter refuses to bundle when not."""
    return results_md(statuses_from_series(series, registry))


def _bad_num(v: Any, lo: float, hi: float) -> bool:
    return isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi


def coherence(metrics: dict, suite_version: str, suite_hash: str,
              task_ids: Sequence[str]) -> List[str]:
    """Per-point invariants of the stored rows; violations, or [] when clean.

    Everything here is checkable offline by a stranger holding only the file:
    rates in [0,1], at least one sample, non-negative spread, failure ids that
    name real suite tasks, a graded count inside the suite, timestamps that
    never run backwards within a series, and — on points that carry the stamp —
    exactly the pinned suite. A future suite bump that appended points to an
    old series would mix two different question sets under one line on the
    chart; the stamp check is what makes that loud instead of silent.
    """
    ids, n = set(task_ids), len(task_ids)
    bad: List[str] = []
    for mid, pts in (metrics.get("series") or {}).items():
        prev_t = ""
        for i, p in enumerate(pts):
            w = f"{mid}[{i}]"
            t = p.get("t") or ""
            if t < prev_t:
                bad.append(f"{w}: t {t!r} precedes {prev_t!r}")
            prev_t = t
            if _bad_num(p.get("acc"), 0, 1):
                bad.append(f"{w}: acc {p.get('acc')!r} outside [0,1]")
            if _bad_num(p.get("reliability"), 0, 1):
                bad.append(f"{w}: reliability {p.get('reliability')!r} outside [0,1]")
            if p.get("refusal_rate") is not None and _bad_num(p["refusal_rate"], 0, 1):
                bad.append(f"{w}: refusal_rate {p['refusal_rate']!r} outside [0,1]")
            if _bad_num(p.get("latency_ms"), 0, float("inf")):
                bad.append(f"{w}: latency_ms {p.get('latency_ms')!r} not a number >= 0")
            if p.get("runs", 1) < 1:
                bad.append(f"{w}: runs {p['runs']!r} < 1")
            if p.get("acc_spread", 0) < 0:
                bad.append(f"{w}: acc_spread {p['acc_spread']!r} < 0")
            unknown = sorted(set(p.get("fails") or []) - ids)
            if unknown:
                bad.append(f"{w}: fails name tasks outside the suite: {unknown}")
            g = p.get("graded")
            if g is not None and (isinstance(g, bool) or not isinstance(g, int)
                                  or not 1 <= g <= n):
                bad.append(f"{w}: graded {g!r} outside 1..{n}")
            if p.get("suite") not in (None, suite_version):
                bad.append(f"{w}: suite {p['suite']!r} is not {suite_version!r}")
            if p.get("suite_hash") not in (None, suite_hash):
                bad.append(f"{w}: suite_hash {p['suite_hash']!r} is not {suite_hash!r}")
            fr = p.get("fails_runs")
            if fr is not None:
                for j, sample in enumerate(fr):
                    unknown = sorted(set(sample) - ids)
                    if unknown:
                        bad.append(f"{w}: fails_runs[{j}] names tasks outside "
                                   f"the suite: {unknown}")
                if (p.get("fails") or []) not in fr:
                    bad.append(f"{w}: fails is not one of its own fails_runs samples")
    return bad
