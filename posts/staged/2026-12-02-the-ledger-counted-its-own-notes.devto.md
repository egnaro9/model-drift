---
title: "The ledger counted its own notes as work"
published: false
description: "I audited an append-only ledger before switching a pipeline back on. 1010 lines, zero parse errors. Counting the rows that said an action was taken gave 322. The real number was 293."
tags: showdev, datascience, python, debugging
canonical_url: https://erikhill.dev/notes/2026-12-02-the-ledger-counted-its-own-notes/
---

*Originally published at [erikhill.dev](https://erikhill.dev/notes/2026-12-02-the-ledger-counted-its-own-notes/). The numbers below are checked against the repository they come from.*

I have an automated pipeline that does a thing many times, and writes one JSON line per thing
it did to an append-only file. That file has two jobs. It is the audit record, and it is the
deduplication index: before acting on an item, the pipeline checks whether that item's id is
already in the file.

I was auditing the pipeline before switching it back on after a long pause. The file parsed
clean. 1010 lines, zero malformed. Every id looked like an id. So I counted the rows that said
the pipeline had acted:

```
kind: item, action: sent   ->  322
```

322. That is the number I would have quoted, and it would have been wrong by 29.

### What 29 of those rows actually were

(Field names anonymized; structure and every number are as they are on disk.)

Some of the rows looked like this:

```json
{"kind":"item","action":"sent","id":"4445602725","target":"...","ts":"..."}
```

And 29 of them looked like this:

```json
{"kind":"item","action":"sent","id":"SWEEP-2026-07-28T14-07Z",
 "target":"SWEEP 2026-07-28T14:07Z (10:07 EDT 07-28). Three new alerts since the
 last marker. SENT: ... SKIPPED: ... QUEUED next run if pools thin: ...",
 "ts":"..."}
```

That is a diary entry. At some point a run wanted to leave a note for the next run, and the
append-only file was right there, so the note went in the file. To make it go in, it had to
have the fields the file takes. So it got `kind: item` and `action: sent` and an id, and
from that moment it was indistinguishable, to anything that counted, from a real record.

29 of 322, which is 9.0 percent. The true figure is 293.

Nothing was corrupted. Nothing failed to parse. Every field was the right type. A schema
validator would pass this file today, because `id` is a string and `"SWEEP-2026-07-28T14-07Z"`
is a string.

### The second defect, which is the one that would have cost something

While I was in there, I checked the other half of the file's job. Deduplication works by
looking up a bare numeric id, because that is the id shape the upstream system uses:

```
4466364036
```

587 of the stored ids are bare numerics. Good, the format has not drifted. But 6 real records
are stored like this:

```
insightglobal-ai-engineer-4443156560
catch-talent-fullstack-swe-4441550766
sherlock-swe-internal-tools-4441043465
dewinter-ai-automation-agent-developer-4439531913
the-agentic-loop-generative-ai-engineer-4444903120
veridian-tech-ai-engineer-4444032322
```

The real id is right there, on the end of each one. And a lookup for `4443156560` finds
nothing, because the stored string is not that string. I checked whether any of those six bare
ids appear anywhere else in the file as a separate row. None of them do.

So the dedup index silently does not cover 6 of its 293 records, and the pipeline would act on
all six a second time. About 2 percent. Small, but note the failure mode: **acting twice looks
exactly like acting once.** There is no error, no retry, no alert. The second action succeeds.
The only way to see it is to go and look at the ids.

### A third shape, found while writing the fix

Writing the matching rule turned up a form I had not looked for. 23 rows pack several ids
into one field:

```
4446038970+4446048745+4446059027+4446041912
```

Counting every id in every field, not just the first:

```
152  plus-joined
 27  slug
  6  slug, in the rows that record an action taken
  1  other
```

**160 distinct ids are invisible to an exact-id lookup**, not 6. The 6 are only the ones in
rows that record an action, which is why they are the ones that would cause real damage; the
rest would merely re-surface items already triaged.

And the part I would rather not include, which is exactly why it belongs here: **my first
version of the fix was wrong.** I wrote a matching rule that said "the id equals the target,
or ends with `-<target>`". That handles the slugs. It misses all 152 of the plus-joined ones,
because there the id sits in the middle. I only caught it because I ran the classifier again
afterwards and the number did not go to zero.

The working rule splits on both separators and compares tokens:

```python
def tokens(i):
    return [t for t in re.split(r'[-+]', str(i)) if t]
```

Two characters of difference between a fix that works and a fix that looks like it works.

### Why counting could not find either of these

I did not find these by counting. Counting is what produced the wrong number in the first
place. I found them by classifying: writing a function that puts every row into exactly one
bucket, and then looking at the buckets.

```python
def classify(row):
    i = str(row['id'])
    if i.lower().startswith('sweep'):          return 'NARRATION'
    if i.isdigit() and len(i) == 10:           return 'OK'
    if re.search(r'\d{10}', i):                return 'SLUG_RECOVERABLE'
    return 'NO_ID'
```

```
OK                287
NARRATION          29
SLUG_RECOVERABLE    6
NO_ID               0
```

Four lines of logic, and both defects fall out of it. The `NARRATION` bucket should not exist
and it has 29 rows in it. The `SLUG_RECOVERABLE` bucket should not exist and it has 6.

A count gives you one number and no way to ask whether it is the right kind of number. A
classification gives you a bucket per kind, and an unexpected bucket is a finding. If you have
ever written `len([x for x in rows if x['status'] == 'done'])` and quoted the result, you have
done the thing I did.

### What I would change, and what I would not

The fix for the slugs is three lines: extract the trailing digits. I will do that.

The fix for the narration is not a parser change. It is that an append-only record and a
scratchpad for notes are two different files and I let them be one file. The notes were useful.
They just should not have been able to put on the costume of a record in order to get stored.

The general version, which is the only part of this worth keeping:

**A field being the right type is not the field being the right kind of thing.**
`isinstance(x, str)` was true for every single one of these. Validators check types. They do
not check whether the row is the kind of row the file is for. When one artifact serves two
purposes, the second purpose eventually writes something in the shape of the first, and from
then on your counts are a mixture, and the mixture is invisible by construction.

---
