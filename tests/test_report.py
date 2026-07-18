"""The reporter's judgment: standings always, alarm only on real news.

The whole reason this is the "safer version" is that it doesn't post on a
schedule — it alerts when a model *regressed*. These pin that: a clean week
produces no alert, a regressing week produces one, and the draft names the right
model and number.
"""
from modeldrift.report import ModelStatus, alert_issue, regressions, results_md, social_draft


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
