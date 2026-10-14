---
title: "Two eval scorers passed a wrong answer because it mentioned the right one"
date: 2026-10-14
kind: grader-defect
about: infrastructure
subject: external/inspect-includes-match
fingerprint: grader-defect:external/inspect-includes-match:0edb141
destination: https://erikhill.dev/notes/2026-10-14-two-scorers-passed-a-wrong-answer/
status: published
cadence_exception: the 2026-10-09 post was an off-design direct launch (fault matrix, Friday night); this is a different genre (a public tool and an invitation to break it) and the repo went public 2026-10-12
---

# Two eval scorers passed a wrong answer because it mentioned the right one

The reply was "No. The passage does not support Yes." The target was Yes. Two of the three deterministic scorers that ship with Inspect AI marked it correct.

I found that on Sunday night while adding a third external rubric to a tool I had been building for a week. The tool has one job: take a rubric, take material with known defects, and report whether the rubric can tell good work from bad. By that point it had already produced one finding each in promptfoo and OpenAI evals. Inspect was supposed to be the control, because its BoolQ task uses a scorer that is anchored at both ends and hard to fool.

It is hard to fool. That was the finding. Here is the full table, ten real BoolQ validation rows, seven completions per row, five correct by intent and two wrong:

```
scorer                   detects  false alarms  separation
pattern, as shipped      20/20    20/50         +0.60
includes()               10/20     0/50         +0.50
match(), location=end    10/20    10/50         +0.30
```

The shipped scorer, `pattern(r"\A[\W_]*(Yes|No)[\W_]*\Z")`, accepts nothing wrong. Its 40% false-alarm rate is every correct answer that disobeyed the prompt's "Include nothing else": "Yes, because the passage says so." is rejected, and so is "The passage supports it. Yes." That is a documented choice. The scorer records the reason as `invalid_response_format` and charges it to the model.

The other two are the library's general-purpose scorers, and they are what most custom tasks use. `includes()` casefolds both strings and tests `target in completion`, so a No that mentions Yes contains the target. `match()` strips whitespace, casefolds, strips punctuation and tests `completion.endswith(target)` at its default location, so a sentence that happens to end with the word passes. Nobody chose either of those. They are what a substring check and a suffix check do.

Then the tool did something I did not expect. Its default coverage policy is strict: zero false alarms, and a checkpoint has to catch at least half the defective specimens. Under that policy `includes()` is the scorer that counts as covering the defect class, and the shipped scorer is not. The policy did exactly what it says. It also made the point I keep relearning: whether a format rejection costs more than a substring hole is a decision, and a tool that prints only one column has made it for you.

## The other two tools, one line each

promptfoo's own airline example has a `not-contains "Seat updated to 16F"` assertion on a test where the agent must refuse a third party. The assertion is case-sensitive. A refusal followed by `seat updated to 16f` passes it, which is refusal-then-compliance passing the tool's own refusal test.

OpenAI evals' `Match` is `sampled.startswith(ideal)`, verbatim from `evals/api.py`. On eight real samples from the sarcasm eval: `"10"` is accepted for ideal `"1"`, and `" 1"` with a leading space is rejected. Half the wrong answers in, a third of the right answers out, and both are the predicate rather than a statistic.

None of these is a bug report. Each adapter reproduces the upstream line and does not fix it, because an adapter that quietly repaired the predicate would be measuring a rubric nobody runs.

## What measured it

The tool is called deadcheck. It takes a rubric as code (a checkpoint is a predicate, so no file format can carry one), a specimen set with constructed ground truth (a clean base plus one injection, so each defect is known by construction rather than labelled by opinion), and reports three numbers per checkpoint: separation, which is detection rate minus false-alarm rate; coverage per defect class, measured against what the specimens carry and never against what the rubric claims; and the residual, the classes nothing catches, printed as a column rather than a footnote.

Before any of that it runs a battery of naive probes over the material, including a deterministic coin flip, and prints the floor. A rubric that cannot beat the coin on a class has not measured that class.

The part I trust most is the part that embarrassed me. The seed specimen pack has four specimens per class. The power check turns a detection rate into a Wilson interval and at 3 of 4 it reports [0.21, 0.94], which does not clear the bar. So the tool's own certificate for its own example rubric says UNDERPOWERED, the CI step that checks it is non-blocking and labelled as such, and the fix is sixteen specimens per class, hand-written. I left it red rather than widen the predicate's keyword list, because that is the overfit the same tool had already caught twice that week.

The second embarrassment was cheaper. The first wheel built from the package shipped no adapters at all. The editable install imported them fine, so every test was green while the artifact a user would install was missing the module this whole post is about. There is now a CI step that installs the wheel into a clean venv and imports the adapters from outside the checkout, and it went red on the old package list before it went green on the new one.

Domain specimen packs are not published. Ground truth is hand-made, does not parallelize, and is the part that takes real time to build. The tool, the taxonomy and the seed pack are public.

## Break it

The claim is that this certifies a rubric can fail. The only honest way to trust that is to make it certify something false. Four targets, in the order I would try them, with details in `BREAKING.md` in the repo:

1. Forge a certificate the registry accepts. It re-hashes every evidence file and recomputes every headline, and the last protocol in this family was forged in four bytes by an outside auditor.
2. Score coverage without detecting anything: a predicate that clears the calibration floor on the seed pack while a reviewer reading it would call it blind.
3. Evade a covered checkpoint with a mechanical rewrite that keeps the defect. The paraphrase number is already published; find one the attack suite calls 0%.
4. Show that an adapter misreads its upstream. One counterexample voids the finding it supports, which is why it is on the list.

A reproducible script in an issue is a finding. A finding gets a test named after it.

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

The tool, the three adapters and the fixture: https://github.com/egnaro9/deadcheck

*Every figure above was checked against the repository before publication. The judgement of whether it was worth saying is mine.*
