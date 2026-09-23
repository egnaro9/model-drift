"""Push staged notes to dev.to as DRAFTS.

Never publishes. The API takes `published` true or false and has no date
field, so scheduling is a thing that only exists in dev.to's own UI. This
writes drafts and stops; the decision to publish, and when, stays a human one
in the composer.

Idempotent by title. Running it twice updates the draft it already created
instead of making a second one, because an article API that only knows how to
POST will happily give you five copies of the same post and no way to tell
which one a reader found.

The key is read from DEVTO_API_KEY and never printed, not in an error, not in
a URL, not in a log line. It goes in a header for the same reason the Gemini
key does: this estate has already leaked one credential into a public CI log
by interpolating it into a request line.
"""
from __future__ import annotations

import argparse
import json
import time
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

API = "https://dev.to/api"
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
MAX_TAGS = 4


class PushError(Exception):
    pass


def _key() -> str:
    k = os.environ.get("DEVTO_API_KEY", "").strip()
    if not k:
        raise PushError("DEVTO_API_KEY is not set in this environment")
    return k


# dev.to throttles article creation hard: two POSTs in a row returned 429
# "Retry later". The limit is per-account and recovers on its own, so this
# waits rather than failing the run, and waits longer each time instead of
# hammering a limiter that is already saying no.
RETRY_WAITS = (35, 70, 140)


def _call(method: str, path: str, payload: Optional[dict] = None) -> Tuple[Any, str]:
    for wait in (*RETRY_WAITS, None):
        data, err = _call_once(method, path, payload)
        if err.startswith("HTTP 429") and wait is not None:
            print(f"    rate limited, waiting {wait}s")
            time.sleep(wait)
            continue
        return data, err
    return None, "rate limited after every retry"


def _call_once(method: str, path: str, payload: Optional[dict] = None) -> Tuple[Any, str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"api-key": _key(), "Content-Type": "application/json",
                 "User-Agent": "drift-notes-push/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8")
            return (json.loads(body) if body else {}), ""
    except urllib.error.HTTPError as e:
        # The response body carries dev.to's reason. It never contains the key,
        # but the request line would, so the url is not echoed here.
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        return None, f"HTTP {e.code} on {method} {path}: {detail}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__} on {method} {path}: {e}"


def parse_front(text: str) -> Tuple[Dict[str, str], str]:
    m = FRONT.match(text)
    if not m:
        raise PushError("no front matter")
    fm: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm, text[m.end():].strip()


def existing_drafts() -> Tuple[Dict[str, int], str]:
    """{title: id} for everything already on the account, published or not.

    Both states are checked. Matching only unpublished would re-post an
    article the moment he publishes it, which is the worst possible moment.
    """
    out: Dict[str, int] = {}
    for path in ("/articles/me/unpublished?per_page=100",
                 "/articles/me/published?per_page=100"):
        data, err = _call("GET", path)
        if err:
            return out, err
        for a in data or []:
            out[a["title"].strip()] = a["id"]
    return out, ""


def push(path: Path, known: Dict[str, int], dry: bool) -> str:
    fm, body = parse_front(path.read_text(encoding="utf-8"))
    title = fm.get("title", "").strip()
    if not title:
        raise PushError(f"{path.name}: no title")

    tags = [t.strip() for t in fm.get("tags", "").split(",") if t.strip()][:MAX_TAGS]
    article: Dict[str, Any] = {
        "title": title,
        "body_markdown": body,
        "published": False,          # never true from here
        "tags": tags,
        "canonical_url": fm.get("canonical_url", ""),
        "description": fm.get("description", "")[:180],
    }
    if fm.get("cover_image"):
        article["main_image"] = fm["cover_image"]

    aid = known.get(title)
    verb = "would update" if dry and aid else "would create" if dry else \
           "updated" if aid else "created"
    if dry:
        return f"{verb}  {title[:58]}"

    if aid:
        data, err = _call("PUT", f"/articles/{aid}", {"article": article})
    else:
        data, err = _call("POST", "/articles", {"article": article})
    if err:
        raise PushError(f"{path.name}: {err}")
    return f"{verb}  id={data.get('id')}  {title[:50]}"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="*", help="*.devto.md; default every one in --dir")
    ap.add_argument("--dir", default="posts/staged")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    targets = [Path(f) for f in a.files] or sorted(Path(a.dir).glob("*.devto.md"))
    if not targets:
        print("no .devto.md files found")
        return 0

    try:
        known, err = ({}, "") if a.dry_run else existing_drafts()
        if err:
            print(f"  could not list existing articles: {err}")
            return 1
        for t in targets:
            print("  " + push(t, known, a.dry_run))
    except PushError as e:
        print(f"  REFUSED: {e}")
        return 1

    print(f"\n{len(targets)} article(s) handled. All are DRAFTS; nothing was published.")
    print("dev.to scheduling lives in its own composer, behind the icon beside Publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
