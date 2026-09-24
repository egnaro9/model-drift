---
title: "My regression detector alerted on 4.3 points. The model moves 8.57 between runs."
published: false
description: "On 2026-09-23 my drift tracker reported Grok 4.3 down 4.3 points, to 91.4%. The pipeline drafted it automatically, as designed: a finding clears a threshold, a note gets written, a"
tags: showdev, testing, ai
canonical_url: https://erikhill.dev/notes/2026-11-04-the-detector-alerted-below-its-own-noise/
---

*Originally published at [erikhill.dev](https://erikhill.dev/notes/2026-11-04-the-detector-alerted-below-its-own-noise/). The numbers below are checked against the repository they come from.*

# My regression detector alerted on 4.3 points. The model moves 8.57 between runs.

**The detector had a threshold. It was the wrong quantity, it had been the wrong
quantity for months, and the reason nobody noticed is a sentence in my own
documentation claiming the suite was deterministic.**

## What happened

On 2026-09-23 my drift tracker reported Grok 4.3 down 4.3 points, to 91.4%. The
pipeline drafted it automatically, as designed: a finding clears a threshold, a
note gets written, a human merges or does not.

The draft argued the move was real because it cleared the **resolution floor**
of 2.94 points. That floor is `100 / graded_calls`. It is the smallest
difference a single run can express, because accuracy is a count over a
denominator and you cannot resolve a third of a question.

Then I ran the same frozen suite against the same model three more times.

| | |
|---|---|
| median accuracy over 3 runs | **97.06%** |
| reliability of the median run | 1.0 |
| **spread across the three runs** | **8.57 points** |

The move I was reporting was 4.30 points. The model moves 8.57 points against
an unchanged suite. The finding was less than half the noise, and the median of
three clean runs came in **higher than either number the note compared**.

## The two floors, which are not the same floor

This is the whole defect and it fits in two sentences.

**Resolution floor:** the smallest difference ONE run can print, given its
denominator. `100/34 = 2.94`. Pure arithmetic. It is a fact about counting.

**Noise floor:** how far the SAME model moves between runs of the IDENTICAL
suite. Measured, 8.57. It is a fact about the model and the stack under it.

My detector thresholded on the first and reported anything above it. The second
was roughly three times larger. So the detector was alerting, confidently and
in public, on moves it had no ability to distinguish from taking the sample
again.

This is not a one-model problem. Across the fleet, **10 of 20 models have a
recorded run-to-run spread larger than the arithmetic floor.**

## Why I never looked

The draft template opened every regression note with this:

> against the live models, same questions, same graders, **temperature 0**

All eighteen entries in the model registry carry `temperature: null`. The
provider layer omits the parameter whenever it is None, which is every model on
the board, because none of these models accept it. Nothing was pinned. Nothing
had ever been pinned.

That sentence is why the noise floor was invisible. A reader told a suite is
deterministic has no reason to ask what it varies by, and I was the reader. The
number was not hidden: the runner has been recording `acc_spread` on every
point for months, because it already takes three samples per model per day. I
had the measurement the entire time and never consulted it, because my own
documentation told me it should be zero.

## The fix, and how the fix was also wrong

A move now has to clear **both** floors: the arithmetic one, and the model's own
spread taken as the median of its last ten recorded runs. On the live board that
suppressed exactly one finding, the Grok note above, and left the other four.

Then I checked the estimator against fresh measurements, and it does not hold up
as well as the commit message I wrote for it implied.

| model | board estimate | measured over 3 fresh runs | error |
|---|---|---|---|
| grok-4.3 | 5.72 | 8.57 | under by 1.5x |
| grok-4-fast | 5.71 | 2.86 | **over by 2x** |
| claude-sonnet-5 | 3.11 | 3.28 | within 5% |

It missed in **both directions**, which is worse than missing consistently,
because a bias can be corrected and a scatter cannot. It was accurate on exactly
the model I expected it to fail on.

That last row also retired something else. `probe_repeated`'s docstring has
claimed for months that three runs half an hour apart moved Sonnet 5 by **9
points**. Measured today: 3.28. The repository's own documented noise figure
does not reproduce.

## What this run could and could not have seen

A spread taken from three samples is itself a noisy estimate. Max minus min on
n=3 has large variance, so 8.57 and 2.86 are not precise numbers and I am not
going to pretend they are. What survives is the ordering: these models sit
somewhere in the 3 to 9 point range, and a 2.94 point threshold is below all of
them.

What it CAN see is whether the instrument itself is the source. If the harness
or the grader were adding the variance, every model would scatter. So I ran the
same three-probe procedure against GPT-5, same suite, same grader, same
afternoon:

| | |
|---|---|
| median accuracy | 100.00% |
| reliability | 1.0 |
| graded | 35 of 35 |
| **spread across three runs** | **0.00 points** |

Zero. The same runner that recorded 8.57 points of movement on one model
recorded none at all on another, hours apart. **The variance is in the models,
not in the instrument**, which is what makes a per-model threshold the right
shape and a single global floor the wrong one. A global threshold set high
enough for Grok 4.3 would blind the board to a real three point move on GPT-5,
which this control shows it could resolve.

One confound, and it is mine to state rather than yours to find: GPT-5 scored
**100.00%**. A model that answers everything correctly every time has no room to
move downward, so some of that 0.00 is a ceiling rather than stability. The
control establishes that the harness does not ADD noise. A mid-scoring stable
model would have been the stronger test, and I do not have one on this board.

## What I might have wrong

**The fix is directionally right and numerically soft.** I replaced a threshold
that was definitely wrong with one that is roughly right, and I shipped it
before checking its estimator. The order should have been reversed. The honest
status is that the arithmetic floor was too low by a factor of about three, and
that the median-of-ten is the best number I currently have rather than the
correct one.

**Median-of-ten is a choice I cannot yet defend with data.** I picked the median
over the max because Grok 4.5's worst recorded spread is 91.43 points, which is
an outage signature rather than sampling, and taking the max would have muted
every model that ever had a bad morning. That reasoning is sound. Whether ten is
the right window, and whether the median is the right statistic, is unmeasured.

**The whole thing rests on one fleet and one suite.** Thirty-five questions,
eighteen models, one operator, one grader. I have shown that this detector
alerted below its own noise. I have not shown that anyone else's does, and the
interesting version of this claim is the general one.

If you run an eval suite that reports regressions: find the threshold, and then
ask which of the two floors it is. If the answer is `100/n`, or a constant
somebody picked, run your suite three times without changing anything and
compare.

---

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

Live board: https://egnaro9.github.io/model-drift/
Suite, graders and runner: https://github.com/egnaro9/model-drift

*The retired finding, the threshold change and every number above are in public commits. The confirming runs are GitHub Actions 35945537690, 35946570084 and 35946669164.*
