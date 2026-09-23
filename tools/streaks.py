"""How long has each check been saying the same thing?

A red build is a signal with a half-life. Red since this morning demands
action; red every day for a fortnight is furniture, and the two look identical
in a notification email.

Be clear about the limit, because the case that prompted this is one this tool
would have missed. model-drift's agreement check spent 2026-08-30 to 2026-09-23
SKIPPING rather than failing: the store it queried had been retired, and an
unreachable store is not a disagreeing one. 57 CI runs passed, each printing
"207 passed, 1 skipped". Conclusions are all this reads, and a skipping test is
green. It answers "how long has this been red". That case needed "how long has
this been reporting on nothing", which is a different probe.

So this does not ask whether a workflow is red. It asks how long it has been
red, which is the number that separates a new failure from an accepted one.

It asks the same of the other direction, which is the half people forget: a
test that SKIPS forever is a test that stopped testing, and it is green the
whole time. evalmut once shipped a test that had never passed since the day it
was written, and that red looked exactly like ordinary red for ten days.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# A run that has failed this many times consecutively is not news any more; it
# is a decision nobody made. The value is deliberately small: by the time a
# check has been red for a working week, the emails have already stopped
# meaning anything.
STALE_RED_RUNS = 5
STALE_RED_DAYS = 7


def _gh(args: List[str]) -> Tuple[Any, str]:
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=90)
        if p.returncode != 0:
            return None, p.stderr.strip()[:200]
        return json.loads(p.stdout or "[]"), ""
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def _days_since(stamp: str) -> Optional[int]:
    try:
        d = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - d).days
    except Exception:
        return None


def streak(repo: str, workflow: str, limit: int = 40) -> Dict[str, Any]:
    """The current run of identical conclusions, newest first.

    Counts only COMPLETED runs. An in-progress run has no conclusion, and
    treating its absence as a change would reset the streak every morning
    while the job was still going.
    """
    runs, err = _gh(["run", "list", "--repo", repo, "--workflow", workflow,
                     "--limit", str(limit), "--json",
                     "conclusion,status,createdAt,headSha,databaseId"])
    if err:
        return {"workflow": workflow, "error": err}
    done = [r for r in (runs or []) if r.get("status") == "completed"]
    if not done:
        return {"workflow": workflow, "runs": 0, "note": "no completed runs"}

    current = done[0].get("conclusion")
    n = 0
    for r in done:
        if r.get("conclusion") != current:
            break
        n += 1
    oldest = done[n - 1]
    return {
        "workflow": workflow,
        "conclusion": current,
        "streak_runs": n,
        "streak_days": _days_since(oldest.get("createdAt", "")),
        "since": (oldest.get("createdAt") or "")[:10],
        "since_sha": (oldest.get("headSha") or "")[:7],
        "latest_id": done[0].get("databaseId"),
        "exhausted": n == len(done),   # the streak may be longer than we looked
    }


def last_green(repo: str, workflow: str, limit: int = 60) -> Optional[str]:
    runs, err = _gh(["run", "list", "--repo", repo, "--workflow", workflow,
                     "--limit", str(limit), "--json", "conclusion,status,createdAt"])
    if err or not runs:
        return None
    for r in runs:
        if r.get("status") == "completed" and r.get("conclusion") == "success":
            return (r.get("createdAt") or "")[:10]
    return None


def verdict(s: Dict[str, Any]) -> str:
    """What the streak means, which is not the same as what the colour means."""
    if s.get("error"):
        return "UNKNOWN"
    c = s.get("conclusion")
    if c == "success":
        return "GREEN"
    runs, days = s.get("streak_runs", 0), s.get("streak_days")
    if runs >= STALE_RED_RUNS or (days is not None and days >= STALE_RED_DAYS):
        # The distinction this whole file exists to make.
        return "ACCEPTED RED"
    return "NEW RED"


def report(targets: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for repo, wf in targets:
        s = streak(repo, wf)
        s["repo"] = repo
        s["verdict"] = verdict(s)
        if s["verdict"] in ("ACCEPTED RED", "NEW RED"):
            s["last_green"] = last_green(repo, wf)
        out.append(s)
    return out


DEFAULT = [
    ("egnaro9/model-drift", "ci.yml"),
    ("egnaro9/model-drift", "track.yml"),
    ("egnaro9/model-drift", "draft.yml"),
    ("egnaro9/model-drift", "pages.yml"),
    ("egnaro9/evalmut", "ci.yml"),
    ("egnaro9/evalmut", "notes.yml"),
    ("egnaro9/vac-protocol", "ci.yml"),
    ("egnaro9/vac-protocol", "replay.yml"),
    ("egnaro9/egnaro9.github.io", "ci.yml"),
]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    rows = report(DEFAULT)
    if a.json:
        print(json.dumps(rows, indent=1))
        return 0

    worst = [r for r in rows if r["verdict"] == "ACCEPTED RED"]
    for r in rows:
        if r.get("error"):
            print(f"  {'UNKNOWN':<13} {r['repo'].split('/')[-1]:<18} {r['workflow']:<12} {r['error'][:40]}")
            continue
        if r.get("runs") == 0:
            print(f"  {'NO RUNS':<13} {r['repo'].split('/')[-1]:<18} {r['workflow']}")
            continue
        tail = ""
        if r["verdict"] != "GREEN":
            tail = (f"  {r['streak_runs']} runs / {r['streak_days']}d since {r['since']} "
                    f"({r['since_sha']})"
                    + (f", last green {r['last_green']}" if r.get("last_green") else
                       ", NEVER green in the window"))
        print(f"  {r['verdict']:<13} {r['repo'].split('/')[-1]:<18} {r['workflow']:<12}{tail}")

    if worst:
        print(f"\n{len(worst)} check(s) have been red long enough to stop being news.")
        print("A permanent true alert decays into noise faster than a false one,")
        print("because a false alarm at least gets investigated once.")
    else:
        print("\nNothing has been red long enough to have become furniture.")
    # Always 0: this reports, it does not gate.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
