"""Fill the dev.to rows of the posting A/B log from the dev.to API.

Nineteen runs of the ab-metrics-log routine produced zero rows, because the
routine was a reminder: it told Erik which cells were empty and was explicitly
forbidden from filling them. dev.to publishes reactions, comments and page
views per article, so for that platform the reminder was never necessary.

What this does NOT do is guess. A row is filled only when exactly one published
article matches its date. Two articles on one day, or none, is reported and
skipped, because a plausible wrong number in a measurement log is worse than a
blank: the blank is visibly missing and the wrong one gets analysed.

LinkedIn and X have no comparable public API here and are left alone.
"""
from __future__ import annotations

import argparse, json, os, re, subprocess, sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LOG = Path.home() / "Desktop/Resume/POSTING_AB_LOG.md"
API = "https://dev.to/api/articles/me/published?per_page=100"

# The table this tool may touch. Any other table in the file is off limits: the
# document also holds findings, a pre-registration and a running tally, and a
# tool that edited those would be rewriting conclusions, not recording data.
HEADER = "| # | Date | Platform | Day | Slot (ET) | Story | Impressions | Eng. rate | 1st-hr | Notes |"


def fetch() -> Tuple[List[dict], str]:
    key = os.environ.get("DEVTO_API_KEY", "").strip()
    if not key:
        return [], "DEVTO_API_KEY not set (run under `zsh -ic`; a non-interactive shell does not source .zshrc)"
    try:
        p = subprocess.run(["curl", "-sS", "-H", f"api-key: {key}", API],
                           capture_output=True, text=True, timeout=60)
        return json.loads(p.stdout or "[]"), ""
    except Exception as e:  # noqa: BLE001
        return [], f"{type(e).__name__}: {e}"


def by_date(arts: List[dict]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for a in arts:
        d = (a.get("published_at") or "")[:10]
        if d:
            out.setdefault(d, []).append(a)
    return out


def cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def fill(text: str, index: Dict[str, List[dict]]) -> Tuple[str, List[str]]:
    lines = text.split("\n")
    notes: List[str] = []
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == HEADER)
    except StopIteration:
        return text, ["the Log table header was not found; the file's shape changed, refusing to guess"]

    for i in range(start + 2, len(lines)):
        line = lines[i]
        if not line.strip().startswith("|"):
            break                      # end of this table; do not wander into the next
        c = cells(line)
        if len(c) != 10:
            continue
        num, date, platform, _day, _slot, story, impressions, eng, _hr, _notes = c
        if platform.lower() != "dev.to" or impressions:
            continue

        matches = index.get(date, [])
        if len(matches) != 1:
            notes.append(f"row {num} ({date}): {len(matches)} articles match that date, skipped")
            continue

        a = matches[0]
        views = a.get("page_views_count")
        reactions = a.get("public_reactions_count") or 0
        comments = a.get("comments_count") or 0
        if views in (None, 0):
            notes.append(f"row {num} ({date}): dev.to reports {views} views, too early or not counted, skipped")
            continue

        rate = f"{(reactions + comments) / views * 100:.1f}%"
        c[6] = str(views)
        c[7] = rate
        c[9] = (c[9] + "; " if c[9] else "") + f"auto-filled from dev.to api {a['id']}"
        lines[i] = "| " + " | ".join(c) + " |"
        notes.append(f"row {num} ({date}): views={views} reactions={reactions} comments={comments} rate={rate}")
    return "\n".join(lines), notes


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", default=str(LOG))
    ap.add_argument("--write", action="store_true", help="without this, prints what it would do and changes nothing")
    a = ap.parse_args(argv)

    arts, err = fetch()
    if err:
        print(f"  REFUSED: {err}")
        return 1
    if not arts:
        print("  REFUSED: the API returned no published articles; refusing to conclude the log is complete")
        return 1

    path = Path(a.log)
    before = path.read_text(encoding="utf-8")
    after, notes = fill(before, by_date(arts))

    for n in notes:
        print(f"  {n}")
    if not notes:
        print("  no dev.to rows are both blank and matchable")

    changed = after != before
    if changed and a.write:
        path.write_text(after, encoding="utf-8")
        print(f"\n  wrote {path}")
    elif changed:
        print(f"\n  {after.count(chr(10)) - before.count(chr(10))} line delta; run with --write to apply")
    else:
        print("\n  nothing to change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
