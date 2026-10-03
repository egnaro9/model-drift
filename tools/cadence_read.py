"""Capture the cadence test's view counts from dev.to, as a time series.

WHY THIS EXISTS. The two readings this replaces were one-shot scheduled tasks on
Erik's Mac, each due at a single wall-clock instant. Views only ever accumulate,
so a missed reading is unrecoverable: there is no way to ask dev.to what a post's
count was yesterday. On 2026-09-28 the local scheduler was measured producing
runs for 3 of 13 scheduled slots over 89 hours, twice failing inside windows
where the machine was demonstrably awake. A pre-registered experiment whose only
instrument is that scheduler is an experiment with no data.

So this does not try to read at an instant. It samples repeatedly and APPENDS,
and the analysis picks matched offsets afterwards. Three consequences worth
stating, because they make this a better instrument than the thing it replaces:

- A missed run costs nothing. The next sample still lands, and every reading
  carries the elapsed hours it was actually taken at, so nothing has to pretend
  it happened at exactly T+48h.
- The comparison stops depending on GitHub's cron punctuality. Scheduled runs
  here start up to several hours after their nominal minute, which silently made
  the old "T+48h" figures more like T+46h.
- Readings are append-only. A reading already on disk is never rewritten, so a
  later run cannot quietly restate an earlier number.

It writes NOTHING but the readings file, and it does not interpret. The verdict
against the pre-registration is a separate, deliberately human step.
"""
from __future__ import annotations

import argparse, json, os, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

API = "https://dev.to/api"
UA = "drift-notes-cadence-read/1.0"

# Sampling policy. MIN_GAP_MINUTES keeps a re-run or a dispatch from stacking two
# readings a minute apart; WINDOW_DAYS stops this workflow nagging forever once
# the test is long over.
MIN_GAP_MINUTES = 45
WINDOW_DAYS = 8

ARMS = {
    "A": "2026-09-30-the-grader-reads-the-first-number",
    "B": "2026-10-02-the-gate-could-not-see-what-it-was-gating",
}


class Refused(Exception):
    pass


def _key() -> str:
    k = os.environ.get("DEVTO_API_KEY", "").strip()
    if not k:
        raise Refused("DEVTO_API_KEY is not set")
    return k


def _published() -> List[dict]:
    req = urllib.request.Request(
        f"{API}/articles/me/published?per_page=100",
        headers={"api-key": _key(), "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        raise Refused(f"dev.to returned HTTP {e.code} for the published list")


def parse_iso(s: str) -> datetime:
    """dev.to stamps published_at as ...Z, which fromisoformat rejects before 3.11."""
    t = s.strip().replace("Z", "+00:00")
    d = datetime.fromisoformat(t)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def elapsed_hours(published_at: str, now: datetime) -> float:
    return round((now - parse_iso(published_at)).total_seconds() / 3600.0, 3)


def match_article(articles: List[dict], slug: str) -> Optional[dict]:
    """The one article whose canonical points at this slug, or None if unpublished.

    Matched on canonical_url rather than title. A title is prose Erik may edit
    after the fact; the canonical is the identity the post was cross-posted with.
    More than one match is refused rather than resolved: picking "the first" is
    how the wrong article gets measured, and a silently wrong number is worse
    here than no number, because the wrong number still looks like data.
    """
    hits = [a for a in articles
            if (a.get("canonical_url") or "").rstrip("/").endswith(slug)]
    if len(hits) > 1:
        raise Refused(f"{len(hits)} published articles carry the canonical for {slug}")
    return hits[0] if hits else None


def last_reading(readings: List[dict], arm: str) -> Optional[dict]:
    mine = [r for r in readings if r.get("arm") == arm]
    return max(mine, key=lambda r: r.get("t", ""), default=None)


def should_record(readings: List[dict], arm: str, elapsed_h: float,
                  now: datetime) -> bool:
    """Sample unless we just did, or the test window for this arm has closed."""
    if elapsed_h < 0:
        return False
    if elapsed_h > WINDOW_DAYS * 24:
        return False
    prev = last_reading(readings, arm)
    if prev is None:
        return True
    gap_min = (now - parse_iso(prev["t"])).total_seconds() / 60.0
    return gap_min >= MIN_GAP_MINUTES


def load(path: Path) -> dict:
    if not path.exists():
        return {
            "test": "cadence-2026-09-30-vs-2026-10-02",
            "pre_registration": ("~/Desktop/Resume/POSTING_AB_LOG.md, section "
                                 "'PRE-REGISTERED: the cadence test', written "
                                 "2026-09-23 before either post existed publicly"),
            "arms": {k: {"slug": v} for k, v in ARMS.items()},
            "note": ("Append-only. Every reading carries the elapsed hours it was "
                     "actually taken at; do not assume any of them is exactly 48h. "
                     "Compare matched elapsed values, or interpolate."),
            "readings": [],
        }
    return json.loads(path.read_text())


def collect(articles: List[dict], readings: List[dict], now: datetime) -> List[dict]:
    """The new readings this run should append. Pure, so the tests can drive it."""
    out: List[dict] = []
    for arm, slug in sorted(ARMS.items()):
        art = match_article(articles, slug)
        if art is None or not art.get("published_at"):
            continue
        eh = elapsed_hours(art["published_at"], now)
        if not should_record(readings + out, arm, eh, now):
            continue
        # page_views_count exists ONLY on the authenticated /articles/me/published
        # endpoint; the public /articles listing omits it entirely. If this is
        # ever pointed at the public endpoint, or dev.to renames the field, the
        # readings would still be written with views: null and the series would
        # look populated while holding nothing. Refuse instead.
        if not isinstance(art.get("page_views_count"), int):
            raise Refused(
                f"arm {arm} ({slug}) has no integer page_views_count; this is the "
                "authenticated field, so either the endpoint or the field changed")
        out.append({
            "arm": arm,
            "slug": slug,
            "t": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "published_at": art["published_at"],
            "elapsed_h": eh,
            "views": art.get("page_views_count"),
            "reactions": art.get("public_reactions_count"),
            "comments": art.get("comments_count"),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="posts/cadence_test_readings.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--probe", metavar="SLUG",
                    help="Check an ALREADY published slug end to end and write "
                         "nothing. Use before the test arms publish, so a missing "
                         "field is found while a reading can still be salvaged "
                         "rather than on the one day it cannot.")
    a = ap.parse_args()

    if a.probe:
        try:
            art = match_article(_published(), a.probe)
        except Refused as e:
            print(f"REFUSED: {e}")
            return 1
        if art is None:
            print(f"PROBE FAIL: nothing published carries the canonical for {a.probe}")
            return 1
        v = art.get("page_views_count")
        # PRINT THE VALUE. The old probe asserted isinstance(v, int) and printed
        # "(value present)" without ever showing v, so it returned PASS over a
        # zero for three days while the series it protects held nothing. A probe
        # that does not show the number cannot answer the question it is for.
        # A zero is now a FAIL: present-and-integer is not populated.
        ok = isinstance(v, int) and v > 0
        why = ("MISSING on this endpoint" if not isinstance(v, int)
               else "ZERO: present and integer, but not populated" if v == 0
               else "populated")
        print(f"PROBE {'PASS' if ok else 'FAIL'}: matched {a.probe}, "
              f"page_views_count={v!r} ({type(v).__name__}) -> {why}")

        # Survey every published article, so "does this account get page views
        # at all" is answerable instead of inferred from one post.
        print("\n  SURVEY of page_views_count across everything published:")
        arts = _published()
        nz = 0
        for x in sorted(arts, key=lambda d: d.get("published_at") or ""):
            pv = x.get("page_views_count")
            if isinstance(pv, int) and pv > 0:
                nz += 1
            print(f"    {str(x.get('published_at'))[:10]}  views={str(pv):>6}  "
                  f"reactions={x.get('public_reactions_count')}  "
                  f"{str(x.get('title'))[:46]}")
        print(f"\n  {nz} of {len(arts)} published articles report a non-zero view count.")
        print("  All zero means the field does not populate for this account, and the"
              "\n  cadence test's primary measurement has to change rather than be retried.")
        return 0 if ok else 1

    path = Path(a.out)
    doc = load(path)
    now = datetime.now(timezone.utc)

    try:
        fresh = collect(_published(), doc["readings"], now)
    except Refused as e:
        # Loud on purpose. A read that fails quietly is indistinguishable from a
        # read that found nothing, and this file's whole job is to not lose data.
        print(f"REFUSED: {e}")
        return 1

    if not fresh:
        print("no new reading due")
        return 0

    for r in fresh:
        print(f"{r['arm']} at {r['elapsed_h']}h: views={r['views']} "
              f"reactions={r['reactions']} comments={r['comments']}")
    if a.dry_run:
        print("dry run, nothing written")
        return 0

    doc["readings"].extend(fresh)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"appended {len(fresh)} reading(s) to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
