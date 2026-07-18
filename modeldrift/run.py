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
import re
import statistics
import time
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Dict, List, Optional

from .providers import Model, ProviderError, call, load_registry
from .suite import SUITE, SUITE_VERSION, suite_hash

# Every prompt in the suite is benign, so a response that reads like a refusal is
# an *over*-refusal — the thing that makes a model annoying. Detected by phrase,
# not by a judge; on these terse prompts (answers are "blue", "144") a refusal
# phrase in the output is a strong signal, not noise.
_REFUSAL = re.compile(
    r"\b(i can'?t|i cannot|i'?m (sorry|unable|not able|not sure i can)|i won'?t|"
    r"as an ai|unable to (help|assist|comply)|i (don'?t|do not) (feel comfortable|think i can)|"
    r"i'?m not able to help)\b", re.I)


def is_refusal(text: str) -> bool:
    return bool(_REFUSAL.search(text or ""))


def probe(model: Model) -> dict:
    """Run the whole suite against one model; return an eval_run.json-shaped result.

    Accuracy (fraction of tasks passed) is the headline number. It's mapped onto
    eval-history's `faithfulness` metric so the existing regression comparison
    works unchanged — for a drift probe "faithfulness" reads as "still correct".

    Two more numbers ride along for free, measured on the same calls: **latency**
    (median per-call wall-clock — "is it getting slower?") and **verbosity** (mean
    answer length in characters — "is it getting chattier / pricier?"). Both are
    byproducts of calls already being made, so they cost nothing extra.
    """
    cases, errors, first_error = [], 0, None
    latencies, out_lens, refusals = [], [], 0   # over successful calls only
    for t in SUITE:
        try:
            t0 = time.perf_counter()
            out = call(model, t.prompt, task_id=t.id)
            latencies.append((time.perf_counter() - t0) * 1000.0)  # ms
            out_lens.append(len(out))
            if is_refusal(out):
                refusals += 1
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
        "_latency_ms": round(statistics.median(latencies), 1) if latencies else None,
        "_out_chars": round(statistics.mean(out_lens), 1) if out_lens else None,
        # reliability = fraction of the suite's calls that succeeded (transient
        # errors / rate limits pull it below 1); refusal_rate = fraction of the
        # responses that read like an over-refusal.
        "_reliability": round((len(SUITE) - errors) / len(SUITE), 4),
        "_refusal_rate": round(refusals / len(latencies), 4) if latencies else None,
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


def update_metrics_file(path: str, results: List[dict], stamp: str, cap: int = 104) -> None:
    """Accumulate the extra metrics (latency, verbosity) into a small time-series
    JSON the dashboard reads directly. Kept in the repo and served same-origin —
    no database column, no CORS, and adding a future metric is one more key here.

    Only models that actually responded get a point; a totally-failed probe
    (bad key) adds nothing, same as it isn't recorded in eval-history.
    """
    from pathlib import Path
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    series = data.get("series", {})
    for r in results:
        if r["_latency_ms"] is None:      # nothing got through — don't record
            continue
        pts = series.setdefault(r["run"], [])
        pts.append({"t": stamp, "acc": r["metrics"]["faithfulness"],
                    "latency_ms": r["_latency_ms"], "out_chars": r["_out_chars"],
                    "reliability": r["_reliability"], "refusal_rate": r["_refusal_rate"]})
        del pts[:-cap]                    # keep the series bounded
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"updated": stamp, "series": series}, indent=1), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    from datetime import datetime, timezone
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api", default="https://eval-history.onrender.com")
    p.add_argument("--registry", default=None)
    p.add_argument("--out", default=None, help="also write results as JSON")
    p.add_argument("--metrics", default="dashboard/metrics.json",
                   help="time-series file for latency/verbosity the dashboard reads")
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
        speed = f"{result['_latency_ms']:.0f}ms" if result["_latency_ms"] is not None else "—"
        chars = f"{result['_out_chars']:.0f}c" if result["_out_chars"] is not None else "—"
        kinds = ", ".join(f"{k} {v:.0%}" for k, v in per_kind(result).items())
        print(f"  {m.label:26} acc {acc:.0%} · {speed:>7} · {chars:>5}  ({kinds})")
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

    # latency + verbosity go to the repo-local time series the dashboard reads
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    update_metrics_file(args.metrics, results, stamp)
    print(f"\nwrote latency/verbosity to {args.metrics}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump([{k: v for k, v in r.items() if not k.startswith("_")} for r in results], fh, indent=2)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
