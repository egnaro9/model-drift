"""Probe every available model against the suite, score it, and record the run.

One scored run per model per invocation. On the weekly cron these accumulate in
[eval-history](https://github.com/egnaro9/eval-history) into a score-over-time
series, and eval-history's own comparison flags when this week dropped below last
week — that's the "regressed" signal the tracker exists to surface.

A model that errors mid-run (rate limit, outage) is recorded as a partial run
with a note, not a crash — a drift tracker that dies when one provider hiccups
tracks nothing. eval-history being down likewise doesn't fail the job.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Dict, List, Optional

from .providers import Model, ProviderError, call, load_registry
from .suite import SUITE, SUITE_VERSION, suite_hash


def probe(model: Model) -> dict:
    """Run the whole suite against one model; return an eval_run.json-shaped result.

    Accuracy (fraction of tasks passed) is the headline number. It's mapped onto
    eval-history's `faithfulness` metric so the existing regression comparison
    works unchanged — for a drift probe "faithfulness" reads as "still correct".
    """
    cases, errors, first_error = [], 0, None
    for t in SUITE:
        try:
            out = call(model, t.prompt, task_id=t.id)
            passed = bool(t.grade(out))
            note = t.kind
        except ProviderError as e:
            out, passed, note = "", False, f"{t.kind} · provider error: {str(e)[:220]}"
            errors += 1
            first_error = first_error or str(e)
        cases.append({
            "q": f"[{t.id}] {t.prompt}",
            "answer": out[:500],
            "scores": {"faithfulness": 1.0 if passed else 0.0,
                       "precision@k": 1.0 if passed else 0.0,
                       "recall@k": 1.0 if passed else 0.0, "citation": 1.0 if passed else 0.0},
            "flagged": not passed,
            "note": note,
        })
    n = len(cases)
    acc = sum(1 for c in cases if not c["flagged"]) / n if n else 0.0
    return {
        "run": model.id,                       # the series name in eval-history
        "git_sha": suite_hash(),               # which frozen suite produced this
        "label": f"suite {SUITE_VERSION}" + (f" · {errors} provider error(s)" if errors else ""),
        "metrics": {
            "faithfulness": round(acc, 4), "precision@k": round(acc, 4),
            "recall@k": round(acc, 4), "citation_rate": round(acc, 4),
            "flagged_cases": float(sum(1 for c in cases if c["flagged"])), "n_cases": float(n),
        },
        "cases": cases,
        "_errors": errors,          # stripped before POST; used for the console summary
        "_first_error": first_error,  # full text of the first failure, for diagnosis
    }


def per_kind(result: dict) -> Dict[str, float]:
    by = defaultdict(lambda: [0, 0])
    for c in result["cases"]:
        kind = c["note"].split(" · ")[0]
        by[kind][1] += 1
        if not c["flagged"]:
            by[kind][0] += 1
    return {k: round(ok / total, 3) for k, (ok, total) in by.items()}


def _post(api: str, key: str, payload: dict) -> Optional[str]:
    body = {k: v for k, v in payload.items() if not k.startswith("_")}
    body["source"] = "ci"   # each weekly probe is a legitimate baseline data point
    req = urllib.request.Request(
        f"{api.rstrip('/')}/runs", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())["id"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
        print(f"    (could not record in eval-history: {e})")
        return None


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api", default="https://eval-history.onrender.com")
    p.add_argument("--registry", default=None)
    p.add_argument("--out", default=None, help="also write results as JSON")
    args = p.parse_args(argv)

    key = os.environ.get("EVAL_HISTORY_WRITE_KEY", "").strip()
    models = [m for m in load_registry(args.registry) if m.available]
    skipped = [m for m in load_registry(args.registry) if not m.available]

    print(f"suite {SUITE_VERSION} ({suite_hash()}), {len(SUITE)} tasks")
    print(f"probing {len(models)} model(s); {len(skipped)} skipped for lack of an API key\n")

    results = []
    for m in models:
        result = probe(m)
        results.append(result)
        acc = result["metrics"]["faithfulness"]
        kinds = ", ".join(f"{k} {v:.0%}" for k, v in per_kind(result).items())
        print(f"  {m.label:26} accuracy {acc:.1%}  ({kinds})")
        if result["_errors"]:   # surface the real error so a 0% is diagnosable, not mysterious
            print(f"      ↳ {result['_errors']}/{len(SUITE)} failed — first error: {result['_first_error']}")
        # A probe that entirely failed is an infra/key problem, not a 0% score —
        # don't record it, or the chart shows a fake crash. Partial runs still count.
        if key and result["_errors"] >= len(SUITE):
            print("      (every call failed — not recorded; fix the key/quota, not the model)")
        elif key:
            _post(args.api, key, result)
    if not key:
        print("\n  EVAL_HISTORY_WRITE_KEY unset — probed but not recorded (set it to build history).")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump([{k: v for k, v in r.items() if not k.startswith("_")} for r in results], fh, indent=2)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
