---
title: "A check that cannot fail has never passed"
date: 2026-11-11
kind: defect-class
about: harness
subject: harness/staleness-checks
fingerprint: defect-class:harness/staleness-checks:d39bc74
destination: https://erikhill.dev/notes/2026-11-11-a-check-that-cannot-fail/
status: draft
---

# A check that cannot fail has never passed

version







Yesterday I went to verify a number in my own portfolio: ten repositories, a recorded total of
290 tests. I ran every suite. The real number is 683 passing, and nine of the ten per-repo
figures I had written down were wrong.

That is not the interesting part. The interesting part is why nothing told me.

### 1. The build that reported a number it did not measure

One repo is a Java engine with 59 tests. I ran `./gradlew test`, parsed the JUnit XML, and got
59 passed, zero failures. Correct answer.

Then I read the console output properly:

```
5 actionable tasks: 5 up-to-date
```

Gradle had decided nothing changed and skipped the task. The XML I parsed was from an earlier
run. The number was right by luck, and I had measured a file, not a test suite. Forcing it with
`clean test` gives a bare `> Task :test` with no `UP-TO-DATE` suffix, and an XML timestamp from
seconds ago rather than days.

If that suite had been broken since the last build, I would have reported it green, with
evidence, from a file.

### 2. The suite that reports zero tests instead of failing

Another repo keeps persistence behind an optional extra, which is a reasonable design: the base
install runs in memory and needs no ORM. Its test suite does not. On a base install:

```
ImportError while importing test module 'tests/test_store.py'
E   ModuleNotFoundError: No module named 'sqlalchemy'
!!!! Interrupted: 1 error during collection !!!!
```

pytest never collects a single test. The output contains no count at all. If a pipeline keys on
"did any test fail", the answer is no, because no test ran. CI installs the dev extra and gets
29 passing, so CI is honest; the trap is anyone, including me, running the documented base
command and reading the quiet as calm.

### 3. The badge that had drifted by 163

The same audit against public surfaces: a tests badge reading 198 where execution gives 361. Six
of nine public claims understated. One README's prose said 39 while its own badge, in the same
file, said 42.

Understating is the benign direction, and I will take it over the alternative. But a README that
disagrees with itself gives a reader no reason to trust either number, and that costs more than
being three low.

### 4. The one that changes how I build checks

I keep a set of durable notes, each carrying a small shell command whose job is to detect that
the note has gone stale. The format stores the command and its expected output.

28 of 97 of those commands had recorded their own error as the expected output.

The cause is one missing separator. The field held the command and a human annotation with
nothing between them, so the annotation became arguments:

```
grep applicationId app/build.gradle -> must still read "com.example" (line 8 today); ...
zsh: no matches found: (line 8 today)
```

The shell aborts at glob expansion. `grep` never runs. Whatever wrote the baseline recorded the
failure, and the failure reproduces perfectly, every time. **The check agreed with itself on
every evaluation it ever made.** One of them had been pinning a repository's HEAD commit to a
date three months stale.

Then, repairing them, I wrote a check to count how many were still broken. It took three tries,
and all three failed the same way:

1. Count occurrences of the error pattern across the notes. Returned one too many: it matched
   the pattern quoted in its own prose.
2. Narrow to the right field. Returned one too many again: the pattern appeared inside its own
   command, because the command searches for it.
3. Slice off everything before the separator and search only the recorded output. Correct.

Each fix was a real narrowing, and each one still counted itself. A measuring instrument stored
alongside the things it measures will include itself unless the unit explicitly excludes it.

The fourth failure was the best one. Repairing the last note drove the count to zero, and
`grep -c` exits non-zero on zero matches, so the check went red at exactly the moment it should
have gone green, and would have become the 28th instance of the defect it documents.

### The thing they share

None of these are bugs in the usual sense. Nothing crashed. Every signal was green, and the
green was not false, it was empty. A skipped task, an uncollected suite, a baseline equal to its
own failure mode: each produces a passing result over a value that was never measured.

So the question I now ask of anything that reports a verdict is not "does it pass?" but **"what
would make this go red, and has it ever gone red?"** A check with no demonstrated failure mode is
a check with no demonstrated anything.

Which is easy to say and genuinely hard to apply to monitors, because a monitor cannot fail on
clean data by design, so you cannot mutation-test it the way you would a function. The only way
I have found that works is to pull the predicate out of the monitor and test the predicate.

I would like to be argued with on that last point, because it is the part I am least sure of.
