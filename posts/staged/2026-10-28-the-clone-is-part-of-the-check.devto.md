---
title: "A shallow clone does not fail your history check. It answers it."
published: false
description: "I committed a new check at 18:44:13 and the run that caught it failing started at 18:44:22. Nine seconds. It had passed locally, 282 tests green. In CI it accused my own commit of "
tags: showdev, testing, ai
canonical_url: https://erikhill.dev/notes/2026-10-28-the-clone-is-part-of-the-check/
---

*Originally published at [erikhill.dev](https://erikhill.dev/notes/2026-10-28-the-clone-is-part-of-the-check/). The numbers below are checked against the repository they come from.*

# A shallow clone does not fail your history check. It answers it.

**I replaced a check that could not tell it had stopped working. The
replacement could not tell either. The commit landed at 18:44:13 and the run
that caught it started at 18:44:22. Nine seconds.**

## What happened

I committed a new check at 18:44:13 and the run that caught it failing started
at 18:44:22. Nine seconds. It had passed locally, 282 tests green. In CI it
accused my own commit of secretly editing the results board that every
published number is derived from.

The failure read:

    board commits that are neither the probe nor a declared human edit:
      e9f904c5 by egnaro9: Stage the guard-sibling note, with the fifth
      instance and its probe

That commit adds a blog post. It does not touch the board, and it never has.

The check existed because I had just switched off an older one that compared
the board against a second, hosted store. Switched off, not deleted: it is
still in the file, skipping now with its reason stated. Before that it had
spent twenty-four days reporting green without running, because the store it
queried was retired in August and an unreachable store is not the same fact as
a disagreeing one. Fifty-seven CI runs passed while it compared nothing, each
printing `207 passed, 1 skipped`.

So the replacement asks git instead, because git is already there and cannot be
retired: **has the board been edited outside the run that produced it?** Every
change is a commit with an author and a subject. The probe writes
`chore: update drift standings`. A deliberate human edit says `board:` and
explains itself. Anything else is a stray. And on my laptop, that worked.

## The clone was the problem, and the clone had no error to give

CI checks out at the default depth of 1. My laptop has the full history.

A shallow clone does not make `git log -- <path>` fail. It does not make it
empty. The single fetched commit has no parent, so by parent list a shallow
boundary and a genuine root commit are **the same shape**, and the log answered
as though that commit had created the file.

Measured on two clones of the same repository, at the same commit, minutes
apart:

| question | full clone | depth-1 clone |
|---|---|---|
| commits touching the board | 26 | 1 |
| which commit created it | `9ee59e3` "board: publish the floor..." | `600d503` |
| lines that commit added to it | 0, it never touched the file | 33,403 |

That last row is the whole post. Git reported a 33,403-line insertion that
never happened, attributed it to the person who pushed last, and my check read
that number and did exactly what it was built to do.

## Git did tell me. I did not ask.

I wrote the paragraph above claiming git has no way to signal this. That was
wrong, and an adversarial re-check of my own draft caught it before this went
out. The signal exists and it is one flag away:

    $ git log --diff-filter=A --decorate -- dashboard/drift_board.json
    600d503 (grafted, HEAD -> main, origin/main) A shallow clone does not...

`grafted` is git saying precisely what I needed, per commit rather than per
repository, so it marks exactly which log lines are untrustworthy. The full
clone prints no such marker on the real creating commit. It survives
`--no-decorate` being the scripting default, which is the point: nobody adds
`--decorate` to a query they intend to parse.

So the honest claim is smaller and more useful than the one I made. Git does
not tell you by default, and the field that would tell you is one nobody reads.
The answer was sitting in the output I chose not to ask for.

(Measured on git 2.50.1 only. I have not checked older versions.)

## The guard I had already written for this did not fire

I had anticipated the empty case. The check opened with:

    assert subjects, "no history for the board; this check did not actually run"

That assertion is correct and it is useless here, because the result was not
empty. It was a list of one. A vacuity guard asks "did I get nothing?" and the
shallow clone's answer is "no, you got something." The failure mode I needed to
survive was never absence. It was **a confident, plausible, wrong answer**,
which is the only kind a provenance check cannot survive.

## And the sibling thirty-six lines below already had the fix

`.github/workflows/ci.yml` has two jobs that check out the repository. The
second one already carried this, with a comment explaining why:

    fetch-depth: 0        # the stamped commit must be reachable

The first one did not. Line 29 and line 65 of the same file, one guarded for
an unrelated reason and one not. I added a check that needed full history to the
job that did not have it, in a file that visibly contained the answer.

## How it was found at all, which is the part I got lucky on

Not by reading the email. By a different probe, built earlier the same evening
for that problem, which reports for every scheduled workflow how
many consecutive runs and how many days its verdict has held, and when it was
last green. Run it and one line said:

    NEW RED   model-drift   draft.yml   1 runs / 0d, NEVER green in the window

`NEVER green in the window` means no run it looked at was green. The tool's
own wording is "may never have passed at all" and that hedge is load-bearing:
it reads a fixed number of recent runs, so a long enough red streak is
indistinguishable from a check that has never passed. Here it was the strong
reading, because the workflow had run exactly once. That was a second, unrelated instance of the same family:
a workflow that finds a regression, writes it up, pushes the branch, and then
fails on the final step whose only job is to open a pull request and tell
somebody. The finding existed, complete, in a place nobody would look.

**A notification system that fails at the notification step produces silence,
and silence is indistinguishable from having nothing to report.**

One thing limited the damage, and it is narrower than I first wrote. The code
records "I have already drafted this finding" into the *same commit* as the
draft itself. So an unmerged draft leaves the main ledger untouched and the
finding gets offered again on the next run. Had the ledger been written
separately, the run would have marked the regression seen while the only copy
sat on an abandoned branch, and it would never have been raised again.

That is a re-offer guarantee, not a save. The draft itself is gone: I deleted
the branch, and the commit survives only as an unreachable SHA waiting on
garbage collection. I kept a bundle, which is me being careful rather than the
system being safe. And the workflow's own pull request body told the reader the
opposite, that closing the PR records the finding as seen and it will not be
offered again, which was false for exactly the same reason. I fixed that text
while writing this.

None of that is a design I can claim credit for foreseeing. I noticed it while
checking whether I had lost anything.

## What I did about it

Both layers, because either one alone rots:

The workflow now fetches full history. That is the one-line fix and it is the
less important one, because a workflow file is a different file and will drift
again.

The check now refuses to answer from a clone that cannot answer. It runs the
log, asks `git rev-parse --is-shallow-repository`, and throws the answer away
with the remedy in the message rather than reporting a fabricated stray.
Refusing before the result is USED is the part that matters; refusing before it
is fetched would be tidier and buys nothing.

The predicate is a plain function taking the flag and the commit count, so it
can be handed the shallow case directly, which a real clone cannot be made to
do inside a test run. The case that bit me is now
`test_a_shallow_clone_is_refused_even_though_it_answers`: shallow with one
commit must be refused, even though one passes every vacuity check ever
written.

Proof on a single clone: shallow, two failures naming `fetch-depth`. Then
`git fetch --unshallow`, same clone, same file, thirteen passed. Five of five
mutations caught.

## What I might have wrong

The general claim I want to make is "check the integrity of your environment,
not just your reading of it," and I am not sure that generalizes without
becoming unfalsifiable. Every check runs in an environment. You cannot verify
all of it. I can defend the specific version: if your instrument reads
something the CI runner is free to configure, the configuration is an input to
your instrument and belongs inside it.

I also do not know how common this is outside git. Git is unusual in that a
truncated history is a *supported*, first-class state with no error attached.
Most tools that cannot see something say so. The reason this was invisible is
partly specific to git, and I might be over-reading it as a pattern.

And the honest one. The post I wrote earlier the same evening is about guards
that return a plausible number instead of throwing. I wrote it, staged it, and
then committed exactly that defect, into the file that already contained its
own fix, where I could see it. Knowing the shape of a bug does not appear to
help much at the moment you are writing it. What helped was an unrelated probe
asking a question I had not thought to ask.

If you keep a check that reads git history: clone it shallow and run it. If it
passes, it is not reading what you think it is reading.

---

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

Live board: https://egnaro9.github.io/model-drift/
Suite, graders and runner: https://github.com/egnaro9/model-drift

*Every commit referenced above is public. The two-clone comparison was re-measured while writing this, not copied from the commit message.*
