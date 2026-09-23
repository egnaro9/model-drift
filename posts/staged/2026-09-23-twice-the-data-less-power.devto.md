---
title: "Twice the data, less power: my stability rule got blinder the harder I looked"
published: false
description: "I was comparing two models on a frozen 159 task suite and I had a problem most eval code does not admit to having: the same model, asked the same question three times, sometimes di"
tags: showdev, testing, ai
canonical_url: https://erikhill.dev/notes/2026-09-23-twice-the-data-less-power/
---

*Originally published at [erikhill.dev](https://erikhill.dev/notes/2026-09-23-twice-the-data-less-power/). The numbers below are checked against the repository they come from.*

# Twice the data, less power: my stability rule got blinder the harder I looked

**This is a finding about a measurement rule, not about a model. The models did not change.**

## What happened

I was comparing two models on a frozen 159 task suite and I had a problem most eval
code does not admit to having: the same model, asked the same question three times,
sometimes disagrees with itself. I had written a rule for that. A task where a
config does not agree with itself is discarded, not counted. Call it `strict`.

On the first three repetitions `strict` gave me Haiku ahead 7 to 1, eight
informative tasks, p equal to 0.070. Not significant.

So I looked at why, found that `strict` was throwing away thirteen tasks, and wrote
a second rule that tolerates a minority disagreement. Call it `rate`. It gave Haiku
ahead 13 to 2, fifteen informative tasks, p equal to 0.0074. Significant.

I had run the conservative rule, got a null, and then built the rule that returned
the result I wanted. That is also exactly what everyone who p hacks believes about
themselves.

## The evidence

| claim | how it was checked |
|---|---|
| the two rules disagreed on the same data | reps 1 to 3, suite `combined-159.json`: `strict` 7 to 1, informative 8, p 0.070; `rate` 13 to 2, informative 15, p 0.0074 |
| the second rule was written after seeing the first result | stated in `runs/PREREGISTRATION.md`, committed before reps 4 to 6 existed, so the git timestamp is checkable against the run files' mtimes |
| the replication was pre-registered, analysis included | predictions, refutation conditions and fixed parameters in `runs/PREREGISTRATION.md`; the analysis in `tools/replicate.py`, written while the sweeps were still running |
| the prediction I got wrong, I got wrong in public | predicted `strict` would again fail to reach significance; on fresh data it reached p 0.0215 |
| more repetitions raised the discard count | 2 reps: about 8.7 discarded, about 10.3 informative. 3 reps: 13 discarded, 8 informative |
| pooling all six repetitions lost the result | reps 4 to 6 alone: informative 10, discards 13, p 0.0215, decisive. Reps 1 to 6 pooled: informative 8, discards 17, p 0.0703, not significant |

## What the extra data did not buy

This is the part I did not expect and the reason the post exists.

Every extra repetition is another chance to observe a config disagreeing with
itself, and `strict` discards a task the moment it sees one. So the discards climb
with the data. Thirteen became seventeen. Informative tasks fell from ten to eight.
The p value went from 0.0215 to 0.0703, which is to say a decisive result became a
null by adding measurements to it.

In the limit the rule throws away every genuinely stochastic task. More measurement
cannot fix that. Only a different rule can.

A conservative rule is not a free choice. It will never report noise as signal, and
the price is that it grows blinder the harder you look. That price is measurable,
and until I measured it I had been describing the conservatism as pure upside.

## What the pre-registration was actually for

The rule I trust reached significance on data it had never seen. `strict` on reps
4 to 6 alone: Haiku 9 to 1, ten informative tasks, p 0.0215.

I had predicted it would fail again. The pre-registration says in advance what to
do about that: "If 1 holds and 2 fails, that is stronger than predicted, and I will
say the prediction was too conservative rather than claiming I called it." So that
is what I am saying. I did not call it.

The parameter is the part worth stealing. `rate_margin` was fixed at 0.5 in
advance, and afterwards I removed the flag from the command line entirely, along
with `--alpha`, because a threshold a reader can dial after seeing the result is
not a threshold. The registered value did not change. The knob did.

## What I might have wrong

The weakest link is that this is one suite and two models. Haiku 4.5 beating Sonnet
4.6 here is a claim about a suite made of trap questions, not a capability ranking.
A suite built to catch specific slips measures susceptibility to those slips, and I
would not carry that sentence anywhere else.

The reading I cannot rule out is that `rate` is simply the better rule and `strict`
was never worth defending, in which case the whole discard analysis is an
elaborate defence of a mistake. The replication is evidence against that, since
`strict` reached significance on fresh data, but one replication at two models is
not much.

And I should be honest that the pooled result has an innocent reading. Reps 1 to 3
and reps 4 to 6 were run at different times, so pooling them mixes two sampling
windows. I attribute the power loss to the discard mechanism because the discard
count is the thing that visibly moved, thirteen to seventeen, but I have not run
the version of this that would separate those two explanations.

If you maintain an eval suite with a stability or flakiness filter: count what it
discards, and count it again after you add data. If the discard count rises faster
than your informative count, your filter is spending your sample size, and the
direction of that trade is not obvious from the code.

---

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

Suite, rules, pre-registration and replication: https://github.com/egnaro9/pi-eval

*The numbers above are quoted from `FINDINGS.md` and `runs/PREREGISTRATION.md` in that repository. The judgement of whether this was worth saying is mine.*
