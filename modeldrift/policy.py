"""Policy constants shared across producers, with no module dependencies.

This module exists so there is exactly ONE definition that board.py,
report.py, run.py and emit_vac.py can all import. board imports report, so
a constant living in board could not be imported by report without a
cycle, and the workaround for that (restating the value, or a deferred
import) is how a single source of truth quietly becomes two.
"""

REL_FLOOR = 0.5
"""Accuracy points from runs below this aggregate reliability are not scored.

A rate limit, timeout or provider outage makes a call *absent*, not *wrong*.
Scoring it 0 publishes the provider's bad morning as the model getting dumber.
The Reliability metric keeps these points, because reliability genuinely did
drop and that is the true signal. Keyed on aggregate reliability, never on
"a call failed": a blanket drop-on-failure would inflate accuracy on exactly
the hardest tasks. See docs/a-rate-limit-not-a-regression.md.

This constant is the single source of truth. dashboard/index.html carries the
same 0.5 for its client-side charts; tests/test_reliability_floor.py pins the
two together so they cannot drift apart again. They did drift once: the floor
lived only in the dashboard JS, so RESULTS.md published a Google outage as
three Gemini regressions (-37.1 and -94.3 pts) while the chart above it
correctly showed nothing.
"""
