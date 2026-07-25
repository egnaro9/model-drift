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
