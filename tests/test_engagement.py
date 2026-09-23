"""The owed-thread count, which gates whether a post goes out at all.

Rule 2 of the measured post playbook: a post he cannot work should not go
out, and threads owed a reply are what "cannot work" means. So an inflated
count tells him to hold a post for threads nobody can read.

That is not hypothetical. On 2026-09-23 the index reported six owed and only
two resolved: one crypto recovery scam dev.to had already removed, and three
whose authors were removed or suspended.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import engagement as E  # noqa: E402

ART = "https://dev.to/agentdev9/some-post-1a2b"


def _c(user, body, code, children=None):
    return {"user": {"username": user}, "body_html": body,
            "id_code": code, "children": children or []}


def test_a_thread_someone_else_ended_is_owed(monkeypatch):
    monkeypatch.setattr(E, "resolves", lambda url, timeout=15: True)
    tree = [_c("agentdev9", "my post", "a1", [_c("someone", "a real technical reply here", "b1")])]
    assert len(E.threads_needing_reply(tree, "agentdev9", ART)) == 1


def test_a_thread_he_ended_is_not_owed(monkeypatch):
    monkeypatch.setattr(E, "resolves", lambda url, timeout=15: True)
    tree = [_c("someone", "a question", "a1", [_c("agentdev9", "my answer", "b1")])]
    assert E.threads_needing_reply(tree, "agentdev9", ART) == []


def test_the_leaf_decides_not_the_root(monkeypatch):
    """A thread he started and someone else ended looks, from the root,
    exactly like one he ended himself."""
    monkeypatch.setattr(E, "resolves", lambda url, timeout=15: True)
    tree = [_c("agentdev9", "root", "a1", [
        _c("agentdev9", "mid", "b1", [_c("other", "the last word", "c1")])])]
    owed = E.threads_needing_reply(tree, "agentdev9", ART)
    assert len(owed) == 1 and owed[0]["id_code"] == "c1"


# ── the bug this file exists for ──────────────────────────────────────────

def test_a_thread_whose_permalink_is_dead_is_not_owed(monkeypatch):
    """dev.to's comments index lists threads the site serves 404 for, when an
    author has been removed or suspended. Counting those tells him to hold a
    post for a conversation that no longer exists."""
    monkeypatch.setattr(E, "resolves", lambda url, timeout=15: False)
    tree = [_c("agentdev9", "my post", "a1", [_c("ghost", "a substantive reply", "3bhk7")])]
    assert E.threads_needing_reply(tree, "agentdev9", ART) == []


def test_a_live_thread_still_counts_when_another_is_dead(monkeypatch):
    """The mirror: the liveness filter must not also suppress real threads."""
    monkeypatch.setattr(E, "resolves", lambda url, timeout=15: "live" in url)
    tree = [_c("agentdev9", "p", "dead", [_c("ghost", "gone", "dead")]),
            _c("agentdev9", "p", "live", [_c("real", "still here", "live")])]
    owed = E.threads_needing_reply(tree, "agentdev9", ART)
    assert len(owed) == 1 and owed[0]["id_code"] == "live"


def test_a_recovery_scam_comment_is_not_owed(monkeypatch):
    monkeypatch.setattr(E, "resolves", lambda url, timeout=15: True)
    spam = ("HIRE A HACKER RECOVERY EXPERT. Wizard Hackers Recovery just help me "
            "recover all my lost crypto. WhatsApp: + 1-256-256-8636 TELEGRAM : @x")
    tree = [_c("agentdev9", "my post", "a1", [_c("grace_h", spam, "3c5dc")])]
    assert E.threads_needing_reply(tree, "agentdev9", ART) == []


def test_a_real_comment_mentioning_crypto_is_still_owed(monkeypatch):
    """One marker is a topic. Two is a pitch. A post about crypto evals must
    not be filtered out for saying the word."""
    monkeypatch.setattr(E, "resolves", lambda url, timeout=15: True)
    real = ("I ran your suite against a crypto price oracle and the recovery "
            "expert heuristic you describe did not reproduce for me. Numbers below.")
    tree = [_c("agentdev9", "my post", "a1", [_c("dev", real, "b1")])]
    assert len(E.threads_needing_reply(tree, "agentdev9", ART)) == 1


def test_permalinks_are_built_from_the_article_because_the_api_has_no_url():
    assert E.permalink(ART, "3f7c9") == f"{ART}/comments/3f7c9"
    assert E.permalink("", "3f7c9") == ""
