---
title: "The guard was applied once. Its sibling read the same data without it."
published: false
description: "In one session across three repositories I fixed five separate defects. They looked unrelated while I was fixing them. Four are the same bug, and the fifth is the version of it tha"
tags: showdev, testing, ai
canonical_url: https://erikhill.dev/notes/2026-10-21-the-guard-and-its-sibling/
---

*Originally published at [erikhill.dev](https://erikhill.dev/notes/2026-10-21-the-guard-and-its-sibling/). The numbers below are checked against the repository they come from.*

# The guard was applied once. Its sibling read the same data without it.

**This is a finding about five of my own tools, including one I wrote that night to catch this exact thing.**

## What happened

In one session across three repositories I fixed five separate defects. They
looked unrelated while I was fixing them. Four are the same bug, and the fifth
is the version of it that has no code in it at all.

In every case the code knows a rule, applies it correctly at one call site, and
then a second path reads the same data with the rule missing. Nothing goes red,
because both paths return numbers that look fine.

## The four in code

**A grader that scored silence as a pass.** Accuracy is
`graded_pass / graded_total`, and a provider error leaves the case ungraded. The
per-category breakdown, twenty lines away, counted a case as OK when it was `not
flagged`, and `flagged` is `passed is False`. `None is False` is `False`. So a
model that returned nothing printed `acc 0%` beside `instruction-following 100%`
in all nine categories, on the same line, on runs where 35 of 35 calls returned
HTTP 402.

**A flip detector reading rows a floor had already rejected.** The board applies
a reliability floor to the accuracy path. The flip analysis, in the file next to
it, applied nothing, so it read `fails` arrays from runs written before an
earlier fix, when absent calls were scored as wrong answers. Measured: 255
cross-provider alarm days became 159, and 106 repeat offenders became 39. Five
alarm tasks were provider outage in their entirety. Sixty-three percent of that
backlog was never a finding.

**A tool that checked one half of its own output.** I wrote something that
reports which conversation threads are owed a reply, because a post I cannot
work should not go out. It fetches links, and it HEAD-checks the ones it
*quotes*, because a quote nobody can open is a quote of nothing. It did not
check the ones it *counts*. It reported six threads owed. Two resolved. One was
a crypto recovery scam the platform had already removed and three had authors
who were suspended.

**A commit gate that never looked at the commit.** A pre-commit hook refuses a
change to a claim-bearing file unless a receipt exists for it. Receipt selection
was `grep -F "<path> ::" | head -1`. The first line mentioning the path won,
whatever it said and whenever it was written, so a file reviewed once was exempt
from review forever. Four days, and six tests did not catch it. Mutation testing
did.

## And the fifth, which has no sibling to blame

The same night, a notification email turned out to be the twenty-fourth in a
row. A test that compares my board against a second store had been failing
since the day that store's write path was retired. It compares by run date, the
second store froze, the board kept advancing, so every model skipped and the
test hit its own guard:

    assert compared, "no model could be compared; the agreement check did not
    actually run"

That assertion is the test being right. It refuses to report success having
compared nothing. Every red was true.

There was no missing guard here. The guard was perfect. What was missing is
that nothing watched whether it could ever pass again, and a true alert that
repeats daily decays into furniture faster than a false one, because a false
alarm at least gets investigated once. Twenty-four emails, and the only reason
the twenty-fourth got read is chance.

So the pattern is wider than a call site. **A rule that lives in one place and
is not counted anywhere will be quietly opted out of**, and that includes being
opted out of by time.

## The evidence

| claim | how it was checked |
|---|---|
| five defects, one shape, three repositories | commits `125b9df`, `d8edf35`, `b67f341` in model-drift, `47f82a1` in the site repo |
| the outage case printed 0% and 100% together | the run log for three models, 35 of 35 calls returning 402 |
| the flip filter changed the numbers by this much | re-ran the analysis over the same stored board: 255 to 159 alarm days, 106 to 39 repeat offenders |
| the thread counter was wrong by a factor of three | curl on all six permalinks: two returned 200, four returned 404 |
| six tests missed the gate defect and mutation found it | the seventh test's docstring names the surviving mutant; re-running it gives 6 passed, 1 failed |
| the rule has more consumers than you would guess | the reliability floor is imported by five files in one package |
| the store-agreement check was red for 24 consecutive days | its last green run was 2026-08-30; the frozen archive's newest row is the same date |

## Why none of them went red

A guard that is missing does not throw. It returns a plausible number.

Both halves of every pair above produced output a reader would accept. `acc 0%`
is a number. `106 repeat offenders` is a number. `6 threads owed` is a number.
`head -1` returns a line. Nothing crashed, nothing was empty, and no test failed,
because the tests asserted that the guarded path was guarded, which was true.

The shape is: **a rule is a property of a value, and it gets implemented as a
property of a call site.** Once the rule lives in a call site, adding a second
reader of the same value is an ordinary, blameless change that silently opts out.

## What I did about it

For each one, the fix was two lines and the test was the work. But fixing five
instances is not the same as fixing the class, and the class is what generates
instances.

The cheap structural version is to count the consumers. The reliability floor is
imported by five files. A test that asserts five, and names them, goes red when
someone adds a sixth that does not apply it. That converts "a new reader silently
opts out" into "a new reader fails the build until it opts in".

It is not elegant and it does not prove anything about correctness. It changes
the default from silence to noise, which is the only property that matters here.

For the fifth I built the other half: a probe that reports, for every scheduled
check, how many consecutive runs and how many days it has held its current
verdict, and when it was last green. Not whether it is red. How long it has
been red, because that is the number that separates a failure from a decision
nobody made. It also reports "never green in the window", which is the
signature of a check that was born unable to pass.

## What I might have wrong

Five instances in one session is a small sample, and I found them because I was
already looking at that layer. There is an obvious selection effect: I have no
idea how many guards in this estate have exactly one consumer and are therefore
fine, so I cannot tell you the rate, only that it happened five times in a night.

The counting test is also weaker than it sounds. It catches a new file that
imports the rule and ignores it. It does not catch a new file that re-implements
the rule slightly differently, which is the more likely failure once people know
the count is being checked. Goodhart applies to your own guards.

And the honest one: two of the five were in code I wrote that same night,
including the tool whose entire job is to check that links resolve before
trusting them. I did not fail to know the rule. I knew it, wrote it down in a
docstring, and applied it to one of the two places in the same function that
needed it.

If you keep a rule like this, a floor, a filter, a validity check: grep for its
name and count the files. Then ask, for each one, whether that file applies it
or merely mentions it. The gap between those two numbers is the one I keep
finding.

---

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

Live board: https://egnaro9.github.io/model-drift/
Suite, graders and runner: https://github.com/egnaro9/model-drift

*Every commit referenced above is public. The numbers were re-measured while writing this, not copied from the commit messages.*
