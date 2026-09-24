"""Guards on the only code path that can make an article public.

Each test is a way this could publish the wrong thing, or publish a right thing
with a broken canonical. Both are unrecoverable in the way that matters: they
are live under Erik's name before anyone notices.
"""
import sys, pathlib, pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import devto_publish as D

SLUG = "2026-10-28-the-clone-is-part-of-the-check"


def test_reads_the_title_from_front_matter():
    assert D.title_of(SLUG).startswith("A shallow clone does not fail")


def test_refuses_a_slug_with_no_post():
    with pytest.raises(Exception):
        D.title_of("no-such-post-exists")


def test_refuses_when_no_draft_matches(monkeypatch):
    monkeypatch.setattr(D, "_call", lambda *a, **k: [{"title": "something else"}])
    with pytest.raises(D.Refused, match="found 0"):
        D.find_draft("A title that is not there")


def test_refuses_when_TWO_drafts_match(monkeypatch):
    """The dangerous case. Picking the first would publish a coin flip."""
    monkeypatch.setattr(D, "_call", lambda *a, **k: [{"title": "Same", "id": 1},
                                                     {"title": "Same", "id": 2}])
    with pytest.raises(D.Refused, match="found 2"):
        D.find_draft("Same")


def test_accepts_exactly_one(monkeypatch):
    monkeypatch.setattr(D, "_call", lambda *a, **k: [{"title": "Same", "id": 7},
                                                     {"title": "Other", "id": 8}])
    assert D.find_draft("Same")["id"] == 7


def test_title_match_is_exact_not_substring(monkeypatch):
    """A near title is a different article."""
    monkeypatch.setattr(D, "_call", lambda *a, **k: [{"title": "Same but longer", "id": 1}])
    with pytest.raises(D.Refused):
        D.find_draft("Same")


def test_confirm_published_reads_the_platform_not_the_response(monkeypatch):
    """The PUT returns published: null, so success has to come from the listings."""
    calls = {"n": 0}
    def fake(method, path, payload=None):
        calls["n"] += 1
        return [] if "unpublished" in path else [{"id": 42}]
    monkeypatch.setattr(D, "_call", fake)
    assert D.confirm_published(42) is True
    assert calls["n"] == 2, "must check BOTH listings, not just one"


def test_confirm_published_is_false_while_still_in_drafts(monkeypatch):
    monkeypatch.setattr(D, "_call", lambda m, p, payload=None:
                        [{"id": 42}] if "unpublished" in p else [])
    assert D.confirm_published(42) is False


def test_devto_push_still_cannot_publish():
    """The staging tool must stay incapable of sending. If this goes red,
    the separation this file depends on has been removed."""
    src = (pathlib.Path(__file__).resolve().parent.parent / "tools" / "devto_push.py").read_text()
    assert '"published": False' in src
    assert '"published": True' not in src
