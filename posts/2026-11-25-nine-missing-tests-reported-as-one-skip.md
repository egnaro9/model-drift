---
title: "Nine missing tests reported as "1 skipped""
date: 2026-11-25
kind: evidence-gap
about: infrastructure
subject: egnaro9/agent-graph
fingerprint: evidence-gap:egnaro9/agent-graph:0e2b468
destination: https://erikhill.dev/notes/2026-11-25-nine-missing-tests-reported-as-one-skip/
status: draft
---

# Nine missing tests reported as "1 skipped"

I was correcting a stale badge on one of my repos. The README claimed 30 tests; running the
suite gave 33. Fine, bump the number, move on.

Except the file defines 36.

Three tests existed that pytest never collected, and I could not explain the gap from the
summary line, which read:

```
33 passed, 1 skipped in 0.40s
```

One skip. I had assumed one test.

### The arithmetic

Parsing the test files with `ast` rather than grep, so parametrization and nesting could not
confuse the count:

```
36 test functions defined   (no duplicates, none nested, none in classes)
 -9  tests/test_rag.py, never collected
 +6  parametrize expansions (a 5-value list and a 3-value list, from 2 definitions)
 ---
33 collected
```

Two changes in opposite directions, nine months apart, that happened to nearly cancel. The
badge was wrong, the suite was green, and the net number looked plausible enough that I almost
just wrote 33 and left.

### One skip, nine tests

Line 4 of the uncollected file:

```python
ragevallab = pytest.importorskip("ragevallab", reason="optional rag extra")
```

At module scope, `importorskip` raises during collection. The whole file is skipped, and the
summary reports that as a single skip. Nine tests absent, one line of output, no indication of
magnitude. If those nine had been nine separate module-level skips in nine files, I would have
seen `9 skipped` and looked immediately.

So: how long had they been skipped? The extra is a git dependency:

```toml
rag = ["ragevallab @ git+https://github.com/egnaro9/rag-eval-lab@main"]
```

And the workflow installs:

```yaml
pip install -e ".[dev]"
```

`git log -p` on that workflow file returns exactly one change to that line: the commit that
created the repository. **The extra had never been installed in CI. Those nine tests had never
run, once, in the repository's entire history.**

### The part that actually stung

The nine were not peripheral. The file's docstring:

> The agent's search tool backed by rag-eval-lab's retriever (arrow 1 of the stack).

They are the cross-repository integration tests. This repo is an agent; another repo is a
retrieval pipeline; the claim that one is wired to the other is the only claim in the project
that is about more than one project. That is the part with no coverage. The calculator guard had
ten tests. The thing that made it a system had nine, and they never ran.

I do not think that is a coincidence. The tests that are cheap to run get run. A test needing an
optional dependency, a database, a built artifact, or a second service is the test most likely
to be quietly excluded, and it is also the test covering the integration you cannot verify any
other way. The exclusion mechanism selects against exactly the coverage that matters most.

### They pass

Installing the extra and running the file: `9 passed in 0.37s`.

That is the good version of this. The coverage exists and is correct; it was simply never
reached. The bad version is where you reach a long-unrun test and discover it rotted against an
API that changed under it, which is a different afternoon.

The fix was one line, `".[dev]"` to `".[dev,rag]"`, and the count went 33 to 42. Which means the
badge I had been about to correct from 30 to 33 was wrong in both directions at once: too low
for what exists, too high for what CI verified.

### What I changed about how I read a suite

Not "is it green". Three questions now:

1. **How many tests are defined, and does that match how many ran?** Different numbers, counted
   different ways. `ast` for defined, the runner for collected. They should reconcile, and if
   they do not, the difference is the interesting part.
2. **What does each skip actually cover?** A skip count is a count of skip EVENTS, not of
   skipped tests. One module-level skip can hide an arbitrary number.
3. **Has this test ever passed?** Not "is it passing", which a never-collected test answers
   vacuously. `git log -p` on the CI config answers it faster than reading the test.

The one I keep coming back to: a skip is reported in the same breath as a pass, in the same
summary line, in a tone that invites you to move on. It is the only test outcome that means "we
do not know" while reading like "fine".

If you run a suite with optional extras, I would genuinely like to know how you keep the
optional path honest. A matrix leg is the obvious answer and it doubles CI time, and I am not
sure that is the right trade for every repo.
