---
title: "The gate could not see what it was gating"
date: 2026-10-02
kind: gate-defect
about: harness
subject: egnaro9.github.io/claim-gate
fingerprint: gate-defect:egnaro9.github.io/claim-gate:47f82a1
destination: https://erikhill.dev/notes/2026-10-02-the-gate-could-not-see-what-it-was-gating/
status: draft
cadence_exception: pre-registered cadence test, 2026-09-23. Publishes 48h after 2026-09-30 to break the cadence/account-age confound. See POSTING_AB_LOG.md.
---

# The gate could not see what it was gating

**This is a finding about my own tooling. The gate it describes is mine, and so is the hole.**

## What happened

I keep a pre-commit hook on my portfolio repo that refuses a commit touching a
claim-bearing file unless a receipts file carries a receipt for it. It never judges
whether a claim is true. It checks that a receipt exists and that its pointer
resolves: a local path has to exist, an https pointer has to answer 2xx. Prose alone
cannot satisfy it.

For four days, any file that had been reviewed once was exempt from review forever.

## The defect is one line

```sh
LINE=$(grep -F -- "$f ::" "$ACK" 2>/dev/null | head -1)
```

`head -1` on a pathname. The first line in the receipts file that mentioned the path
won, whatever it said and whenever it was written. A receipt recorded for an earlier
version of a file kept satisfying every later version of it.

So the gate reported success along a path where it never examined the staged
content. That is the precise failure I build tooling to find, sitting in the tooling
I built to find it.

## The evidence

| claim | how it was checked |
|---|---|
| the defect line existed | `git show 47f82a1^:.githooks/pre-commit` line 61, the `head -1` shown above |
| the window was four days | the hook's full history is four commits: installed `c9af511` 2026-08-23, fixed `47f82a1` 2026-08-27 |
| selection is now by blob | the fix reads `BLOB=$(git rev-parse ":$f")` and greps `":: blob $BLOB"`, so line order decides nothing |
| a stale receipt is now refused by name | the hook prints `no receipt carries the staged blob $BLOB` |
| six tests did not catch it | `tools/test_claim_receipt_blob.py` has 7 tests; the seventh is the one that kills the mutant |
| I re-ran the mutant while writing this | baseline 7 passed. Truncating the comparison to `${BLOB:0:4}`: 1 failed, 6 passed, and the failure is `test_a_blob_prefix_is_not_a_blob` |

## What found it, and what did not

I wrote six tests for the fix. A receipt for the previous blob is refused. The
refusal names the blob. A legacy path-only receipt satisfies nothing. An honest
receipt passes. A stale line sitting first does not shadow a correct one below it. A
stale override is refused too, because an escape hatch that never expires is the
same hole.

All six passed. Then I mutated the guard: compare only the blob's first four hex
characters.

All six still passed. The hole was still open.

The seventh test is the one that kills that mutant, and its docstring says so:

> Found by mutation, not by inspection: truncating the comparison to the blob's
> first four hex characters survived every other test in this file.

Six is not a coverage number. It is how many tests I wrote before I felt finished,
and my sense of finished ran out exactly one test before the bug did.

## I had already written the symptom down and filed it wrong

Two days before the fix, in a different commit, I described this:

> passing needed two receipts for one file in a specific order, because the generic
> loop reads the first matching line only. That ordering was load-bearing and
> recorded nowhere.

I noticed that line order was deciding outcomes. I filed it as a documentation gap.

It was the bug. Inspection had the evidence in hand and did not convert it into a
failing test, because inspection asks what I believe the code does. Mutation does
not ask. It breaks the code and reports which assertion noticed.

## What I might have wrong

The hook's own header states the residual and I am not going to soften it: `git
commit --no-verify` skips every client-side hook, so no local hook is a complete
policy boundary. This gate stops an accident. It does not stop a decision.

I know the window and not the damage. Four days is a fact about dates. I did not go
back and check whether any claim actually shipped through the hole while it was
open, so I cannot tell you the blast radius, only its duration.

The receipts file is gitignored, so my own migration state is not independently
checkable by a reader. Take that part on my word or leave it.

And the mutation was hand-applied by me to a shell script, which means the operator
set is whatever I happened to think of. That is the same limitation that produced
the six-test blind spot in the first place, one level up.

If you have run mutation testing against your *guard* code rather than your product
code, I would like to know what it killed that you were sure was fine.

---

I build deterministic evaluation and verification tooling for LLM systems, and I am looking for my first full-time role in AI evaluation or QA engineering. Remote US Eastern, or Charleston SC. https://erikhill.dev

The gate, its tests and the fix: https://github.com/egnaro9/egnaro9.github.io

*Verified by re-running the mutant against the committed hook while writing this. The judgement of whether it was worth saying is mine.*
