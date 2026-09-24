---
title: "RETIRED: the 4.3 point drop was smaller than the instrument's own spread"
date: 2026-11-04
kind: regression
about: models
subject: xai:grok-4.3
fingerprint: regression:xai:grok-4.3:xai:grok-4.3@2026-09-23
destination: https://erikhill.dev/notes/2026-09-23-grok-4-3-4-3-pts-to-91-4/
status: retired
---

# RETIRED. The finding did not survive a confirming run.

**This note is kept as a record of a finding that was wrong, not as a post.**
`status: retired` keeps it out of the index and out of the publisher.

On 2026-09-23 the tracker reported grok-4.3 down 4.3 points, and the drafted
note below argued the move cleared the resolution floor of 2.86 points. A
confirming run settled it. Three independent probes of the same frozen suite,
GitHub Actions run 35945537690:

| | |
|---|---|
| usable runs | 3 |
| median accuracy | **97.06%** |
| reliability of the median run | 1.0 |
| graded calls | 34 of 35 |
| **accuracy spread across the three runs** | **8.57 points** |

The move under investigation was 4.30 points. The model's own run-to-run spread
is 8.57. The finding is less than half the noise, and the median of three clean
runs is higher than either number the original note compared.

Two things this exposes, both larger than the retired finding:

**The resolution floor is not the noise floor, and the note confused them.** The
floor asks what the smallest difference ONE run can print is, given its
denominator: 100/34, or 2.94 points. That is a property of arithmetic. It says
nothing about how far the same model moves between runs of the same suite,
which is 8.57 points here. The detector alerts on the first number and the
second one is roughly three times larger, so it will keep reporting noise as
regression until that threshold changes.

**The note also claimed "temperature 0", and nothing here is pinned.** All 18
registry entries carry `temperature: null` because none of these models accept
the parameter. That sentence came from the draft template and has been
corrected at source, but it is what made the spread above invisible: a reader
told the suite is deterministic has no reason to ask what it varies by.

The original draft follows, unedited below this line, because a retired finding
that quietly disappears teaches nothing.

---

# Grok 4.3 -4.3 pts to 91.4% (as originally drafted)

## What happened

<!-- HELD 2026-09-23. Dated 2026-11-04 so it does not displace the four notes
     already staged for 09-30 through 10-28. The measurement date is 2026-09-23
     and is stated in the text below; the front matter date is the publish slot.
     Before this ships, re-run the suite against grok-4.3 at full reliability.
     This post's own conclusion is that the baseline was measured on half a run,
     and a confirming run either turns this into a real finding or retires it. -->

On 2026-09-23 my drift tracker ran its frozen suite (2026-07-v3) against the live models, same questions, same graders. Grok 4.3 -4.3 pts to 91.4%.

Nothing here is pinned to temperature 0, despite what an earlier version of
this sentence said. None of the eighteen models in the registry accept the
parameter, so it is omitted for all of them and run-to-run sampling spread is
part of every number below.

## The evidence

| claim | how it was checked |
|---|---|
| Grok 4.3 moved -4.3 pts run over run | latest 91.4% vs previous, dated 2026-09-23 |
| the move is larger than this run could print by accident | graded 35 calls, so the floor is 2.86 pts and the move was 4.3 |
| the run was not an outage being scored as a score | reliability 1.0, at or above the 0.5 floor |

## What stayed green anyway

7 of the models that reported this run did not move: GPT-5, GPT-5 mini, GPT-4o mini, GPT-5 nano, Claude Opus 4.8, Claude Haiku 4.5, Grok 4 Fast.

That matters more than the finding does. A board that reports movement every week is measuring its own noise, and the models that held still are the reason the one that moved is worth looking at.

## What this run could and could not have seen

The smallest movement this run could print is 2.94 points at its coarsest. Anything under that is the denominator moving, not a model, and is not reported here at all.

## What I might have wrong

**The baseline is the weak link, and the evidence table above does not check it.**

That table asks whether THIS run was an outage being scored as a score, and
answers with reliability 1.0. It says nothing about the run being compared
against. Measured:

| run | accuracy | reliability |
|---|---|---|
| 2026-09-13 | 95.71% | **0.5143** |
| 2026-09-23 | 91.43% | 1.0 |

The baseline graded roughly half its calls. It cleared the 0.5 floor by four
hundredths. So a full run is being compared against a barely qualifying one,
and a 95.71% computed on half the calls is a much noisier number than the same
figure computed on all of them. Regression to the mean from a noisy high
reading produces exactly this shape.

Two smaller things. The comparison is run over run but not day over day: the
runs are ten days apart, 09-13 to 09-23, so anything xAI shipped in between is
inside the gap. And the post quotes two different resolution floors, 2.86 from
35 graded calls in the evidence table and 2.94 "at its coarsest" further down,
which is the smallest-denominator model on the board rather than this one. Both
are correct and printing them in one post without saying which is which is not.

The honest version of the headline is narrower than the headline: Grok 4.3
measured 4.3 points lower than a baseline that was itself measured on half a
run. The right next step is another full-reliability run, not a post.


---

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

Live board: https://egnaro9.github.io/model-drift/
Suite, graders and runner: https://github.com/egnaro9/model-drift

*Drafted automatically from the run that produced it. The numbers above are generated; the judgement of whether this is worth saying is not.*
