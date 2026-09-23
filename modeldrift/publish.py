"""The index the public notes page reads.

Publishing is one word. A draft lands in posts/ with `status: draft` in its
front matter and is invisible; flipping that to `published` and merging is what
puts it on the site. There is no separate publish action to forget, and no way
to publish by accident, because the default state of anything this pipeline
writes is unpublished.

The index is generated, never hand-kept. A hand-kept index is how a site ends
up listing a post that no longer exists, or quietly dropping one that does.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def parse_front_matter(text: str) -> Dict[str, str]:
    """The subset this pipeline writes: flat `key: value`, values may be quoted."""
    m = FRONT.match(text)
    if not m:
        return {}
    out: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"')
    return out


def body_of(text: str) -> str:
    m = FRONT.match(text)
    return text[m.end():] if m else text


def summarize(body: str, limit: int = 240) -> str:
    """First real paragraph, for the index card.

    Skips headings and the bold framing line, because a card reading "This is a
    finding about infrastructure, not about a model." for every infrastructure
    note tells a reader nothing about which note it is.
    """
    for block in body.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(("#", "|", "-", "*", ">")):
            continue
        if block.startswith("**") and block.endswith("**"):
            continue
        # The card renders this as plain escaped text, so markdown syntax would
        # show as literal backticks and asterisks. Strip the markers, keep the
        # words.
        flat = " ".join(block.split())
        flat = re.sub(r"`([^`]+)`", r"\1", flat)
        flat = re.sub(r"\*\*([^*]+)\*\*", r"\1", flat)
        flat = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", flat)
        return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + "…"
    return ""


def is_post(path: Path) -> bool:
    """A markdown file in posts/ is only a post if it has front matter.

    posts/ also holds BACKLOG.md, which is a worklist rather than a note.
    Counting it as an unpublished draft would report a to-do list as a post
    waiting to go out.
    """
    return bool(parse_front_matter(path.read_text(encoding="utf-8")))


def build_index(posts_dir: str) -> List[Dict[str, Any]]:
    """Published notes, newest first. Drafts are absent, not hidden."""
    out = []
    for path in sorted(Path(posts_dir).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fm = parse_front_matter(text)
        if not fm or fm.get("status") != "published":
            continue
        out.append({
            "slug": path.stem,
            "file": path.name,
            "title": fm.get("title", path.stem),
            "date": fm.get("date", ""),
            "kind": fm.get("kind", ""),
            "about": fm.get("about", ""),
            "subject": fm.get("subject", ""),
            "summary": summarize(body_of(text)),
        })
    out.sort(key=lambda p: (p["date"], p["slug"]), reverse=True)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--posts", default="posts")
    ap.add_argument("--out", default="posts/index.json")
    a = ap.parse_args(argv)

    Path(a.posts).mkdir(parents=True, exist_ok=True)
    index = build_index(a.posts)
    Path(a.out).write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    drafts = sum(1 for p in Path(a.posts).glob("*.md")
                 if is_post(p)
                 and parse_front_matter(p.read_text(encoding="utf-8")).get("status") != "published")
    print(f"{len(index)} published note(s) indexed; {drafts} still marked draft")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
