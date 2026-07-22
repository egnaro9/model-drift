"""Known-answer model-identity check — catch a silently-swapped backend.

Seven (dev.to, on the harness thread) named the failure this guards against: the
config says model X, every surface reports healthy, but the provider is actually
serving model Y — a cheaper alias, a routing-layer downgrade, a proxy pointed at
the wrong backend. Accuracy alone can't see it; a small quality drop looks like
ordinary drift, which is exactly what this repo would otherwise *mislabel* as the
model getting worse.

The observable a swapped backend can't fake for free is the model id it **echoes
back** in its own response. OpenAI (and the OpenAI-compatible xAI/Groq) and
Anthropic return `model`; Gemini returns `modelVersion`. We assert the served id
is consistent with the one we asked for.

What this does and does not prove — stated plainly, because overclaiming a check
is worse than not having it:

- It CATCHES the common, undramatic cases: an alias that resolves elsewhere, a
  mismatched deploy, a router that downgraded the model without telling you, a
  base URL pointed at the wrong service. All of those change the echoed id.
- It does NOT prove the weights. A provider that lies in *both* the label and the
  echoed id defeats it — and no cheap check catches that, so we don't pretend to.

A behavioural fingerprint ("only model X answers this canary correctly") is
deliberately NOT used: model outputs are not unique enough to make it reliable,
and a check that false-alarms is worse than one that occasionally can't decide —
so an id the provider simply doesn't echo is reported as *unverified*, never as a
mismatch.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .providers import Model, ProviderError, call_raw, load_registry

# A trivial prompt: we only need a valid response whose metadata we can read, so
# keep it tiny — one short call per model is the whole cost of the check.
_PING = "Reply with the single word: ok"

# Separators a provider may append before a version/date suffix on the base id.
_VERSION_SEPARATORS = ("-", ".", ":", "_", "@", "/")


def served_model_id(provider: str, raw: dict) -> Optional[str]:
    """The model id the provider echoed back in its own response, or None if this
    provider/response doesn't carry one. OpenAI, the OpenAI-compatible providers
    (xAI, Groq) and Anthropic all return `model`; Gemini returns `modelVersion`.
    A missing or blank value is None — 'we couldn't read it', not 'it's wrong'."""
    if provider in ("openai", "openai-compatible", "anthropic", "mock"):
        v = raw.get("model")
    elif provider == "gemini":
        v = raw.get("modelVersion") or raw.get("model")
    else:
        v = None
    return v.strip() if isinstance(v, str) and v.strip() else None


def _consistent(requested: str, served: str) -> bool:
    """Whether the requested and served ids agree.

    Providers commonly return a dated/versioned variant of the base id
    (`gpt-4o` -> `gpt-4o-2024-08-06`, `claude-opus-4-8` -> `claude-opus-4-8-20260514`,
    `grok-4-fast-non-reasoning` served as `grok-4-fast`), so a match is: identical,
    or one is the other followed by a version separator. A *bare* prefix is not
    enough — `gpt-4` must not silently match `gpt-4o`, or the check would wave
    through exactly the downgrade it exists to catch.
    """
    a, b = requested.strip().lower(), served.strip().lower()
    if a == b:
        return True
    lo, hi = sorted((a, b), key=len)
    return hi.startswith(lo) and hi[len(lo):len(lo) + 1] in _VERSION_SEPARATORS


@dataclass(frozen=True)
class Identity:
    model_id: str          # our registry id, e.g. "openai:gpt-5"
    requested: str         # the model we asked the provider for
    served: Optional[str]  # the model the provider says it served (None = not echoed)
    verified: bool         # we actually read a served id to compare against
    ok: bool               # served is consistent with requested (True when unverified)

    @property
    def status(self) -> str:
        if not self.verified:
            return "unverified"          # provider didn't echo an id — can't tell
        return "match" if self.ok else "MISMATCH"


def check(model: Model, raw: dict) -> Identity:
    """Compare the model we asked for against the one the provider says it served.
    Pure: no network — hand it a response dict (real or canned)."""
    served = served_model_id(model.provider, raw)
    verified = served is not None
    ok = True if not verified else _consistent(model.model, served)
    return Identity(model.id, model.model, served, verified, ok)


def attest(model: Model) -> Identity:
    """Make one cheap call and verify the provider served the model we asked for.

    Raises ProviderError if the call itself fails — an unreachable or rate-limited
    provider is a reliability problem for the caller to report, not a mismatch. A
    mismatch means the call *succeeded* and returned the wrong model's id.
    """
    return check(model, call_raw(model, _PING))


def attest_registry(path: Optional[str] = None) -> List[Identity]:
    """Attest every available model in the registry (skips those without a key,
    same rule as the probe). Unreachable providers are skipped, not failed."""
    out: List[Identity] = []
    for m in load_registry(path):
        if not m.available:
            continue
        try:
            out.append(attest(m))
        except ProviderError:
            continue
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: verify each provider serves the model it was asked for.

    Exit 1 on any mismatch so CI can gate on it; `--strict` also fails on an
    unverified model (a provider that doesn't echo an id at all).
    """
    import argparse

    p = argparse.ArgumentParser(description="Verify each provider serves the model it was asked for.")
    p.add_argument("--registry", default=None)
    p.add_argument("--strict", action="store_true",
                   help="exit non-zero if any model is unverified, not only on a mismatch")
    args = p.parse_args(argv)

    mismatches, unverified, checked = 0, 0, 0
    for m in load_registry(args.registry):
        if not m.available:
            continue
        checked += 1
        try:
            ident = attest(m)
        except ProviderError as e:
            print(f"  {m.label:26} — call failed (reliability, not identity): {str(e)[:110]}")
            continue
        if ident.status == "MISMATCH":
            mismatches += 1
            print(f"  {m.label:26} MISMATCH — asked {ident.requested!r}, served {ident.served!r}")
        elif ident.status == "unverified":
            unverified += 1
            print(f"  {m.label:26} unverified — provider did not echo a model id")
        else:
            print(f"  {m.label:26} ok — served {ident.served}")

    print(f"\n{checked} checked · {mismatches} mismatch(es) · {unverified} unverified")
    if mismatches:
        return 1
    if unverified and args.strict:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
