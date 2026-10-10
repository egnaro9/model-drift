"""The direct-to-database recording path, against a real database.

Nothing here is mocked on both ends. The payload is the one `probe()` builds, it goes
through eval-history's real `ingest`, and the assertions read the row back out of the
database. A test whose input is a stub and whose output is a stub measures that two
stubs agree, which is how a scoring suite elsewhere stayed green while the thing it
checked was discarded entirely.

SQLite rather than Postgres because `make_engine` supports both and CI should not need a
service container for a schema-contract test. What is being asserted is that model-drift's
payload satisfies eval-history's `RunIn` and survives the round trip, and that is the same
question on either backend.

This is also a CROSS-REPO CONTRACT test. model-drift builds the body; eval-history owns
the schema. If `RunIn` gains a required field, this goes red here rather than at 06:17 UTC
in a weekly job nobody is watching.
"""
from __future__ import annotations

import json

import pytest

from evalhistory.db import make_engine
from sqlalchemy import text

from modeldrift.suite import SUITE

from modeldrift.providers import Model
from modeldrift.run import _store_direct, probe

sqlalchemy = pytest.importorskip(
    "sqlalchemy",
    reason="evalhistory is a dev dependency; `pip install -e \".[dev]\"` should provide it",
)

# The deterministic mock provider tests/test_probe.py uses: no keys, no network.
STABLE = Model("mock:stable", "Mock", "mock", "mock", "NONE")
DRIFTED = Model("mock:drifted", "Mock (drifted)", "mock", "mock-drifted", "NONE")


def payload(model=STABLE):
    """The real thing probe() builds, not a hand-written imitation of it.

    The first version of this file invented the payload and got it wrong: `scores`
    carries four keys and the fixture supplied one, so RunIn rejected it. That failure
    was the test working, and the lesson is the cheaper one, which is not to hand-roll
    a fixture for a shape the code already produces. Calling probe() means this test
    pins what model-drift ACTUALLY sends, so a change to the payload is caught here
    instead of at 06:17 UTC on a Sunday.
    """
    return probe(model)


@pytest.fixture
def db_url(tmp_path):
    """A real, empty eval-history database.

    init_db() is required: make_engine only connects, it does not create the schema.
    Postgres already has the tables, so forgetting this fails only in the test, which
    is the right place for it to fail.
    """
    url = f"sqlite:///{tmp_path / 'history.db'}"
    from evalhistory.db import init_db, make_engine
    init_db(make_engine(url))
    return url


def test_a_run_is_stored_and_reads_back_with_its_metrics(db_url):
    p = payload()
    rid = _store_direct(db_url, p)
    assert rid, "nothing was stored"

    with make_engine(db_url).connect() as c:
        rows = c.execute(text("select * from runs")).mappings().all()
    assert len(rows) == 1, "exactly one row should exist"
    row = dict(rows[0])
    assert str(row["id"]) == rid, "the id returned is not the id stored"
    assert row["name"] == "mock:stable"

    # The values that had to travel. Asserting only that a row exists would pass with
    # every metric discarded, which is the defect this file's docstring is about.
    # eval-history flattens metrics into columns rather than storing the dict.
    assert row["faithfulness"] == p["metrics"]["faithfulness"] == 1.0
    assert row["citation_rate"] == p["metrics"]["citation_rate"]
    assert row["precision_at_k"] == p["metrics"]["precision@k"]
    assert row["recall_at_k"] == p["metrics"]["recall@k"]
    assert row["n_cases"] == p["metrics"]["n_cases"] == float(len(SUITE))

    # The nested half. 35 cases went in; a store that kept the summary and dropped the
    # detail would satisfy every assertion above.
    with make_engine(db_url).connect() as c:
        assert c.execute(text("select count(*) from cases")).scalar_one() == len(SUITE)


def test_graded_total_does_not_survive_the_round_trip(db_url):
    """A real gap, pinned rather than fixed, because the fix belongs in eval-history.

    probe() puts `graded_total` in metrics deliberately: accuracy is
    graded_pass/graded_total, the denominator moves when a call truncates, and
    report.min_detectable_change needs it. eval-history's `runs` table has no such
    column, so it is dropped on ingest and nothing downstream of the database can
    recover it. The committed board in this repo still carries it, which is why this is
    a gap and not an outage.

    If a `graded_total` column is ever added upstream, this test goes red and should be
    replaced by one asserting the value survives.
    """
    p = payload()
    assert "graded_total" in p["metrics"], "probe stopped sending it; this test is stale"
    rid = _store_direct(db_url, p)
    assert rid
    with make_engine(db_url).connect() as c:
        row = dict(c.execute(text("select * from runs")).mappings().one())
    assert "graded_total" not in row


def test_private_keys_are_stripped_and_source_is_set(db_url):
    """`_errors` and `_first_error` are diagnostics, not data, and must not be stored."""
    rid = _store_direct(db_url, payload())
    with make_engine(db_url).connect() as c:
        row = dict(c.execute(text("select * from runs")).mappings().one())
    assert rid
    assert row["source"] == "ci"
    blob = json.dumps(row, default=str)
    assert "_errors" not in blob
    assert "_first_error" not in blob


def test_two_runs_of_the_same_model_both_land(db_url):
    """History is the point. A second probe must add a row, not replace one."""
    a = _store_direct(db_url, payload(STABLE))
    b = _store_direct(db_url, payload(DRIFTED))
    assert a and b and a != b
    with make_engine(db_url).connect() as c:
        n = c.execute(text("select count(*) from runs")).scalar_one()
    assert n == 2


def test_an_unreachable_database_returns_none_rather_than_raising():
    """A recording failure must not take the weekly probe down with it."""
    assert _store_direct("postgresql://nobody@127.0.0.1:1/nope", payload()) is None


def test_a_payload_the_schema_rejects_returns_none(db_url):
    """RunIn requires run, metrics and cases. A body missing one is not silently kept."""
    bad = payload()
    del bad["metrics"]
    assert _store_direct(db_url, bad) is None


def test_it_reports_rather_than_raises_when_evalhistory_is_absent(db_url, monkeypatch, capsys):
    """The probe runs on machines with no database driver; that must stay true."""
    import builtins
    real = builtins.__import__

    def refuse(name, *a, **kw):
        if name.startswith("evalhistory"):
            raise ImportError("No module named 'evalhistory'")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert _store_direct(db_url, payload()) is None
    out = capsys.readouterr().out
    assert "eval-history is not installed" in out
    assert "pip install" in out, "the message has to say how to fix it"
