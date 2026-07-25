"""Which tasks flipped — and whether the probe or the models are to blame.

An aggregate delta cannot tell these three apart, and they need different
responses:

  * **noise**   — one task flips once on one model. A 35-task suite has a
                  resolution of 100/35 = 2.86 points, so a single flip *is* the
                  smallest number the instrument can print. Not a finding.
  * **signal**  — the same task flips repeatedly on the same model across
                  independent runs. That is a model-or-stack change worth
                  writing up.
  * **probe**   — the same task fails on several providers on the same day.
                  Models from different labs do not regress in unison; a shared
                  failure points at the harness — a changed prompt, a broken
                  grader, an environment problem. This is an alarm about *us*.

The data was already on disk: every run is kept, and each point now carries the
ids of the tasks that failed. The identity was being discarded at the aggregate.

The read that separating these three matters is ANP2 Network's, on the
"four regression alerts, zero regressions" field note.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Optional

# A task failing on at least this many distinct providers in one day is treated
# as an accusation against the probe rather than against the models.
PROBE_ALARM_PROVIDERS = 3


def _provider(model_id: str) -> str:
    """'openai:gpt-5' -> 'openai'. Falls back to the whole id."""
    return model_id.split(":", 1)[0] if ":" in model_id else model_id


def _day(stamp: str) -> str:
    return (stamp or "")[:10]


def flips_for_model(points: list[dict]) -> list[dict]:
    """Per-task flips between consecutive runs of one model, newest last.

    A flip is a task changing pass/fail state from one stored run to the next.
    Returns one entry per task that ever flipped, with how often it did.
    """
    seen = [(p.get("t", ""), set(p.get("fails") or [])) for p in points if "fails" in p]
    if len(seen) < 2:
        return []
    counts: Counter = Counter()
    last_dir: dict[str, str] = {}
    for (_, prev), (t, cur) in zip(seen, seen[1:]):
        for task in (cur - prev):
            counts[task] += 1
            last_dir[task] = f"broke on {_day(t)}"
        for task in (prev - cur):
            counts[task] += 1
            last_dir[task] = f"recovered on {_day(t)}"
    return sorted(
        ({"task": t, "flips": n, "latest": last_dir[t]} for t, n in counts.items()),
        key=lambda r: (-r["flips"], r["task"]),
    )


def analyze(series: dict[str, list[dict]],
            probe_alarm_providers: int = PROBE_ALARM_PROVIDERS) -> dict[str, Any]:
    """Full read over every model's stored runs.

    Returns:
      repeat_offenders — task/model pairs that flipped more than once (signal)
      one_offs         — task/model pairs that flipped exactly once (noise)
      probe_alarms     — tasks failing across >= N providers on the same day
    """
    repeat, once = [], []
    for model_id, points in series.items():
        if model_id.startswith("mock:"):
            continue
        for row in flips_for_model(points):
            entry = {"model": model_id, **row}
            (repeat if row["flips"] > 1 else once).append(entry)

    # Cross-provider: for each day, which tasks failed on how many providers.
    by_day: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for model_id, points in series.items():
        if model_id.startswith("mock:"):
            continue
        prov = _provider(model_id)
        for p in points:
            if "fails" not in p:
                continue
            for task in (p.get("fails") or []):
                by_day[_day(p.get("t", ""))][task].add(prov)

    alarms = []
    for day, tasks in by_day.items():
        for task, provs in tasks.items():
            if len(provs) >= probe_alarm_providers:
                alarms.append({"day": day, "task": task,
                               "providers": sorted(provs), "n_providers": len(provs)})
    alarms.sort(key=lambda a: (-a["n_providers"], a["day"], a["task"]))

    # How many stored runs actually carry per-task identity. Without at least two
    # for some model there is nothing to compare, and "nothing flipped" would be a
    # lie of omission — the same false reassurance this module exists to prevent.
    comparable = sum(1 for pts in series.values()
                     if sum(1 for p in pts if "fails" in p) >= 2)

    return {
        "repeat_offenders": sorted(repeat, key=lambda r: (-r["flips"], r["model"])),
        "one_offs": once,
        "probe_alarms": alarms,
        "models_with_enough_history": comparable,
    }


def summarize(report: dict[str, Any]) -> str:
    """A short human read, for the console or a field note."""
    lines: list[str] = []
    alarms = report["probe_alarms"]
    if alarms:
        lines.append(f"PROBE ALARM — {len(alarms)} task/day pair(s) failed across "
                     f"multiple providers at once; suspect the harness, not the models:")
        for a in alarms[:5]:
            lines.append(f"  {a['day']}  {a['task']}  on {a['n_providers']} providers "
                         f"({', '.join(a['providers'])})")
    rep = report["repeat_offenders"]
    if rep:
        lines.append(f"{len(rep)} task/model pair(s) flipped more than once — the "
                     f"candidates worth investigating:")
        for r in rep[:8]:
            lines.append(f"  {r['model']}  {r['task']}  ×{r['flips']}  ({r['latest']})")
    n_once = len(report["one_offs"])
    if n_once:
        lines.append(f"{n_once} single flip(s) — at 2.86 points per task on a 35-task "
                     f"suite, that is the instrument's resolution, not a finding.")
    if lines:
        return "\n".join(lines)
    if not report.get("models_with_enough_history"):
        return ("No per-task history yet — runs only started recording which tasks "
                "failed recently, so there is nothing to compare. This is 'no data', "
                "not 'no flips'; it will fill in after two more scheduled runs.")
    return "No task flipped in the stored history."
