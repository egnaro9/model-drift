# model-drift — *Is My Model Drifting?*

[![ci](https://github.com/egnaro9/model-drift/actions/workflows/ci.yml/badge.svg)](https://github.com/egnaro9/model-drift/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![tests](https://img.shields.io/badge/tests-132-brightgreen)](tests)

**A small public LLM observability board. A frozen suite runs against live models on a schedule and keeps every result — so you can watch each model's quality *and* speed, verbosity, reliability, and refusal rate over time, and see when any of them moves.**

### ▶ [Live tracker](https://egnaro9.github.io/model-drift/)

Model providers ship silent updates. A [peer-reviewed study](https://arxiv.org/abs/2311.11123) found that on a silent model change, **58.8% of prompt+model combinations lost accuracy** — no error, no version bump, no way to know except to keep measuring. This measures — across five metrics, toggled on the dashboard:

| Metric | What it answers | Source |
| --- | --- | --- |
| **Accuracy** | Did answers get worse? | eval-history (with regression alerts) |
| **Speed** | Median call latency — is it slower? | measured on the same calls |
| **Verbosity** | Avg answer length — chattier / pricier? | " |
| **Reliability** | Share of calls that succeeded — flaky? | " |
| **Refusals** | Share of benign prompts refused — over-refusing? | " |

The last four are byproducts of calls already made (near-zero extra cost) and live in a repo-committed `metrics.json` the dashboard reads from raw GitHub. Accuracy is the one that fires the automatic regression alert.

```
frozen suite ──►  live model APIs  ──►  deterministic grader  ──►  eval-history  ──►  chart + "▼ regressed"
```

## Why it's trustworthy

- **The grader is not a model.** Every one of the 35 tasks is graded mechanically — exact match, substring, regex, or a numeric compare. If the judge were an LLM you couldn't tell a real regression from the judge having a bad day; here a score change means the *model* moved. ([`suite.py`](modeldrift/suite.py))
- **Hard enough that flagships have headroom.** Some tasks are deliberate failure modes for strong models — counting letters in "strawberry", numeric-vs-lexical sorting, 9.9 vs 9.11 — so a top model's line can actually move instead of flatlining at 100%.
- **The suite is frozen and versioned.** A drift chart only means something if the questions never change under it. `SUITE_VERSION` is stamped on every run, and [`suite_hash()`](modeldrift/suite.py) fingerprints the exact questions so a silent edit is detectable.
- **Deterministic where the model allows it.** Every task has a single indisputable answer, so a drop is a real drop, not grader noise. Temperature is pinned to `0` on models that accept it; flagships that reject the param (Opus 4.8, GPT-5) run at their default — set per-model in [`models.json`](modeldrift/models.json).
- **Per-capability breakdown.** Not just "it dropped" but *which kind* dropped — instruction-following, factual recall, arithmetic, reasoning, counting, string manipulation, formatting, extraction, refusal calibration — because that's the useful part.
- **It's all here.** The suite, the graders, and the runner are open and auditable; the numbers are reproducible.

**Wrong is not the same as absent.** A call that never returned an answer — a rate limit, a timeout, an outage — is *absent*, not *wrong*; scoring it `0` reports the provider's bad morning as the model getting dumber (see [the field note](docs/a-rate-limit-not-a-regression.md)). Telling the two apart is the **Reliability** metric's whole job. So the dashboard **drops a run's accuracy point when its reliability falls below 50%** while the Reliability line keeps it. That exclusion is keyed on *aggregate reliability*, never on "a call failed" — a [deliberate design rule](docs/a-rate-limit-not-a-regression.md#design-note-not-a-blanket-drop-on-failure), because a blanket drop-on-failure would inflate accuracy on exactly the hardest tasks.

## Add a model — no code, just a secret

The runner **only probes a model whose API key is present**, so you fund exactly what you choose. Add the secret in the repo's Settings → Secrets → Actions and it appears on the next run:

| Provider (tiers tracked) | Secret |
| --- | --- |
| OpenAI — GPT-5 · GPT-5 mini · GPT-4o mini · GPT-5 nano | `OPENAI_API_KEY` |
| Anthropic — Fable 5 · Opus 4.8 · Sonnet 5 · Haiku 4.5 | `ANTHROPIC_API_KEY` |
| Google — Gemini 3.1 Pro · 3.5 Flash · 3.1 Flash-Lite | `GEMINI_API_KEY` |
| xAI — Grok 4.5 · 4.3 · 4 Fast | `XAI_API_KEY` |
| Meta — Llama 3.3 70B · Llama 3.1 8B (open-weights; served free via Groq) | `GROQ_API_KEY` |

Plus `EVAL_HISTORY_WRITE_KEY` to record runs. Each provider is tracked across the tiers it actually has — **heavy → flagship → mid → mini → nano** — so you can see whether a cheap tier keeps pace with the top model (tiers are only added where a real model exists; Google and xAI have no model above their flagship on the API, so they stay at three — no padding). Edit [`models.json`](modeldrift/models.json) to change models; any OpenAI-compatible endpoint works with a `base_url`, and a model that rejects a `temperature` param (Fable 5, Opus 4.8, Sonnet 5, GPT-5 / mini / nano, Grok 4.5 / 4.3 / 4 Fast) sets `"temperature": null`. **16 models**, 35 prompts each, daily — still **cents per run** (Fable 5 is the priciest at ~$10/$50 per 1M, but the tiny token count keeps it under a cent) on the free GitHub Actions cron.

```bash
pip install -e .
OPENAI_API_KEY=... EVAL_HISTORY_WRITE_KEY=... python -m modeldrift.run
# or with no keys at all — the deterministic mock proves the pipeline, no spend:
python -m modeldrift.run
```

## One run is a sample, not a measurement

Three runs of this identical frozen suite, half an hour apart, moved **Claude Sonnet 5 by 9 points** and **Fable 5 by 6**, while **11 of 16 models did not move at all**. Same questions, same deterministic grader, same day. None of the 16 models accept a `temperature` parameter, so nothing can be pinned to 0 — that spread is the floor under any drift signal, and a board that alerts on a single run alerts on sampling noise.

So each model is probed **three times per night and the median is recorded**. A number only moves when two of three runs agree, which is exactly the "is this a fluke?" question. A real regression shows up in most runs and survives; one odd run doesn't.

The **spread is stored alongside it** (`runs`, `acc_spread` on every point) rather than smoothed away. An aggregate that hides its own variance is a worse lie than a noisy chart — if a model is erratic, that *is* the finding.

```
Claude Sonnet 5    77 → 83 → 86     recorded: 83, spread 9
GPT-5             100 → 100 → 100   recorded: 100, spread 0
```

Cost: 35 tasks × 16 models × 3 runs is ~1,700 calls a night, still cents.

## Why the suite is hard on purpose

A drift chart needs a test that can *move*. The first version was deliberately dull — unambiguous questions a capable model should always get right — and it worked until it didn't: **seven of sixteen models sat at 100%**, five distinct scores across the whole board. A suite everyone passes measures nothing, and a flat line is indistinguishable from a broken probe.

So **v3** adds tasks aimed at where capable models still slip:

| Probe | Why it separates |
| --- | --- |
| **Strict output form** — *"output exactly OK, no punctuation"* | The failure mode is helpfulness. A `Sure!` in front of the answer breaks a machine consumer, so it scores as a miss. |
| **A negative constraint** — *"name a colour with no letter e"* | Following a prohibition is harder than following an instruction, and it can't be satisfied by pattern-matching a common answer. |
| **Character-level work** — counting `s` in *Mississippi* | Tokenisation actively works against the model here. |
| **Float and sign comparison** — `-0.5` vs `-0.05` | Two reliably bad days for otherwise strong models. |
| **A needle to extract** | Retrieval from filler, for a few hundred tokens rather than a long-context bill. |

Difficulty is the point; ambiguity never is. **An arguable task makes the grader wrong rather than the model** — which is not hypothetical here: the first draft of the no-letter-e task accepted *"grey"*, which would have scored a wrong answer right. [`tests/test_suite.py`](tests/test_suite.py) now asserts that every accepted answer actually satisfies the constraint its prompt states, that no grader takes an empty reply, and that strict-format tasks reject a preamble.

## Which *kind* of thing moved

Every task is tagged with the capability it exercises, and each run scores them separately — instruction-following, formatting, reasoning, arithmetic, recall, counting, string manipulation, extraction, refusal calibration. The dashboard charts any of them.

That breakdown is the useful half of a drift signal. A model at 77% overall is usually near-perfect on recall and *failing formatting*, and the aggregate tells you neither. Two of the five headline metrics — **reliability** and **refusal rate** — are flat whenever nothing breaks and nothing over-refuses, which is most days. That's a working safety net, not a boring chart; they exist to move on the day something goes wrong.

## The board writes its own prose

My portfolio describes this board in a paragraph, and that paragraph went **false twice** — both times for the same reason. *"Gemini 3.5 Flash is the only 100% that isn't a flagship"* was true the day it was written and false the week two OpenAI models also hit 100%. Nobody was careless; prose about weekly data simply can't move when the data does.

So [`narrative.py`](modeldrift/narrative.py) writes it. Each sentence is a **claim** — a predicate over the current numbers plus a renderer — and a claim whose predicate stops holding is *dropped*, not reworded. The generator can be silent. It can't be wrong.

```bash
python -m modeldrift.narrative      # -> dashboard/narrative.json
```

What it refuses to do, because each one is a way this kind of tool lies:

| Refusal | Why |
| --- | --- |
| **Break a tie silently** | "The slowest model" is false when two tie. Superlatives return *every* row at the extreme, so the renderer has to say so. |
| **Print one number beside several models** | It caught this in its own first output — Flash and Flash-Lite are at 100% and 95%, and the template said both were at 100%. Scores are per-model now. |
| **Round a percentage up** | 99.6% shown as "100%" is a perfect score a model didn't get, in the figure a reader checks hardest. Truncation can only understate. |
| **Date the prose by a file write** | `metrics.json`'s `updated` is stamped on *every* write, including a mock-only CI run. The date comes from the newest real measurement. |
| **Let a throttled model win a superlative** | A partial provider failure still records a point, with a depressed score and a latency measured over whatever calls got through. Those rows stay on the chart but out of the comparisons — and the paragraph says how many were left out before it compares anything. |
| **Generalise past its own predicate** | A cheap tier beating *its own lab's* flagship says nothing about cheap tiers generally — on this board, Meta's and OpenAI's cost plenty. |

The tests are mostly **mutation tests**: change a number, assert the prose changed to match. A test that only checks today's output passes forever while the generator quietly stops tracking reality. Every guard was verified by reintroducing the bug and watching it go red — which is how the first version of the pairing test was caught being decorative: it compared *sets* of percentages rather than which model each was attached to, so it stayed green against the exact bug it was written for.

The portfolio pulls the result in through [a weekly job](https://github.com/egnaro9/egnaro9.github.io/blob/main/.github/workflows/refresh-drift-paragraph.yml) that opens a **pull request** rather than pushing — the page is outward-facing, so publishing stays a human act.

## Automatic — but signal, not noise

The [daily workflow](.github/workflows/track.yml) runs on its own (08:17 UTC), and after each probe it:

- **updates [`RESULTS.md`](RESULTS.md)** — the current standings, committed to the repo, every run;
- **opens a GitHub issue *only when a model regressed*** week-over-week — the automatic "go look" trigger;
- **attaches a ready-to-post writeup** to the run when there's a regression, for you to publish by hand.

That last part is deliberate. A drift post is worth making when a model *actually drifted* — "Claude dropped 8 points this week" — not on a fixed clock; a weekly "nothing changed" post is spam. So the machine runs, records, and raises the alarm automatically; the outward-facing post stays a human decision, on real news. Automate the launches, never the approval.

## Honest about being free

The tracker runs daily on a free cron and a small spend. The dashboard shows **"last updated"** plainly, so if a run is skipped you see it — a drift tracker that hides its own staleness would be the very thing it warns about.

## What it reuses

Built on the pieces it needed already: [eval-history](https://github.com/egnaro9/eval-history) stores the runs and computes the run-to-run comparison; the scoring mirrors [rag-eval-lab](https://github.com/egnaro9/rag-eval-lab). stdlib `urllib` only — no SDKs, no dependencies.

```bash
pip install -e ".[dev]" && pytest -q     # 135 tests, stdlib only
```

## Field notes

- [The drift that was a rate limit](docs/a-rate-limit-not-a-regression.md) — a Llama model "dropped" 66 points overnight. It was Groq's 30 RPM cap, not the model. How I caught it and hardened the probe so a rate limit can't read as a regression.

---
MIT · by [Erik Hill](https://egnaro9.github.io)
