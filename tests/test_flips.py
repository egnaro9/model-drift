"""Noise vs signal vs a broken probe — the three the aggregate can't separate."""
from modeldrift.flips import analyze, flips_for_model, summarize


def pt(day, fails):
    return {"t": f"2026-07-{day}T10:00:00Z", "acc": 1.0, "fails": list(fails)}


def test_single_flip_is_noise_not_signal():
    series = {"openai:gpt-5": [pt(21, []), pt(22, ["bsearch"]), pt(23, ["bsearch"])]}
    r = analyze(series)
    assert r["repeat_offenders"] == []                      # broke once, stayed broken
    assert [x["task"] for x in r["one_offs"]] == ["bsearch"]


def test_a_task_flapping_across_runs_is_signal():
    series = {"openai:gpt-5": [pt(20, []), pt(21, ["to_roman"]), pt(22, []),
                               pt(23, ["to_roman"]), pt(24, [])]}
    r = analyze(series)
    assert len(r["repeat_offenders"]) == 1
    row = r["repeat_offenders"][0]
    assert row["task"] == "to_roman" and row["flips"] == 4
    assert "recovered" in row["latest"]


def test_same_task_failing_across_providers_indicts_the_probe():
    day = [pt(24, ["merge_intervals"])]
    series = {
        "openai:gpt-5": day, "anthropic:claude-sonnet-5": day,
        "google:gemini-3.1-pro": day, "meta:llama-3.3-70b": day,
    }
    r = analyze(series)
    assert len(r["probe_alarms"]) == 1
    a = r["probe_alarms"][0]
    assert a["task"] == "merge_intervals" and a["n_providers"] == 4
    assert a["providers"] == ["anthropic", "google", "meta", "openai"]
    assert "PROBE ALARM" in summarize(r)


def test_two_models_from_one_provider_is_not_a_probe_alarm():
    """Two OpenAI models failing together is a lab event, not a harness bug."""
    day = [pt(24, ["flatten"])]
    series = {"openai:gpt-5": day, "openai:gpt-5-mini": day}
    assert analyze(series)["probe_alarms"] == []


def test_mock_series_are_excluded():
    day = [pt(24, ["x"])]
    series = {f"mock:{i}": day for i in range(5)}
    r = analyze(series)
    assert r["probe_alarms"] == [] and r["repeat_offenders"] == [] and r["one_offs"] == []


def test_points_without_fails_are_skipped_not_crashed():
    """Runs recorded before `fails` existed must not break the analysis."""
    series = {"openai:gpt-5": [{"t": "2026-07-20T10:00:00Z", "acc": 1.0},
                               pt(21, ["bsearch"]), pt(22, [])]}
    r = analyze(series)
    assert [x["task"] for x in r["one_offs"]] == ["bsearch"]


def test_flips_for_model_needs_two_runs():
    assert flips_for_model([pt(24, ["a"])]) == []
    assert flips_for_model([]) == []


def test_summary_is_quiet_when_nothing_moved():
    series = {"openai:gpt-5": [pt(23, []), pt(24, [])]}
    assert "No task flipped" in summarize(analyze(series))


def test_no_data_is_not_reported_as_no_flips():
    """The failure mode this module exists to prevent, applied to itself."""
    legacy = {"openai:gpt-5": [{"t": "2026-07-20T10:00:00Z", "acc": 1.0},
                               {"t": "2026-07-21T10:00:00Z", "acc": 1.0}]}
    out = summarize(analyze(legacy))
    assert "No per-task history yet" in out
    assert "no data" in out

    real = {"openai:gpt-5": [pt(23, []), pt(24, [])]}
    assert "No task flipped" in summarize(analyze(real))


# ── a fail recorded during an outage is not a flip ────────────────────────

def _run(day, fails, reliability=1.0, acc=0.9):
    return {"t": f"{day}T00:00:00Z", "fails": list(fails),
            "reliability": reliability, "acc": acc}


def test_a_degraded_run_cannot_manufacture_a_probe_alarm():
    """Rows written before the refusal fix scored absent calls as wrong
    answers, so their `fails` arrays carry fabricated task failures. Reading
    those republishes a provider outage as a cross-provider harness alarm,
    which is the exact error this project exists to debunk.

    Measured on the live board 2026-09-23: unfiltered, 255 alarm task-days
    across 14 tasks; filtered, 159 across 9. Five tasks were outage entirely.
    """
    series = {
        f"{lab}:m": [_run("2026-09-01", [], 1.0),
                     # every call failed, so every task "failed"
                     _run("2026-09-02", ["math-order", "fact-capital"], 0.03, 0.03)]
        for lab in ("openai", "anthropic", "google")
    }
    assert analyze(series)["probe_alarms"] == [], \
        "three providers degraded on the same day is an outage, not a probe alarm"


def test_a_clean_run_still_raises_the_alarm():
    """The mirror: the filter must not also suppress the real thing."""
    series = {
        f"{lab}:m": [_run("2026-09-01", [], 1.0),
                     _run("2026-09-02", ["math-order"], 1.0)]
        for lab in ("openai", "anthropic", "google")
    }
    alarms = analyze(series)["probe_alarms"]
    assert len(alarms) == 1 and alarms[0]["task"] == "math-order"


def test_a_flip_into_or_out_of_a_degraded_run_is_not_counted():
    """A task that 'failed' only because the provider was down, then 'passed'
    when it came back, is two fabricated flips on one model."""
    series = {"openai:m": [_run("2026-09-01", [], 1.0),
                           _run("2026-09-02", ["math-order"], 0.1, 0.1),
                           _run("2026-09-03", [], 1.0),
                           _run("2026-09-04", ["math-order"], 0.1, 0.1),
                           _run("2026-09-05", [], 1.0)]}
    assert analyze(series)["repeat_offenders"] == []


def test_partial_degradation_is_also_excluded():
    """Reliability 0.97 means one call never landed. Any absent call in a run
    can fabricate a fail, so flips need every call, not merely most of them.

    Built so it can actually go red: three providers, so a probe alarm WOULD
    fire, and alternating fails, so repeat offenders WOULD fire. Only the
    0.97 keeps both empty. A REL_FLOOR-style 0.5 bar would let all of it
    through, which is why the bar here is 1.0.
    """
    series = {
        f"{lab}:m": [_run("2026-09-01", [], 1.0),
                     _run("2026-09-02", ["math-order"], 0.97, 0.88),
                     _run("2026-09-03", [], 0.97, 0.88),
                     _run("2026-09-04", ["math-order"], 0.97, 0.88)]
        for lab in ("openai", "anthropic", "google")
    }
    r = analyze(series)
    assert r["probe_alarms"] == [], r["probe_alarms"]
    assert r["repeat_offenders"] == [], r["repeat_offenders"]
