"""How long a check has been saying the same thing.

The number that matters is not the colour, it is the streak. A permanent true
alert and a new one look identical in an inbox.

Note what this does NOT cover, measured on the case that prompted it:
model-drift's agreement check spent 2026-08-30 to 2026-09-23 SKIPPING, because
the store it queried had been retired and an unreachable store is not a
disagreeing one. 57 CI runs passed while it compared nothing. This tool reads
workflow conclusions, and a skipping test is green, so it would not have caught
that. It answers "how long has this been red"; that case needed "how long has
this been reporting on nothing".
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import streaks as S  # noqa: E402


def _run(conclusion, days_ago, sha="abc1234"):
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {"conclusion": conclusion, "status": "completed",
            "createdAt": when.replace("+00:00", "Z"), "headSha": sha, "databaseId": 1}


def _streak_of(runs, monkeypatch):
    monkeypatch.setattr(S, "_gh", lambda args: (runs, ""))
    return S.streak("owner/repo", "ci.yml")


def test_a_single_red_is_new_not_accepted(monkeypatch):
    s = _streak_of([_run("failure", 0), _run("success", 1)], monkeypatch)
    assert s["streak_runs"] == 1 and S.verdict(s) == "NEW RED"


def test_a_long_red_run_is_accepted_not_new(monkeypatch):
    """The 24-day case. Same colour, categorically different meaning."""
    s = _streak_of([_run("failure", d) for d in range(24)], monkeypatch)
    assert s["streak_runs"] == 24
    assert s["streak_days"] >= S.STALE_RED_DAYS
    assert S.verdict(s) == "ACCEPTED RED"


def test_a_few_reds_over_many_days_still_counts_as_accepted(monkeypatch):
    """A weekly job red three times is three weeks of red. Counting runs alone
    would call that new, because the RUN count is small."""
    s = _streak_of([_run("failure", 0), _run("failure", 7), _run("failure", 14),
                    _run("success", 21)], monkeypatch)
    assert s["streak_runs"] == 3 and s["streak_runs"] < S.STALE_RED_RUNS
    assert S.verdict(s) == "ACCEPTED RED", "three weeks of red is not news"


def test_green_is_green(monkeypatch):
    s = _streak_of([_run("success", 0), _run("failure", 1)], monkeypatch)
    assert S.verdict(s) == "GREEN"


def test_an_in_progress_run_does_not_reset_the_streak(monkeypatch):
    """A running job has no conclusion. Counting its absence as a change would
    reset the streak every morning while the job was still going."""
    running = {"conclusion": None, "status": "in_progress",
               "createdAt": datetime.now(timezone.utc).isoformat(), "headSha": "x", "databaseId": 9}
    s = _streak_of([running] + [_run("failure", d) for d in range(1, 9)], monkeypatch)
    assert s["conclusion"] == "failure" and s["streak_runs"] == 8


def test_the_streak_reports_when_it_hit_the_window_edge(monkeypatch):
    """If every run we looked at is the same, the real streak may be longer.
    Saying so is the difference between a measurement and a floor."""
    s = _streak_of([_run("failure", d) for d in range(5)], monkeypatch)
    assert s["exhausted"] is True


def test_a_streak_that_ends_inside_the_window_is_not_exhausted(monkeypatch):
    s = _streak_of([_run("failure", 0), _run("success", 1)], monkeypatch)
    assert s["exhausted"] is False


def test_no_completed_runs_is_not_an_error(monkeypatch):
    """A scheduled job that has not fired yet is a fact, not a failure."""
    monkeypatch.setattr(S, "_gh", lambda args: ([], ""))
    s = S.streak("owner/repo", "notes.yml")
    assert s["runs"] == 0 and S.verdict(s) == "UNKNOWN" or s.get("note")
