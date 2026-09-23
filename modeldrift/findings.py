"""What, if anything, is worth writing up this week.

This is the gate between "a run finished" and "there is something to say". It
exists because the failure mode of an automated blog is publishing on a
schedule rather than on a finding, and the failure mode of *that* is publishing
the instrument's own noise as news. Both have already happened on this board:

  * a Google outage was published as three Gemini regressions (-37.1, -94.3)
    before REL_FLOOR existed, and
  * one regression was auto-logged 19 times, because the calendar was treated
    as the identity of the event instead of the runs being compared.

So every finding here carries three things a schedule-driven generator does not
have: the evidence it was derived from, an `about` field naming whether the
subject is a model, the harness, or infrastructure, and a `run_key` identity so
the same event cannot be reported twice.

Nothing in this module decides to publish. It decides whether a human should be
asked to look.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .flips import analyze as analyze_flips
from .policy import REL_FLOOR
from .report import ModelStatus, min_detectable_change

# What a finding can be *about*. This is the field that stops a provider outage
# being written up as a model getting worse, which is the single most expensive
# mistake this board can make: it is wrong, it is public, and it is the exact
# claim the project exists to debunk.
ABOUT_MODELS = "models"
ABOUT_HARNESS = "harness"
ABOUT_INFRA = "infrastructure"


@dataclass
class Finding:
    kind: str
    about: str
    subject: str
    headline: str
    run_key: List[str]
    evidence: List[Dict[str, str]] = field(default_factory=list)
    # Date of the run this describes, for findings that have one. Harness
    # findings span many days and leave it None.
    when: Optional[str] = None

    def fingerprint(self) -> str:
        """Identity of the *event*, not of the day it was noticed.

        A model whose newer runs all fail the reliability floor keeps the same
        floored standing, so the same comparison re-derives every single day.
        Keying on the runs compared is what stopped the 19 duplicate logs.
        """
        return f"{self.kind}:{self.subject}:" + ",".join(sorted(self.run_key))

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "about": self.about, "subject": self.subject,
                "headline": self.headline, "run_key": sorted(self.run_key),
                "evidence": self.evidence, "fingerprint": self.fingerprint()}


def _pts(delta: Optional[float]) -> str:
    return "—" if delta is None else f"{delta * 100:+.1f} pts"


def regressions_and_recoveries(statuses: Sequence[ModelStatus]) -> List[Finding]:
    """Run-over-run moves that clear the instrument's own resolution.

    A delta smaller than 100/graded_total is the denominator moving, not the
    model, so it is not reported at all. When graded_total is unknown (rows
    predating per-point emission) the move is reported but the evidence says
    the floor could not be computed, because silently treating unknown as
    zero is how an unmeasurable claim gets published as a measured one.
    """
    out: List[Finding] = []
    for s in statuses:
        if s.verdict not in ("regressed", "improved") or s.delta is None:
            continue
        floor = min_detectable_change(s.graded)
        move_pts = abs(s.delta) * 100
        if floor is not None and move_pts < floor:
            continue
        kind = "regression" if s.verdict == "regressed" else "recovery"
        out.append(Finding(
            kind=kind,
            about=ABOUT_MODELS,
            subject=s.id,
            headline=f"{s.label} {_pts(s.delta)} to {s.latest * 100:.1f}%",
            run_key=[f"{s.id}@{s.when}"],
            when=s.when,
            evidence=[
                {"claim": f"{s.label} moved {_pts(s.delta)} run over run",
                 "how": f"latest {s.latest * 100:.1f}% vs previous, dated {s.when}"},
                {"claim": "the move is larger than this run could print by accident",
                 "how": (f"graded {s.graded} calls, so the floor is "
                         f"{floor:.2f} pts and the move was {move_pts:.1f}")
                        if floor is not None else
                        "graded_total not recorded on this row, so the floor is UNKNOWN"},
                {"claim": "the run was not an outage being scored as a score",
                 "how": (f"reliability {s.observed_reliability}, at or above the "
                         f"{REL_FLOOR} floor" if s.observed_qualified
                         else "reliability BELOW floor, standing is the last "
                              "qualifying run")},
            ],
        ))
    return out


def dark_providers(statuses: Sequence[ModelStatus]) -> List[Finding]:
    """Credentials or billing, never capability.

    Filed under infrastructure on purpose. On 2026-09-22 three Gemini models
    returned 402 on 35 of 35 calls and the board printed `acc 0%` beside
    `instruction-following 100%`; a generator that read that as a model story
    would have published the billing status of a credit card.
    """
    out: List[Finding] = []
    for s in statuses:
        if s.observed_qualified is not False:
            continue
        out.append(Finding(
            kind="provider-dark",
            about=ABOUT_INFRA,
            subject=s.id,
            headline=f"{s.label} did not return a scoreable run",
            run_key=[f"{s.id}@{s.observed_when}"],
            when=s.observed_when,
            evidence=[
                {"claim": "the latest observation did not clear the reliability floor",
                 "how": f"reliability {s.observed_reliability} < {REL_FLOOR}, "
                        f"observed {s.observed_when}"},
                {"claim": "this is not an accuracy result",
                 "how": "absent calls are absent, not wrong; the standing shown "
                        f"is the last qualifying run ({s.when})"},
            ],
        ))
    return out


def harness_alarms(series: Dict[str, List[dict]]) -> List[Finding]:
    """A task failing across several providers at once accuses the probe.

    Models from different labs do not regress in unison. flips.analyze already
    classifies this; what is added here is COLLAPSING BY TASK. The raw analysis
    returns one alarm per task per day, and `constraint-no-e` has tripped on 3
    or more providers on seventeen separate days. That is one finding about one
    task, stated once with its full recurrence as evidence, not seventeen posts.

    Recurrence makes the accusation stronger, so it belongs in the evidence
    rather than in the count of findings.
    """
    report = analyze_flips(series)
    out: List[Finding] = []

    by_task: Dict[str, List[dict]] = {}
    for a in report["probe_alarms"]:
        by_task.setdefault(a["task"], []).append(a)
    for task, alarms in sorted(by_task.items()):
        days = sorted(a["day"] for a in alarms)
        provs = sorted({p for a in alarms for p in a["providers"]})
        worst = max(a["n_providers"] for a in alarms)
        out.append(Finding(
            kind="probe-alarm",
            about=ABOUT_HARNESS,
            subject=task,
            headline=(f"Task {task} fails across providers at once, on "
                      f"{len(days)} separate day" + ("" if len(days) == 1 else "s")),
            # Identity is the TASK, not the day. A task that keeps tripping is
            # the same open finding; re-reporting it every week is the
            # 19-duplicate-logs bug wearing a different hat.
            run_key=[task],
            evidence=[
                {"claim": f"{task} failed on up to {worst} providers on the same day",
                 "how": f"observed on {len(days)} day(s), {days[0]} to {days[-1]}"},
                {"claim": "the failures span independent labs",
                 "how": f"providers seen failing it: {', '.join(provs)}"},
                {"claim": "independent labs do not regress in unison",
                 "how": "so the suspect is the prompt, the grader or the "
                        "environment, not the models"},
            ],
        ))

    by_pair: Dict[str, dict] = {}
    for r in report["repeat_offenders"]:
        by_pair[f"{r['model']}/{r['task']}"] = r
    for pair, r in sorted(by_pair.items()):
        out.append(Finding(
            kind="repeat-flip",
            about=ABOUT_MODELS,
            subject=pair,
            headline=f"{r['task']} flipped {r['flips']}x on {r['model']}",
            run_key=[pair],
            evidence=[
                {"claim": f"{r['task']} changed pass/fail state {r['flips']} times",
                 "how": f"across stored runs of {r['model']}; latest state {r['latest']}"},
                {"claim": "repeated flips are not the instrument's resolution",
                 "how": "a single flip is 100/35 = 2.86 pts and would be noise; "
                        "this one recurred"},
            ],
        ))
    return out


def detect(series: Dict[str, List[dict]], statuses: Sequence[ModelStatus]) -> List[Finding]:
    """Everything worth a human's attention, most consequential first."""
    found = (harness_alarms(series) + regressions_and_recoveries(statuses)
             + dark_providers(statuses))
    order = {"probe-alarm": 0, "regression": 1, "repeat-flip": 2,
             "recovery": 3, "provider-dark": 4}
    return sorted(found, key=lambda f: (order.get(f.kind, 9), f.subject))


def current(findings: Sequence[Finding], as_of: str,
            window_days: int = 14) -> List[Finding]:
    """Drop findings whose run is too old to be this week's news.

    The floored standing compares the last two runs that CLEARED the
    reliability floor. When a provider then goes dark for a month, those two
    runs stay the newest qualifying pair and the same delta re-derives forever:
    Gemini 3.1 Pro at -17.2 pts is a real comparison between two real runs in
    August, and reporting it in late September would publish a month-old
    measurement as current news. Findings with no date (harness findings, which
    span many days by construction) always pass.
    """
    from datetime import date

    def _d(text: str):
        try:
            return date.fromisoformat(text[:10])
        except (TypeError, ValueError):
            return None

    edge = _d(as_of)
    if edge is None:
        return list(findings)
    out = []
    for f in findings:
        when = _d(f.when) if f.when else None
        if when is None or (edge - when).days <= window_days:
            out.append(f)
    return out


def unseen(findings: Sequence[Finding], ledger_path: str) -> List[Finding]:
    """Findings whose event has not already been drafted.

    The ledger stores fingerprints, not dates. A frozen standing re-derives the
    same fingerprint every run and is therefore silently dropped, which is the
    behaviour that the 19-times-logged regression needed and did not have.
    """
    try:
        with open(ledger_path, encoding="utf-8") as fh:
            seen = set(json.load(fh))
    except (FileNotFoundError, json.JSONDecodeError):
        seen = set()
    return [f for f in findings if f.fingerprint() not in seen]


def record(findings: Sequence[Finding], ledger_path: str) -> None:
    try:
        with open(ledger_path, encoding="utf-8") as fh:
            seen = set(json.load(fh))
    except (FileNotFoundError, json.JSONDecodeError):
        seen = set()
    seen.update(f.fingerprint() for f in findings)
    with open(ledger_path, "w", encoding="utf-8") as fh:
        json.dump(sorted(seen), fh, indent=1)
        fh.write("\n")


def main(argv: Optional[List[str]] = None) -> int:
    """Write a draft per unseen finding. Exit 0 always: no finding is not a
    failure, it is the common and correct outcome of a quiet week."""
    import argparse
    import os
    from pathlib import Path

    from .board import statuses_from_series
    from .draft import render, slugify
    from .narrative import run_date as _run_date, build_rows
    from .suite import SUITE_VERSION

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", default="dashboard/drift_board.json")
    ap.add_argument("--registry", default="modeldrift/models.json")
    ap.add_argument("--out", default="drafts")
    ap.add_argument("--ledger", default="drafts/.drafted.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--window-days", type=int, default=14,
                    help="how recent a model finding's run must be to count as news")
    # One. Two posts in a day is the lowest-yield move in the measured record:
    # the 2026-08-14 double launch got under 25 views each and zero comments,
    # while the same topic alone five days earlier got 48 views and 5 comments.
    ap.add_argument("--max", type=int, default=1,
                    help="most drafts to write in one run; the rest are named, never dropped silently")
    ap.add_argument("--seed-ledger", action="store_true",
                    help="record every current finding as already-seen without writing "
                         "drafts, to establish a baseline against historical backlog")
    a = ap.parse_args(argv)

    board = json.loads(Path(a.board).read_text(encoding="utf-8"))
    registry = json.loads(Path(a.registry).read_text(encoding="utf-8"))
    series = board.get("series") or {}
    statuses = statuses_from_series(series, registry)
    stamp = _run_date(build_rows(board, registry)) or ""
    day = (stamp or "")[:10] or "undated"

    all_found = detect(series, statuses)
    found = current(all_found, day, a.window_days)
    stale = len(all_found) - len(found)
    fresh = unseen(found, a.ledger)
    print(f"{len(all_found)} finding(s); {stale} older than {a.window_days} days "
          f"and not this week's news; {len(fresh)} of the rest not yet drafted")
    for f in found:
        mark = " " if f in fresh else "·"
        print(f"  {mark} [{f.about:14}] {f.kind:14} {f.headline}")

    if a.seed_ledger:
        # Seeding silences the historical backlog so weekly runs report only new
        # events. The backlog itself is real material and several of these are
        # the strongest findings on the board, so it gets written down rather
        # than swallowed: marking something as seen is not the same as deciding
        # it was not worth saying.
        Path(a.out).mkdir(parents=True, exist_ok=True)
        blog = Path(a.out) / "BACKLOG.md"
        lines = ["# Findings backlog at ledger seed",
                 "",
                 f"Seeded {day}. These existed before the pipeline started and are",
                 "marked as seen so weekly runs report only new events. They are NOT",
                 "dismissed; several are the strongest findings on the board. Write any",
                 "of them up by hand and delete the line.",
                 ""]
        for f in all_found:
            lines.append(f"- [ ] `{f.about}` **{f.kind}** — {f.headline}")
        blog.write_text("\n".join(lines) + "\n", encoding="utf-8")
        record(all_found, a.ledger)
        print(f"\nSeeded the ledger with {len(all_found)} existing finding(s) and "
              f"wrote them to {blog}. None were drafted; they are the backlog, "
              f"not this week's news.")
        return 0

    if not fresh:
        print("\nNothing new to write up. A quiet week is a result, not a gap.")
        return 0

    # A cap keeps one run from opening an unreviewable PR, but a silent cap
    # would read as "that was everything". Name what is being held back.
    held_back = fresh[a.max:]
    fresh = fresh[:a.max]
    if held_back:
        print(f"\n  holding back {len(held_back)} further finding(s) this run:")
        for f in held_back:
            print(f"    - [{f.about}] {f.headline}")
        print("  they stay unrecorded, so the next run will offer them again.")

    Path(a.out).mkdir(parents=True, exist_ok=True)
    written = []
    for f in fresh:
        path = Path(a.out) / f"{day}-{slugify(f.headline)}.md"
        body = render(f, statuses, day, SUITE_VERSION, registry)
        if not a.dry_run:
            path.write_text(body, encoding="utf-8")
        written.append(str(path))
        print(f"  wrote {path}")

    if not a.dry_run:
        record(fresh, a.ledger)
    # Hand the paths to the workflow so it can open one PR per run.
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"drafts={' '.join(written)}\n")
            fh.write(f"count={len(written)}\n")
            fh.write(f"headline={fresh[0].headline}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
