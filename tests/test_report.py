"""The reporter's judgment: standings always, alarm only on real news.

The whole reason this is the "safer version" is that it doesn't post on a
schedule — it alerts when a model *regressed*. These pin that: a clean week
produces no alert, a regressing week produces one, and the draft names the right
model and number.
"""
import json

from modeldrift.report import (ModelStatus, alert_issue, append_stub_note,
                               min_detectable_change, regressions, results_md,
                               social_draft)


def S(label, latest, delta, verdict, when="2026-07-20"):
    return ModelStatus(label.lower(), label, latest, delta, verdict, when)


STABLE_WEEK = [S("GPT-4o mini", 0.92, 0.0, "unchanged"), S("Claude", 0.90, 0.008, "improved")]
BAD_WEEK = [S("GPT-4o mini", 0.92, 0.0, "unchanged"),
            S("Claude 3.5 Haiku", 0.75, -0.15, "regressed"),
            S("Gemini", 0.80, -0.02, "regressed")]


def test_no_regression_means_no_alert():
    assert regressions(STABLE_WEEK) == []


def test_regression_is_detected():
    regs = regressions(BAD_WEEK)
    assert {s.label for s in regs} == {"Claude 3.5 Haiku", "Gemini"}


def test_results_md_lists_every_model_including_no_data():
    md = results_md(STABLE_WEEK + [S("Llama", None, None, "no-data")])
    assert "GPT-4o mini" in md and "Llama" in md and "no runs yet" in md
    assert "🟢 improved" in md and "⚪ unchanged" in md


def test_alert_names_the_worst_drop():
    title, body = alert_issue(regressions(BAD_WEEK))
    assert "Claude 3.5 Haiku" in title      # -0.15 is worse than Gemini's -0.02
    assert "-15.0 pts" in title
    assert "Gemini" in body                  # the other regression still listed


def test_draft_leads_with_the_worst_and_is_postable():
    draft = social_draft(regressions(BAD_WEEK), BAD_WEEK)
    assert "Claude 3.5 Haiku" in draft and "-15.0 points" in draft
    assert "github.com/egnaro9/model-drift" in draft
    assert "#" in draft                      # has hashtags, ready to paste


def test_draft_mentions_secondary_regressions():
    draft = social_draft(regressions(BAD_WEEK), BAD_WEEK)
    assert "Also down" in draft and "Gemini" in draft


def test_stub_note_logs_the_worst_drop_as_a_stub(tmp_path):
    f = tmp_path / "notes.json"
    assert append_stub_note(str(f), regressions(BAD_WEEK), "2026-07-20") is True
    notes = json.loads(f.read_text())
    assert len(notes) == 1
    n = notes[0]
    assert n["stub"] is True and n["date"] == "2026-07-20" and n["metric"] == "accuracy"
    assert "Claude 3.5 Haiku" in n["title"]      # -0.15 is the worst drop


def test_stub_note_does_not_double_log_the_same_day(tmp_path):
    f = tmp_path / "notes.json"
    append_stub_note(str(f), regressions(BAD_WEEK), "2026-07-20")
    assert append_stub_note(str(f), regressions(BAD_WEEK), "2026-07-20") is False
    assert len(json.loads(f.read_text())) == 1


def test_stub_note_prepends_and_keeps_hand_written_notes(tmp_path):
    f = tmp_path / "notes.json"
    f.write_text(json.dumps([{"date": "2026-07-01", "title": "hand-written", "stub": False}]))
    append_stub_note(str(f), regressions(BAD_WEEK), "2026-07-20")
    notes = json.loads(f.read_text())
    assert len(notes) == 2
    assert notes[0]["date"] == "2026-07-20"       # newest first
    assert notes[1]["title"] == "hand-written"    # existing note preserved


# ── minimum detectable change ───────────────────────────────────────────────
# Accuracy is graded_pass/graded_total and a truncated call leaves the denominator,
# so the floor is 100/graded_total and moves run to run. The board once showed a model
# at -1.0 pts on 33 graded calls — less than one question, i.e. the denominator moving.

def test_min_detectable_change_scales_with_graded_count():
    assert round(min_detectable_change(35), 3) == 2.857
    assert round(min_detectable_change(33), 3) == 3.030
    # coarser when fewer calls grade — the whole reason it is not hardcoded
    assert min_detectable_change(33) > min_detectable_change(35)


def test_min_detectable_change_is_none_without_a_graded_count():
    assert min_detectable_change(None) is None
    assert min_detectable_change(0) is None


def test_results_md_flags_a_delta_beneath_the_floor():
    below = ModelStatus("s", "Claude Sonnet 5", 0.8182, -0.010, "regressed",
                        "2026-07-31", 33)
    md = results_md([below])
    assert "below floor" in md, "a sub-question delta must be marked, not printed bare"
    assert "±3.0" in md


def test_results_md_does_not_flag_a_delta_above_the_floor():
    above = ModelStatus("g", "Gemini 3.1 Pro", 0.886, -0.029, "regressed",
                        "2026-07-31", 35)
    md = results_md([above])
    assert "below floor" not in md
    assert "±2.9" in md


def test_results_md_tolerates_runs_predating_graded_total():
    old = ModelStatus("o", "Old Run", 0.90, -0.029, "regressed", "2026-07-20", None)
    md = results_md([old])
    assert "below floor" not in md
    assert "Old Run" in md
