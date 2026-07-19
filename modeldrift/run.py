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

from .providers import Model, ProviderError, call, list_models, load_registry
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

    Four more numbers ride along for free, measured on the same calls:
    **latency** (median per-call wall-clock — "is it getting slower?"),
    **verbosity** (mean answer length — "is it getting chattier / pricier?"),
    **reliability** (share of calls that succeeded) and **refusal rate** (share of
    benign prompts declined). All four are byproducts of calls already being
    made, so they cost nothing extra.
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


def probe_repeated(model: Model, runs: int = 3) -> dict:
    """Probe a model `runs` times and return the **median** run.

    A single probe is not a measurement of a model, it is one sample from it.
    Three runs of this identical frozen suite, half an hour apart, moved Claude
    Sonnet 5 by 9 points and Fable 5 by 6 — while 11 of 16 models did not move
    at all. None of the 16 accept `temperature`, so nothing can be pinned to 0
    and that spread is the floor under any drift signal. Alerting on a single
    run means alerting on sampling noise.

    So: take the median. It needs two of three runs to agree before a number
    moves, which is exactly the "is it a fluke?" question.

    The spread is kept, not hidden — `_acc_spread` rides along on the result, so
    the board can show how noisy a model is instead of implying a precision the
    sampling doesn't support. An aggregate that conceals its own variance is a
    worse lie than a noisy chart.
    """
    samples = [probe(model) for _ in range(max(1, runs))]
    # A run where every call failed is an infra problem, not a sample of the
    # model. Median over the usable ones; fall back to everything if none are.
    usable = [r for r in samples if r["_errors"] < len(SUITE)] or samples

    def med(field, of=None):
        vals = [(of(r) if of else r[field]) for r in usable]
        vals = [v for v in vals if v is not None]
        return statistics.median(vals) if vals else None

    accs = sorted(r["metrics"]["faithfulness"] for r in usable)
    median_acc = statistics.median(accs)
    # Return the sample closest to the median so `cases` stay real answers from
    # one actual run rather than a stitched-together average of several.
    rep = min(usable, key=lambda r: abs(r["metrics"]["faithfulness"] - median_acc))
    out = dict(rep)
    out["metrics"] = dict(rep["metrics"])
    for k in ("faithfulness", "precision@k", "recall@k", "citation_rate"):
        out["metrics"][k] = round(median_acc, 4)
    out["_latency_ms"] = med("_latency_ms")
    out["_out_chars"] = med("_out_chars")
    out["_reliability"] = med("_reliability")
    out["_refusal_rate"] = med("_refusal_rate")
    out["_runs"] = len(usable)
    out["_acc_spread"] = round(max(accs) - min(accs), 4)
    out["label"] = f"suite {SUITE_VERSION} · median of {len(usable)} runs"
    return out


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
    """Accumulate the extra metrics (latency, verbosity, per-capability) into a small time-series
    JSON the dashboard reads directly. Kept in the repo and read from raw.githubusercontent —
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
                    "reliability": r["_reliability"], "refusal_rate": r["_refusal_rate"],
                    # Per-capability scores were already being computed every run
                    # and printed to the console, then thrown away. They are where
                    # models actually differ — a model at 77% overall is usually
                    # near-perfect on recall and failing formatting, and the single
                    # aggregate hides exactly that.
                    "by_kind": per_kind(r),
                    # how many samples the median came from, and how far apart
                    # they were - so a reader can see the noise, not just the
                    # number that survived it
                    "runs": r.get("_runs", 1), "acc_spread": r.get("_acc_spread", 0.0)})
        del pts[:-cap]                    # keep the series bounded
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"updated": stamp, "series": series}, indent=1), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    from datetime import datetime, timezone
    from pathlib import Path
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api", default="https://eval-history.onrender.com")
    p.add_argument("--registry", default=None)
    p.add_argument("--out", default=None, help="also write results as JSON")
    p.add_argument("--metrics", default="dashboard/metrics.json",
                   help="time-series file for latency/verbosity the dashboard reads")
    p.add_argument("--runs", type=int, default=3,
                   help="probe each model this many times and record the median "
                        "(1 = single sample; the noise floor across 3 runs was 9 points)")
    p.add_argument("--narrative", default="dashboard/narrative.json",
                   help="generated prose summary of the board, for the portfolio")
    p.add_argument("--list-models", action="store_true",
                   help="print the model IDs each provider exposes to your key, then exit")
    args = p.parse_args(argv)

    if args.list_models:
        seen = set()
        for m in load_registry(args.registry):
            tag = (m.provider, m.key_env, m.base_url)
            if m.provider == "mock" or not m.available or tag in seen:
                continue
            seen.add(tag)
            try:
                ids = list_models(m)
                print(f"\n{m.key_env} ({m.provider}) — {len(ids)} models:")
                for i in sorted(ids):
                    print(f"    {i}")
            except ProviderError as e:
                print(f"\n{m.key_env} ({m.provider}) — could not list: {e}")
        return 0

    key = os.environ.get("EVAL_HISTORY_WRITE_KEY", "").strip()
    models = [m for m in load_registry(args.registry) if m.available]
    skipped = [m for m in load_registry(args.registry) if not m.available]

    print(f"suite {SUITE_VERSION} ({suite_hash()}), {len(SUITE)} tasks")
    print(f"probing {len(models)} model(s) x{args.runs} run(s); "
          f"{len(skipped)} skipped for lack of an API key\n")

    results = []
    for m in models:
        result = probe_repeated(m, args.runs)
        results.append(result)
        acc = result["metrics"]["faithfulness"]
        speed = f"{result['_latency_ms']:.0f}ms" if result["_latency_ms"] is not None else "—"
        chars = f"{result['_out_chars']:.0f}c" if result["_out_chars"] is not None else "—"
        kinds = ", ".join(f"{k} {v:.0%}" for k, v in per_kind(result).items())
        spread = result.get("_acc_spread") or 0.0
        band = f" ±{spread*100:.0f}" if spread else "    "
        print(f"  {m.label:26} acc {acc:.0%}{band} · {speed:>7} · {chars:>5}  ({kinds})")
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

    # Rebuild the portfolio's paragraph from the numbers just written, so the
    # prose can't drift from the board the way a hand-written one did. Wrapped
    # because a formatting bug in a *summary* must never fail the probe that
    # produced the data — the run is the product, the sentence is a view of it.
    try:
        from .narrative import narrate
        registry = json.loads(
            (Path(args.registry) if args.registry
             else Path(__file__).parent / "models.json").read_text(encoding="utf-8"))
        metrics_now = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
        blurb = narrate(metrics_now, registry)
        out = Path(args.narrative)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(blurb, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {blurb['claims_fired']} generated claim(s) to {args.narrative}")
    except Exception as e:                     # noqa: BLE001 - never fail the probe
        print(f"    (narrative not written: {e})")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump([{k: v for k, v in r.items() if not k.startswith("_")} for r in results], fh, indent=2)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
