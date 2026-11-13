---
title: "1 registry entry stopped replaying: model-drift/vac"
date: 2026-10-22
kind: replay-change
about: harness
subject: vac-protocol/registry-replay
fingerprint: replay-change:vac-protocol/registry-replay:vac-protocol:replay@1c0a93c9a984ed00
destination: https://erikhill.dev/notes/2026-10-22-1-registry-entry-stopped-replaying-model-drift-vac/
status: draft
---

# 1 registry entry stopped replaying: model-drift/vac

**This is a finding about my own harness. The suspect is the probe, not the models it measures.**

## What happened

On 2026-10-22 my drift tracker ran its frozen suite (2026-07-v3) against the live models, same questions, same graders. Nothing is pinned: no model here accepts a temperature, so run-to-run spread is part of the measurement. 1 registry entry stopped replaying: model-drift/vac.

## The evidence

| claim | how it was checked |
|---|---|
| the weekly independent replay outcome changed | run 39243050498 on 2026-10-19, workflow replay.yml, overall failure |
| model-drift/vac went from success to failure | job 'model-drift/vac' in replay run 39243050498; the baseline recorded success |
| agent-certlab/claude-code-cloud-2026-10-11 appears in the replay for the first time | absent from notes/baseline.json, present in run 39243050498 |
| 1 entry is not currently replaying | not-success conclusions: model-drift/vac |
| the cause is not established by this signal alone | a job conclusion records that the gate refused, not which of its steps refused; the run log distinguishes them |

## What stayed green anyway

12 of the models that reported this run did not move: GPT-5, GPT-5 mini, GPT-4o mini, GPT-5 nano, Claude Fable 5, Claude Opus 4.8, Claude Sonnet 5, Claude Haiku 4.5, Gemini 3.5 Flash, Gemini 3.1 Flash-Lite, GPT-OSS 20B, Qwen3.8 27B.

That cohort is the control. If the suite were broken outright these would have moved too, so whatever is wrong is specific to the task above rather than general to the harness.

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
