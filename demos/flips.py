"""Read the committed board history and separate harness failures from model changes.

A task that flips on one model on one day is inside the instrument's resolution
and means nothing. The same task flipping on five providers on the same day is
not five simultaneous regressions — it is the harness. This is a pure read of
dashboard/drift_board.json: no API calls, nothing written.
"""

import json
import re
import textwrap

from demos._ansi import dim, fail, ident, muted, ok, text, warn
from modeldrift.flips import analyze, summarize

series = json.load(open("dashboard/drift_board.json"))["series"]

for raw in summarize(analyze(series)).splitlines():
    indent = re.match(r"\s*", raw).group()
    body = raw.strip()

    # Colour by what the reader should do about the line, not by its shape.
    if body.startswith("PROBE ALARM"):
        paint = lambda s: fail(s, bold=True)  # noqa: E731 — stop and check the harness
    elif re.match(r"^\d+ (task|single)", body):
        paint = text  # section headings
    elif "recovered" in body:
        paint = ok
    elif "broke" in body:
        paint = warn
    elif re.match(r"^\d{4}-\d{2}-\d{2}", body):
        paint = ident
    else:
        paint = dim

    for i, line in enumerate(textwrap.wrap(body, width=80 - len(indent)) or [""]):
        print(indent + ("  " if i else "") + paint(line))

print()
print("  " + muted("read-only · dashboard/drift_board.json · no API calls"))
