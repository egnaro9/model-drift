"""Tests for the generated board paragraph.

The generator exists because hand-written prose about live data went false
twice. So these tests are mostly *mutation* tests: change the numbers, assert
the prose changed to match. A test that only checks the prose against today's
data would pass forever while the generator quietly stopped tracking reality —
which is the failure it was built to prevent.

The property tests at the bottom are the real guardrails. The strongest is the
*pairing* one: every "<Model> at <N>%" in the prose must match that model's own
accuracy. An earlier version only checked that each printed percentage existed
*somewhere* in the data — which stayed green while the generator printed
"A Small and A Tiny at 100%" with A Tiny actually on 90%, because 100% was a
real score, just not that model's. Set membership is not pairing.
"""
from __future__ import annotations

import re

import pytest

from modeldrift.narrative import (
    _pct, build_rows, claim_cheap_matches_flagship, claim_perfect_scores,
    claim_slowest, claim_speed_accuracy, claim_verbosity, narrate,
)

# LabA deliberately has TWO cheaper tiers under one flagship — the shape Google
# actually has (Pro / Flash / Flash-Lite). A fixture with one cheap model per lab
# can never produce two winners with different scores, which is exactly the state
# that hid the collapsed-score bug from an earlier version of these tests.
REGISTRY = [
    {"id": "lab-a:big", "label": "A Big", "group": "LabA", "tier": "flagship"},
    {"id": "lab-a:small", "label": "A Small", "group": "LabA", "tier": "mini"},
    {"id": "lab-a:tiny", "label": "A Tiny", "group": "LabA", "tier": "nano"},
    {"id": "lab-b:big", "label": "B Big", "group": "LabB", "tier": "flagship"},
    {"id": "lab-b:small", "label": "B Small", "group": "LabB", "tier": "nano"},
    {"id": "mock:stable", "label": "Mock", "group": "Mock", "tier": "mock"},
]

# Every "<Label> at <N>%" pair the prose can emit, for the pairing property test.
_PAIR = re.compile(r"\b([AB] (?:Big|Small|Tiny)) at (\d+)%")


def _pt(acc, latency, chars, reliability=1.0, refusal=0.0):
    return {"t": "2026-07-18T00:00:00Z", "acc": acc, "latency_ms": latency,
            "out_chars": chars, "reliability": reliability, "refusal_rate": refusal}


def metrics(**overrides):
    """Baseline board: LabA's two cheap tiers sit at *different* scores, both at
    or above their flagship — the Google shape, and the state that catches a
    renderer printing one score for several models."""
    series = {
        "lab-a:big":   [_pt(0.90, 1000, 10)],
        "lab-a:small": [_pt(1.00, 200, 8)],
        "lab-a:tiny":  [_pt(0.90, 150, 8)],
        "lab-b:big":   [_pt(1.00, 3000, 100)],
        "lab-b:small": [_pt(0.50, 100, 5)],
        "mock:stable": [_pt(1.00, 0, 5)],
    }
    series.update(overrides)
    return {"updated": "2026-07-18T22:28:23Z", "series": series}


def rows(**overrides):
    return build_rows(metrics(**overrides), REGISTRY)


# ─────────────────────────── basic behaviour ────────────────────────────
def test_mock_series_is_never_narrated():
    assert all(not r.id.startswith("mock:") for r in rows())


def test_paragraph_carries_the_run_date_not_todays_date():
    out = narrate(metrics(), REGISTRY)
    assert "18 Jul 2026" in out["html"]


@pytest.mark.parametrize("value,shown", [
    (1.0, "100%"), (0.9999, "99%"), (0.996, "99%"), (0.9545, "95%"),
    (0.7727, "77%"), (0.5, "50%"), (0.0, "0%"),
    # Exact two-decimal values: 0.58 * 100 is 57.99999999999999 in binary
    # floating point, so a bare floor() prints a measured 58% as "57%".
    (0.58, "58%"), (0.29, "29%"), (0.77, "77%"), (0.91, "91%"), (0.07, "7%"),
])
def test_percentages_truncate_so_only_a_real_100_prints_as_100(value, shown):
    """Rounding would print a model on 99.6% as "100%" — a perfect score it did
    not get, in the number a reader checks hardest. Truncation can understate by
    under a point; it can never award a score that wasn't earned."""
    assert _pct(value) == shown


def test_no_percentage_is_ever_rounded_up():
    for i in range(0, 1000):
        v = i / 1000
        assert float(_pct(v).rstrip("%")) <= v * 100 + 1e-9


def test_the_mock_series_cannot_set_the_run_date():
    """`metrics["updated"]` is stamped whenever the file is written — including
    a CI run that probed nothing but the mock. On the live board it currently
    reads 22:28Z while the newest real measurement is 19:23Z. Dating the prose
    by a file write rather than by a measurement is a small lie, so the date
    comes from the newest non-mock point.
    """
    m = metrics()
    m["updated"] = "2027-01-01T00:00:00Z"                    # a much later write
    m["series"]["mock:stable"] = [_pt(1.0, 0, 5)]
    m["series"]["mock:stable"][0]["t"] = "2027-01-01T00:00:00Z"
    out = narrate(m, REGISTRY)
    assert "18 Jul 2026" in out["html"]
    assert "2027" not in out["html"]


def test_a_throttled_model_cannot_win_a_superlative():
    """A partial provider failure still records a point: `probe()` scores the
    failed calls as wrong and measures latency over whichever calls got
    through. That row's numbers describe the provider's morning, not the model,
    so it is excluded from the comparisons rather than crowned the fastest.
    """
    throttled = rows(**{"lab-b:small": [_pt(0.10, 5, 5, reliability=0.4)]})
    fast = claim_speed_accuracy(throttled)
    assert fast is None or "B Small" not in fast
    assert "B Small" not in (claim_slowest(throttled) or "")


def test_the_denominator_is_stated_when_models_are_left_out():
    m = metrics()
    m["series"]["lab-b:small"] = [_pt(0.10, 5, 5, reliability=0.4)]
    out = narrate(m, REGISTRY)
    assert "did not return a clean run" in out["text"]


def test_model_and_lab_counts_come_from_the_data():
    out = narrate(metrics(), REGISTRY)
    assert "5 models across 2 labs" in out["html"]


# ──────────────────────────── mutation tests ────────────────────────────
def test_mutate_flagship_ahead__cheap_tier_claim_goes_silent():
    """Baseline: A Small ties A Big, so the claim fires. Push the flagship
    ahead and the claim must disappear rather than soften."""
    assert claim_cheap_matches_flagship(rows()) is not None
    ahead = rows(**{"lab-a:big": [_pt(0.99, 1000, 10)],
                    "lab-a:small": [_pt(0.80, 200, 8)],
                    "lab-a:tiny": [_pt(0.70, 150, 8)],
                    "lab-b:big": [_pt(0.99, 3000, 100)]})
    assert claim_cheap_matches_flagship(ahead) is None


def test_mutate_scores_apart__each_model_prints_its_own_number():
    """The bug this exists to stop: naming two models and one score.

    A Small (0.90) ties the flagship; B Small (0.95) beats a 0.90 flagship.
    Whatever fires, no model may be printed next to a score it didn't get.
    """
    out = claim_cheap_matches_flagship(
        rows(**{"lab-b:big": [_pt(0.90, 3000, 100)],
                "lab-b:small": [_pt(0.95, 100, 5)]}))
    assert out is not None
    if "B Small" in out and "A Small" in out:
        assert "95%" in out and "90%" in out


def test_mutate_a_tie_for_slowest__prose_says_both():
    tied = rows(**{"lab-a:big": [_pt(0.90, 3000, 10)]})
    out = claim_slowest(tied)
    assert out is not None
    assert "A Big" in out and "B Big" in out and " are " in out


def test_mutate_everything_flat__no_superlative_is_invented():
    """All identical: there is no slowest, no chattiest, no tradeoff."""
    flat = {k: [_pt(0.80, 500, 20)] for k in
            ("lab-a:big", "lab-a:small", "lab-a:tiny", "lab-b:big", "lab-b:small")}
    r = build_rows(metrics(**flat), REGISTRY)
    assert claim_slowest(r) is None
    assert claim_verbosity(r) is None
    out = narrate(metrics(**flat), REGISTRY)
    assert "slowest" not in out["text"].lower()


def test_mutate_verbosity_below_threshold__claim_goes_silent():
    """A 1.5x spread is noise; the generator must not narrate it."""
    assert claim_verbosity(rows()) is not None
    quiet = rows(**{"lab-b:big": [_pt(1.00, 3000, 7.5)],
                    "lab-a:big": [_pt(0.90, 1000, 5)],
                    "lab-a:small": [_pt(0.90, 200, 5)],
                    "lab-a:tiny": [_pt(0.90, 150, 5)],
                    "lab-b:small": [_pt(0.50, 100, 5)]})
    assert claim_verbosity(quiet) is None


def test_mutate_all_perfect__says_so_instead_of_naming_a_winner():
    perfect = {k: [_pt(1.0, 500 + i * 100, 20)] for i, k in enumerate(
        ("lab-a:big", "lab-a:small", "lab-a:tiny", "lab-b:big", "lab-b:small"))}
    out = claim_perfect_scores(build_rows(metrics(**perfect), REGISTRY))
    assert "All 5 models that reported cleanly are at 100%" in out


def test_only_a_model_at_exactly_100_is_called_correct():
    """"Answers the whole suite correctly" means 100%, not "close to it".

    Baseline has A Small and B Big at 100%, and A Big / A Tiny at 90%. Loosening
    the threshold to >= 0.9 would sweep the 90% models into the sentence and
    print a claim about them that is simply false — and the count assertion
    alone doesn't catch it, so this checks *which models* get named.
    """
    out = claim_perfect_scores(rows())
    assert "2 of the 5 models that reported cleanly" in out
    assert "A Small" in out and "B Big" in out
    assert "A Big" not in out and "A Tiny" not in out


@pytest.mark.parametrize("mutation", [
    {},
    {"lab-a:tiny": [_pt(0.99, 150, 8)]},
    {"lab-b:small": [_pt(0.999, 100, 5)]},
])
def test_property_only_100_percent_models_are_named_as_correct(mutation):
    """No model below 100% may be named in the perfect-scores sentence."""
    m = metrics(**mutation)
    out = claim_perfect_scores(build_rows(m, REGISTRY)) or ""
    if "answer the whole suite correctly" not in out:
        return
    named = out.split("(", 1)[1].rstrip(").") if "(" in out else ""
    for e in REGISTRY:
        if e["id"] in m["series"] and e["label"] in named:
            assert m["series"][e["id"]][-1]["acc"] == 1.0, (
                f"{e['label']} named as correct at "
                f"{m['series'][e['id']][-1]['acc']} — in: {out}")


def test_mutate_none_perfect__reports_the_leader_not_a_fake_100():
    low = {k: [_pt(0.5, 500, 20)] for k in
           ("lab-a:small", "lab-a:tiny", "lab-b:big", "lab-b:small")}
    low["lab-a:big"] = [_pt(0.75, 500, 20)]
    out = claim_perfect_scores(build_rows(metrics(**low), REGISTRY))
    assert "Nothing reached 100%" in out and "A Big" in out and "75%" in out


@pytest.mark.parametrize("acc", [1.0, 0.7727, 0.5])
def test_no_tradeoff_is_invented_when_every_model_ties_on_accuracy(acc):
    """A tie makes "scores lowest" vacuously true and the tradeoff a lie.

    With zero accuracy variance the argmin returns *every* row, so a naive
    `fastest in worst` check is trivially satisfied and the generator called a
    joint-100% model the lowest scorer. A frozen suite against improving models
    saturates by design — 7 of 16 live models are already at 100% — so this is
    where the board is heading, not a contrived state.
    """
    tied = {k: [_pt(acc, 500 + i * 100, 20)] for i, k in enumerate(
        ("lab-a:big", "lab-a:small", "lab-a:tiny", "lab-b:big", "lab-b:small"))}
    out = claim_speed_accuracy(build_rows(metrics(**tied), REGISTRY))
    assert out is not None
    assert "scores lowest" not in out and "tradeoff" not in out


@pytest.mark.parametrize("acc", [1.0, 0.7727])
def test_property_the_paragraph_never_claims_a_tradeoff_without_a_spread(acc):
    tied = {k: [_pt(acc, 500 + i * 100, 20 + i * 40)] for i, k in enumerate(
        ("lab-a:big", "lab-a:small", "lab-a:tiny", "lab-b:big", "lab-b:small"))}
    text = narrate(metrics(**tied), REGISTRY)["text"]
    assert "tradeoff" not in text and "scores lowest" not in text


def test_fastest_is_not_called_a_tradeoff_when_it_is_also_accurate():
    """The tradeoff sentence may only fire when fastest == lowest-scoring."""
    good = rows(**{"lab-b:small": [_pt(1.00, 100, 5)]})
    out = claim_speed_accuracy(good)
    assert out is not None and "scores lowest" not in out


# ────────────────────── degenerate / missing data ───────────────────────
def test_single_model_falls_back_instead_of_comparing():
    out = narrate({"updated": "2026-07-18T00:00:00Z",
                   "series": {"lab-a:big": [_pt(1.0, 100, 10)]}}, REGISTRY)
    assert "not enough to rank" in out["text"]
    assert out["claims_fired"] == 0


def test_empty_board_does_not_crash_or_claim():
    out = narrate({"updated": "", "series": {}}, REGISTRY)
    assert "0 clean runs" in out["text"]


def test_null_metrics_are_skipped_not_treated_as_zero():
    """A model that errored has null latency; it must not become 'fastest'."""
    r = build_rows(metrics(**{"lab-b:small": [
        {"t": "x", "acc": 0.5, "latency_ms": None, "out_chars": None,
         "reliability": 0.0, "refusal_rate": None}]}), REGISTRY)
    out = claim_speed_accuracy(r)
    assert out is None or "B Small" not in out.split("—")[0]


def test_model_missing_from_registry_is_never_narrated():
    """A series with no registry entry is a config drift, not a finding.

    Its numbers are real but unattributable — no lab, no tier, and quite
    possibly a model that was removed from the registry while its old points
    stayed behind. It stays out of every claim rather than being narrated as
    "the slowest" under a raw id.
    """
    out = narrate({"updated": "2026-07-18T00:00:00Z", "series": {
        "lab-a:big": [_pt(1.0, 100, 10)], "lab-a:small": [_pt(0.5, 200, 40)],
        "ghost:x": [_pt(0.1, 900, 90)]}}, REGISTRY)
    assert "ghost:x" not in out["text"]
    assert out["text"]  # and it does not crash or blank the paragraph


def test_zero_length_answers_do_not_divide_by_zero():
    r = rows(**{"lab-b:small": [_pt(0.5, 100, 0)]})
    assert claim_verbosity(r) is None


# ───────────────────────── property guardrails ──────────────────────────
@pytest.mark.parametrize("mutation", [
    {},
    {"lab-a:small": [_pt(1.00, 50, 3)]},
    {"lab-b:big": [_pt(0.10, 9000, 900)]},
    {"lab-a:big": [_pt(0.90, 3000, 10)]},
    {"lab-b:small": [_pt(1.00, 100, 5)]},
])
def test_property_every_name_in_the_prose_exists_in_the_data(mutation):
    m = metrics(**mutation)
    out = narrate(m, REGISTRY)
    known = {e["label"] for e in REGISTRY} | set(m["series"])
    for label in re.findall(r"\b[A-Z]\s(?:Big|Small)\b", out["text"]):
        assert label in known


@pytest.mark.parametrize("mutation", [
    {},
    {"lab-a:small": [_pt(1.00, 50, 3)]},
    {"lab-b:big": [_pt(0.10, 9000, 900)]},
    {"lab-b:small": [_pt(0.95, 100, 5)], "lab-b:big": [_pt(0.90, 3000, 100)]},
])
def test_property_every_percentage_is_a_score_some_model_actually_got(mutation):
    """No percentage may appear that no model scored.

    Necessary but NOT sufficient — it compares sets, so it stays green while a
    model is printed next to another model's (real) score. The pairing test
    below is the one that actually catches that.
    """
    m = metrics(**mutation)
    out = narrate(m, REGISTRY)
    real = {f"{p[-1]['acc'] * 100:.0f}%" for k, p in m["series"].items()
            if not k.startswith("mock:")}
    printed = set(re.findall(r"\d+%", out["text"]))
    assert printed <= real, f"prose printed {printed - real}, no model scored that"


@pytest.mark.parametrize("mutation", [
    {},
    {"lab-a:tiny": [_pt(0.95, 150, 8)]},
    {"lab-a:small": [_pt(1.00, 50, 3)], "lab-a:tiny": [_pt(0.92, 150, 8)]},
    {"lab-a:big": [_pt(0.50, 1000, 10)]},
    {"lab-b:small": [_pt(0.95, 100, 5)], "lab-b:big": [_pt(0.90, 3000, 100)]},
])
def test_property_each_model_is_printed_beside_its_own_score(mutation):
    """THE guardrail. Every "<Model> at <N>%" pair in the prose must match that
    model's actual accuracy.

    The set-based test above passed while the generator printed "A Small and
    A Tiny at 100%" with A Tiny actually on 90% — 100% was a real score, just
    not that model's. Checking the *pairing* is what catches it, and it is the
    same lesson as every other substring assertion that quietly stopped testing.
    """
    m = metrics(**mutation)
    out = narrate(m, REGISTRY)
    actual = {e["label"]: m["series"][e["id"]][-1]["acc"]
              for e in REGISTRY if e["id"] in m["series"]}
    pairs = _PAIR.findall(out["text"])
    assert pairs, "expected at least one '<Model> at <N>%' pair to check"
    for label, printed in pairs:
        assert f"{actual[label] * 100:.0f}" == printed, (
            f"prose says {label} at {printed}%, data says "
            f"{actual[label] * 100:.0f}% — in: {out['text']}")


def test_a_stale_point_is_not_narrated_as_part_of_this_run():
    """A model whose provider was down for a month keeps its last point at the
    top of its series. Comparing it against this week's numbers would narrate a
    months-old measurement as current."""
    m = metrics()
    old = _pt(0.01, 3, 999)
    old["t"] = "2026-01-01T00:00:00Z"          # months behind the others
    m["series"]["lab-b:small"] = [old]
    out = narrate(m, REGISTRY)
    assert "B Small" not in out["text"]
    assert "18 Jul 2026" in out["html"]


def test_ties_never_print_one_members_number_for_the_group():
    """Two models tied on latency but on different scores: naming both and
    printing one accuracy reads as both having scored it."""
    tied = rows(**{"lab-a:small": [_pt(1.00, 100, 8)],
                   "lab-b:small": [_pt(0.50, 100, 5)]})
    out = claim_speed_accuracy(tied) or ""
    if "A Small" in out and "B Small" in out:
        assert "100%" not in out and "50%" not in out


def test_a_lab_without_a_flagship_gets_no_flagship_sentence():
    reg = [e for e in REGISTRY if e["id"] != "lab-a:big"]
    m = metrics()
    m["series"].pop("lab-a:big")
    out = claim_cheap_matches_flagship(build_rows(m, reg)) or ""
    assert "LabA" not in out


def test_a_heavy_tier_score_is_never_printed_as_the_flagships():
    """`heavy` sits above `flagship` (Fable 5 over Opus 4.8). Folding them into
    one "top tier" printed the heavy model's number under "the flagship's"."""
    reg = REGISTRY + [{"id": "lab-a:heavy", "label": "A Heavy",
                       "group": "LabA", "tier": "heavy"}]
    m = metrics()
    m["series"]["lab-a:heavy"] = [_pt(1.00, 4000, 30)]
    out = claim_cheap_matches_flagship(build_rows(m, reg)) or ""
    assert "A Heavy" not in out


def test_two_flagships_in_one_lab_produce_no_flagship_sentence():
    """"against the flagship's N%" is ambiguous when a lab has two — it hides
    which one the cheap model actually beat, so the lab is skipped."""
    reg = REGISTRY + [{"id": "lab-a:big2", "label": "A Big Two",
                       "group": "LabA", "tier": "flagship"}]
    m = metrics()
    m["series"]["lab-a:big2"] = [_pt(1.00, 900, 10)]
    out = claim_cheap_matches_flagship(build_rows(m, reg)) or ""
    assert "LabA" not in out


def test_a_tie_for_fastest_never_produces_the_tradeoff_sentence():
    """The tradeoff needs one model unambiguously fastest *and* lowest. With a
    tie at either extreme, naming the group and printing one member's numbers
    is the collapsed-score bug wearing a different hat."""
    tied = rows(**{"lab-a:tiny": [_pt(0.95, 100, 8)],
                   "lab-b:small": [_pt(0.50, 100, 5)]})
    out = claim_speed_accuracy(tied) or ""
    assert "scores lowest" not in out and "tradeoff" not in out


def test_a_tie_for_lowest_accuracy_never_produces_the_tradeoff_sentence():
    tied = rows(**{"lab-b:small": [_pt(0.50, 100, 5)],
                   "lab-a:tiny": [_pt(0.50, 800, 8)]})
    out = claim_speed_accuracy(tied) or ""
    assert "scores lowest" not in out and "tradeoff" not in out
