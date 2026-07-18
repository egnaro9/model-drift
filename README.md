# model-drift — *Is My Model Drifting?*

[![ci](https://github.com/egnaro9/model-drift/actions/workflows/ci.yml/badge.svg)](https://github.com/egnaro9/model-drift/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![tests](https://img.shields.io/badge/tests-7-brightgreen)](tests)

**A public LLM regression tracker. A frozen suite runs against live models on a schedule; every score is kept, so you can watch each model's quality over time — and see when it drops.**

### ▶ [Live tracker](https://egnaro9.github.io/model-drift/)

Model providers ship silent updates. A [peer-reviewed study](https://arxiv.org/abs/2311.11123) found that on a silent model change, **58.8% of prompt+model combinations lost accuracy** — no error, no version bump, no way to know except to keep measuring. This measures.

```
frozen suite ──►  live model APIs  ──►  deterministic grader  ──►  eval-history  ──►  chart + "▼ regressed"
```

## Why it's trustworthy

- **The grader is not a model.** Every one of the 12 tasks is graded by exact match, regex, or a numeric compare. If the judge were an LLM you couldn't tell a real regression from the judge having a bad day; here a score change means the *model* moved. ([`suite.py`](modeldrift/suite.py))
- **The suite is frozen and versioned.** A drift chart only means something if the questions never change under it. `SUITE_VERSION` is stamped on every run, and [`suite_hash()`](modeldrift/suite.py) fingerprints the exact questions so a silent edit is detectable.
- **`temperature=0`, deterministic tasks.** The tasks are deliberately dull and unambiguous — the point isn't difficulty, it's that the right answer isn't in dispute, so a drop is a drop.
- **Per-capability breakdown.** Not just "it dropped" but *which kind* dropped — instruction-following, factual recall, arithmetic, formatting, refusal calibration — because that's the useful part.
- **It's all here.** The suite, the graders, and the runner are open and auditable; the numbers are reproducible.

## Add a model — no code, just a secret

The runner **only probes a model whose API key is present**, so you fund exactly what you choose. Add the secret in the repo's Settings → Secrets → Actions and it appears on the next run:

| Model | Secret |
| --- | --- |
| GPT-4o mini | `OPENAI_API_KEY` |
| Claude 3.5 Haiku | `ANTHROPIC_API_KEY` |
| Gemini 2.0 Flash | `GEMINI_API_KEY` |
| Llama 3.3 70B (Groq, free tier) | `GROQ_API_KEY` |

Plus `EVAL_HISTORY_WRITE_KEY` to record runs. Edit [`models.json`](modeldrift/models.json) to track different models; any OpenAI-compatible endpoint works with a `base_url`. The suite is ~12 prompts × a handful of models, weekly — **cents per run**, on the free GitHub Actions cron.

```bash
pip install -e .
OPENAI_API_KEY=... EVAL_HISTORY_WRITE_KEY=... python -m modeldrift.run
# or with no keys at all — the deterministic mock proves the pipeline, no spend:
python -m modeldrift.run
```

## Honest about being free

The tracker runs weekly on a free cron and a small spend. The dashboard shows **"last updated"** plainly, so if a run is skipped you see it — a drift tracker that hides its own staleness would be the very thing it warns about.

## What it reuses

Built on the pieces it needed already: [eval-history](https://github.com/egnaro9/eval-history) stores the runs and computes the run-to-run comparison; the scoring mirrors [rag-eval-lab](https://github.com/egnaro9/rag-eval-lab). stdlib `urllib` only — no SDKs, no dependencies.

```bash
pip install -e ".[dev]" && pytest -q     # 7 tests, stdlib only
```

---
MIT · by [Erik Hill](https://egnaro9.github.io)
