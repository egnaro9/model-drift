"""Nothing edits the board except the run that produced it.

This replaces an invariant that used to live in a second store. run.py posted
every probe to a hosted eval-history service AND wrote the same numbers into
dashboard/drift_board.json, and a test compared them. The idea was that if two
stores disagree, one is lying.

It was never really a cross-check. Both stores were written by the same process
from the same in-memory values in the same run, so they could only disagree if
something altered one afterwards. That is a tamper check wearing the costume of
an independence check.

And the hosted half died. Its host was retired in August 2026, the archive
froze, and the comparison could no longer run at all. CI was red for 24
consecutive days on a test that could not pass, and the same fact had left a
present-tense sentence on the portfolio saying the service was live.

Git answers the real question for free: has the board been altered outside the
run that produced it? Every change is a commit with an author and a message. No
hosting, no write key, no uptime, and it works offline.

A deliberate human edit is allowed and has happened once, for a schema change.
It just has to say so.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BOARD = "dashboard/drift_board.json"

# The probe's own commit, written by track.yml.
PROBE_SUBJECT = "chore: update drift standings"

# A human editing the board on purpose says so in the subject. The one
# historical case, a schema change publishing the floor and the qualifying
# standing, already used this prefix.
HUMAN_PREFIX = "board:"


def strays_in(entries: list[tuple[str, str, str]]) -> list[str]:
    """Which (sha, author, subject) rows are neither the probe nor declared.

    Split out from the live-history check on purpose.

    That check is a MONITOR: it watches real history and can only go red when
    reality goes wrong. On a clean repository no assertion it makes can fire,
    so mutating it away changes nothing and mutation testing reports a false
    alarm. The logic is what has to be proven, and this function can be fed a
    stray directly, which history cannot be.
    """
    out = []
    for sha, author, subject in entries:
        if subject.startswith(PROBE_SUBJECT) or subject.startswith(HUMAN_PREFIX):
            continue
        out.append(f"{sha[:8]} by {author}: {subject[:70]}")
    return out


def _log(*args: str) -> list[str]:
    p = subprocess.run(["git", "-C", str(ROOT), *args],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        pytest.skip(f"git unavailable: {p.stderr.strip()[:80]}")
    return [l for l in p.stdout.splitlines() if l.strip()]


def test_every_board_commit_is_the_probe_or_says_it_is_not():
    """An unexplained board edit is the thing this file exists to catch.

    Not because a human may not edit it, but because an edit that does not
    announce itself is indistinguishable from the probe's own output, and the
    board is what every published figure is derived from.
    """
    subjects = _log("log", "--format=%H%x09%an%x09%s", "--", BOARD)
    assert subjects, "no history for the board; this check did not actually run"

    strays = strays_in([tuple(l.split("\t", 2)) for l in subjects])
    assert not strays, (
        "board commits that are neither the probe nor a declared human edit:\n  "
        + "\n  ".join(strays)
        + f"\n\nThe probe writes '{PROBE_SUBJECT}'. A deliberate edit starts with "
          f"'{HUMAN_PREFIX}' and explains itself in the body.")


def test_the_probe_is_still_the_main_author_of_the_board():
    """A drifting ratio is the early signal. If hand edits start outnumbering
    probe runs, the board has quietly become a document rather than a record,
    and no single commit would have looked wrong."""
    lines = _log("log", "--format=%s", "--", BOARD)
    probe = sum(1 for s in lines if s.startswith(PROBE_SUBJECT))
    human = sum(1 for s in lines if s.startswith(HUMAN_PREFIX))
    assert probe > human, (
        f"{human} declared human edit(s) against {probe} probe commit(s); "
        "the board is supposed to be mostly measured, not mostly written")


def test_the_check_can_see_the_file_it_guards():
    """The mirror of every vacuous-pass bug in this repo: if the path is wrong,
    the log is empty and both tests above pass having checked nothing."""
    assert (ROOT / BOARD).is_file(), f"{BOARD} is not where this test thinks it is"
    assert _log("log", "--oneline", "-1", "--", BOARD), "no commits found for the board path"


# ── the logic itself, on input a clean repository cannot produce ──────────

def test_an_undeclared_edit_is_a_stray():
    """The case the live history does not contain, which is why this exists."""
    rows = [("deadbeefcafe", "someone", "fix: tweak a number on the board")]
    assert strays_in(rows) == ["deadbeef by someone: fix: tweak a number on the board"]


def test_the_probe_is_not_a_stray():
    rows = [("aaaaaaaa1111", "github-actions[bot]", PROBE_SUBJECT + " [skip ci]")]
    assert strays_in(rows) == []


def test_a_declared_human_edit_is_not_a_stray():
    rows = [("bbbbbbbb2222", "egnaro9", "board: publish the floor and the qualifying standing")]
    assert strays_in(rows) == []


def test_a_stray_is_found_among_legitimate_commits():
    """One bad row in a pile of good ones is the realistic shape."""
    rows = [("aaaa1111", "github-actions[bot]", PROBE_SUBJECT),
            ("bbbb2222", "egnaro9", "board: a declared schema change"),
            ("cccc3333", "egnaro9", "chore: quick fix"),
            ("dddd4444", "github-actions[bot]", PROBE_SUBJECT)]
    found = strays_in(rows)
    assert len(found) == 1 and "cccc3333" in found[0]


def test_a_subject_that_merely_mentions_the_probe_is_still_a_stray():
    """startswith, not 'in'. A commit describing the probe is not the probe."""
    rows = [("eeee5555", "egnaro9", f"revert the {PROBE_SUBJECT} commit")]
    assert len(strays_in(rows)) == 1
