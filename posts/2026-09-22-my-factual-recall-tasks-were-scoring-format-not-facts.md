---
title: "My factual-recall tasks were scoring format, not facts"
date: 2026-09-22
kind: probe-alarm
about: harness
subject: fact-element
fingerprint: probe-alarm:fact-element:fact-element
destination: https://erikhill.dev/notes/2026-09-22-my-factual-recall-tasks-were-scoring-format-not-facts/
status: published
---

# My factual-recall tasks were scoring format, not facts

**This is a finding about my own harness. The suspect is the probe, not the models it measures.**

## What happened

I built a detector that decides whether a day's drift run contains anything worth
writing up. The first thing it did was accuse my own suite. One task,
`fact-element`, had failed on three or more providers on the same day, on 46
separate days.

The task is this:

> What is the chemical symbol for gold? Two letters only.

Graded by exact match against `au`, after stripping whitespace and lowercasing.

Claude Sonnet 5 failed it **60 times out of 60**. GPT-4o mini failed it **59 out
of 59**. Llama 3.1 8B, 23 out of 23. Those are not knowledge results. A model
that scores 83% across a 35-task suite does not have a 100% failure rate on
whether gold is Au.

## The evidence

| claim | how it was checked |
|---|---|
| `fact-element` failed on 3 or more providers on the same day, 46 times | cross-provider flip analysis over every stored run in `dashboard/drift_board.json` |
| those were graded failures, not outages | every run counted had `reliability: 1.0`, so no call errored and none was truncated |
| the models know the answer | `gpt-4o-mini` answered `'The chemical symbol for gold is Au.'`; `claude-sonnet-5` answered `'**Au**\n\nThat's the chemical symbol for gold, derived from the Latin word *aurum*.'` |
| the same models pass a near-identical task | all three answered `fact-capital` with exactly `'Tokyo'`, 0 failures in 59 and 60 runs |
| one trailing period is the whole difference | `gpt-4o-mini` answered `fact-planet` with `'Mercury.'` and was recorded wrong 59 times out of 59 |
| a model that formats tersely passes cleanly | `claude-opus-4-8` answered `'Au'`, `'Mercury'`, `'Tokyo'`, and fails `fact-element` on 1 of 60 runs |

The answers above are not from the board. They came from nine live calls made
through the probe's own call path, printed with `repr()` so punctuation and
markdown are visible rather than inferred.

## What stayed green anyway

`fact-capital` is the control, and it is the reason this is a finding rather
than a theory. It asks for the capital of Japan and every model in the table
answers `'Tokyo'`, exactly, on every run. Same grader, same strictness, same
models, same day. Nothing about exact matching is broken in general.

The three tasks differ in one way. `fact-capital` says **"Answer with only the
city name"**, which is an instruction about the shape of the output.
`fact-element` says **"Two letters only"** and `fact-planet` says **"One word"**,
which are descriptions of the answer. Models appear to read the first as a
constraint they must obey and the other two as a hint about what is being asked,
and then answer in their house style: a full sentence, a bolded token with an
etymology, a word with a period after it.

## What this run could and could not have seen

The suite has 35 tasks, so the smallest accuracy change it can print is
100/35 = 2.86 points. `fact-element` and `fact-planet` together are 5.7 points
of every affected model's score, permanently, for reasons that have nothing to
do with the models.

Worse than the points: these tasks are tagged `factual-recall`, and that tag
feeds a per-category breakdown on the public board. GPT-4o mini's
factual-recall score has been reading as a knowledge number when two thirds of
it is a formatting number. Anyone comparing models on that column, including
me, was comparing how terse they are.

## What I might have wrong

The part I am least sure of is the explanation, not the measurement. The numbers
are solid and the live answers are quoted verbatim, but "models treat *answer
with only X* as a constraint and *X only* as a hint" is one story that fits nine
calls. I have not tested it. The honest version is that I know the format
differs and I am guessing at why.

Two things genuinely argue against my reading. Grok 4.5 fails `fact-element` on
26 of 49 runs, which is close to a coin flip, and a rigid house style should not
produce that. And Claude Sonnet 5 failed `fact-planet` on 38 of 60 historical
runs but answered `'Mercury'` cleanly when I called it today, so at least some
of this moves over time and is not a fixed property of the model.

There is also a real question about what the fix should be, and I do not think
it is obviously "loosen the grader". A grader that accepts `'Mercury.'` also
accepts a model that ignores the instruction, and the instruction was part of
the task. Making the grader lenient would convert a visible measurement problem
into an invisible one. The alternative is to say plainly that these are
instruction-following tasks and retag them, which changes what the board has
been reporting for three months.

If you maintain an eval suite with exact-match graders on short answers: check
what your passing models actually return, not just whether they passed. The
board I built recorded *which* tasks failed for three months and never once
recorded *what the model said*, which is why this took a live call to see. That
gap is the more embarrassing half of this post.

---

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

Live board: https://egnaro9.github.io/model-drift/
Suite, graders and runner: https://github.com/egnaro9/model-drift

*The finding was surfaced automatically by the drift detector. The investigation, the live calls and the judgement of whether it was worth saying are mine.*
