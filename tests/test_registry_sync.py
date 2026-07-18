"""The model list exists in two places. This makes them prove they agree.

`modeldrift/models.json` drives the probe; a hand-kept `MODELS` array in
`dashboard/index.html` drives the chart's legend, colours and tier filters.
Adding a model to the registry without touching the dashboard leaves it
*tracked but invisible* — probed weekly, posted to eval-history, and absent from
the board a reader is looking at. Nothing failed loudly when that happened,
which is the definition of a silent staleness bug.

The honest fix is one source of truth, and the registry now carries `group`,
`tier` and `color` so it can be that source. Rewiring the dashboard to fetch it
is a change to a working, live chart; this test is the cheap half — it can't
remove the duplication, but it makes divergence fail a build instead of
degrading a page quietly. Rewiring can follow once there's a reason to touch
that file anyway.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "modeldrift" / "models.json"
DASHBOARD_PATH = ROOT / "dashboard" / "index.html"

VALID_TIERS = {"flagship", "heavy", "mid", "mini", "nano", "mock"}

_ENTRY = re.compile(
    r'\{\s*id:\s*"(?P<id>[^"]+)",\s*label:\s*"(?P<label>[^"]*)",\s*'
    r'color:\s*"(?P<color>[^"]+)",\s*group:\s*"(?P<group>[^"]+)",\s*'
    r'tier:\s*"(?P<tier>[^"]+)"\s*\}')


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def dashboard():
    return {m.group("id"): m.groupdict() for m in
            _ENTRY.finditer(DASHBOARD_PATH.read_text(encoding="utf-8"))}


def test_the_dashboard_array_is_still_parseable():
    """If this fails the array was reformatted and the checks below went blind
    — a test that silently stops testing is worse than no test."""
    assert len(dashboard()) >= 10


def test_every_probed_model_appears_on_the_dashboard():
    missing = [e["id"] for e in registry()
               if e.get("tier") != "mock" and e["id"] not in dashboard()]
    assert not missing, (
        f"tracked but invisible on the board: {missing} — add them to the "
        f"MODELS array in dashboard/index.html")


def test_the_dashboard_shows_nothing_that_is_not_probed():
    known = {e["id"] for e in registry()}
    extra = [i for i in dashboard() if i not in known]
    assert not extra, f"on the board but not probed: {extra}"


@pytest.mark.parametrize("field", ["group", "tier", "color"])
def test_dashboard_metadata_matches_the_registry(field):
    reg = {e["id"]: e for e in registry()}
    for model_id, entry in dashboard().items():
        assert entry[field] == reg[model_id].get(field), (
            f"{model_id}.{field}: dashboard has {entry[field]!r}, "
            f"registry has {reg[model_id].get(field)!r}")


def test_registry_entries_are_well_formed():
    """Catches the PR that adds a model without tagging it — an untiered model
    is excluded from every generated claim, so this fails loudly instead."""
    seen = set()
    for e in registry():
        assert e["id"] not in seen, f"duplicate id {e['id']}"
        seen.add(e["id"])
        assert e.get("label"), f"{e['id']} has no label"
        assert e.get("group"), f"{e['id']} has no group"
        assert e.get("tier") in VALID_TIERS, f"{e['id']} has tier {e.get('tier')!r}"
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", e.get("color", "")), \
            f"{e['id']} has color {e.get('color')!r}"
