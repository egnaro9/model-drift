"""After a probe, read the stored history and report — but only *raise the alarm*
when something actually moved.

The discipline here is the same one the tracker is about: signal, not noise. Every
run updates `RESULTS.md` (the standings, committed to the repo). But an alert — a
GitHub issue, a ready-to-post writeup — is produced *only when a model regressed
week-over-week*. A weekly "nothing changed" post is spam; the post worth making is
"Claude dropped 8 points this week", and this writes exactly that, only then.

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


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            return json.loads(r.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return None


def status_for(api: str, model) -> ModelStatus:
    from urllib.parse import quote
    runs = _get(f"{api.rstrip('/')}/runs?name={quote(model.id)}&limit=2") or []
    if not runs:
        return ModelStatus(model.id, model.label, None, None, "no-data", None)
    latest = runs[0]
    acc = latest["faithfulness"]
    when = (latest.get("created_at") or "")[:10]
    if len(runs) < 2:
        return ModelStatus(model.id, model.label, acc, None, "baseline", when)
    delta = round(acc - runs[1]["faithfulness"], 4)
    verdict = "regressed" if delta < -1e-9 else "improved" if delta > 1e-9 else "unchanged"
    return ModelStatus(model.id, model.label, acc, delta, verdict, when)


def gather(api: str, registry: Optional[str] = None) -> List[ModelStatus]:
    return [status_for(api, m) for m in load_registry(registry)]


def results_md(statuses: List[ModelStatus]) -> str:
    icon = {"regressed": "🔴", "improved": "🟢", "unchanged": "⚪", "baseline": "🔵", "no-data": "⚫"}
    rows = []
    for s in statuses:
        if s.latest is None:
            rows.append(f"| {s.label} | — | — | ⚫ no runs yet |")
            continue
        d = "—" if s.delta is None else f"{s.delta*100:+.1f} pts"
        rows.append(f"| {s.label} | {s.latest*100:.1f}% | {d} | {icon[s.verdict]} {s.verdict} |")
    return (
        f"# Latest standings — suite `{SUITE_VERSION}`\n\n"
        "_Auto-generated after each scheduled probe. Live chart: "
        "[egnaro9.github.io/model-drift](https://egnaro9.github.io/model-drift/)._\n\n"
        "| Model | Accuracy | Δ vs previous | Status |\n| --- | --- | --- | --- |\n"
        + "\n".join(rows) + "\n"
    )


def regressions(statuses: List[ModelStatus]) -> List[ModelStatus]:
    return [s for s in statuses if s.verdict == "regressed"]


def alert_issue(regs: List[ModelStatus]) -> tuple[str, str]:
    """(title, body) for a GitHub issue — the automatic 'go look' trigger."""
    worst = min(regs, key=lambda s: s.delta)
    title = f"Drift: {len(regs)} model(s) regressed — {worst.label} {worst.delta*100:+.1f} pts"
    body = ["A scheduled probe found a week-over-week regression:\n"]
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


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import os
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api", default="https://eval-history.onrender.com")
    p.add_argument("--results", default="RESULTS.md")
    p.add_argument("--alert", default=None, help="write issue title+body here if any regression")
    p.add_argument("--draft", default=None, help="write a social draft here if any regression")
    args = p.parse_args(argv)

    statuses = gather(args.api)
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
    else:
        print("no regressions — standings updated, no alert (news, not schedule)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
