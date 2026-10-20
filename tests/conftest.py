"""Run every test from the repository root, whatever directory pytest was started in.

Several tests and tools name committed files by relative path ("posts/sources.json",
the "posts" default of tools/devto_publish.title_of). Those resolve against the
process working directory, so they pass when pytest starts at the repo root, which
is how ci.yml runs it, and fail when it does not.

The VAC replay does not. vac-protocol's replay.yml runs the bundle's replay block
from the BUNDLE directory, so the command is `v/bin/pytest -q issuer` with the
working directory one level above the checkout. On 2026-10-19 that made
test_reads_the_title_from_front_matter and test_the_committed_sources_file_is_valid
fail in the replay (run 39243050498) while both passed in this repo's own CI on the
same commit. Same code, same files, different starting directory.

Pinning the working directory here makes the suite independent of where it is
launched, which is what "the full test suite passes" in the replay block promises.
Tests that need a different directory still use monkeypatch.chdir, which restores
to this root afterwards.
"""
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True, scope="session")
def _run_from_repo_root():
    before = os.getcwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(before)
