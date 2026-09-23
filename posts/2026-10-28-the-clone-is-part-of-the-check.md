---
title: "A shallow clone does not fail your history check. It answers it."
date: 2026-10-28
kind: defect-class
about: harness
subject: estate/instrument-environment
fingerprint: defect-class:estate/instrument-environment:2026-09-23
destination: https://erikhill.dev/notes/2026-10-28-the-clone-is-part-of-the-check/
status: draft
---

# A shallow clone does not fail your history check. It answers it.

**I replaced a check that could not tell it had stopped working. The
replacement could not tell either. It failed that way on its first run, about
ninety minutes after I wrote it.**

## What happened

I had just deleted a test that compared my results board against a second,
hosted store. That test had spent twenty-four days reporting green without
running. The store it queried was retired in August, and an unreachable store
is not the same fact as a disagreeing one, so the check skipped. Fifty-seven CI
runs passed while it compared nothing.

The replacement asks git instead, because git is already there and cannot be
retired: **has the board been edited outside the run that produced it?** Every
change is a commit with an author and a subject. The probe writes
`chore: update drift standings`. A deliberate human edit says `board:` and
explains itself. Anything else is a stray.

It passed locally, 282 tests green. I pushed it. CI went red, and the failure
said this:

    board commits that are neither the probe nor a declared human edit:
      e9f904c5 by egnaro9: Stage the guard-sibling note, with the fifth
      instance and its probe

That commit does not touch the board. It adds a blog post.

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

## And the sibling thirty lines below already had the fix

`.github/workflows/ci.yml` has two jobs that check out the repository. The
second one already carried this, with a comment explaining why:

    fetch-depth: 0        # the stamped commit must be reachable

The first one did not. Same file, thirty lines apart, one guarded for an
unrelated reason and one not. I added a check that needed full history to the
job that did not have it, in a file that visibly contained the answer.

## How it was found at all, which is the part I got lucky on

Not by reading the email. By a different probe, built earlier the same evening
for that problem, which reports for every scheduled workflow how
many consecutive runs and how many days its verdict has held, and when it was
last green. Run it and one line said:

    NEW RED   model-drift   draft.yml   1 runs / 0d, NEVER green in the window

`NEVER green in the window` is the signature of a check that has not passed
since it was written. That was a second, unrelated instance of the same family:
a workflow that finds a regression, writes it up, pushes the branch, and then
fails on the final step whose only job is to open a pull request and tell
somebody. The finding existed, complete, in a place nobody would look.

**A notification system that fails at the notification step produces silence,
and silence is indistinguishable from having nothing to report.**

One thing saved that: the code records "I have already drafted this finding"
into the *same commit* as the draft itself. So the failed run lost both
together and the finding will be offered again. Had the ledger been written
separately, the run would have marked the regression seen while the only copy
sat on an abandoned branch. That is not a design I can claim credit for
foreseeing. I noticed it while checking whether I had lost anything.

## What I did about it

Both layers, because either one alone rots:

The workflow now fetches full history. That is the one-line fix and it is the
less important one, because a workflow file is a different file and will drift
again.

The check now refuses to answer from a clone that cannot answer. It reads
`git rev-parse --is-shallow-repository` first and fails with the remedy in the
message instead of reporting a fabricated stray. The predicate is a plain
function taking the flag and the commit count, so it can be handed the shallow
case directly, which a real clone cannot be made to do inside a test run. The
case that bit me is now a named test: `shallow, 1 commit` must be refused,
even though `1` passes every vacuity check ever written.

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
