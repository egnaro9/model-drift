---
title: "Our mutation score said 42 of 46 caught. It meant 42 of 46 labelled."
published: false
description: "evalmut takes an eval case your grader already passes, plants a known defect in the output, and reruns the grader. If the grader still passes a provably wrong output, that is a hol"
tags: showdev, testing, ai
canonical_url: https://erikhill.dev/notes/2026-10-14-labelled-caught-is-not-caught/
---

*Originally published at [erikhill.dev](https://erikhill.dev/notes/2026-10-14-labelled-caught-is-not-caught/). The numbers below are checked against the repository they come from.*

# Our mutation score said 42 of 46 caught. It meant 42 of 46 labelled.

**This is a finding about my own tool's evidence, not about its result. The number did not move.**

## What happened

evalmut takes an eval case your grader already passes, plants a known defect in the
output, and reruns the grader. If the grader still passes a provably wrong output,
that is a hole: a class of regression your eval would let ship green.

The honest test of a tool like that is pointing it at its own dependency, so evalmut
runs against gradecore's grader families and the README prints the result:

```
  mutation score    91.3%   (42 caught / 46 applied; 223 n/a)
  holes            4  (2 blind, 2 coverage-gap)
```

I shipped that. Then I went looking at what was behind the word "caught".

## Two facts, and neither of them is "caught"

The run proved gradecore had been imported, via `inspect.getfile`. And it recorded a
label for each row. That was all.

Import plus label does not reach what a reader hears in "caught". Caught says a
grader looked at a defective output and rejected it. Import says the right module
loaded. Between those two sits every way a harness can quietly answer for the
library it claims to be measuring: an adapter that falls back to its own comparison
when the upstream call raises, a cached result, a guard that returns early before
the call happens at all.

The irritating part is that evalmut already shipped the machinery for this. There is
a witness for in-process graders and one for subprocess graders, and the second one
refuses outright any row that arrives without proof. The dogfood demo, the one the
published number came from, used neither.

## The obvious fix would have been a second lie

Count calls into the grader. One per row, done.

That would have been a false witness in both directions, because evalmut's own
operators call the grader while deciding whether they apply. In this run those
probes account for 59 calls. A naive counter would report "multiple calls" on
healthy rows and would be satisfied just as happily by a probe on a row where the
decision never happened.

So every entry is attributed by its caller frame. The call on the decision line
witnesses a decision. The call in the baseline witnesses the clean control. Anything
from the operator module is a probe and satisfies neither. Anything else is
unattributed and fails the row closed.

A row counts as an outcome only when both forms were witnessed. Rows that cannot
show it leave the denominator and are listed as incomplete with a reason. A
population with zero witnessed rows reports null and renders unavailable. Not 1.0,
which is safe arithmetic and unsafe evidence, and not 0.0, which reads as a measured
failure.

## The number did not move

42 of 46. Gated score identical to ungated. Zero incomplete rows, zero unattributed
calls, and the 59 operator probes sorted into a bucket where they count for nothing.

An unchanged number is a bad headline and a good result. If the witness had moved
the score, I would have had a more exciting post and a worse tool, because it would
have meant the old number was counting something other than what it said.

What changed is not the value. Before, 42 rows carried a label. Now 42 rows carry a
label backed by a recorded entry into a named callable and the verdict that came
back out of it.

## The witness shipped with its own broken field

Each witness site records a hash that claims to identify the grader implementation.
I implemented it as a hash of compiled bytecode, which identifies bytecode on one
interpreter instead.

That cost two things. The committed artifact could not verify anywhere except the
machine that produced it, because it was generated on CPython 3.14 and checked by a
3.11 and 3.12 matrix. And worse, bytecode could not distinguish two different
adversarial graders whose instructions match and whose closure constants differ, so
88 witness sites carried one hash for two implementations. A provenance field that
merges two implementations is not weaker evidence. It is wrong evidence.

My first attempt at the portability half was to pin the dependency version in CI.
That could not have worked: the grader source was byte-identical between my checkout
and the published wheel. The variable was the interpreter. Pinning the dependency is
the obvious fix and the wrong one.

And the test that should have caught it had been red since the day it was written:

> It is not a test that broke, it is a test that was born unable to pass, which
> produces the same red and generates none of the urgency.

CI failed on every run from 2026-08-20 and first went green again on 2026-08-30, at
the re-emit that followed the fix. Ten days of red that looked exactly like ordinary
red.

## What I might have wrong

Portability is argued, not proven. The source-text fingerprint should be interpreter
independent, but only one Python is installed on my machine. The CI matrix is the
proof and it fails on whichever leg disagrees, which is the right design and is not
the same as me having verified it.

The witness is a separate command. One subcommand gates rows and the other does not,
and the README banner is still the ungated one. They agree on this suite. They are
not the same claim.

The stamped evidence bundle still carries the unwitnessed run. The witnessed
artifact lives beside it and is not inside the sealed bundle yet.

And one document in the repo currently contradicts another. The README says 91.3%
with four holes. The paper draft still says 91.4% with three. That is mine to fix,
not a rounding difference, and I am pointing at it here rather than quietly
correcting it before anyone notices.

The witness proves entry and return, and nothing else. It says nothing about whether
the grader judged well. A witnessed row is a row whose numbers are about gradecore.
That is the entire claim.

If you publish a score from a harness that wraps someone else's library: ask what
would still be true if the library were never called. If the answer is "the score",
your harness is answering for it.

---

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

The tool, the witness and the dogfood run: https://github.com/egnaro9/evalmut

*Every figure above was checked against the repository before publication. The judgement of whether it was worth saying is mine.*
