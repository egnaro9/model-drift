"""Generate the board's prose summary from the board's own numbers.

The portfolio used to carry a hand-written paragraph about this board. Twice it
went false — not through carelessness, but because a weekly cron kept moving the
data underneath frozen prose. "Gemini 3.5 Flash is the only 100% that isn't a
flagship" was true the day it was written and false the week two OpenAI models
also hit 100%. Prose about live data has a shelf life.

So the prose is computed here instead. Every sentence is emitted by a *claim*: a
predicate over the current numbers plus a renderer. A claim that doesn't hold
isn't phrased more carefully — it isn't emitted at all. That's the whole design:
the generator can be silent, but it can't be wrong.

Three rules the claims obey, because each is a way a generator like this lies:

1. **Ties are never silently broken.** "The slowest model" is a lie when two tie.
   `_extremes` returns every row at the extreme and the renderers say "tie".
2. **Every number is printed from the value it describes.** No number is written
   into a template by hand, and rounding happens *after* the comparison, so a
   ratio described as "22x" is 22x at the precision shown.
3. **Nothing is claimed about a model with no data.** A probe that failed
   entirely is absent from the series, so it can't be named a winner or a loser.
"""
from __future__ import annotations

import json
import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Tiers that count as a lab's top offering. Everything else is a cheaper tier,
# which is what makes "the cheap one matches the flagship" a real finding.
_TOP_TIERS = ("flagship", "heavy")
_CHEAP_TIERS = ("mid", "mini", "nano")


def _num(value) -> Optional[float]:
    """A usable number, or None. `bool` is deliberately rejected — it is an int
    subclass in Python, so `True` would otherwise sail through as 1.0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


class Row:
    """One model's latest point, joined to its registry metadata."""

    def __init__(self, model_id: str, point: dict, meta: Optional[dict] = None) -> None:
        meta = meta or {}
        self.id = model_id
        self.label = meta.get("label") or model_id
        self.group = meta.get("group") or ""
        self.tier = meta.get("tier") or ""
        self.stamp = point.get("t") or ""
        self.acc = _num(point.get("acc"))
        self.latency = _num(point.get("latency_ms"))
        self.chars = _num(point.get("out_chars"))
        self.reliability = _num(point.get("reliability"))
        self.refusals = _num(point.get("refusal_rate"))

    def has(self, field: str) -> bool:
        return getattr(self, field, None) is not None

    @property
    def clean(self) -> bool:
        """Did every call in this model's run succeed?

        This is the difference between a measurement and an artifact. `probe()`
        scores a failed call as wrong and still records the point, so a model
        that got rate-limited halfway through comes back with a depressed
        accuracy and a latency measured over whichever calls happened to get
        through. Narrating that as "the fastest model" or "the lowest scorer"
        would be reporting the provider's Monday morning as a property of the
        model. Degraded rows stay on the chart; they just can't win a
        superlative.
        """
        return (self.reliability is not None and self.reliability >= 1.0
                and self.acc is not None
                and 0.0 <= self.acc <= 1.0
                and self.tier not in ("", "mock"))


def _extremes(rows: Sequence[Row], field: str, want_max: bool) -> List[Row]:
    """Every row tied at the extreme of `field` — never just the first one.

    Returning a list rather than a single row is what keeps "the slowest model"
    honest: if two models tie, the caller has to say so.
    """
    have = [r for r in rows if r.has(field)]
    if not have:
        return []
    best = (max if want_max else min)(getattr(r, field) for r in have)
    return [r for r in have if getattr(r, field) == best]


def _names(rows: Sequence[Row]) -> str:
    labels = [r.label for r in rows]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _pct(value: float) -> str:
    """Truncates rather than rounds, so the number shown is never larger than
    the number measured. `.0f` would print a model on 99.6% as "100%" — a
    perfect score it did not get, in the one place a reader checks hardest."""
    if value >= 1.0:
        return "100%"
    return f"{math.floor(value * 100)}%"


def _ms(value: float) -> str:
    return f"{value / 1000:.1f} s" if value >= 1000 else f"{value:.0f} ms"


def _ratio(high: float, low: float) -> str:
    """Also truncating: "20.1x" understates 20.19 and never overstates it."""
    return f"{math.floor((high / low) * 10) / 10:g}x"


# ────────────────────────────── the claims ───────────────────────────────
# Each returns a sentence, or None when its predicate doesn't hold. Order is
# priority: the renderer takes the first `limit` that fire.

def claim_cheap_matches_flagship(rows: Sequence[Row]) -> Optional[str]:
    """A lab's cheaper tier scoring at or above that same lab's top tier.

    Joined *within a lab*: "the cheap one matches the flagship" is only a
    finding about a lab that has both, and comparing one lab's mini against
    another lab's flagship is how the original false claim got made.
    """
    rows = _ok(rows)
    best = None
    for group in sorted({r.group for r in rows if r.group}):
        mine = [r for r in rows if r.group == group and r.has("acc")]
        top = [r for r in mine if r.tier in _TOP_TIERS]
        cheap = [r for r in mine if r.tier in _CHEAP_TIERS]
        if not top or not cheap:
            continue
        top_acc = max(r.acc for r in top)
        winners = [r for r in cheap if r.acc >= top_acc]
        if winners and (best is None or len(winners) > len(best[1])):
            best = (group, winners, top_acc)
    if not best:
        return None
    group, winners, top_acc = best
    # Each winner is printed with *its own* score. Naming several models and then
    # one number reads as "all of them scored that", which is false the moment
    # they differ — a cheap tier that merely ties the flagship gets folded into
    # one that beat it. The scores are per-model or the sentence is a lie.
    if all(r.acc > top_acc for r in winners):
        verb = "beat"
    elif all(r.acc == top_acc for r in winners):
        verb = "match"
    else:
        verb = "match or beat"
    scores = " and ".join(f"{r.label} at {_pct(r.acc)}" for r in
                          sorted(winners, key=lambda r: -r.acc))
    plural = "" if len(winners) == 1 else "s"
    # Scoped to the lab it was computed over. "the cheap seat costs nothing"
    # reads as a claim about cheap models generally, and on this same board
    # Meta's and OpenAI's cheaper tiers cost a great deal — the sentence would
    # be a generalisation the predicate never checked.
    return (f"<strong>{group}'s cheaper tier{plural} {verb} its own flagship</strong> — "
            f"{scores}, against the flagship's {_pct(top_acc)} — so within that lab, "
            f"on this suite, paying more buys no accuracy.")


def claim_perfect_scores(rows: Sequence[Row]) -> Optional[str]:
    """How many models answered the whole suite correctly."""
    scored = _ok(rows)
    if not scored:
        return None
    perfect = [r for r in scored if r.acc >= 1.0]
    if not perfect:
        leaders = _extremes(scored, "acc", want_max=True)
        return (f"<strong>Nothing is at 100%</strong> — {_names(leaders)} "
                f"lead{'s' if len(leaders) == 1 else ''} at {_pct(leaders[0].acc)}.")
    if len(perfect) == len(scored):
        return (f"<strong>Every model on the board is at 100%</strong> — "
                f"the suite has stopped separating them, which is its own signal.")
    return (f"<strong>{len(perfect)} of {len(scored)} models answer the whole suite "
            f"correctly</strong> ({_names(perfect)}).")


def claim_verbosity(rows: Sequence[Row]) -> Optional[str]:
    """The spread between the wordiest and tersest answers.

    Needs a ratio of at least 2x to be worth a sentence — below that it's noise,
    and a generator that narrates noise is how you get prose nobody trusts.
    """
    rows = _ok(rows)
    chattiest = _extremes(rows, "chars", want_max=True)
    tersest = _extremes(rows, "chars", want_max=False)
    if not chattiest or not tersest or chattiest[0].chars == tersest[0].chars:
        return None
    lo = tersest[0].chars
    if lo <= 0:
        return None
    ratio = chattiest[0].chars / lo
    if ratio < 2:
        return None
    times = _ratio(chattiest[0].chars, lo)
    return (f"<strong>{_names(chattiest)} answer{'s' if len(chattiest) == 1 else ''} with "
            f"{times} the characters of the tersest model</strong> — it explains "
            f"instead of answering, and lands at {_pct(chattiest[0].acc)}."
            if chattiest[0].has("acc") else
            f"<strong>{_names(chattiest)} answer{'s' if len(chattiest) == 1 else ''} with "
            f"{times} the characters of the tersest model</strong>.")


def claim_speed_accuracy(rows: Sequence[Row]) -> Optional[str]:
    """The speed/quality tradeoff, stated only in the shape the data supports."""
    rows = _ok(rows)
    fastest = _extremes(rows, "latency", want_max=False)
    if not fastest or not fastest[0].has("acc"):
        return None
    scored = [r for r in rows if r.has("acc")]
    if len(scored) < 2:
        return None
    worst = _extremes(scored, "acc", want_max=False)
    fast_ids = {r.id for r in fastest}
    if any(r.id in fast_ids for r in worst):
        return (f"<strong>{_names(fastest)} answer{'s' if len(fastest) == 1 else ''} fastest "
                f"and score{'s' if len(fastest) == 1 else ''} lowest</strong> "
                f"({_ms(fastest[0].latency)} at {_pct(fastest[0].acc)}) — a speed/quality "
                f"tradeoff you can see rather than argue about.")
    return (f"<strong>{_names(fastest)} lead{'s' if len(fastest) == 1 else ''} on speed</strong> "
            f"at {_ms(fastest[0].latency)} and {_pct(fastest[0].acc)} accuracy.")


def claim_slowest(rows: Sequence[Row]) -> Optional[str]:
    rows = _ok(rows)
    slowest = _extremes(rows, "latency", want_max=True)
    fastest = _extremes(rows, "latency", want_max=False)
    if not slowest or not fastest or slowest[0].latency == fastest[0].latency:
        return None
    return (f"The slowest {'is' if len(slowest) == 1 else 'are'} {_names(slowest)} at "
            f"{_ms(slowest[0].latency)}.")


CLAIMS: List[Callable[[Sequence[Row]], Optional[str]]] = [
    claim_cheap_matches_flagship,
    claim_verbosity,
    claim_speed_accuracy,
    claim_perfect_scores,
    claim_slowest,
]


# ───────────────────────────── assembly ──────────────────────────────────
def build_rows(metrics: dict, registry: Sequence[dict]) -> List[Row]:
    """Latest point per real model, joined to registry metadata.

    The mock series is excluded by *tier*, not by an id prefix: the control
    exists to prove the pipeline works, and narrating it would mean reporting a
    fixture as a model. Anything the registry marks `tier: "mock"` is out.
    """
    meta = {m["id"]: m for m in registry}
    mock_ids = {m["id"] for m in registry if m.get("tier") == "mock"}
    rows = []
    for model_id, points in (metrics.get("series") or {}).items():
        if model_id in mock_ids or model_id.startswith("mock:") or not points:
            continue
        rows.append(Row(model_id, points[-1], meta.get(model_id)))
    return sorted(rows, key=lambda r: r.id)


def run_date(rows: Sequence[Row]) -> str:
    """The date of the most recent *real* run.

    Deliberately not `metrics["updated"]`. That field is stamped whenever the
    file is written, including a mock-only CI run — on the live board today it
    reads 22:28Z while the newest real measurement is 19:23Z. Dating a
    paragraph by when a file was touched rather than when the models were
    measured is exactly the kind of small lie this generator exists to prevent.
    """
    stamps = [r.stamp for r in rows if r.stamp]
    return max(stamps) if stamps else ""


def _ok(rows: Sequence[Row]) -> List[Row]:
    """The cohort every claim quantifies over: models that reported cleanly."""
    return [r for r in rows if r.clean]


def narrate(metrics: dict, registry: Sequence[dict], limit: int = 3) -> dict:
    """The paragraph, plus the parts it was assembled from.

    Sentences come back separately so a caller can render them differently and
    so the tests can assert on individual claims instead of a blob of prose.
    """
    rows = build_rows(metrics, registry)
    clean = _ok(rows)
    stamp = run_date(rows)
    tracked = len([m for m in registry if m.get("tier") not in ("mock", None)])

    if len(clean) < 2:
        n = len(clean)
        body = (f"The board has {n} clean run{'' if n == 1 else 's'} to compare so far "
                f"— not enough to rank models against each other yet.")
        return {"sentences": [], "html": body, "text": _strip(body),
                "models": len(rows), "clean": n, "updated": stamp, "claims_fired": 0}

    sentences = []
    for claim in CLAIMS:
        if len(sentences) >= limit:
            break
        out = claim(rows)
        if out:
            sentences.append(out)

    labs = len({r.group for r in clean if r.group})
    lead = (f"A frozen, deterministically-graded suite against "
            f"<strong>{len(clean)} models across {labs} labs</strong>.")
    # When some models didn't report cleanly, say so *before* any superlative.
    # Otherwise "the fastest model" silently means "the fastest of the ones that
    # happened to work this week", which is the reader's reasonable other
    # reading and not what the sentence says.
    if len(clean) < tracked:
        lead += (f" {tracked - len(clean)} of the {tracked} tracked models did not "
                 f"return a clean run and are left out of the comparisons below.")
    tail = (f"<em>Generated from the run of {_date(stamp)} — this paragraph is rebuilt "
            f"from the board's own numbers, never hand-written.</em>")
    html = " ".join([lead] + sentences + [tail])
    return {"sentences": sentences, "html": html, "text": _strip(html),
            "models": len(rows), "clean": len(clean), "updated": stamp,
            "claims_fired": len(sentences)}


def _date(stamp: str) -> str:
    """2026-07-18T22:28:23Z → 18 Jul 2026. Falls back to the raw stamp."""
    from datetime import datetime
    try:
        d = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return f"{d.day} {d.strftime('%b %Y')}"
    except (ValueError, AttributeError):
        return stamp or "an unrecorded date"


def _strip(html: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    from pathlib import Path
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--metrics", default="dashboard/metrics.json")
    p.add_argument("--registry", default=None)
    p.add_argument("--out", default="dashboard/narrative.json")
    args = p.parse_args(argv)

    registry_path = Path(args.registry) if args.registry else Path(__file__).parent / "models.json"
    metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    result = narrate(metrics, registry)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"{result['claims_fired']} claim(s) fired over {result['models']} model(s) -> {out}")
    print(f"\n{result['text']}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
