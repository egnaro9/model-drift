# model-drift — *Is My Model Drifting?*

[![ci](https://github.com/egnaro9/model-drift/actions/workflows/ci.yml/badge.svg)](https://github.com/egnaro9/model-drift/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![tests](https://img.shields.io/badge/tests-18-brightgreen)](tests)

**A public LLM regression tracker. A frozen suite runs against live models on a schedule; every score is kept, so you can watch each model's quality over time — and see when it drops.**

### ▶ [Live tracker](https://egnaro9.github.io/model-drift/)

Model providers ship silent updates. A [peer-reviewed study](https://arxiv.org/abs/2311.11123) found that on a silent model change, **58.8% of prompt+model combinations lost accuracy** — no error, no version bump, no way to know except to keep measuring. This measures.

```
frozen suite ──►  live model APIs  ──►  deterministic grader  ──►  eval-history  ──►  chart + "▼ regressed"
```

## Why it's trustworthy

- **The grader is not a model.** Every one of the 22 tasks is graded by exact match, regex, or a numeric compare. If the judge were an LLM you couldn't tell a real regression from the judge having a bad day; here a score change means the *model* moved. ([`suite.py`](modeldrift/suite.py))
- **Hard enough that flagships have headroom.** Some tasks are deliberate failure modes for strong models — counting letters in "strawberry", numeric-vs-lexical sorting, 9.9 vs 9.11 — so a top model's line can actually move instead of flatlining at 100%.
- **The suite is frozen and versioned.** A drift chart only means something if the questions never change under it. `SUITE_VERSION` is stamped on every run, and [`suite_hash()`](modeldrift/suite.py) fingerprints the exact questions so a silent edit is detectable.
- **Deterministic where the model allows it.** Every task has a single indisputable answer, so a drop is a real drop, not grader noise. Temperature is pinned to `0` on models that accept it; flagships that reject the param (Opus 4.8, GPT-5) run at their default — set per-model in [`models.json`](modeldrift/models.json).
- **Per-capability breakdown.** Not just "it dropped" but *which kind* dropped — instruction-following, factual recall, arithmetic, reasoning, counting, string manipulation, formatting, refusal calibration — because that's the useful part.
- **It's all here.** The suite, the graders, and the runner are open and auditable; the numbers are reproducible.

## Add a model — no code, just a secret

The runner **only probes a model whose API key is present**, so you fund exactly what you choose. Add the secret in the repo's Settings → Secrets → Actions and it appears on the next run:

| Provider (flagship + mini tracked) | Secret |
| --- | --- |
| OpenAI — GPT-5 · GPT-4o mini | `OPENAI_API_KEY` |
| Anthropic — Claude Opus 4.8 · Haiku 4.5 | `ANTHROPIC_API_KEY` |
| Google — Gemini 2.5 Pro · 2.5 Flash | `GEMINI_API_KEY` |
| xAI — Grok 4.5 · Grok 4.1 Fast | `XAI_API_KEY` |
| Groq — Llama 3.3 70B (free tier) | `GROQ_API_KEY` |

Plus `EVAL_HISTORY_WRITE_KEY` to record runs. Each provider is tracked at a **flagship** (the headline — GPT-5, Opus 4.8) and a **mini** (moves week-to-week, near-free). Edit [`models.json`](modeldrift/models.json) to change models; any OpenAI-compatible endpoint works with a `base_url`, and a model that rejects a `temperature` param (Opus 4.8, GPT-5) sets `"temperature": null`. The suite is ~22 prompts × a handful of models, weekly — **cents per run**, on the free GitHub Actions cron.

```bash
pip install -e .
OPENAI_API_KEY=... EVAL_HISTORY_WRITE_KEY=... python -m modeldrift.run
# or with no keys at all — the deterministic mock proves the pipeline, no spend:
python -m modeldrift.run
```

## Automatic — but signal, not noise

The [weekly workflow](.github/workflows/track.yml) runs on its own (Monday cron), and after each probe it:

- **updates [`RESULTS.md`](RESULTS.md)** — the current standings, committed to the repo, every run;
- **opens a GitHub issue *only when a model regressed*** week-over-week — the automatic "go look" trigger;
- **attaches a ready-to-post writeup** to the run when there's a regression, for you to publish by hand.

That last part is deliberate. A drift post is worth making when a model *actually drifted* — "Claude dropped 8 points this week" — not on a fixed clock; a weekly "nothing changed" post is spam. So the machine runs, records, and raises the alarm automatically; the outward-facing post stays a human decision, on real news. Automate the launches, never the approval.

## Honest about being free

The tracker runs weekly on a free cron and a small spend. The dashboard shows **"last updated"** plainly, so if a run is skipped you see it — a drift tracker that hides its own staleness would be the very thing it warns about.

## What it reuses

Built on the pieces it needed already: [eval-history](https://github.com/egnaro9/eval-history) stores the runs and computes the run-to-run comparison; the scoring mirrors [rag-eval-lab](https://github.com/egnaro9/rag-eval-lab). stdlib `urllib` only — no SDKs, no dependencies.

```bash
pip install -e ".[dev]" && pytest -q     # 18 tests, stdlib only
```

---
MIT · by [Erik Hill](https://egnaro9.github.io)
