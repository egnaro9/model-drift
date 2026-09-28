"""Tests for the cadence-test reader.

Each one is written against a way this could lose or corrupt a reading, because
losing a reading is the failure that has no remedy: dev.to will not tell you what
a post's view count was yesterday.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.cadence_read import (ARMS, MIN_GAP_MINUTES, WINDOW_DAYS, Refused,
                                collect, elapsed_hours, last_reading, load,
                                match_article, parse_iso, should_record)

A_SLUG = ARMS["A"]
B_SLUG = ARMS["B"]
PUB = "2026-09-30T12:34:00Z"


def art(slug: str, *, title: str = "whatever", views: int = 1,
        published_at: str = PUB, reactions: int = 0, comments: int = 0) -> dict:
    return {"title": title,
            "canonical_url": f"https://erikhill.dev/notes/{slug}/",
            "published_at": published_at,
            "page_views_count": views,
            "public_reactions_count": reactions,
            "comments_count": comments}


def at(hours_after_pub: float) -> datetime:
    return parse_iso(PUB) + timedelta(hours=hours_after_pub)


# ---- parsing and arithmetic ----

def test_parse_iso_accepts_devtos_z_suffix():
    assert parse_iso("2026-09-30T12:34:00Z").tzinfo is not None


def test_parse_iso_assumes_utc_when_offset_is_absent():
    assert parse_iso("2026-09-30T12:34:00").tzinfo == timezone.utc


def test_elapsed_hours_measures_from_published_at():
    assert elapsed_hours(PUB, at(48)) == 48.0
    assert elapsed_hours(PUB, at(46.5)) == 46.5


# ---- identity: the wrong article must never be measured ----

def test_match_is_on_canonical_not_title():
    """A retitled post must still be found, and a same-titled one must not match."""
    arts = [art(A_SLUG, title="something Erik renamed it to"),
            art("2026-01-01-unrelated", title="whatever")]
    assert match_article(arts, A_SLUG)["canonical_url"].endswith(f"{A_SLUG}/")


def test_match_tolerates_missing_trailing_slash():
    a = art(A_SLUG)
    a["canonical_url"] = f"https://erikhill.dev/notes/{A_SLUG}"
    assert match_article([a], A_SLUG) is not None


def test_match_returns_none_when_the_post_is_not_published_yet():
    assert match_article([art(B_SLUG)], A_SLUG) is None


def test_match_refuses_rather_than_picking_the_first_of_two():
    """Two canonicals for one slug is ambiguous; a silently wrong number is worse
    than none, because a wrong number still looks like data."""
    with pytest.raises(Refused):
        match_article([art(A_SLUG, views=10), art(A_SLUG, views=999)], A_SLUG)


def test_match_ignores_articles_with_no_canonical():
    assert match_article([{"title": "x", "published_at": PUB}], A_SLUG) is None


# ---- sampling policy ----

def test_first_reading_is_always_recorded():
    assert should_record([], "A", 0.5, at(0.5)) is True


def test_a_second_reading_inside_the_gap_is_refused():
    prev = [{"arm": "A", "t": at(48).isoformat().replace("+00:00", "Z")}]
    just_after = at(48 + (MIN_GAP_MINUTES - 5) / 60.0)
    assert should_record(prev, "A", 48.5, just_after) is False


def test_a_reading_after_the_gap_is_recorded():
    prev = [{"arm": "A", "t": at(48).isoformat().replace("+00:00", "Z")}]
    later = at(48 + (MIN_GAP_MINUTES + 5) / 60.0)
    assert should_record(prev, "A", 49.0, later) is True


def test_the_gap_is_per_arm_not_global():
    """B's first reading must not be suppressed by A having just been read."""
    prev = [{"arm": "A", "t": at(48).isoformat().replace("+00:00", "Z")}]
    assert should_record(prev, "B", 0.2, at(48.1)) is True


def test_readings_stop_once_the_window_closes():
    assert should_record([], "A", WINDOW_DAYS * 24 + 1, at(WINDOW_DAYS * 24 + 1)) is False


def test_negative_elapsed_is_refused():
    """A clock skew or a future published_at must not write a nonsense reading."""
    assert should_record([], "A", -3.0, at(-3)) is False


def test_last_reading_picks_the_newest_not_the_last_appended():
    out_of_order = [
        {"arm": "A", "t": "2026-10-02T18:00:00Z"},
        {"arm": "A", "t": "2026-10-02T09:00:00Z"},
    ]
    assert last_reading(out_of_order, "A")["t"] == "2026-10-02T18:00:00Z"


# ---- collect ----

def test_collect_records_both_arms_when_both_are_live():
    arts = [art(A_SLUG, views=100), art(B_SLUG, views=7, published_at="2026-10-02T12:34:00Z")]
    got = collect(arts, [], at(48))
    assert sorted(r["arm"] for r in got) == ["A", "B"]


def test_collect_carries_the_actual_elapsed_not_an_assumed_48():
    got = collect([art(A_SLUG)], [], at(46.25))
    assert got[0]["elapsed_h"] == 46.25


def test_collect_does_not_emit_two_readings_for_one_arm_in_one_run():
    """Guards the bug where the in-progress batch is not considered."""
    arts = [art(A_SLUG), art(A_SLUG.replace("grader", "grader"))]
    got = collect([arts[0]], [], at(48))
    assert len([r for r in got if r["arm"] == "A"]) == 1


def test_collect_is_idempotent_across_back_to_back_runs():
    arts = [art(A_SLUG, views=100)]
    first = collect(arts, [], at(48))
    second = collect(arts, first, at(48))
    assert first and second == []


def test_collect_skips_an_arm_whose_post_has_not_published():
    got = collect([art(A_SLUG)], [], at(48))
    assert [r["arm"] for r in got] == ["A"]


def test_collect_records_the_view_count_it_was_given():
    got = collect([art(A_SLUG, views=137, reactions=4, comments=2)], [], at(48))
    assert (got[0]["views"], got[0]["reactions"], got[0]["comments"]) == (137, 4, 2)


def test_collect_never_mutates_existing_readings():
    existing = [{"arm": "A", "t": "2026-10-01T00:00:00Z", "views": 1}]
    snapshot = json.dumps(existing, sort_keys=True)
    collect([art(B_SLUG, published_at="2026-10-02T12:34:00Z")], existing, at(60))
    assert json.dumps(existing, sort_keys=True) == snapshot


# ---- the file ----

def test_load_seeds_a_document_that_names_its_pre_registration(tmp_path: Path):
    doc = load(tmp_path / "missing.json")
    assert doc["readings"] == []
    assert "POSTING_AB_LOG" in doc["pre_registration"]
    assert set(doc["arms"]) == {"A", "B"}


def test_load_round_trips_existing_readings(tmp_path: Path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"readings": [{"arm": "A", "t": "2026-10-02T00:00:00Z"}]}))
    assert len(load(p)["readings"]) == 1
