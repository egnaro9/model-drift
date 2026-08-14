"""After a probe, read the stored history and report — but only *raise the alarm*
when something actually moved.

The discipline here is the same one the tracker is about: signal, not noise. Every
run updates `RESULTS.md` (the standings, committed to the repo). But an alert — a
GitHub issue, a ready-to-post writeup — is produced *only when a model regressed
against its previous run*. A daily "nothing changed" post is spam; the post worth
making is "Claude dropped 8 points", and this writes exactly that, only then.

Note the resolution limit this implies. Accuracy is graded_pass/graded_total and a
truncated call leaves the *denominator* rather than counting as wrong, so the smallest
measurable movement is 100/graded_total — about 2.9 points when all 35 tasks grade, and
coarser when they do not. It is not a constant, which is the trap: the board once showed
a model at -1.0 pts, and one point is not even a whole question. That delta was the
denominator moving, not the model. `min_detectable_change` computes the floor per run and
`results_md` prints it beside the delta, flagging any movement that falls beneath it.

Reads eval-history (no key needed). The per-model verdict is eval-history's own
`latest-comparison` — this doesn't recompute regressions, it asks the store that
already knows.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

from .providers import load_registry
from .suite import SUITE_VERSION


@dataclass
class ModelStatus:
    id: str
    label: str
    latest: Optional[float]      # latest accuracy, or None if no runs
    delta: Optional[float]       # vs previous run
    verdict: str                 # regressed | improved | unchanged | baseline | no-data
    when: Optional[str]
    graded: Optional[int] = None  # calls actually graded in the latest run; sets the floor


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            return json.loads(r.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return None


def min_detectable_change(graded: Optional[int]) -> Optional[float]:
    """Smallest movement this run could possibly show, in points.

    Accuracy is graded_pass/graded_total, and a truncated call leaves the denominator
    rather than counting as wrong (see run.probe). So the floor is 100/graded_total, and
    it is *not* a constant: a run that grades 33 of 35 has a coarser floor than one that
    grades all 35. Any delta smaller than this is the denominator moving, not the model.

    Returns None when the run predates graded_total being emitted.
    """
    if not graded:
        return None
    return 100.0 / graded


def status_for(api: str, model) -> ModelStatus:
    from urllib.parse import quote
    runs = _get(f"{api.rstrip('/')}/runs?name={quote(model.id)}&limit=2") or []
    if not runs:
        return ModelStatus(model.id, model.label, None, None, "no-data", None, None)
    latest = runs[0]
    acc = latest["faithfulness"]
    when = (latest.get("created_at") or "")[:10]
    graded = latest.get("graded_total")
    graded = int(graded) if graded else None
    if len(runs) < 2:
        return ModelStatus(model.id, model.label, acc, None, "baseline", when, graded)
    delta = round(acc - runs[1]["faithfulness"], 4)
    verdict = "regressed" if delta < -1e-9 else "improved" if delta > 1e-9 else "unchanged"
    return ModelStatus(model.id, model.label, acc, delta, verdict, when, graded)


def gather(api: str, registry: Optional[str] = None) -> List[ModelStatus]:
    return [status_for(api, m) for m in load_registry(registry)]


def fill_graded_from_metrics(statuses: List[ModelStatus], metrics: dict) -> None:
    """Join the accuracy denominator from the committed rows.

    run.py posts graded_total to eval-history, but eval-history's schema has no
    such column — it is dropped on write, `status_for` always got None back, and
    every published Min-detectable cell printed "—": the floor was structurally
    unpublishable from any stored artifact. The committed metrics file is its
    real home now (each point carries `graded`), so take the denominator from
    the model's newest stored point — written by the same probe run this report
    reads — and the column fills in as points carry it. Points that predate the
    field leave the status untouched, and the cell keeps printing "—"; visible
    absence, never a guessed constant.
    """
    series = (metrics or {}).get("series") or {}
    for s in statuses:
        pts = series.get(s.id)
        g = pts[-1].get("graded") if pts else None
        if s.graded is None and g:
            s.graded = int(g)


def results_md(statuses: List[ModelStatus]) -> str:
    icon = {"regressed": "🔴", "improved": "🟢", "unchanged": "⚪", "baseline": "🔵", "no-data": "⚫"}
    rows = []
    for s in statuses:
        if s.latest is None:
            rows.append(f"| {s.label} | — | — | — | ⚫ no runs yet |")
            continue
        d = "—" if s.delta is None else f"{s.delta*100:+.1f} pts"
        floor = min_detectable_change(s.graded)
        # Print the floor beside the delta so a movement smaller than one question cannot
        # be read as a result. Flag it explicitly when the delta is under the floor — that
        # is the denominator moving, not the model.
        if floor is None:
            f_txt = "—"
        elif s.delta is not None and 1e-9 < abs(s.delta * 100) < floor:
            f_txt = f"±{floor:.1f} ⚠ below floor"
        else:
            f_txt = f"±{floor:.1f}"
        rows.append(
            f"| {s.label} | {s.latest*100:.1f}% | {d} | {f_txt} | {icon[s.verdict]} {s.verdict} |"
        )
    return (
        f"# Latest standings — suite `{SUITE_VERSION}`\n\n"
        "_Auto-generated after each scheduled probe. Live chart: "
        "[egnaro9.github.io/model-drift](https://egnaro9.github.io/model-drift/)._\n\n"
        "**Min detectable** is the smallest movement a run could show: `100 / graded calls`. "
        "Accuracy is scored over graded calls only — a truncated call leaves the denominator "
        "rather than counting as wrong — so the floor is not a constant, and a delta beneath "
        "it is the denominator moving, not the model.\n\n"
        "| Model | Accuracy | Δ vs previous | Min detectable | Status |\n"
        "| --- | --- | --- | --- | --- |\n"
        + "\n".join(rows) + "\n"
    )


def regressions(statuses: List[ModelStatus]) -> List[ModelStatus]:
    return [s for s in statuses if s.verdict == "regressed"]


def alert_issue(regs: List[ModelStatus]) -> tuple[str, str]:
    """(title, body) for a GitHub issue — the automatic 'go look' trigger."""
    worst = min(regs, key=lambda s: s.delta)
    title = f"Drift: {len(regs)} model(s) regressed — {worst.label} {worst.delta*100:+.1f} pts"
    body = ["A scheduled probe found a regression against the previous run:\n"]
    for s in regs:
        body.append(f"- **{s.label}**: {s.delta*100:+.1f} pts → now {s.latest*100:.1f}%")
    body.append("\nChart: https://egnaro9.github.io/model-drift/ · A draft writeup is attached to the "
                "workflow run. Post it if it's worth saying.")
    return title, "\n".join(body)


def social_draft(regs: List[ModelStatus], all_statuses: List[ModelStatus]) -> str:
    """A ready-to-post writeup — you publish it, on news, by hand."""
    worst = min(regs, key=lambda s: s.delta)
    tracked = [s for s in all_statuses if s.latest is not None]
    lines = [
        f"Caught an LLM regression this week with my public drift tracker.\n",
        f"**{worst.label}** dropped **{worst.delta*100:+.1f} points** on a frozen, "
        "deterministically-graded suite — same questions, same grader, temperature 0, so it's the "
        "model that moved, not the test.\n",
    ]
    if len(regs) > 1:
        lines.append("Also down: " + ", ".join(f"{s.label} ({s.delta*100:+.1f})" for s in regs if s is not worst) + ".\n")
    lines += [
        "Providers ship silent updates; a prompt that worked can quietly get worse with no error. "
        "So I run a fixed suite against the live models weekly and keep every score.\n",
        "Live chart + how it works: https://egnaro9.github.io/model-drift/",
        "Code (suite, graders, runner): https://github.com/egnaro9/model-drift",
        "",
        "#LLM #AIEngineering #Evals",
    ]
    return "\n".join(lines)


def append_stub_note(path: str, regs: List[ModelStatus], today: str) -> bool:
    """Log a stub Field Note when a regression fires, so the moment is captured
    automatically — a human writes the prose later. Automate the capture, not the
    story. Returns True if a new note was written (False if today's already logged)."""
    from pathlib import Path
    worst = min(regs, key=lambda s: s.delta if s.delta is not None else 0.0)
    stub = {
        "date": today,
        "title": f"Regression: {worst.label} {worst.delta * 100:+.1f} pts",
        "metric": "accuracy",
        "models": [s.id for s in regs],
        "summary": (f"{len(regs)} model(s) regressed against the previous run; worst was "
                    f"{worst.label} at {worst.delta * 100:+.1f} pts. Auto-logged — "
                    "confirm it's real before writing it up."),
        "body": [{"p": "Auto-logged when the scheduled probe flagged a run-over-run "
                       "regression. Before this becomes a post, check the run log and the "
                       "Reliability metric — a rate limit or provider outage can look exactly "
                       "like a regression. If it holds up, the written explanation goes here."}],
        "stub": True,
    }
    p = Path(path)
    try:
        notes = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(notes, list):
            notes = []
    except (FileNotFoundError, json.JSONDecodeError):
        notes = []
    if notes and notes[0].get("stub") and notes[0].get("date") == today:
        return False   # newest-first; don't double-log the same day
    notes.insert(0, stub)
    p.write_text(json.dumps(notes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import os
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api", default="https://eval-history.onrender.com")
    p.add_argument("--results", default="RESULTS.md")
    p.add_argument("--metrics", default="dashboard/metrics.json",
                   help="committed time-series file; supplies the graded-call "
                        "denominator the Min-detectable column needs")
    p.add_argument("--alert", default=None, help="write issue title+body here if any regression")
    p.add_argument("--draft", default=None, help="write a social draft here if any regression")
    p.add_argument("--notes", default=None, help="append a stub Field Note here on a regression")
    args = p.parse_args(argv)

    statuses = gather(args.api)
    try:
        from pathlib import Path
        fill_graded_from_metrics(
            statuses, json.loads(Path(args.metrics).read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        pass   # no stored rows to join — the column prints "—", same as before
    with open(args.results, "w", encoding="utf-8") as fh:
        fh.write(results_md(statuses))
    print(f"wrote {args.results}")

    regs = regressions(statuses)
    # Signal the workflow (only alert/draft on real news).
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as fh:
            fh.write(f"regressed={'true' if regs else 'false'}\n")

    if regs:
        print(f"⚠ {len(regs)} regression(s) — writing alert + draft")
        if args.alert:
            title, body = alert_issue(regs)
            with open(args.alert, "w", encoding="utf-8") as fh:
                fh.write(title + "\n\n" + body)
        if args.draft:
            with open(args.draft, "w", encoding="utf-8") as fh:
                fh.write(social_draft(regs, statuses))
        if args.notes:
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).date().isoformat()
            if append_stub_note(args.notes, regs, today):
                print(f"logged a stub Field Note to {args.notes}")
    else:
        print("no regressions — standings updated, no alert (news, not schedule)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
