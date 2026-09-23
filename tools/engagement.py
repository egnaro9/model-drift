"""What people actually said, so a follow-up post can quote instead of invent.

The strongest post in the record was not the one with the most reach. It was
the one with 68 comments on 510 views, where the author wrote 47 percent of the
thread himself. The thread was the product. So the natural material for a
follow-up is the thread, not a restatement of the post that started it.

This reads dev.to, where comments are public and the API is readable without a
key. It does not read LinkedIn, which has no API for this, and it does not
guess: every line it emits is a real comment with a real permalink, or it says
it found nothing.

Nothing here posts. It produces a scaffold a human fills in, because "what I
changed because of what you said" is the one sentence in a follow-up that
cannot be generated.
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

API = "https://dev.to/api"
UA = {"User-Agent": "drift-notes-engagement/1.0"}


def _get(url: str, timeout: int = 30) -> Tuple[Optional[Any], str]:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), ""
    except urllib.error.HTTPError as e:
        # The server answered. A 404 here means the article or thread is gone,
        # which is a different fact from "no comments" and must not be folded
        # into it.
        return None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def articles(username: str, per_page: int = 30) -> Tuple[List[dict], str]:
    data, err = _get(f"{API}/articles?username={username}&per_page={per_page}")
    return (data or []), err


def comments(article_id: int) -> Tuple[List[dict], str]:
    data, err = _get(f"{API}/comments?a_id={article_id}")
    return (data or []), err


def _walk(node: dict, depth: int = 0):
    """Yield (comment, depth, is_leaf). Threads nest; the top-level author
    tells you nothing about who spoke last."""
    kids = node.get("children") or []
    yield node, depth, not kids
    for k in kids:
        yield from _walk(k, depth + 1)


def _user(c: dict) -> str:
    return ((c.get("user") or {}).get("username") or "?").lower()


def _strip(html: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return " ".join(text.split())


def threads_needing_reply(tree: List[dict], me: str) -> List[dict]:
    """A thread needs a reply when the DEEPEST-LAST speaker is not the author.

    Walking to the leaf matters: a thread the author started and someone else
    ended looks, from the root, exactly like one he ended himself.
    """
    out = []
    for root in tree:
        nodes = list(_walk(root))
        leaves = [n for n, _, leaf in nodes if leaf]
        last = leaves[-1] if leaves else root
        if _user(last) != me:
            out.append(last)
    return out


def permalink(article_url: str, id_code: str) -> str:
    """dev.to comments carry no url field; the link is the article plus the code."""
    return f"{article_url.rstrip('/')}/comments/{id_code}" if article_url and id_code else ""


def resolves(url: str, timeout: int = 15) -> bool:
    """Whether the permalink actually renders.

    The comments index goes stale: it has listed 70 comments while the site
    rendered 66 and served 404 for three permalinks whose authors had been
    removed. Quoting a comment nobody can open is quoting nothing, so each
    link is checked before it is printed.
    """
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def notable(tree: List[dict], me: str, limit: int = 8,
            article_url: str = "") -> List[dict]:
    """Other people's substantive comments, longest first.

    Length is a crude proxy for substance and it is an honest one: a person who
    wrote four sentences engaged with the argument, and a person who wrote
    "nice post" did not. It is not a ranking of quality and is not presented as
    one.
    """
    flat = []
    for root in tree:
        for n, _, _ in _walk(root):
            if _user(n) == me:
                continue
            body = _strip(n.get("body_html", ""))
            if len(body) < 80:
                continue
            flat.append({"user": _user(n), "body": body,
                         "url": permalink(article_url, n.get("id_code", "")),
                         "id": n.get("id_code")})
    flat.sort(key=lambda c: len(c["body"]), reverse=True)
    return flat[:limit]


def report(username: str, article_limit: int = 5) -> Dict[str, Any]:
    arts, err = articles(username)
    if err:
        return {"error": f"could not list articles: {err}"}
    out: Dict[str, Any] = {"username": username, "articles": [], "problems": []}
    for a in arts[:article_limit]:
        tree, cerr = comments(a["id"])
        if cerr:
            out["problems"].append(f"{a['title'][:40]}: comments {cerr}")
            continue
        owed = threads_needing_reply(tree, username.lower())
        out["articles"].append({
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "reactions": a.get("public_reactions_count"),
            "comments": a.get("comments_count"),
            "threads_owed_a_reply": len(owed),
            "notable": notable(tree, username.lower(), article_url=a.get("url", "")),
        })
    return out


def scaffold(rep: Dict[str, Any]) -> str:
    """The follow-up post, with the quotes filled and the judgement left open."""
    lines = ["# Midweek follow-up scaffold", ""]
    owed = sum(a["threads_owed_a_reply"] for a in rep.get("articles", []))
    if owed:
        lines += [f"**{owed} thread(s) are waiting on a reply from you.** Rule 2 of the "
                  "playbook: the thread is the product, and a post you cannot work "
                  "should not go out. Answer these before posting anything new.", ""]
    said = [c for a in rep.get("articles", []) for c in a["notable"]]
    if not said:
        lines += ["No substantive comments found on the last few articles, so there is "
                  "nothing to quote. A follow-up built on invented pushback is worse "
                  "than no follow-up.", ""]
    else:
        voices = {c["user"] for c in said}
        lines += ["## What people actually said", ""]
        if len(voices) == 1:
            # One person is a correspondent, not a consensus. A follow-up that
            # says "people pushed back" off a single commenter overstates it.
            lines += [f"**All of the substantive comments below are from one person, "
                      f"@{next(iter(voices))}.** That is a correspondent, not a "
                      "consensus, and the follow-up should say so.", ""]
        for c in said[:5]:
            live = resolves(c["url"]) if c["url"] else False
            mark = c["url"] if live else f"{c['url']} (DOES NOT RESOLVE, do not cite)"
            lines += [f"**@{c['user']}**  {mark}", f"> {c['body'][:420]}", ""]
        lines += ["## The one line you have to write yourself", "",
                  "What did you CHANGE because of the above? Name the commit, the "
                  "number that moved, or say plainly that you disagreed and why. "
                  "A follow-up that thanks people and changes nothing is an "
                  "acknowledgement, not a finding.", ""]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user", default="agentdev9")
    ap.add_argument("--articles", type=int, default=5)
    ap.add_argument("--out", default=None, help="write the scaffold here")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    rep = report(a.user, a.articles)
    if "error" in rep:
        print(f"  {rep['error']}")
        return 0
    if a.json:
        print(json.dumps(rep, indent=1))
        return 0

    for art in rep["articles"]:
        print(f"  {art['reactions']:>4} reactions  {art['comments']:>3} comments  "
              f"{art['threads_owed_a_reply']} owed  {art['title'][:52]}")
    for p in rep["problems"]:
        print(f"  PROBLEM: {p}")

    text = scaffold(rep)
    if a.out:
        from pathlib import Path
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"\n  wrote {a.out}")
    else:
        print("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
