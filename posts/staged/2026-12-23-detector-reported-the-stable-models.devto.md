---
title: "My instability detector was reporting the stable models"
published: false
description: "A queue of 55 findings said two Gemini models were unstable. Measuring it a second way said they never disagree with themselves. 268 of 895 flips were manufactured by outages my detector never filtered."
tags: showdev, testing, ai, datascience
canonical_url: https://erikhill.dev/notes/2026-12-23-detector-reported-the-stable-models/
---

*Originally published at [erikhill.dev](https://erikhill.dev/notes/2026-12-23-detector-reported-the-stable-models/). Every number below is checked against the repository it describes.*

# My instability detector was reporting the stable models

I have a tracker that watches twenty LLMs against a frozen 35-task suite and
flags tasks that change their answer. It had a queue of 55 findings waiting to be
written up. Twenty-five were on one model, `gemini-3.1-flash-lite`, and twenty
more on `gemini-3.1-pro`.

Forty-five of fifty-five on two models from one provider is not a coincidence. I
sat down to write a post about Gemini instability.

That post would have been wrong in every part. `gemini-3.1-flash-lite` has six
real flips. The other seventy-two were manufactured by my own detector, and the
models that actually change their answers between runs were the ones it never
mentioned.

## The number that did not fit

Before writing I wanted the shape of the instability, so I measured something the
findings do not: how often a model's three runs on the same day disagree with
each other. Every point on this board is three runs of the same frozen suite, and
each one stores which tasks failed in each run. Disagreement within a day is the
cleanest possible instability signal, because nothing about the world changed
between those runs except the sampling.

| model | days measured | days where the 3 runs disagreed |
|---|---|---|
| xai:grok-4.3 | 43 | 43 (100%) |
| anthropic:claude-sonnet-5 | 52 | 51 (98%) |
| xai:grok-4-fast | 42 | 41 (97%) |
| google:gemini-3.1-pro | 13 | 0 (0%) |
| google:gemini-3.1-flash-lite | 13 | 0 (0%) |
| openai:gpt-5 | 51 | 0 (0%) |

The two models generating forty-five of my findings had never once disagreed with
themselves. Grok 4.3, which generated almost none, disagreed on every single day
it ran.

That is not a small discrepancy to explain away. It is the opposite of what the
findings said, so either my measurement was wrong or the detector was.

## What the detector was actually comparing

`flips_for_model` compares a task's pass/fail state between CONSECUTIVE STORED
POINTS. Each point is a day, and its `fails` list is that day's median across the
three runs.

So it measures change between days, and I had measured change within a day. Both
are real, and they are different failure modes:

- **Within-day disagreement** is sampling. Nothing changed but the dice. Grok and
  Sonnet do this constantly.
- **Between-day change** with no within-day disagreement is the stack moving under
  you. The model is internally consistent each day and consistently different the
  next.

A detector that only compares daily medians can see the second and is blind to the
first. That is a design choice, not a bug, and it is defensible: the noise floor
elsewhere in the pipeline exists precisely to absorb the sampling kind.

The bug was underneath it.

## One outage, counted thirty times

`flips_for_model` was reading raw points. The board separately tracks reliability,
and a point below a 0.5 floor means the provider did not answer, not that the
model got the answer wrong. There is a function for dropping those, called
`trusted_points`, and it lives in the file next door.

This module never called it.

A provider outage therefore reads as every task breaking at once and recovering a
run later. One real transition from the board:

```
2026-07-28 -> 2026-07-31 on gemini-3.5-flash: 29 tasks "broke" in one step
              reliability 0.2, against a floor of 0.5
```

Twenty-nine flips, then twenty-nine more on the way back out. Across the board:

| model | flips recorded | flips real | manufactured |
|---|---|---|---|
| google:gemini-3.5-flash | 153 | 15 | 138 |
| google:gemini-3.1-pro | 102 | 44 | 58 |
| google:gemini-3.1-flash-lite | 78 | 6 | 72 |
| everything else | 562 | 562 | 0 |

268 of 895 recorded flips were phantom, produced by nineteen untrusted points, and
every single one was on a Gemini model. Not because Gemini is unstable, but
because Gemini is the provider that went dark on this board, nine times on one
model alone.

## The fix is one call, and that is the uncomfortable part

```python
for model_id, raw_points in series.items():
    points = trusted_points(raw_points)
```

`trusted_points` moved from `board.py` to `policy.py` on the way, because
`flips.py` could not import `board` without a cycle and copying the predicate
would have made two definitions that must agree. The policy module's own docstring
was written years' worth of lessons ago to warn about exactly that.

What changed:

| | before | after |
|---|---|---|
| repeat offenders | 105 | 81 |
| one-offs | 53 | 2 |
| probe alarms | 253 | 213 |
| undrafted findings in the queue | 55 | 9 |

One-offs falling from 53 to 2 is the bug's signature. A one-off is a task that
flipped exactly once, which is precisely what an outage produces in bulk: every
task breaks together, recovers together, and never does it again.

The forty lost probe alarms are the same error told about my own harness. A probe
alarm fires when one task fails across three providers on the same day, on the
reasoning that models from different labs do not regress in unison. It is supposed
to accuse the test, not the models. An outage trips it just as neatly, so forty of
those accusations were also a provider being down.

After the fix the top repeat offenders are `nth-char` on grok-4-fast at 37, 
`extract-year` on grok-4.3 at 33, and `count-s-mississippi` on claude-sonnet-5 at
31. Which is what the within-day table said in the first place.

## What I actually did wrong

Not the missing filter. That is an ordinary omission.

The error was reading a count of findings as a measurement of models. Fifty-five
findings, forty-five on two Gemini models, is a fact about my pipeline's output.
I treated it as a fact about Gemini, and I was one paragraph from publishing it.

What stopped me was measuring the same claim a second way and getting an answer
that could not coexist with the first. Not scepticism, not review, just a second
instrument pointed at the same thing. The discrepancy did the work.

## What I might have wrong

The within-day table is not equal-sample. The Gemini models have 13 days with
stored per-run detail against 42 to 52 for Grok and Claude, so "never disagreed"
rests on a thinner record than "disagreed every day". It is enough to contradict
the findings and not enough to rank the models.

I also have not shown that between-day change on the Gemini models is a serving
stack moving rather than something else. Six real flips on flash-lite is a small
number to theorise over, and the honest reading is that I removed a false signal
rather than that I found a true one.

And the probe alarms are now 213 rather than 253, which I am reporting as an
improvement without having checked the survivors. Some of those may be the same
class of error from a different direction, and a count falling is not the same as
a count becoming correct.
