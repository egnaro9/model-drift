"""Findings emitted by the other instruments in the estate.

model-drift is not the only thing here that measures something on a schedule.
vac-protocol re-replays every published claim weekly from a machine that never
saw the evidence; evalmut plants known defects into a target eval suite and
reports which of its checks stayed green. Both produce dated, falsifiable
results and neither had anywhere to send them.

Each instrument commits `notes/findings.json` to its own main. This module
fetches those and turns them into the same Finding objects the local detector
produces, so one archive, one ledger and one draft format serve all of them.

Deliberately not a webhook or a repository_dispatch. Those need a token in
every instrument repo, and a finding that lives in a payload is gone the moment
the run is garbage-collected. A committed file is version-controlled at its
source and readable by anyone, which is the same reason the notes page reads
posts from raw.githubusercontent rather than keeping a copy.

THE PAYLOAD IS DATA, NEVER INSTRUCTIONS. It is fetched over the network and
rendered into something published under Erik's name, so it is validated
strictly and refused on any mismatch rather than coerced into working. A
generator that quietly repairs a malformed finding is a generator that will
one day publish a malformed finding.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .findings import ABOUT_HARNESS, ABOUT_INFRA, ABOUT_MODELS, Finding

# Versioned on purpose. The same reasoning as the DERIVATIONS registry in the
# suite build: a reader must not be able to be silently repointed at a payload
# with a different shape. An unknown schema is refused, never best-guessed.
SCHEMA = "drift-notes/finding@1"

VALID_ABOUT = {ABOUT_MODELS, ABOUT_HARNESS, ABOUT_INFRA}

# Bounds exist so one bad emitter cannot flood the archive or blow up a page.
MAX_FINDINGS = 25
MAX_EVIDENCE = 12
MAX_TEXT = 400


class RefusedPayload(Exception):
    """A payload that did not validate. The reason is the message."""


def _text(value: Any, field_name: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise RefusedPayload(f"{field_name} is {type(value).__name__}, expected string")
    v = value.strip()
    if not v:
        raise RefusedPayload(f"{field_name} is empty")
    if len(v) > limit:
        raise RefusedPayload(f"{field_name} is {len(v)} chars, limit {limit}")
    return v


def parse(payload: Any, source: str) -> List[Finding]:
    """Validate one instrument's findings.json into Finding objects.

    Raises RefusedPayload with a precise reason rather than returning a partial
    list: half a finding is worse than none, because the missing half is
    usually the evidence.
    """
    if not isinstance(payload, dict):
        raise RefusedPayload(f"{source}: payload is not an object")
    got = payload.get("schema")
    if got != SCHEMA:
        raise RefusedPayload(f"{source}: schema is {got!r}, expected {SCHEMA!r}")

    raw = payload.get("findings")
    if not isinstance(raw, list):
        raise RefusedPayload(f"{source}: findings is not a list")
    if len(raw) > MAX_FINDINGS:
        raise RefusedPayload(f"{source}: {len(raw)} findings, limit {MAX_FINDINGS}")

    out: List[Finding] = []
    for i, item in enumerate(raw):
        where = f"{source}.findings[{i}]"
        if not isinstance(item, dict):
            raise RefusedPayload(f"{where} is not an object")

        about = _text(item.get("about"), f"{where}.about", 40)
        if about not in VALID_ABOUT:
            # This field is what stops an outage being published as a model
            # story. A wrong value is not a typo to fix, it is a claim about
            # what the finding is about.
            raise RefusedPayload(
                f"{where}.about is {about!r}, expected one of {sorted(VALID_ABOUT)}")

        run_key = item.get("run_key")
        if not isinstance(run_key, list) or not run_key:
            raise RefusedPayload(f"{where}.run_key must be a non-empty list")
        keys = [_text(k, f"{where}.run_key[]", 120) for k in run_key]

        ev_raw = item.get("evidence")
        if not isinstance(ev_raw, list) or not ev_raw:
            # A finding with no evidence is an assertion, and this pipeline
            # does not publish assertions.
            raise RefusedPayload(f"{where}.evidence must be a non-empty list")
        if len(ev_raw) > MAX_EVIDENCE:
            raise RefusedPayload(f"{where}.evidence has {len(ev_raw)} rows, limit {MAX_EVIDENCE}")
        evidence = []
        for j, row in enumerate(ev_raw):
            if not isinstance(row, dict):
                raise RefusedPayload(f"{where}.evidence[{j}] is not an object")
            evidence.append({"claim": _text(row.get("claim"), f"{where}.evidence[{j}].claim"),
                             "how": _text(row.get("how"), f"{where}.evidence[{j}].how")})

        when = item.get("when")
        if when is not None:
            when = _text(when, f"{where}.when", 10)

        out.append(Finding(
            kind=_text(item.get("kind"), f"{where}.kind", 40),
            about=about,
            # Namespaced by source so two instruments cannot collide on a
            # subject, and so a fingerprint says where it came from.
            subject=f"{source}/{_text(item.get('subject'), f'{where}.subject', 120)}",
            headline=_text(item.get("headline"), f"{where}.headline", 200),
            run_key=[f"{source}:{k}" for k in keys],
            evidence=evidence,
            when=when,
        ))
    return out


def fetch(url: str, timeout: int = 30) -> Tuple[Optional[Any], str]:
    """(payload, error). A 404 is reported as a 404, not as 'no findings'.

    The distinction is the whole point: an instrument that has not emitted yet
    and an instrument whose file has moved look identical from here unless the
    status code is carried through. See the pin-drift blind spot, where a
    renamed artifact read as a healthy 200 for four days.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), ""
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except json.JSONDecodeError as e:
        return None, f"not JSON: {e}"
    except Exception as e:  # noqa: BLE001 - the reason travels, whatever it is
        return None, f"{type(e).__name__}: {e}"


def collect(sources: Sequence[Dict[str, str]]) -> Tuple[List[Finding], List[str]]:
    """(findings, problems). One bad source never silences the others.

    Problems are returned rather than raised so the caller can report them.
    A source that is failing is itself news about the estate.
    """
    found: List[Finding] = []
    problems: List[str] = []
    for src in sources:
        name, url = src.get("source", "?"), src.get("url", "")
        if not url:
            problems.append(f"{name}: no url configured")
            continue
        payload, err = fetch(url)
        if payload is None:
            problems.append(f"{name}: {err} at {url}")
            continue
        try:
            found.extend(parse(payload, name))
        except RefusedPayload as e:
            problems.append(f"REFUSED {e}")
    return found, problems


def load_sources(path: str) -> List[Dict[str, str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data.get("sources", []) if isinstance(data, dict) else []
