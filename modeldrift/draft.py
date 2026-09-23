"""Turn a finding into a post a human can edit and publish.

The format is fixed on purpose, and it is a promise rather than a topic: one
measured finding, the evidence it rests on, and what stayed green anyway. The
third section is the one that makes the first two worth reading. A blog that
only prints movement teaches a reader that the board finds something every
time, which is the same lie as a suite that never goes red.

Nothing here publishes. It writes a file for review.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from .findings import ABOUT_HARNESS, ABOUT_INFRA, Finding
from .report import ModelStatus, min_detectable_change

HOME = "https://erikhill.dev"
BOARD = "https://egnaro9.github.io/model-drift/"
REPO = "https://github.com/egnaro9/model-drift"

# What the lead sentence has to say before anything else, per finding class.
# A reader who stops after one line should still not come away with the wrong
# subject: infrastructure findings are not model findings.
FRAMING = {
    ABOUT_INFRA: ("This is a finding about infrastructure, not about a model. "
                  "Nothing below says a model got worse."),
    ABOUT_HARNESS: ("This is a finding about my own harness. The suspect is the "
                    "probe, not the models it measures."),
}


def slugify(text: str, limit: int = 60) -> str:
    """URL-safe, and cut at a word boundary. A slug truncated mid-word
    ("...at-once-on-17-se") reads as a broken link even when it resolves."""
    s = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-"))
    if len(s) <= limit:
        return s or "finding"
    cut = s[:limit]
    if "-" in cut:
        cut = cut[:cut.rindex("-")]
    return cut.strip("-") or "finding"


def _held(statuses: Sequence[ModelStatus], exclude: str,
          registry: Optional[Sequence[dict]] = None) -> List[ModelStatus]:
    """Models that reported cleanly and did not move.

    Two exclusions, both load-bearing. A model that was dark did not "stay
    green"; it said nothing, and counting silence as stability is the failure
    this whole project is about. And the mock control is excluded by TIER, not
    by an id prefix, exactly as narrative.build_rows does it: the fixture
    exists to prove the pipeline works, and naming it in a post reports a
    fixture as a model.
    """
    mock_ids = {m["id"] for m in (registry or []) if m.get("tier") == "mock"}
    return [s for s in statuses
            if s.id != exclude
            and s.id not in mock_ids
            and s.verdict == "unchanged"
            and s.observed_qualified is not False]


def render(finding: Finding, statuses: Sequence[ModelStatus],
           run_date: str, suite_version: str,
           registry: Optional[Sequence[dict]] = None) -> str:
    """The post, as markdown with front matter naming its destination."""
    held = _held(statuses, finding.subject, registry)
    title = finding.headline
    lines = [
        "---",
        f'title: "{title}"',
        f"date: {run_date}",
        f"kind: {finding.kind}",
        f"about: {finding.about}",
        f"subject: {finding.subject}",
        f"fingerprint: {finding.fingerprint()}",
        f"destination: {HOME}/notes/{run_date}-{slugify(title)}/",
        "status: draft",
        "---",
        "",
        f"# {title}",
        "",
    ]

    framing = FRAMING.get(finding.about)
    if framing:
        lines += [f"**{framing}**", ""]

    lines += [
        "## The finding",
        "",
        f"{finding.headline}, on a frozen suite ({suite_version}) run "
        f"{run_date}. Same questions, same graders, temperature 0.",
        "",
        "## The evidence",
        "",
        "| claim | how it was checked |",
        "|---|---|",
    ]
    for row in finding.evidence:
        lines.append(f"| {row['claim']} | {row['how']} |")

    lines += ["", "## What stayed green anyway", ""]
    if held:
        names = ", ".join(s.label for s in held)
        # The closing line has to match the finding's subject. A probe alarm
        # is not "the one that moved" — nothing moved, the instrument is under
        # suspicion, and the stable cohort means something different there.
        if finding.about == ABOUT_HARNESS:
            why = ("That cohort is the control. If the suite were broken outright "
                   "these would have moved too, so whatever is wrong is specific "
                   "to the task above rather than general to the harness.")
        elif finding.about == ABOUT_INFRA:
            why = ("None of that is affected by the outage above. An unreachable "
                   "provider says nothing about the models that did answer.")
        else:
            why = ("That matters more than the finding does. A board that reports "
                   "movement every week is measuring its own noise, and the models "
                   "that held still are the reason the one that moved is worth "
                   "looking at.")
        lines += [
            f"{len(held)} of the models that reported this run did not move: {names}.",
            "",
            why,
        ]
    else:
        # Saying "everything else was stable" when nothing else reported is the
        # exact shape of the bug this project exists to catch.
        lines += [
            "Nothing else reported a scoreable run, so there is no stable cohort "
            "to compare against this week. That is a gap in the measurement, not "
            "evidence that the rest of the board is fine.",
        ]

    floors = [min_detectable_change(s.graded) for s in statuses if s.graded]
    if floors:
        lines += [
            "",
            "## What this run could and could not have seen",
            "",
            f"The smallest movement this run could print is "
            f"{max(floors):.2f} points at its coarsest. Anything under that is the "
            "denominator moving, not a model, and is not reported here at all.",
        ]

    lines += [
        "",
        "---",
        "",
        f"Live board: {BOARD}",
        f"Suite, graders and runner: {REPO}",
        "",
        "*Drafted automatically from the run that produced it. The numbers above "
        "are generated; the judgement of whether this is worth saying is not.*",
    ]
    return "\n".join(lines) + "\n"


def share_text(finding: Finding, url: str) -> str:
    """The LinkedIn link-share that points at the post.

    Deliberately short and deliberately not the post. LinkedIn cannot author a
    native article through its public API, so the post lives on erikhill.dev
    and this is the distribution: a link with a reason to click it.
    """
    lead = finding.headline
    if finding.about == ABOUT_INFRA:
        lead = f"{finding.headline} — and that is a billing story, not a model story."
    elif finding.about == ABOUT_HARNESS:
        lead = f"{finding.headline} — which accuses my own harness, not the models."
    return (f"{lead}\n\n"
            f"Evidence table and what stayed green anyway: {url}\n\n"
            f"Board: {BOARD}")
