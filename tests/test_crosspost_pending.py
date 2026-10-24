"""The catch-up that replaced a red run with a retry.

Each test is either a way it could publish something it should not (a stale
note, two at once, a coin-flip draft, a dead canonical) or a way it could hide
a real failure behind green (a broken site, an unreadable dev.to).
"""
import datetime as dt, sys, pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import crosspost_pending as C

NOW = dt.datetime(2026, 10, 16, 18, 0, tzinfo=dt.timezone.utc)


def today():
    """main() reads the real clock, not NOW. A note dated NOW went STALE on
    2026-10-23, which turned the refusal test red and let the dry-run test pass
    without ever reaching a PUBLISH row."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def note(tmp, slug, status="published", title=None, date="2026-10-14"):
    title = title or f"Title of {slug}"
    (tmp / f"{slug}.md").write_text(
        f'---\ntitle: "{title}"\ndate: {date}\nstatus: {status}\n---\n\n# {title}\n', encoding="utf-8")
    return title


def draft(slug, title, id_=1):
    return {"id": id_, "title": title, "canonical_url": f"https://erikhill.dev/notes/{slug}/"}


def test_a_published_note_with_a_waiting_draft_is_pending(tmp_path):
    t = note(tmp_path, "2026-10-14-a")
    rows = C.pending(str(tmp_path), [draft("2026-10-14-a", t)])
    assert [r["slug"] for r in rows] == ["2026-10-14-a"]


def test_a_draft_note_is_never_pending_even_with_a_devto_draft(tmp_path):
    """Upcoming notes have staged dev.to drafts on purpose. They are not late."""
    t = note(tmp_path, "2026-10-21-b", status="draft", date="2026-10-21")
    assert C.pending(str(tmp_path), [draft("2026-10-21-b", t)]) == []


def test_a_note_already_on_devto_is_not_pending(tmp_path):
    note(tmp_path, "2026-10-14-a")
    assert C.pending(str(tmp_path), []) == []


def test_backlog_without_front_matter_is_ignored(tmp_path):
    (tmp_path / "BACKLOG.md").write_text("# worklist\n", encoding="utf-8")
    assert C.pending(str(tmp_path), [{"title": "BACKLOG", "id": 9}]) == []


def test_two_drafts_with_one_title_is_refused_not_resolved(tmp_path):
    t = note(tmp_path, "2026-10-14-a")
    rows = C.decide(C.pending(str(tmp_path), [draft("2026-10-14-a", t, 1), draft("2026-10-14-a", t, 2)]),
                    NOW, None, lambda s: True)
    assert rows[0]["verdict"] == "REFUSED"


def test_a_canonical_for_another_slug_is_refused(tmp_path):
    t = note(tmp_path, "2026-10-14-a")
    rows = C.decide(C.pending(str(tmp_path), [draft("2026-10-14-OTHER", t)]), NOW, None, lambda s: True)
    assert rows[0]["verdict"] == "REFUSED"


def _rows(tmp_path, *specs):
    drafts = []
    for i, (slug, date) in enumerate(specs):
        drafts.append(draft(slug, note(tmp_path, slug, date=date), i + 1))
    return C.pending(str(tmp_path), drafts)


def test_live_fresh_and_spacing_open_publishes(tmp_path):
    rows = C.decide(_rows(tmp_path, ("2026-10-14-a", "2026-10-14")), NOW,
                    NOW - dt.timedelta(days=6, hours=1), lambda s: True)
    assert rows[0]["verdict"] == "PUBLISH"


def test_page_not_live_inside_grace_waits_and_is_not_red(tmp_path):
    rows = C.decide(_rows(tmp_path, ("2026-10-15-a", "2026-10-15")), NOW, None, lambda s: False)
    assert rows[0]["verdict"] == "WAITING"


def test_page_not_live_past_grace_is_broken(tmp_path):
    """The one case that must stay red: a site that never builds the page."""
    rows = C.decide(_rows(tmp_path, ("2026-10-13-a", "2026-10-13")), NOW, None, lambda s: False)
    assert rows[0]["verdict"] == "BROKEN"


def test_a_stale_note_is_never_auto_posted(tmp_path):
    """2026-10-07 was lost for nine days. Posting it now is Erik's call."""
    rows = C.decide(_rows(tmp_path, ("2026-10-07-a", "2026-10-07")), NOW, None, lambda s: True)
    assert rows[0]["verdict"] == "STALE"


def test_spacing_holds_a_live_fresh_note(tmp_path):
    rows = C.decide(_rows(tmp_path, ("2026-10-14-a", "2026-10-14")), NOW,
                    NOW - dt.timedelta(days=2), lambda s: True)
    assert rows[0]["verdict"] == "HELD"


def test_at_most_one_publish_per_run_oldest_first(tmp_path):
    rows = C.decide(_rows(tmp_path, ("2026-10-15-b", "2026-10-15"), ("2026-10-14-a", "2026-10-14")),
                    NOW, None, lambda s: True)
    assert [(r["slug"], r["verdict"]) for r in rows] == [
        ("2026-10-14-a", "PUBLISH"), ("2026-10-15-b", "HELD")]


def test_an_unparseable_date_can_only_be_reported(tmp_path):
    rows = C.decide(_rows(tmp_path, ("2026-10-14-a", "someday")), NOW, None, lambda s: True)
    assert rows[0]["verdict"] == "STALE"


def test_main_is_red_when_devto_cannot_be_read(tmp_path, monkeypatch):
    """No reading is not a clean reading."""
    def boom(*a, **k):
        raise C.D.Refused("HTTP 503")
    monkeypatch.setattr(C.D, "_call", boom)
    assert C.main(["--posts", str(tmp_path)]) == 1


def test_main_dry_run_publishes_nothing(tmp_path, monkeypatch):
    t = note(tmp_path, "2026-10-14-a", date=today())
    monkeypatch.setattr(C.D, "_call", lambda m, p, *a: [draft("2026-10-14-a", t)] if "unpublished" in p else [])
    monkeypatch.setattr(C, "is_live", lambda s: True)
    called = []
    monkeypatch.setattr(C.D, "main", lambda argv: called.append(argv) or 0)
    assert C.main(["--posts", str(tmp_path), "--dry-run"]) == 0
    assert called == []


def test_main_publishes_through_devto_publish_and_reports_its_refusal(tmp_path, monkeypatch):
    """The publish goes through devto_publish.main so its refusals still apply,
    and a refusal there turns this run red."""
    t = note(tmp_path, "2026-10-14-a", date=today())
    monkeypatch.setattr(C.D, "_call", lambda m, p, *a: [draft("2026-10-14-a", t)] if "unpublished" in p else [])
    monkeypatch.setattr(C, "is_live", lambda s: True)
    calls = []
    monkeypatch.setattr(C.D, "main", lambda argv: calls.append(argv) or 1)
    assert C.main(["--posts", str(tmp_path)]) == 1
    assert calls == [["--slug", "2026-10-14-a", "--posts", str(tmp_path)]]


def test_waiting_and_stale_and_held_do_not_turn_the_run_red(tmp_path, monkeypatch):
    t = note(tmp_path, "2026-10-01-old", date="2026-10-01")
    monkeypatch.setattr(C.D, "_call", lambda m, p, *a: [draft("2026-10-01-old", t)] if "unpublished" in p else [])
    monkeypatch.setattr(C, "is_live", lambda s: True)
    monkeypatch.setattr(C.D, "main", lambda argv: pytest.fail("a stale note must not be posted"))
    assert C.main(["--posts", str(tmp_path)]) == 0


# --- crosspost_on: a date a person chose -----------------------------------

def _sched(tmp_path, slug, date, on):
    t = note(tmp_path, slug, date=date)
    p = tmp_path / f"{slug}.md"
    p.write_text(p.read_text(encoding="utf-8").replace("status: published\n",
                 f"status: published\ncrosspost_on: {on}\n"), encoding="utf-8")
    return C.pending(str(tmp_path), [draft(slug, t)])


def test_scheduled_before_its_date_is_not_posted(tmp_path):
    rows = C.decide(_sched(tmp_path, "2026-10-07-a", "2026-10-07", "2026-10-19"), NOW, None, lambda s: True)
    assert rows[0]["verdict"] == "SCHEDULED"


def test_scheduled_on_its_date_but_before_9am_eastern_waits(tmp_path):
    """Midnight UTC is 8pm the evening before in Eastern time."""
    early = dt.datetime(2026, 10, 19, 12, 59, tzinfo=dt.timezone.utc)  # 8:59am EDT
    rows = C.decide(_sched(tmp_path, "2026-10-07-a", "2026-10-07", "2026-10-19"), early, None, lambda s: True)
    assert rows[0]["verdict"] == "SCHEDULED"


def test_scheduled_and_due_publishes_even_if_stale_and_spacing_is_closed(tmp_path):
    due = dt.datetime(2026, 10, 19, 13, 0, tzinfo=dt.timezone.utc)  # 9:00am EDT
    rows = C.decide(_sched(tmp_path, "2026-10-07-a", "2026-10-07", "2026-10-19"), due,
                    due - dt.timedelta(days=2), lambda s: True)
    assert rows[0]["verdict"] == "PUBLISH"


def test_scheduled_and_due_still_needs_a_live_page(tmp_path):
    due = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)
    rows = C.decide(_sched(tmp_path, "2026-10-07-a", "2026-10-07", "2026-10-19"), due, None, lambda s: False)
    assert rows[0]["verdict"] == "BROKEN"


def test_a_crosspost_on_that_is_not_a_date_is_refused(tmp_path):
    rows = C.decide(_sched(tmp_path, "2026-10-07-a", "2026-10-07", "Monday"), NOW, None, lambda s: True)
    assert rows[0]["verdict"] == "REFUSED"


def test_scheduled_still_means_one_publish_per_run(tmp_path):
    due = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)
    rows = _sched(tmp_path, "2026-10-07-a", "2026-10-07", "2026-10-19")
    t = note(tmp_path, "2026-10-18-b", date="2026-10-18")
    rows = C.decide(C.pending(str(tmp_path), [rows[0]["drafts"][0], draft("2026-10-18-b", t, 2)]),
                    due, None, lambda s: True)
    assert [(r["slug"], r["verdict"]) for r in rows] == [("2026-10-07-a", "PUBLISH"), ("2026-10-18-b", "HELD")]


def test_two_scheduled_notes_due_together_still_publish_one(tmp_path):
    """The schedule waives freshness and spacing, not the one-per-run limit."""
    due = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)
    a = _sched(tmp_path, "2026-10-07-a", "2026-10-07", "2026-10-19")[0]["drafts"][0]
    b = _sched(tmp_path, "2026-10-08-b", "2026-10-08", "2026-10-19")
    rows = C.decide(C.pending(str(tmp_path), [a, b[-1]["drafts"][0]]), due, None, lambda s: True)
    assert [(r["slug"], r["verdict"]) for r in rows] == [("2026-10-07-a", "PUBLISH"), ("2026-10-08-b", "HELD")]
