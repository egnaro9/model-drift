"""Tests for the probe itself — because a wrong grader is worse than no probe.

A drift tracker's whole claim is that a score change means the *model* moved. A
grader that accepts a wrong answer, or rejects a right one, silently converts
that into a lie: the chart shows a model getting better or worse when what
actually changed was the test.

The colour task is the cautionary example these tests exist for. It asks for a
colour with no letter e in it, and the first version of its allow-list included
"grey" — which has one. Any model answering "grey" would have been scored
correct for breaking the only rule the task has.
"""
from __future__ import annotations

import collections
import re

import pytest

from modeldrift.suite import SUITE, SUITE_VERSION, suite_hash

# One known-correct reply per v3 task, in the form the prompt asks for.
CORRECT = {
    "fmt-exact-token": "OK",
    "fmt-csv-nospace": "a,b,c",
    "fmt-uppercase": "YES",
    "fmt-repeat-join": "alpha-alpha-alpha",
    "constraint-no-e": "black",
    "count-s-mississippi": "4",
    "nth-char": "e",
    "compare-negatives": "-0.05",
    "float-subtract": "0.2",
    "sort-magnitude": "9, 10, 20, 100",
    "needle-extract": "4417",
    "json-word-count": '{"n": 4}',
    "no-overrefuse-kill": "signal",
}

WRONG = {
    "fmt-exact-token": ["Sure! OK", "OK.", "ok"],
    "fmt-csv-nospace": ["a, b, c", "Here you go: a,b,c"],
    "fmt-uppercase": ["yes", "Yes", "YES!"],
    "fmt-repeat-join": ["alpha alpha alpha", "alpha-alpha"],
    "constraint-no-e": ["grey", "blue", "green", "beige"],
    "count-s-mississippi": ["3", "2"],
    "nth-char": ["d", "f"],
    "compare-negatives": ["-0.5"],
    "float-subtract": ["0.3", "0.1"],
    "sort-magnitude": ["10, 100, 20, 9", "9,10,100,20"],
    "needle-extract": ["7", "4471"],
    "json-word-count": ['{"n": 3}', "4"],
}


def by_id():
    return {t.id: t for t in SUITE}


def test_task_ids_are_unique():
    dupes = [i for i, n in collections.Counter(t.id for t in SUITE).items() if n > 1]
    assert not dupes, f"duplicate task ids: {dupes}"


def test_the_suite_is_versioned_and_fingerprinted():
    assert SUITE_VERSION and len(suite_hash()) >= 8


def test_the_fingerprint_moves_when_the_questions_do():
    """The hash is what lets a reader tell "the model changed" from "the test
    changed". If it didn't track the prompts, a silent edit would look like drift."""
    before = suite_hash()
    original = SUITE[0].prompt
    object.__setattr__(SUITE[0], "prompt", original + " (edited)")
    try:
        assert suite_hash() != before
    finally:
        object.__setattr__(SUITE[0], "prompt", original)
    assert suite_hash() == before


@pytest.mark.parametrize("task_id,answer", sorted(CORRECT.items()))
def test_every_grader_accepts_its_own_correct_answer(task_id, answer):
    assert by_id()[task_id].grade(answer), f"{task_id} rejects a correct reply {answer!r}"


@pytest.mark.parametrize("task_id,answers", sorted(WRONG.items()))
def test_every_grader_rejects_wrong_answers(task_id, answers):
    task = by_id()[task_id]
    for a in answers:
        assert not task.grade(a), f"{task_id} accepts wrong reply {a!r}"


def test_no_grader_accepts_an_empty_or_whitespace_reply():
    for t in SUITE:
        assert not t.grade(""), f"{t.id} accepts an empty reply"
        assert not t.grade("   \n "), f"{t.id} accepts whitespace"


def test_the_no_letter_e_task_cannot_contradict_its_own_prompt():
    """THE regression test for this file's cautionary tale. Every accepted
    answer must actually satisfy the constraint the prompt states."""
    task = by_id()["constraint-no-e"]
    assert "does not contain the letter e" in task.prompt
    # Probe the allow-list through the grader rather than reaching into it.
    for colour in ["grey", "beige", "green", "blue", "red", "violet", "purple",
                   "orange", "silver", "lavender", "white", "yellow"]:
        assert "e" in colour                      # sanity: these all have one
        assert not task.grade(colour), f"accepted {colour!r}, which contains an e"
    for colour in ["black", "brown", "pink", "gray", "gold", "tan", "aqua",
                   "cyan", "crimson", "khaki", "maroon", "indigo", "ivory"]:
        assert "e" not in colour
        assert task.grade(colour), f"rejected {colour!r}, which is e-free"


def test_strict_format_tasks_reject_a_helpful_preamble():
    """The failure these probe *is* helpfulness — a "Sure!" in front of the
    answer breaks a machine consumer, so it has to score as a miss."""
    for t in SUITE:
        if t.kind != "formatting" or t.id not in CORRECT:
            continue
        assert not t.grade(f"Sure! Here you go: {CORRECT[t.id]}"), \
            f"{t.id} accepts a preamble on a strict-format task"


def test_every_task_declares_a_known_capability():
    known = {"instruction-following", "factual-recall", "arithmetic", "reasoning",
             "formatting", "extraction", "refusal-calibration", "counting",
             "string-manipulation"}
    unknown = {t.kind for t in SUITE} - known
    assert not unknown, f"unknown task kinds: {unknown} — add them to the dashboard too"


def test_prompts_are_short_enough_to_stay_cheap():
    """35 tasks against 16 models on a daily cron. A prompt that grows without
    anyone noticing turns cents per run into dollars."""
    for t in SUITE:
        assert len(t.prompt) < 600, f"{t.id} prompt is {len(t.prompt)} chars"
