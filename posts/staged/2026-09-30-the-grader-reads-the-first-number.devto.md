---
title: "My arithmetic grader reads the first number in the sentence, not the answer"
published: false
description: "A week ago I published a post saying three of my factual-recall tasks were scoring format rather than facts, and I ended it with a guess I had not tested. The guess was that models"
tags: showdev, testing, ai
canonical_url: https://erikhill.dev/notes/2026-09-30-the-grader-reads-the-first-number/
---

*Originally published at [erikhill.dev](https://erikhill.dev/notes/2026-09-30-the-grader-reads-the-first-number/). The numbers below are checked against the repository they come from.*

# My arithmetic grader reads the first number in the sentence, not the answer

**This is a finding about my own harness. No model got the arithmetic wrong.**

## What happened

A week ago I published a post saying three of my factual-recall tasks were scoring
format rather than facts, and I ended it with a guess I had not tested. The guess
was that models read `Answer with only the city name` as a constraint on the output
and `Two letters only` as a description of the answer, and that the difference
decides whether you get a bare token or a sentence.

This week the same suite's arithmetic grader failed Claude Opus 4.8 on sixty
consecutive clean runs of a task that asks what 0.3 minus 0.1 is.

So I went and looked, and the guess held in a place I did not plant it.

## The defect

```python
def _number(expected: float, tol: float = 1e-6):
    def g(out: str) -> bool:
        m = re.search(r"-?\d+(?:\.\d+)?", out.replace(",", ""))
        return m is not None and abs(float(m.group()) - expected) <= tol
    return g
```

`re.search` returns the **first** match. So the grader reads the first number that
appears anywhere in the output and compares that to the expected answer. If a model
restates the question before answering it, the first number in the output is a
number from the question.

Seven of the eight tasks graded this way put a number in the prompt that is not the
answer. `Compute 3 + 4 * 5` expects 23 and leads with 3. `What is 15% of 200`
expects 30 and leads with 15. `What is 0.3 minus 0.1` expects 0.2 and leads with
0.3.

## The evidence

| claim | how it was checked |
|---|---|
| the grader takes the first number, not the answer | `modeldrift/suite.py:64`, `re.search(r"-?\d+(?:\.\d+)?", ...)` |
| 7 of its 8 tasks lead with a number that is not the answer | enumerated over `SUITE`: math-order 3 vs 23, math-percent 15 vs 30, reason-older 30 vs 25, multi-step-math 3 vs 8, unit-minutes 2.5 vs 150, compare-negatives -0.5 vs -0.05, float-subtract 0.3 vs 0.2. Only compare-decimals leads with its own answer |
| it bites on runs where nothing errored | `float-subtract` fails on 9 models across runs with `reliability: 1.0`, worst Claude Opus 4.8 at 60 of 60 |
| every model had the right answer | live calls through the probe's own path: gpt-4o-mini `'0.3 minus 0.1 equals 0.2. To one decimal place, the answer is 0.2.'`; opus-4-8 `'0.3 minus 0.1 is **0.2**.'`; sonnet-5 `'0.3 minus 0.1 equals **0.2**'` |
| changing only the instruction flips the outcome | same arithmetic, three wordings, three models, nine calls: as-shipped FAIL x3 with first=0.3; `Give only the number` and `Number only` PASS x3 with first=0.2 |
| the same models pass the other number tasks in the same call | all three answered math-order `'23'`, math-percent `'30'`, unit-minutes `'150'`, bare, no restatement |

## What separates the task that fails from the seven that do not

This is the part that makes it more than a bug report.

The tasks that pass say **"Give only the number"** and **"Number only"**. Those are
instructions about the shape of the output. The task that fails says **"Give the
number to one decimal place"**. That is an instruction about the *format of the
value*, and it appears to invite the model to show that it has formatted it, which
means saying what it started from.

Last week's post guessed exactly that distinction from nine calls on three
factual-recall tasks, and said plainly that it was one story fitting nine calls. It
now fits twenty one calls, across two different grader families, with the same
split: an output-shape instruction gets a bare token, a description of the answer
gets a sentence.

I would rather have found it the other way around. A guess that survives a test I
did not design for it is worth more than a guess I go looking to confirm.

## So I ran the experiment

The paragraph above used to say this was a pattern I had observed twice rather than
a mechanism I had demonstrated, and that the test was one sweep away. Here is the
sweep. Same arithmetic, same three models, three instruction wordings, nine calls.
The frozen suite was not edited, because its hash travels in published claims; the
variants were sent directly.

```
as-shipped  "Give the number to one decimal place"   FAIL x3   first=0.3
            opus-4-8     '0.3 minus 0.1 equals **0.2**.'
            sonnet-5     '0.3 - 0.1 = **0.2**'
            gpt-4o-mini  '0.3 minus 0.1 equals 0.2. To one decimal place, the answer is 0.2.'

"Give only the number"                             PASS x3   first=0.2   all answered '0.2'
"Number only"                                      PASS x3   first=0.2   all answered '0.2'
```

Nine for nine. The only thing that changed was the instruction, and it flipped every
row.

It also kills the alternative I could not rule out. I had written that `0.3 minus
0.1` is the canonical floating point example and a model might restate it because it
recognises the exercise rather than because of the wording. If that were the cause,
the restatement would survive `Give only the number`. It does not survive it once.

## What I might have wrong

The experiment is three models and one task. It demonstrates that the wording
controls the restatement here; it does not establish how far that generalises, and I
would not carry the claim to a model family I have not called.

And the count needs a caveat. Seven of eight tasks are vulnerable *in principle*,
because their prompts lead with the wrong number. Only one of them is observed
failing at scale. The others pass because these models happen to answer them
tersely, which is not a property of my grader, it is a property of this month's
models. The grader is one style change away from failing all seven.

The fix is not obvious either, and I have not made it. Reading the last number
instead of the first would pass `'0.3 minus 0.1 equals 0.2'` and would also pass a
model that shows its work and lands on the wrong final value. Requiring a bare
number would be honest but would turn an arithmetic task into a formatting task,
which is the exact complaint this post is making.

If you grade numeric answers with a regex: check which end of the string you are
reading, and check it against an output that restates the question. Mine had been
reading the question back to itself for months, and the board recorded the result as
an arithmetic failure.

---

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

Live board: https://egnaro9.github.io/model-drift/
Suite, graders and runner: https://github.com/egnaro9/model-drift

*The finding was surfaced by the drift detector. The live calls, the enumeration and the judgement of whether it was worth saying are mine.*
