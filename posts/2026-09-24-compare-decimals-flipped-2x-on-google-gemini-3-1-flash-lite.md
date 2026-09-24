---
title: "compare-decimals flipped 2x on google:gemini-3.1-flash-lite"
date: 2026-09-24
kind: repeat-flip
about: models
subject: google:gemini-3.1-flash-lite/compare-decimals
fingerprint: repeat-flip:google:gemini-3.1-flash-lite/compare-decimals:google:gemini-3.1-flash-lite/compare-decimals
destination: https://erikhill.dev/notes/2026-09-24-compare-decimals-flipped-2x-on-google-gemini-3-1-flash-lite/
status: draft
---

# compare-decimals flipped 2x on google:gemini-3.1-flash-lite

## What happened

On 2026-09-24 my drift tracker ran its frozen suite (2026-07-v3) against the live models, same questions, same graders. Nothing is pinned: no model here accepts a temperature, so run-to-run spread is part of the measurement. compare-decimals flipped 2x on google:gemini-3.1-flash-lite.

## The evidence

| claim | how it was checked |
|---|---|
| compare-decimals changed pass/fail state 2 times | across stored runs of google:gemini-3.1-flash-lite; latest state recovered on 2026-09-23 |
| repeated flips are not the instrument's resolution | a single flip is 100/35 = 2.86 pts and would be noise; this one recurred |

## What stayed green anyway

13 of the models that reported this run did not move: GPT-5, GPT-5 mini, GPT-4o mini, GPT-5 nano, Claude Fable 5, Claude Opus 4.8, Claude Haiku 4.5, Gemini 3.1 Pro, Gemini 3.5 Flash, Gemini 3.1 Flash-Lite, Grok 4.5, GPT-OSS 120B, Qwen3.8 27B.

That matters more than the finding does. A board that reports movement every week is measuring its own noise, and the models that held still are the reason the one that moved is worth looking at.

## What this run could and could not have seen

The smallest movement this run could print is 2.94 points at its coarsest. Anything under that is the denominator moving, not a model, and is not reported here at all.

## What I might have wrong

<!-- REQUIRED before this can be published. The playbook rule is
     measured, not stylistic: a post with nothing to argue with does
     not open a thread, and the thread is the product. Name the
     weakest link in the evidence above, or the reading you cannot
     rule out. If you cannot find one, that is a reason not to
     publish this. -->

TODO

---

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

Live board: https://egnaro9.github.io/model-drift/
Suite, graders and runner: https://github.com/egnaro9/model-drift

*Drafted automatically from the run that produced it. The numbers above are generated; the judgement of whether this is worth saying is not.*
