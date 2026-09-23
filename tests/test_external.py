"""Findings arriving from other repos, which is a trust boundary.

A payload here is fetched over the network and rendered into something
published under Erik's name. Every test below pins a way that could go wrong
quietly. The rule the module is built on is that a malformed finding is
REFUSED with a reason, never repaired: a generator that quietly fixes a broken
payload is a generator that will one day publish a broken payload.
"""
from __future__ import annotations

import json

import pytest

from modeldrift.external import (MAX_EVIDENCE, MAX_FINDINGS, SCHEMA, RefusedPayload,
                                 collect, load_sources, parse)


def _ok(**over):
    f = {"kind": "coverage-gap", "about": "harness", "subject": "promptfoo/contains",
         "headline": "2 of promptfoo's new assertions pass a planted defect",
         "run_key": ["promptfoo@v0.118.0"],
         "evidence": [{"claim": "a planted defect passed", "how": "evalmut run, 2 holes"}]}
    f.update(over)
    return {"schema": SCHEMA, "findings": [f]}


# ── the schema pin ────────────────────────────────────────────────────────

def test_a_known_schema_parses():
    out = parse(_ok(), "evalmut")
    assert len(out) == 1 and out[0].kind == "coverage-gap"


def test_an_unknown_schema_is_refused_not_guessed():
    """Versioned for the same reason the suite's DERIVATIONS registry is: a
    reader must not be silently repointed at a payload of a different shape."""
    bad = _ok()
    bad["schema"] = "drift-notes/finding@2"
    with pytest.raises(RefusedPayload, match="schema"):
        parse(bad, "evalmut")


def test_a_missing_schema_is_refused():
    bad = _ok()
    del bad["schema"]
    with pytest.raises(RefusedPayload, match="schema"):
        parse(bad, "evalmut")


# ── the field that stops an outage being published as a model story ───────

def test_an_unrecognised_about_value_is_refused():
    """`about` is what keeps infrastructure from being written up as
    capability. A wrong value is a claim, not a typo to correct."""
    with pytest.raises(RefusedPayload, match="about"):
        parse(_ok(about="models-ish"), "evalmut")


@pytest.mark.parametrize("about", ["models", "harness", "infrastructure"])
def test_every_valid_about_value_is_accepted(about):
    assert parse(_ok(about=about), "evalmut")[0].about == about


# ── evidence is not optional ──────────────────────────────────────────────

def test_a_finding_with_no_evidence_is_refused():
    """An assertion is not a finding, and this pipeline does not publish
    assertions."""
    with pytest.raises(RefusedPayload, match="evidence"):
        parse(_ok(evidence=[]), "evalmut")


def test_evidence_rows_must_carry_both_claim_and_how():
    with pytest.raises(RefusedPayload, match="how"):
        parse(_ok(evidence=[{"claim": "something happened"}]), "evalmut")


def test_too_much_evidence_is_refused():
    rows = [{"claim": f"c{i}", "how": f"h{i}"} for i in range(MAX_EVIDENCE + 1)]
    with pytest.raises(RefusedPayload, match="limit"):
        parse(_ok(evidence=rows), "evalmut")


# ── bounds, so one bad emitter cannot flood the archive ───────────────────

def test_too_many_findings_is_refused():
    payload = {"schema": SCHEMA, "findings": [_ok()["findings"][0]] * (MAX_FINDINGS + 1)}
    with pytest.raises(RefusedPayload, match="limit"):
        parse(payload, "evalmut")


def test_an_absurdly_long_headline_is_refused():
    with pytest.raises(RefusedPayload, match="limit"):
        parse(_ok(headline="x" * 5000), "evalmut")


def test_a_non_string_field_is_refused_not_coerced():
    with pytest.raises(RefusedPayload, match="expected string"):
        parse(_ok(headline=42), "evalmut")


# ── namespacing, so two instruments cannot collide ────────────────────────

def test_the_source_namespaces_the_subject_and_run_key():
    """Two instruments can both have a finding about 'contains'. Without the
    namespace they would share a fingerprint and the second would be silently
    dropped as already-drafted."""
    a = parse(_ok(subject="contains"), "evalmut")[0]
    b = parse(_ok(subject="contains"), "vac-protocol")[0]
    assert a.subject == "evalmut/contains" and b.subject == "vac-protocol/contains"
    assert a.fingerprint() != b.fingerprint()


# ── one bad source never silences the others ──────────────────────────────

def test_a_failing_source_is_reported_and_the_others_still_load(monkeypatch):
    import modeldrift.external as ext

    def fake_fetch(url, timeout=30):
        if "broken" in url:
            return None, "HTTP 404"
        return _ok(), ""

    monkeypatch.setattr(ext, "fetch", fake_fetch)
    found, problems = ext.collect([{"source": "broken", "url": "https://x/broken.json"},
                                   {"source": "good", "url": "https://x/good.json"}])
    assert len(found) == 1 and found[0].subject.startswith("good/")
    assert any("404" in p for p in problems)


def test_a_refused_payload_names_the_source_in_the_problem(monkeypatch):
    import modeldrift.external as ext
    monkeypatch.setattr(ext, "fetch", lambda url, timeout=30: (_ok(about="nonsense"), ""))
    found, problems = ext.collect([{"source": "evalmut", "url": "https://x/f.json"}])
    assert found == []
    assert problems and "evalmut" in problems[0] and "REFUSED" in problems[0]


def test_a_missing_sources_file_means_local_only_not_a_crash(tmp_path):
    assert load_sources(str(tmp_path / "nope.json")) == []


def test_a_corrupt_sources_file_means_local_only_not_a_crash(tmp_path):
    p = tmp_path / "sources.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_sources(str(p)) == []


def test_the_committed_sources_file_is_valid():
    """The real file, not a fixture. A typo here silently disables an
    instrument, which is exactly the failure this pipeline exists to catch."""
    srcs = load_sources("posts/sources.json")
    assert srcs, "posts/sources.json has no sources"
    for s in srcs:
        assert s.get("source"), s
        assert s.get("url", "").startswith("https://raw.githubusercontent.com/"), s
        assert s["url"].endswith("/notes/findings.json"), s
