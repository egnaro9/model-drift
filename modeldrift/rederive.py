"""Regenerate every derived file from the board.

RESULTS.md and dashboard/narrative.json are pure functions of
dashboard/drift_board.json and modeldrift/models.json. That matters for more
than tidiness: it means a merge conflict in either of them has a deterministic
resolution that is neither side of the conflict.

On 2026-09-22 a probe finished after 47 minutes and ~1,800 API calls, and its
commit hit exactly that. The board merged cleanly; the two renderings of the
board conflicted; the rebase stopped; the run's data was never pushed. The
retry loop above it was written for a non-fast-forward push and handled that
correctly, but a content conflict is a different failure and text-merging a
generated file is the wrong operation for it.

So: never merge a derived file. Take the merged inputs and derive it again.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from .board import results_md_offline
from .narrative import narrate


def rederive(board_path: str, registry_path: str,
             results_path: str, narrative_path: str) -> List[str]:
    board = json.loads(Path(board_path).read_text(encoding="utf-8"))
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))

    written = []
    results = results_md_offline(board.get("series") or {}, registry)
    if Path(results_path).read_text(encoding="utf-8") != results:
        Path(results_path).write_text(results, encoding="utf-8")
        written.append(results_path)

    story = json.dumps(narrate(board, registry), indent=1) + "\n"
    if Path(narrative_path).read_text(encoding="utf-8") != story:
        Path(narrative_path).write_text(story, encoding="utf-8")
        written.append(narrative_path)
    return written


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", default="dashboard/drift_board.json")
    ap.add_argument("--registry", default="modeldrift/models.json")
    ap.add_argument("--results", default="RESULTS.md")
    ap.add_argument("--narrative", default="dashboard/narrative.json")
    a = ap.parse_args(argv)

    changed = rederive(a.board, a.registry, a.results, a.narrative)
    if changed:
        print("rederived from the board: " + ", ".join(changed))
    else:
        print("derived files already match the board")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
