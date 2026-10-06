---
title: "Twelve drafts, three confirmed, three dead, and the queue behind them"
published: false
description: "My drift detector opened twelve pull requests in eleven days. Three have been through a confirming run. All three died, and the queue behind them is 55 deep."
tags: showdev, testing, ai, datascience
canonical_url: https://erikhill.dev/notes/2026-12-02-twelve-drafts-three-dead/
---

*Originally published at [erikhill.dev](https://erikhill.dev/notes/2026-12-02-twelve-drafts-three-dead/). Every number below is checked against the repository and the pull request history it describes.*

# Twelve drafts, three confirmed, three dead, and the queue behind them

My drift detector opened twelve draft pull requests in eleven days. Three have
since been put through a confirming run. All three died.

The last two died today, while I was writing this post about them. I had them
down as the live candidates, the two that cleared the floor binding them. Three
fresh probes of the same frozen suite put that model's spread at 8.58 points.
One move was 5.71. The other was 8.57. Both sit inside a single bounce.

I went in expecting to find the detector crying wolf. The detector is better
designed than I am. What it is fed is the problem, and so am I.

## The record

Between 2026-09-24 and 2026-10-04 the daily probe drafted this:

| date | PR | state | claim |
|---|---|---|---|
| 09-24 | #72 | merged | Grok 4.3 -4.3 pts to 91.4% |
| 09-24 | #73 | open | compare-decimals flipped 2x on gemini-3.1-flash-lite |
| 09-25 | #75 | closed | Gemini 3.5 Flash -2.9 pts to 97.1% |
| 09-26 | #77 | closed | GPT-OSS 20B -2.9 pts to 97.1% |
| 09-27 | #79 | open | compare-decimals flipped 2x, same model |
| 09-28 | #81 | closed | Claude Opus 4.8 -2.9 pts to 88.6% |
| 09-29 | #83 | open | Grok 4 Fast -8.6 pts to 88.6% |
| 09-30 | #85 | open | compare-decimals flipped 2x, same model |
| 10-01 | #86 | open | compare-decimals flipped 2x, same model |
| 10-02 | #88 | open | compare-decimals flipped 2x, same model |
| 10-03 | #90 | open | Grok 4 Fast -5.7 pts to 91.4% |
| 10-04 | #92 | open | compare-decimals flipped 2x, same model |

Twelve rows, but not twelve findings. Six carry the same title, and the PR body
says why in its own words: "An unmerged draft will be offered again, which is
the intended behaviour: a draft nobody merged is a finding nobody recorded."
Those six are one finding re-offered six times. Counting them as six would be
counting my own retries, which is the kind of arithmetic this whole project
exists to object to. Seven distinct findings.

## The one I approved

PR #72 was created at 2026-09-24T01:53:41Z and merged at 01:56:57Z. Three
minutes and sixteen seconds. That is roughly how long it takes to read a
generated post without checking anything in it.

At 02:02:27Z, five and a half minutes after the merge, I dispatched the confirm
workflow against the same model: three probes of the same frozen suite, Actions
run 35945537690. Median accuracy 97.06%, which is higher than either number the
note had compared, and 8.57 points of spread across the three runs. The move I
had just published was 4.3 points, barely half the distance the model travels on
its own between identical runs.

`posts/2026-09-23-RETIRED-grok-4-3-regression.md` now carries `status: retired`
and the sentence that the finding did not survive a confirming run.

One approval in twelve, and it is the wrong one. The review step did not catch
it. Re-running the measurement did, and only because I happened to press the
button six minutes later for unrelated reasons.

## The two I ignored, and what happened when I finally looked

Here is the part that changed while the post was open.

The detector does not threshold on one number. `reportable_threshold` in
`modeldrift/report.py` returns `max(arithmetic_floor, noise_pts)`, and its
docstring is explicit: "A move must clear BOTH floors: the arithmetic one, below
which the run could not have resolved it at all, and the model's own measured
spread, below which it is not distinguishable from taking the sample again."
That shipped in commit 738817d on 2026-09-23 at 22:14, before eleven of these
twelve drafts existed.

So every draft carries the floor that actually bound it, in its own evidence
table. PR #83:

> graded 35 calls gives an arithmetic floor of 2.86 pts; this model's measured
> run-to-run spread is 5.67 pts; the spread binds at 5.67 pts and the move was 8.57

And PR #90: spread 4.25, binding 4.25, move 5.71. Both cleared the floor that
applied to them. #83 had been open since 09-29, #90 since 10-03, neither read.

I dispatched the confirm workflow against grok-4-fast, three runs, testing the
5.71. Actions run 37348056831:

| | |
|---|---|
| usable runs | 3 |
| median accuracy | **91.43%** |
| reliability of the median run | 1.0 |
| graded calls | 35 |
| **spread across the three runs** | **8.58 points** |

> The move under investigation was 5.71 points. That is INSIDE this model's own
> run-to-run spread of 8.58 points. So the reported move is not distinguishable
> from sampling noise on this suite, and should not go out as a finding.

That kills #90. It also kills #83, whose move was 8.57 against the same 8.58.
By a hundredth of a point, which is not a margin, it is a coincidence.

Note the median: 91.43%. That is the exact number #90 reported as the new, lower
value. The model sits at 91.43 and bounces nearly nine points around it. Both
drafts were reporting positions within one bounce and calling them movement.

## The floor is a measurement too, and it moved by half

This is the finding I did not have before today, and it is the one worth keeping.

The floors those two drafts cleared were 5.67 and 4.25 points. Today the same
model, same frozen suite, measures 8.58. The binding floor was not wrong because
the formula was wrong. It was wrong because the spread fed into it is itself a
small-sample estimate of a quantity that moves, and on those two days it came in
low.

A gate of the form `max(arithmetic, measured_spread)` is exactly right in shape
and only as good as the second term. Mine is estimated from a handful of runs,
stored, and then trusted as though it were a property. It is not a property. It
is yesterday's reading of a noisy thing, used today as a constant.

Three confirmed, three dead. The detector has not yet produced a score movement
that survived being measured again.

## The three that should not have been drafted, and already are not

The three -2.9 drafts, on 09-25, 09-26 and 09-28, were each a single item
changing its answer. The suite is frozen at 35 tasks, so one item is 100/35, or
2.857 points, which is exactly the arithmetic floor. They cleared the gate
because the test was `move_pts < floor`, which admits a move sitting precisely
on it.

I changed that on 2026-09-28 at 15:23, in commit aa7ee79. `clears_floor` now
requires the move to exceed the floor rather than reach it, and its docstring
names all three drafts so the next reader knows what the rule is for. No
one-item draft has appeared in the week since.

That one is in the instrument's favour. The gate had a boundary bug, it was
found by looking at the output, and it was fixed in four days.

## What I got wrong on the way here

I almost published the opposite of this post.

I opened `modeldrift/draft.py`, found line 156 computing
`min_detectable_change(graded)`, and concluded that the detector thresholds on
the arithmetic floor and ignores the measured noise. It reads exactly like a
gate. I had a thesis, a line number, and a dozen pull requests that looked like
supporting evidence.

Nothing branches on that line. It generates the prose for a section titled "What
this run could and could not have seen." The decision is made in
`modeldrift/findings.py:120`, in a different file, on a different function.

The line that computes a number is not the line that decides with it. I have
spent a week finding that shape in other people's code, and in test suites that
could not fail, and in a workflow step that collapsed three exit states into
two. It reads the same from the inside: a plausible mechanism, found quickly,
never checked against what actually runs.

That error also cost me two numbers. The arithmetic floor is 2.86, not 2.94; I
had taken 100/34 from the single confirming run that graded 34 calls instead of
100/35 from the suite. And 8.57 is not a constant. It is grok-4.3's spread in
one confirming run, and it is also, coincidentally, three items out of
thirty-five. I compared a grok-4-fast move against a grok-4.3 spread and called
it indistinguishable from noise, when its own binding floor was 5.67 and it
cleared it.

## The six that looked like six findings

While writing this I counted twelve pull requests and seven findings, and I was
still wrong, because I had not asked why the same title kept arriving.

The pipeline drafts ONE pull request per run. The board currently holds 175
findings, of which 55 have never been drafted. So the daily pull request is not
today's news. It is the next item in a 55-deep queue, re-offered because an
unmerged draft is offered again by design.

That is why `compare-decimals flipped 2x on gemini-3.1-flash-lite` appeared on
09-24, 09-27, 09-30, 10-01, 10-02, 10-04 and 10-05. Six of those are now closed
as duplicates of one finding. The queue depth was invisible until something
printed it, which is the same reason none of this was visible before: the number
existed and nothing said it out loud.

## This is the sequel to a post that asked for it

An earlier note on this board, scheduled for 2026-11-04, found that my threshold
was the arithmetic floor and replaced it with a median of recent spreads. Its own
closing section says the quiet part: *"I replaced a threshold that was definitely
wrong with one that is roughly right, and I shipped it before checking its
estimator. The order should have been reversed."*

This post is that check. The median-of-ten it could not defend turns out to be
built from three-run estimates of a quantity three runs cannot estimate.

It is also where my worst mistake in this investigation came from. I read that
post's framing, opened `modeldrift/draft.py`, found a line computing the
arithmetic floor, and concluded the detector still thresholded on the wrong
number. It does not and has not since commit 738817d, which predates eleven of
the twelve drafts. Nothing branches on the line I found; the gate lives in
`modeldrift/findings.py` and takes `max(arithmetic, measured spread)`. The line
that computes a number is not the line that decides with it.

## What I changed, and what it cost

Two things, both measured before shipping.

**The floor now pools the runs.** `noise_floor` took a median of per-day spreads,
and each of those spreads is itself three runs. Three runs does not estimate this
quantity: grok-4-fast measured 2.86 points of spread on 09-29 and 8.58 on 10-03.
`pooled_noise_floor` estimates from the individual runs instead, thirty samples
over ten days rather than ten medians-of-three, using data already on disk at no
additional cost in API calls. It is a 5 to 95 band and not a range, because a
range grows with sample size by construction and would credit the estimator for
nothing but a bigger n. It ADDS to the median rather than replacing it, so a floor
can only rise.

Backtested over 973 trusted model-days:

| | current floor | pooled floor |
|---|---|---|
| draft-days | 71 | 49 |
| suppressed | | 22 |
| newly drafted | | 0 |

Both of the drafts in this post die under it: #83's 8.57 against a band of 11.43,
#90's 5.71 against 8.57.

**Confirming is no longer something I have to remember.** A score move is now
re-probed three times before its pull request exists, and the PR opens only if the
move exceeds the spread measured in that fresh run. It fails closed: a probe that
errors, a model whose key is missing, fewer than two usable runs, each stop the
draft. A confirm that could not run has not confirmed.

The honest limit on that: a task flip cannot be settled by re-measuring accuracy,
so flips pass the gate untested and their pull request says UNCONFIRMED. That is
most of the queue.

## What I might have wrong

The confirming runs are three probes each. Three is a thin basis for a spread,
and that cuts both ways here: the 8.58 that killed these two findings rests on
exactly the same kind of small sample as the 5.67 and 4.25 that admitted them. I
am using n=3 to overturn n=3. The honest claim is that the moves are not
established, not that the model held still.

Three dead findings is also not a false positive rate. Nine of the twelve drafts
have never been confirmed either way, and the six repeats are one finding. I
cannot say what fraction of this detector's output is noise. I can say that
every claim of its I have actually tested has failed.

Finally, nothing on this board is pinned. No model here accepts a temperature,
so run-to-run spread is part of the measurement rather than something I can
switch off. Every floor in this post exists because of that, and a provider
changing their serving stack quietly would move the floor without moving
anything I can see.

The pooled floor is still an estimate of a moving quantity, and the backtest that
justifies it measures how many drafts it removes, not how many of those were real.
Nothing on this board has survived a confirming run, so I have no false negative
to point at and no way to show I have not started suppressing true findings.

And the 55 are not 55 problems. Most are task flips, which the confirming probe
cannot settle, so a queue that deep mostly means a backlog of things I do not yet
have an instrument for.
