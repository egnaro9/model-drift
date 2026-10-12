---
title: "My gate told me what it hadn't checked. I didn't read it."
date: 2026-11-18
kind: gate-defect
about: harness
subject: egnaro9/vac-gate
fingerprint: gate-defect:egnaro9/vac-gate:1a9dc23
destination: https://erikhill.dev/notes/2026-11-18-my-gate-told-me-what-it-had-not-checked/
status: draft
---

# My gate told me what it hadn't checked. I didn't read it.

I write verification gates for a living, more or less. The one in question checks a signed-ish
capability claim: a JSON bundle asserting that some agent passed some task set, with hashes over
the inputs and a recipe for re-earning the verdicts. The gate refuses the bundle unless it holds
up.

It had been passing. It also printed this, on every single run:

```
not run: semantic invalidation: no bindings declared — recorded subject/protocol
         pins were not compared to this consumer's current inputs
```

That is the gate's strongest check. It is the one that asks whether the certificate still
describes reality, rather than whether the certificate is internally consistent. It had never
run. The gate told me so, in the same block as the passes, in a line beginning `not run:`.

I read that output many times. I read it as a pass.

### What the gate got right, which is the interesting part

This is not a story about a badly built gate. The design is better than mine usually are.

It separates its report into `ran:` and `not run:`. It refuses to let an unperformed check read
as a performed one. When I later tried to enable the missing check and got it wrong, the gate
caught that too, with a named reason. And it carries scope lines on every pass stating what a
green result does **not** mean.

The defect was entirely in the reading. A report that distinguishes `ran` from `not run` only
works if someone compares the two lists. I was checking the exit code.

So the gate was honest and the result was still worthless, which is a combination I had not
really considered. I had been thinking about instruments that lie. This one told the truth to
nobody.

### Then the fix nearly became the bug

Enabling the check meant writing a file declaring my current bound inputs. The gate compares
each declared key to the bundle's recorded pin and fails on mismatch. The bundle records:

```json
"subject":  {"id": "claude-code-headless",
             "version": {"model": null, "harness_commit": "7954393", "python": "3.14.6"}},
"protocol": {"task": "machine",
             "hashes": {"taskset_hash": "4430506556753096",
                        "prompt_hash":  "a61a9abe48592e97"}}
```

The obvious way to write that file is to copy those values across. It takes a minute, the gate
goes green, the `not run:` line disappears.

It would also have been worthless, for a reason I want to state precisely, because I nearly did
it. A declared binding is supposed to be **what I am using now**. The recorded pin is **what was
used then**. If I populate "now" from "then," the gate compares a document to itself. It passes
on the day I write it and it passes forever after, including on every day the thing it describes
has changed. It cannot fail. And a check that cannot fail has never passed.

So I derived the two hashes instead, by calling the live code:

```python
from certlab.regrade import FAMILIES
FAMILIES['machine'].taskset_hash()   # '4430506556753096'
FAMILIES['machine'].prompt_hash()    # 'a61a9abe48592e97'
```

They matched. That match is worth something, because it was computed from the current task
definitions rather than read off the certificate. Edit a task and the hash moves and the gate
fires `binding-drift`. That is a live check.

### Three keys I left undeclared, which is the honest part

`model` is recorded `null`. The gate treats a null pin as unrecorded and refuses a declaration
against it, with a comment I now think is the best line in the codebase: a gate that read an
unpinned input as *matching your current one* would be laundering the claim. An explicit "not
pinned" is information. Treating it as agreement destroys that information.

`python` and `harness_commit` describe the subject at certification time. My CI runner is on a
different Python, and the repository has moved on. I do not have a way to read what the subject
runs *today*, so declaring either would mean asserting something I never checked. Same failure
as copying the hashes, wearing a different hat.

The result says `4 declared binding(s) compared, 4 matched exactly`. Not six. Six was available
and would have looked better.

### How I now check that a check can fail

Before trusting the new file, I mutated it, one key at a time, against the gate's own comparison
logic:

```
unmutated            -> PASS
mutate agent_id      -> agent_id:drift
mutate family        -> family:drift
mutate taskset_hash  -> taskset_hash:drift
mutate prompt_hash   -> prompt_hash:drift
add model (null pin) -> model:unrecorded
```

Six lines, and the only ones that convinced me of anything were the five that failed. A green
run tells you the check agrees with the world today. A red run under mutation tells you the
check is attached to the world at all.

### The two questions I keep now

**What did this not check?** Not "did it pass." Any report that separates `ran` from `not run`
is handing you that answer, and I had been throwing it away. If your tooling does not separate
them, that is the first thing to fix, because the alternative is a single boolean that cannot
express "I declined."

**Could this check ever have failed?** Ask it of the check itself, not the system under test. If
the answer involves comparing a thing to a copy of itself, you have built a mirror.

The uncomfortable version, which is why I am writing it down: the gate was well designed, its
output was honest and specific, and it still took me weeks to notice, because `not run:` and
`ran:` both sit under a green check mark. I would like to know how other people surface a
declined check so it cannot be read as a passed one. Failing the build on any skip is the
obvious answer and I do not think it is right, because a legitimately inapplicable check would
then block everything.
