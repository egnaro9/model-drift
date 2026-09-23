"""The gate between "a run finished" and "there is something to say".

Every test here pins a mistake this board has actually made or narrowly avoided:
publishing an outage as a regression, reporting a move smaller than the
instrument can resolve, logging one event repeatedly because the calendar was
treated as its identity, and claiming stability from silence.
"""
from __future__ import annotations

import json
import re

from modeldrift.draft import render, share_text, slugify
from modeldrift.findings import (ABOUT_INFRA, ABOUT_MODELS, Finding, detect,
                                 dark_providers, harness_alarms, record,
                                 regressions_and_recoveries, unseen)
from modeldrift.report import ModelStatus


def _status(mid, label, latest, delta, verdict, when="2026-09-22",
            graded=35, qualified=True, reliability=1.0):
    return ModelStatus(mid, label, latest, delta, verdict, when, graded,
                       observed_when=when, observed_acc=latest,
                       observed_reliability=reliability, observed_spread=0.0,
                       observed_qualified=qualified)


# ── the resolution floor ──────────────────────────────────────────────────

def test_a_move_smaller_than_the_floor_is_not_a_finding():
    """35 graded calls means the floor is 2.86 pts. A 1-point move cannot be
    a real measurement on this instrument, so it must not reach a draft."""
    s = _status("openai:x", "X", 0.90, -0.01, "regressed", graded=35)
    assert regressions_and_recoveries([s]) == []


def test_a_move_larger_than_the_floor_is_a_finding():
    s = _status("openai:x", "X", 0.80, -0.10, "regressed", graded=35)
    found = regressions_and_recoveries([s])
    assert len(found) == 1 and found[0].kind == "regression"


def test_an_unknown_floor_is_reported_as_unknown_not_as_zero():
    """Rows predating graded_total have no floor. Treating unknown as zero
    would publish an unmeasurable claim as a measured one."""
    s = _status("openai:x", "X", 0.80, -0.10, "regressed", graded=None)
    ev = regressions_and_recoveries([s])[0].evidence
    assert any("UNKNOWN" in row["how"] for row in ev), ev


# ── an outage is not a regression ─────────────────────────────────────────

def test_a_dark_provider_is_filed_as_infrastructure_not_as_a_model_story():
    """2026-09-22: three Gemini models returned 402 on every call. A generator
    that filed this under models would publish a credit card's status."""
    s = _status("google:g", "G", 0.90, None, "baseline",
                qualified=False, reliability=0.0)
    found = dark_providers([s])
    assert len(found) == 1
    assert found[0].about == ABOUT_INFRA
    assert found[0].kind == "provider-dark"


def test_a_dark_provider_never_becomes_a_regression():
    s = _status("google:g", "G", 0.90, -0.30, "regressed",
                qualified=False, reliability=0.0)
    kinds = {f.kind for f in detect({}, [s])}
    assert "regression" not in kinds or ABOUT_MODELS not in {
        f.about for f in detect({}, [s]) if f.kind == "provider-dark"}
    assert "provider-dark" in kinds


def test_the_draft_says_out_loud_that_an_outage_is_not_a_model_story():
    f = dark_providers([_status("google:g", "G", 0.9, None, "baseline",
                                qualified=False, reliability=0.0)])[0]
    body = render(f, [], "2026-09-22", "2026-07-v3")
    assert "not about a model" in body
    assert "Nothing below says a model got worse" in body


# ── the harness accuses itself ────────────────────────────────────────────

def test_one_task_failing_across_providers_accuses_the_probe():
    series = {
        f"{lab}:m": [{"t": "2026-09-22T00:00:00Z", "fails": ["math-order"], "acc": 0.9},
                     {"t": "2026-09-21T00:00:00Z", "fails": [], "acc": 0.9}]
        for lab in ("openai", "anthropic", "google")
    }
    alarms = [f for f in harness_alarms(series) if f.kind == "probe-alarm"]
    assert alarms, "three providers failing one task on one day is a probe alarm"
    assert alarms[0].about == "harness"


def test_a_probe_alarm_outranks_a_regression_in_the_draft_order():
    """If the instrument is suspect, nothing it measured should lead."""
    series = {
        f"{lab}:m": [{"t": "2026-09-22T00:00:00Z", "fails": ["math-order"], "acc": 0.9},
                     {"t": "2026-09-21T00:00:00Z", "fails": [], "acc": 0.9}]
        for lab in ("openai", "anthropic", "google")
    }
    s = _status("xai:x", "X", 0.80, -0.10, "regressed")
    assert detect(series, [s])[0].kind == "probe-alarm"


# ── one event, reported once ──────────────────────────────────────────────

def test_the_same_event_is_not_drafted_twice(tmp_path):
    """A frozen standing re-derives the same comparison every run. Keyed on
    the calendar, one regression was logged 19 times."""
    s = _status("openai:x", "X", 0.80, -0.10, "regressed")
    first = regressions_and_recoveries([s])
    ledger = str(tmp_path / "seen.json")
    assert unseen(first, ledger) == first
    record(first, ledger)
    again = regressions_and_recoveries([s])
    assert unseen(again, ledger) == [], "same runs compared, so not a new event"


def test_a_genuinely_new_run_is_still_drafted(tmp_path):
    """The mirror of the test above: dedupe must not also suppress real news."""
    ledger = str(tmp_path / "seen.json")
    old = _status("openai:x", "X", 0.80, -0.10, "regressed", when="2026-09-22")
    record(regressions_and_recoveries([old]), ledger)
    new = _status("openai:x", "X", 0.70, -0.10, "regressed", when="2026-09-29")
    assert len(unseen(regressions_and_recoveries([new]), ledger)) == 1


def test_the_ledger_survives_a_corrupt_file(tmp_path):
    ledger = tmp_path / "seen.json"
    ledger.write_text("{not json", encoding="utf-8")
    s = _status("openai:x", "X", 0.80, -0.10, "regressed")
    found = regressions_and_recoveries([s])
    assert unseen(found, str(ledger)) == found
    record(found, str(ledger))
    assert json.loads(ledger.read_text())


# ── silence is not stability ──────────────────────────────────────────────

def test_stayed_green_never_counts_a_model_that_did_not_report():
    """A dark model did not hold steady. It said nothing."""
    moved = _status("openai:x", "X", 0.80, -0.10, "regressed")
    dark = _status("google:g", "G", 0.90, 0.0, "unchanged",
                   qualified=False, reliability=0.0)
    f = regressions_and_recoveries([moved])[0]
    body = render(f, [moved, dark], "2026-09-22", "2026-07-v3")
    assert "G" not in body.split("What stayed green anyway")[1].split("##")[0]
    assert "no stable cohort" in body


def test_stayed_green_names_the_models_that_actually_held():
    moved = _status("openai:x", "X", 0.80, -0.10, "regressed")
    held = _status("anthropic:a", "Claude A", 0.90, 0.0, "unchanged")
    f = regressions_and_recoveries([moved])[0]
    section = render(f, [moved, held], "2026-09-22", "2026-07-v3")
    section = section.split("What stayed green anyway")[1]
    assert "Claude A" in section


# ── the artifact itself ───────────────────────────────────────────────────

def test_the_draft_is_marked_draft_and_points_at_erikhill_dev():
    f = regressions_and_recoveries([_status("openai:x", "X", 0.8, -0.1, "regressed")])[0]
    body = render(f, [], "2026-09-22", "2026-07-v3")
    assert "status: draft" in body
    assert "destination: https://erikhill.dev/notes/2026-09-22-" in body


def test_every_evidence_row_is_rendered():
    f = regressions_and_recoveries([_status("openai:x", "X", 0.8, -0.1, "regressed")])[0]
    body = render(f, [], "2026-09-22", "2026-07-v3")
    for row in f.evidence:
        assert row["claim"] in body, row


def test_the_share_text_carries_the_infrastructure_caveat():
    """The link share is the part most likely to be read alone."""
    f = dark_providers([_status("google:g", "G", 0.9, None, "baseline",
                                qualified=False, reliability=0.0)])[0]
    assert "not a model story" in share_text(f, "https://erikhill.dev/notes/x/")


def test_slugify_is_url_safe():
    assert slugify("Gemini 3.1 Pro -17.2 pts to 74.3%") == "gemini-3-1-pro-17-2-pts-to-74-3"


REGISTRY = [
    {"id": "mock:stable", "label": "Mock (stable)", "tier": "mock"},
    {"id": "openai:x", "label": "X", "tier": "flagship"},
    {"id": "anthropic:a", "label": "Claude A", "tier": "mid"},
]


def test_the_mock_fixture_is_never_named_as_a_model_that_stayed_green():
    """The control exists to prove the pipeline works. Naming it in a post
    reports a fixture as a model, which narrative.py already refuses to do."""
    moved = _status("openai:x", "X", 0.80, -0.10, "regressed")
    mock = _status("mock:stable", "Mock (stable)", 1.0, 0.0, "unchanged")
    held = _status("anthropic:a", "Claude A", 0.90, 0.0, "unchanged")
    body = render(f_reg(moved), [moved, mock, held], "2026-09-22", "v", REGISTRY)
    green = body.split("What stayed green anyway")[1].split("##")[0]
    assert "Mock" not in green, green
    assert "Claude A" in green


def test_a_harness_finding_does_not_claim_a_model_moved():
    """Nothing moved in a probe alarm. The stable-cohort sentence must not
    talk about 'the one that moved' when the subject is the instrument."""
    held = _status("anthropic:a", "Claude A", 0.90, 0.0, "unchanged")
    f = Finding(kind="probe-alarm", about="harness", subject="t1",
                headline="Task t1 fails across providers", run_key=["t1"])
    green = render(f, [held], "2026-09-22", "v", REGISTRY)
    green = green.split("What stayed green anyway")[1].split("##")[0]
    assert "the one that moved" not in green, green


def test_the_slug_does_not_cut_a_word_in_half():
    """The real one read '...at-once-on-17-se'. Assert the property, not one
    unlucky string: every segment of the slug must be a whole source word."""
    text = ("Task constraint-no-e fails across providers at once, on 17 "
            "separate day(s) and counting")
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    slug = slugify(text)
    assert len(slug) <= 60
    assert all(part in words for part in slug.split("-")), slug


def f_reg(status):
    return regressions_and_recoveries([status])[0]


# ── the post playbook, which is measured rather than stylistic ────────────

def test_a_draft_opens_with_an_incident_and_a_number_not_a_maxim():
    """Playbook rule 7, from Erik's own dev.to data: the breakout post opened
    with a first-person incident; the zero-comment launches opened with a claim."""
    f = f_reg(_status("openai:x", "X", 0.80, -0.10, "regressed"))
    first = render(f, [], "2026-09-22", "v", REGISTRY).split("## What happened")[1]
    first = first.split("##")[0]
    assert "my drift tracker" in first
    assert "2026-09-22" in first


def test_a_draft_cannot_be_published_without_something_to_argue_with():
    """Rule 1: publish to open a thread, never to announce. The section is
    emitted with a TODO precisely so an unedited draft cannot pass as finished."""
    f = f_reg(_status("openai:x", "X", 0.80, -0.10, "regressed"))
    body = render(f, [], "2026-09-22", "v", REGISTRY)
    assert "## What I might have wrong" in body
    assert "TODO" in body.split("## What I might have wrong")[1]


def test_an_owned_post_closes_with_exactly_one_availability_line():
    """Rule 8, and the half that matters is that it is ONE line, not a plea."""
    f = f_reg(_status("openai:x", "X", 0.80, -0.10, "regressed"))
    body = render(f, [], "2026-09-22", "v", REGISTRY)
    assert body.count("looking for my first full-time role") == 1
    assert "open to opportunities" not in body


def test_the_backlog_worklist_is_not_counted_as_an_unpublished_post(tmp_path):
    """posts/ holds BACKLOG.md, which is a to-do list, not a note waiting to
    go out. It has no front matter, which is what makes it not a post."""
    from modeldrift.publish import build_index, is_post
    (tmp_path / "BACKLOG.md").write_text("# Findings backlog\n\n- [ ] a thing\n")
    (tmp_path / "2026-09-22-real.md").write_text(
        '---\ntitle: "Real"\ndate: 2026-09-22\nstatus: published\n---\n\nBody here.\n')
    assert not is_post(tmp_path / "BACKLOG.md")
    idx = build_index(str(tmp_path))
    assert [p["slug"] for p in idx] == ["2026-09-22-real"]


def test_a_draft_never_reaches_the_published_index(tmp_path):
    from modeldrift.publish import build_index
    (tmp_path / "2026-09-22-draft.md").write_text(
        '---\ntitle: "Draft"\ndate: 2026-09-22\nstatus: draft\n---\n\nBody.\n')
    assert build_index(str(tmp_path)) == []
