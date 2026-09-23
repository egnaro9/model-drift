"""Turn a published note into the three things the other surfaces need.

The note on erikhill.dev is the canonical artifact. dev.to, LinkedIn and X each
get a pointer to it, shaped for that surface, and none of them gets a copy: a
second full text is a second thing to correct when the first one is wrong.

Emits, per post, into a staging directory:
  <slug>.devto.md      dev.to front matter, published:false, canonical_url set
  <slug>.linkedin.txt  the share, one availability line, no hashtag spam
  <slug>.x.txt         a thread, each part already inside 280 characters

Nothing here posts anything. dev.to scheduling is UI only (the API has
published true/false and no date field), LinkedIn scheduling is in the composer,
and X is a channel with a pre-registered evaluation that has not been closed out.
All three are a human action on purpose.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

X_LIMIT = 280

# Measured from his own dev.to data: both top posts were ~4 minute reads and
# `showdev` is a commenting community rather than a scrolling one.
DEFAULT_TAGS = ["showdev", "testing", "ai"]

AVAILABILITY = ("I build deterministic evaluation and verification tooling for LLM "
                "systems, and I am looking for my first full-time role in AI evaluation "
                "or QA engineering. Remote US Eastern, or Charleston SC.")

FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def parse(text: str) -> Tuple[Dict[str, str], str]:
    m = FRONT.match(text)
    if not m:
        raise SystemExit("no front matter")
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm, text[m.end():]


# The footer sits after a horizontal rule and carries no heading, so it stays
# inside the last section unless it is cut off first. Left in, it becomes the
# "last prose paragraph" and the kicker quotes a list of links.
FOOTER_RULE = re.compile(r"\n---\n(?=[^-])")


def strip_footer(body: str) -> str:
    m = list(FOOTER_RULE.finditer(body))
    return body[:m[-1].start()] if m else body


def sections(body: str) -> Dict[str, str]:
    body = strip_footer(body)
    out, cur, buf = {}, None, []
    for line in body.splitlines():
        if line.startswith("## "):
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = line[3:].strip(), []
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def _paras(block: str) -> List[str]:
    """Prose paragraphs only. Tables, code fences and bold framing lines are
    structure, not sentences, and reading them as prose produces nonsense."""
    out, fence = [], False
    for p in block.split("\n\n"):
        p = p.strip()
        if p.startswith("```"):
            fence = not fence if p.count("```") % 2 else fence
            continue
        if fence or not p or p.startswith(("|", "#", ">", "-", "*")):
            continue
        if p.startswith("**") and p.endswith("**"):
            continue
        out.append(" ".join(p.split()))
    return out


def hook(secs: Dict[str, str]) -> str:
    """The first real paragraph of 'What happened'.

    Rule 7 of his measured post playbook: open with a first-person incident and
    a number, never a maxim. That paragraph already is one.
    """
    for name in ("What happened", "The finding"):
        if name in secs:
            ps = _paras(secs[name])
            if ps:
                return ps[0]
    return ""


def kicker(secs: Dict[str, str]) -> str:
    """The sentence worth quoting: the last prose line of the closing section,
    which in this format is the 'if you maintain an eval suite' instruction."""
    for name in ("What I might have wrong", "What the extra data did not buy"):
        if name in secs:
            ps = _paras(secs[name])
            if ps:
                return ps[-1]
    return ""


def devto(fm: Dict[str, str], body: str, url: str, tags: List[str],
          cover: Optional[str]) -> str:
    """A pointer plus the opening, never the whole post.

    canonical_url is not optional. Cross-posting a full text without it splits
    the search result and reads as duplication.
    """
    secs = sections(body)
    lines = ["---", f'title: "{fm["title"]}"', "published: false",
             f'description: "{hook(secs)[:180]}"',
             f"tags: {', '.join(tags[:4])}",
             f"canonical_url: {url}"]
    if cover:
        lines.append(f"cover_image: {cover}")
    lines += ["---", "",
              f"*Originally published at [erikhill.dev]({url}). The numbers below are "
              "checked against the repository they come from.*", "", body.strip(), ""]
    return "\n".join(lines)


def linkedin(fm: Dict[str, str], body: str, url: str) -> str:
    secs = sections(body)
    parts = [hook(secs), ""]
    k = kicker(secs)
    if k:
        parts += [k, ""]
    parts += [f"Full note, with the evidence table: {url}", "", AVAILABILITY,
              "", "https://erikhill.dev"]
    return "\n".join(parts)


def x_thread(fm: Dict[str, str], body: str, url: str) -> List[str]:
    """Split on sentences, never mid-sentence.

    A thread cut at 280 characters regardless of where the sentence ends reads
    as a bot, and the point of this channel is that it does not.
    """
    secs = sections(body)
    text = hook(secs)
    k = kicker(secs)

    chunks, cur = [], ""
    for sentence in re.split(r"(?<=[.?!]) ", text):
        if len(cur) + len(sentence) + 1 > X_LIMIT - 8:
            if cur:
                chunks.append(cur.strip())
            cur = sentence
        else:
            cur = f"{cur} {sentence}".strip()
    if cur:
        chunks.append(cur.strip())
    if k and len(k) <= X_LIMIT - 8:
        chunks.append(k)
    chunks.append(f"Full note, with the evidence: {url}")

    n = len(chunks)
    return [f"{c} {i}/{n}" if n > 1 else c for i, c in enumerate(chunks, 1)]


def stage(path: Path, out_dir: Path, cover: Optional[str]) -> List[Path]:
    fm, body = parse(path.read_text(encoding="utf-8"))
    url = fm.get("destination") or f"https://erikhill.dev/notes/{path.stem}/"
    tags = DEFAULT_TAGS
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    for suffix, content in (
        (".devto.md", devto(fm, body, url, tags, cover)),
        (".linkedin.txt", linkedin(fm, body, url)),
        (".x.txt", "\n\n---\n\n".join(x_thread(fm, body, url))),
    ):
        p = out_dir / f"{path.stem}{suffix}"
        p.write_text(content, encoding="utf-8")
        written.append(p)

    over = [i for i, part in enumerate(x_thread(fm, body, url), 1) if len(part) > X_LIMIT]
    if over:
        # Loud, not silent. A thread part over the limit is not postable, and
        # discovering that in the compose box is discovering it too late.
        print(f"  WARNING {path.stem}: X part(s) {over} exceed {X_LIMIT} characters")
    return written


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("posts", nargs="*", help="post files; default every post with front matter")
    ap.add_argument("--dir", default="posts")
    ap.add_argument("--out", default="posts/staged")
    ap.add_argument("--cover", default=None, help="cover image url for dev.to")
    a = ap.parse_args(argv)

    targets = [Path(p) for p in a.posts] or [
        p for p in sorted(Path(a.dir).glob("*.md")) if FRONT.match(p.read_text(encoding="utf-8"))]
    if not targets:
        print("no posts found")
        return 0

    for t in targets:
        print(f"{t.name}")
        for p in stage(t, Path(a.out), a.cover):
            print(f"  wrote {p}")
    print(f"\n{len(targets)} post(s) staged into {a.out}")
    print("Nothing was posted. dev.to scheduling is UI only, LinkedIn scheduling is in "
          "the composer, and X has an open evaluation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
