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


def _shared(rows: Sequence[Row], field: str):
    """The value of `field` if every row has the same one, else None.

    Guards the tie bug that kept recurring: a renderer names three models and
    then prints `rows[0].acc`, which reads as all three having scored it. A
    value may only be printed alongside a group when the whole group shares it.
    """
    values = {getattr(r, field) for r in rows}
    return values.pop() if len(values) == 1 else None


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
    # The epsilon is not decoration: 0.58 * 100 is 57.99999999999999 in binary
    # floating point, so a bare floor prints a measured 58% as "57%". Nudging by
    # a millionth of a point fixes that without ever reaching the next integer
    # from a value genuinely below it.
    return f"{math.floor(value * 100 + 1e-9)}%"


def _ms(value: float) -> str:
    return f"{value / 1000:.1f} s" if value >= 1000 else f"{value:.0f} ms"


def _ratio(high: float, low: float) -> str:
    """Also truncating: "20.1x" understates 20.19 and never overstates it."""
    return f"{math.floor((high / low) * 10) / 10:g}x"


# ────────────────────────────── the claims ───────────────────────────────
# Each returns a sentence, or None when its predicate doesn't hold. Order is
# priority: the renderer takes the first `limit` that fire.

def claim_cheap_matches_flagship(rows: Sequence[Row]) -> Optional[str]:
    """A lab's cheaper tier scoring at or above that lab's own flagship.

    Joined *within a lab*: comparing one lab's mini against another lab's
    flagship is how the original false claim got made.

    "Flagship" means `tier == "flagship"` and nothing else. `heavy` sits above
    it (Fable 5 over Opus 4.8), so folding the two into one "top tier" and
    taking the max printed a heavy model's score under the words "the
    flagship's". A lab with no flagship in the cohort — because it has none, or
    because its flagship got throttled out — is skipped rather than described
    against whatever model happens to be left.
    """
    rows = _ok(rows)
    best = None
    for group in sorted({r.group for r in rows if r.group}):
        mine = [r for r in rows if r.group == group and r.has("acc")]
        flagships = [r for r in mine if r.tier == "flagship"]
        cheap = [r for r in mine if r.tier in _CHEAP_TIERS]
        # Exactly one flagship, or "the flagship's N%" is ambiguous about which.
        if len(flagships) != 1 or not cheap:
            continue
        flagship = flagships[0]
        winners = [r for r in cheap if r.acc >= flagship.acc]
        if winners and (best is None or len(winners) > len(best[1])):
            best = (group, winners, flagship)
    if not best:
        return None
    group, winners, flagship = best
    # Each winner prints its *own* score. Naming several models and then one
    # number reads as all of them having scored it, which is false the moment
    # they differ — a cheap tier that merely ties gets folded in with one that beat.
    if all(r.acc > flagship.acc for r in winners):
        verb = "beat"
    elif all(r.acc == flagship.acc for r in winners):
        verb = "match"
    else:
        verb = "match or beat"
    parts = [f"{r.label} at {_pct(r.acc)}" for r in sorted(winners, key=lambda r: -r.acc)]
    scores = (parts[0] if len(parts) == 1 else
              " and ".join(parts) if len(parts) == 2 else
              ", ".join(parts[:-1]) + f", and {parts[-1]}")
    plural = "" if len(winners) == 1 else "s"
    # Scoped to the lab it was computed over. "the cheap seat costs nothing"
    # reads as a claim about cheap models generally, and on this same board
    # Meta's and OpenAI's cheaper tiers cost a great deal.
    return (f"<strong>{group}'s cheaper tier{plural} {verb} its own flagship</strong> — "
            f"{scores}, against {flagship.label} at {_pct(flagship.acc)} — so within "
            f"that lab, on this suite, paying more buys no accuracy.")


def claim_perfect_scores(rows: Sequence[Row]) -> Optional[str]:
    """How many models answered the whole suite correctly.

    Scoped to the models that reported cleanly, never to "the board" — the
    chart above shows every model including the throttled ones, so "every model
    on the board is at 100%" can sit directly above a chart showing 59%.
    """
    scored = _ok(rows)
    if not scored:
        return None
    n = len(scored)
    perfect = [r for r in scored if r.acc >= 1.0]
    if not perfect:
        leaders = _extremes(scored, "acc", want_max=True)
        return (f"<strong>Nothing reached 100%</strong> — {_names(leaders)} "
                f"lead{'s' if len(leaders) == 1 else ''} at {_pct(leaders[0].acc)}.")
    if len(perfect) == n:
        return (f"<strong>All {n} models that reported cleanly are at 100%</strong> — "
                f"the suite has stopped separating them, which is its own signal.")
    return (f"<strong>{len(perfect)} of the {n} models that reported cleanly answer "
            f"the whole suite correctly</strong> ({_names(perfect)}).")


def claim_verbosity(rows: Sequence[Row]) -> Optional[str]:
    """The spread between the wordiest and tersest answers.

    Needs a 2x ratio to be worth a sentence — a generator that narrates noise
    produces prose nobody trusts.
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
    verb = "answers" if len(chattiest) == 1 else "answer"
    head = (f"<strong>{_names(chattiest)} {verb} with {times} the characters of the "
            f"tersest model</strong>")
    # Accuracy only rides along when the whole named group shares it — otherwise
    # three models get named and one model's score gets printed for all of them.
    acc = _shared(chattiest, "acc")
    if acc is None:
        return head + "."
    # No editorial about *why*. "It explains instead of answering" is a story
    # about a model that may be sitting at 100%, and length is not a defect.
    return f"{head}, at {_pct(acc)}."


def claim_speed_accuracy(rows: Sequence[Row]) -> Optional[str]:
    """The speed/quality tradeoff, stated only in the shape the data supports."""
    rows = _ok(rows)
    fastest = _extremes(rows, "latency", want_max=False)
    if not fastest:
        return None
    scored = [r for r in rows if r.has("acc")]
    if len(scored) < 2:
        return None
    worst = _extremes(scored, "acc", want_max=False)
    best = _extremes(scored, "acc", want_max=True)
    lead_verb = "leads" if len(fastest) == 1 else "lead"
    fast_acc = _shared(fastest, "acc")
    speed_only = (f"<strong>{_names(fastest)} {lead_verb} on speed</strong> at "
                  f"{_ms(fastest[0].latency)}"
                  + (f" and {_pct(fast_acc)} accuracy." if fast_acc is not None else "."))
    if len(worst) == len(scored) and len(best) == len(scored):
        # Zero accuracy variation: the minimum *is* the maximum, so "scores
        # lowest" is vacuous and there is no tradeoff to trade against. A frozen
        # suite against improving models saturates by design.
        return speed_only
    # The tradeoff sentence needs the *same* model to be fastest and lowest —
    # and unambiguously so. If either extreme is a tie, naming the group and
    # printing one member's number is the collapsed-score bug again.
    if len(fastest) == 1 and len(worst) == 1 and fastest[0].id == worst[0].id:
        r = fastest[0]
        return (f"<strong>{r.label} answers fastest and scores lowest</strong> "
                f"({_ms(r.latency)} at {_pct(r.acc)}) — a speed/quality tradeoff you "
                f"can see rather than argue about.")
    return speed_only


def claim_slowest(rows: Sequence[Row]) -> Optional[str]:
    rows = _ok(rows)
    slowest = _extremes(rows, "latency", want_max=True)
    fastest = _extremes(rows, "latency", want_max=False)
    if not slowest or not fastest or slowest[0].latency == fastest[0].latency:
        return None
    # Latency is the field they tied on, so it is shared and safe to print.
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
    """The cohort every claim quantifies over: models that reported cleanly *in
    the most recent run*.

    The run filter matters as much as the clean one. A model dropped from the
    registry, or one whose provider was down all of last month, keeps its final
    point at the top of its series forever — and without this it would be
    compared against this week's numbers as though it had just been measured.
    "The fastest model" would then mean "the fastest of these, one of which was
    timed in February".
    """
    clean = [r for r in rows if r.clean]
    if not clean:
        return []
    latest = max(r.stamp for r in clean)
    return [r for r in clean if r.stamp == latest]


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
