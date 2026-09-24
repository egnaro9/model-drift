"""Publish an existing dev.to DRAFT, matched to a post by title.

Separate from devto_push.py on purpose. That file hardcodes `published: False`
and has no code path that can publish; it stays that way, because the thing
that stages drafts should not be able to send them. This is the one place that
flips the bit, it takes a single slug, and it refuses everything it is not sure
about.

Three refusals, each from something that actually went wrong:

- EXACTLY ONE draft must match the title. Not the first of several. A near-title
  match publishing the wrong article is unrecoverable in the way that matters:
  it is public under Erik's name before anyone notices.
- The draft's canonical_url must END WITH the slug. On 2026-09-23 two notes were
  cross-posted carrying canonicals that 404'd, which tells search engines the
  real article is at a page that does not exist.
- The canonical must be LIVE. Checked here as well as in the workflow, because a
  guard that exists in one place and not its sibling is this estate's most
  expensive recurring defect.

The response to a publish returns `published: null` and confirms nothing, so
success is read from the platform's own listings instead.
"""
from __future__ import annotations

import argparse, json, os, re, sys, time, urllib.error, urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

API = "https://dev.to/api"
UA = "drift-notes-publish/1.0"


class Refused(Exception):
    pass


def _key() -> str:
    k = os.environ.get("DEVTO_API_KEY", "").strip()
    if not k:
        raise Refused("DEVTO_API_KEY is not set")
    return k


def _call(method: str, path: str, payload: Optional[dict] = None) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                 headers={"api-key": _key(), "User-Agent": UA,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:200]
        except Exception:
            pass
        # the url is not echoed: it would carry nothing secret, but the header would
        raise Refused(f"HTTP {e.code} on {method} {path}: {detail}") from None


def title_of(slug: str, posts: str = "posts") -> str:
    text = Path(posts, f"{slug}.md").read_text(encoding="utf-8")
    m = re.search(r'^title:\s*"?(.+?)"?\s*$', text, re.M)
    if not m:
        raise Refused(f"{slug}: no title in front matter")
    return m.group(1).strip()


def find_draft(title: str) -> Dict[str, Any]:
    drafts = _call("GET", "/articles/me/unpublished?per_page=100") or []
    hits = [d for d in drafts if d.get("title", "").strip() == title]
    if len(hits) != 1:
        raise Refused(
            f"expected exactly 1 unpublished draft titled {title!r}, found {len(hits)}. "
            "Refusing rather than guessing which one to make public.")
    return hits[0]


def canonical_is_live(url: str, attempts: int = 10, wait: int = 20) -> Tuple[bool, int]:
    last = 0
    for _ in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as r:
                last = r.status
                if 200 <= r.status < 300:
                    return True, r.status
        except urllib.error.HTTPError as e:
            last = e.code
        except Exception:
            last = 0
        time.sleep(wait)
    return False, last


def confirm_published(article_id: int) -> bool:
    """The PUT returns published: null. Ask the platform instead."""
    un = _call("GET", "/articles/me/unpublished?per_page=100") or []
    if any(d.get("id") == article_id for d in un):
        return False
    pub = _call("GET", "/articles/me/published?per_page=100") or []
    return any(d.get("id") == article_id for d in pub)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--posts", default="posts")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    try:
        title = title_of(a.slug, a.posts)
        draft = find_draft(title)
        canonical = (draft.get("canonical_url") or "").rstrip("/")
        if not canonical.endswith(a.slug):
            raise Refused(f"draft {draft['id']} canonical {canonical!r} does not end with {a.slug!r}")

        print(f"  title     {title[:66]}")
        print(f"  draft id  {draft['id']}")
        print(f"  canonical {canonical}/")

        live, code = canonical_is_live(canonical + "/")
        if not live:
            raise Refused(f"canonical returned {code}, not 200. Nothing published. "
                          "A cross-post with a dead canonical is worse than a late one.")
        print("  canonical is live")

        if a.dry_run:
            print("  DRY RUN, nothing published")
            return 0

        _call("PUT", f"/articles/{draft['id']}", {"article": {"published": True}})
        if not confirm_published(draft["id"]):
            raise Refused(f"article {draft['id']} is still listed as unpublished. "
                          "Not retrying: a double publish is worse than a missing one.")
        print(f"  PUBLISHED and confirmed against the platform listing")
        return 0
    except Refused as e:
        print(f"  REFUSED: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
