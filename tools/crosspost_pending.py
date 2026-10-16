"""Cross-post a published note whose dev.to draft is still waiting, once its page is live.

Why this exists. publish.yml flips a note to published, pushes, then waits 30
minutes for erikhill.dev to build the page before cross-posting. The site's
notes workflow is on a four-times-an-hour cron, but GitHub delivers a fraction
of scheduled runs: on 2026-10-09 and again on 2026-10-14 the next site build
came hours later. The gate timed out and refused to cross-post, which was
right, and then NOTHING retried: the note was no longer a draft, so --pick
never saw it again. Two cross-posts were lost and the job sat red by design.

The fix keeps the refusal and adds the retry. The pending state is not stored
here, it is read from the platform: a published note with exactly one
unpublished dev.to draft of the same title is PENDING. Each run:

- pending, page live, fresh, spacing allows  -> publish ONE, through
  devto_publish.main, so every one of its refusals still applies
- pending, page not live, inside the grace    -> WAITING, a warning, not red
- pending, page not live, past the grace       -> red: the site is broken, not slow
- pending, page live, held by spacing         -> HELD, a warning
- pending but older than FRESH_DAYS           -> STALE, a warning naming it for
  Erik. Auto-posting a note weeks after its moment is a content decision, not
  a retry, so this never does it on its own.

At most one publish per run, and only when dev.to's OWN published list shows
nothing in the last SPACING_DAYS. The weekly rule is measured (the 2026-08-14
double launch got under 25 views each), and the platform listing is the record
of what readers actually saw, not our commit log.
"""
from __future__ import annotations

import argparse, datetime as dt, os, sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import devto_publish as D  # noqa: E402
from modeldrift.publish import is_post, parse_front_matter  # noqa: E402

GRACE_HOURS = 48     # a page missing this long after its date is a broken site
FRESH_DAYS = 7       # older pending notes are a decision for Erik, not a retry
SPACING_DAYS = 6     # same window as publish.yml's one-post-per-week rule


def pending(posts: str, drafts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Published notes with unpublished dev.to drafts, oldest first.

    Ambiguity is reported, never resolved: two drafts with one title, or a
    draft whose canonical does not end with the slug, is a REFUSED row.
    """
    out = []
    for p in sorted(Path(posts).glob("*.md")):
        if not is_post(p):
            continue
        fm = parse_front_matter(p.read_text(encoding="utf-8"))
        if fm.get("status") != "published":
            continue
        title = fm.get("title", "").strip()
        hits = [d for d in drafts if (d.get("title") or "").strip() == title]
        if not hits:
            continue
        row = {"slug": p.stem, "title": title, "date": fm.get("date", ""), "drafts": hits}
        canon = (hits[0].get("canonical_url") or "").rstrip("/")
        if len(hits) != 1:
            row["refused"] = f"{len(hits)} dev.to drafts carry this title"
        elif not canon.endswith(p.stem):
            row["refused"] = f"draft canonical {canon!r} does not end with the slug"
        out.append(row)
    out.sort(key=lambda r: (r["date"], r["slug"]))
    return out


def age_hours(date: str, now: dt.datetime) -> float:
    """Hours since the note's date began, UTC. An unparseable date is treated
    as very old, so it can only be reported, never auto-posted."""
    try:
        d = dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return float("inf")
    return (now - d).total_seconds() / 3600


def last_devto_publish(published: List[Dict[str, Any]]) -> Optional[dt.datetime]:
    stamps = []
    for a in published:
        s = a.get("published_at") or ""
        try:
            stamps.append(dt.datetime.fromisoformat(s.replace("Z", "+00:00")))
        except ValueError:
            continue
    return max(stamps) if stamps else None


def is_live(slug: str) -> bool:
    ok, _ = D.canonical_is_live(f"https://erikhill.dev/notes/{slug}/", attempts=1, wait=0)
    return ok


def decide(rows: List[Dict[str, Any]], now: dt.datetime, last_pub: Optional[dt.datetime],
           live) -> List[Dict[str, Any]]:
    """Give every pending row a verdict. Pure, so every branch is testable
    without the network: `live` is a callable slug -> bool."""
    spacing_open = last_pub is None or (now - last_pub) >= dt.timedelta(days=SPACING_DAYS)
    chosen = False
    for r in rows:
        age = age_hours(r["date"], now)
        if "refused" in r:
            r["verdict"] = "REFUSED"
            continue
        up = live(r["slug"])
        r["live"] = up
        if not up:
            r["verdict"] = "BROKEN" if age > GRACE_HOURS else "WAITING"
        elif age > FRESH_DAYS * 24:
            r["verdict"] = "STALE"
        elif chosen or not spacing_open:
            r["verdict"] = "HELD"
        else:
            r["verdict"] = "PUBLISH"
            chosen = True
    return rows


NOTE = {
    "WAITING": "page not live yet; the next run retries",
    "BROKEN": f"page still missing more than {GRACE_HOURS}h after its date: check the notes workflow in egnaro9.github.io",
    "STALE": f"older than {FRESH_DAYS} days, so not auto-posted. Erik's call: publish the dev.to draft by hand or delete it",
    "HELD": f"page is live; held so dev.to gets at most one post per {SPACING_DAYS} days",
    "REFUSED": "ambiguous, refusing to guess",
}


def summary(lines: List[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--posts", default="posts")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    now = dt.datetime.now(dt.timezone.utc)
    try:
        drafts = D._call("GET", "/articles/me/unpublished?per_page=100") or []
        published = D._call("GET", "/articles/me/published?per_page=100") or []
    except D.Refused as e:
        # No reading is not a clean reading. Red, so it is never mistaken for
        # "nothing pending".
        print(f"  REFUSED: could not read dev.to: {e}")
        return 1

    rows = decide(pending(a.posts, drafts), now, last_devto_publish(published), is_live)
    out = ["## Cross-post catch-up", ""]
    if not rows:
        print("  nothing pending: every published note is on dev.to")
        summary(out + ["Nothing pending. Every published note is on dev.to."])
        return 0

    rc = 0
    for r in rows:
        v = r["verdict"]
        print(f"  {v:8} {r['slug']}  {r.get('refused') or NOTE.get(v, '')}")
        if v == "PUBLISH":
            if a.dry_run:
                print("           DRY RUN, nothing published")
                out.append(f"- DRY RUN would publish `{r['slug']}`")
                continue
            if D.main(["--slug", r["slug"], "--posts", a.posts]) != 0:
                rc = 1
                out.append(f"- **REFUSED at publish** `{r['slug']}` (see log)")
                continue
            out.append(f"- **Published** `{r['slug']}`: https://erikhill.dev/notes/{r['slug']}/")
            li = Path(a.posts, "staged", f"{r['slug']}.linkedin.txt")
            if li.exists():
                out += ["", "### Paste this into the Drift Notes newsletter", "", "```",
                        li.read_text(encoding="utf-8").rstrip(), "```", ""]
        else:
            if v in ("BROKEN", "REFUSED"):
                rc = 1
                print(f"::error::{r['slug']}: {r.get('refused') or NOTE[v]}")
            else:
                print(f"::warning::{r['slug']}: {NOTE[v]}")
            out.append(f"- {v} `{r['slug']}`: {r.get('refused') or NOTE[v]}")
    summary(out)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
