"""Read the committed board history and separate harness failures from model changes.

A task that flips on one model on one day is inside the instrument's resolution
and means nothing. The same task flipping on five providers on the same day is
not five simultaneous regressions — it is the harness. This is a pure read of
dashboard/metrics.json: no API calls, nothing written.
"""

import json
import re
import textwrap

from demos._ansi import amber, dim, faint, fg, red, teal, violet
from modeldrift.flips import analyze, summarize

series = json.load(open("dashboard/metrics.json"))["series"]

for raw in summarize(analyze(series)).splitlines():
    indent = re.match(r"\s*", raw).group()
    body = raw.strip()

    if body.startswith("PROBE ALARM"):
        colour = lambda s: red(s, bold=True)  # noqa: E731
    elif body.startswith(("15 ", "14 ")) or re.match(r"^\d+ (task|single)", body):
        colour = fg
    elif "recovered" in body:
        colour = teal
    elif "broke" in body:
        colour = amber
    elif re.match(r"^\d{4}-\d{2}-\d{2}", body):
        colour = violet
    else:
        colour = faint

    for i, line in enumerate(textwrap.wrap(body, width=80 - len(indent)) or [""]):
        print(indent + ("  " if i else "") + colour(line))

print()
print(dim("  ") + faint("read-only · dashboard/metrics.json · no API calls"))
