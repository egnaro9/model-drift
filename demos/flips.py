"""Read the committed board history and separate harness failures from model changes.

A task that flips on one model on one day is inside the instrument's resolution
and means nothing. The same task flipping on five providers on the same day is
not five simultaneous regressions — it is the harness. This is a pure read of
dashboard/metrics.json: no API calls, nothing written.
"""

import json
import re
import textwrap

from modeldrift.flips import analyze, summarize

series = json.load(open("dashboard/metrics.json"))["series"]

for line in summarize(analyze(series)).splitlines():
    indent = re.match(r"\s*", line).group()
    print(textwrap.fill(line, width=80, subsequent_indent=indent + "  ") or "")
