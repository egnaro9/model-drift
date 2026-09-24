

# ── a required section left as TODO must block publication ────────────────

def _post(body_for_section):
    return ('---\ntitle: "T"\ndate: 2026-01-01\nstatus: draft\n---\n\n'
            '# T\n\n## What happened\n\nSomething.\n\n'
            f'## What I might have wrong\n\n{body_for_section}\n\n'
            '---\n\nAvailability line.\n')


def test_a_TODO_section_is_not_due(tmp_path):
    from modeldrift.publish import due_drafts
    (tmp_path / "2026-01-01-x.md").write_text(_post("TODO"))
    assert due_drafts(str(tmp_path), today="2026-06-01") == []


def test_a_section_holding_only_the_template_comment_is_not_due(tmp_path):
    from modeldrift.publish import due_drafts
    (tmp_path / "2026-01-01-x.md").write_text(
        _post("<!-- REQUIRED before this can be published. -->\n\nTODO"))
    assert due_drafts(str(tmp_path), today="2026-06-01") == []


def test_an_empty_section_is_not_due(tmp_path):
    from modeldrift.publish import due_drafts
    (tmp_path / "2026-01-01-x.md").write_text(_post(""))
    assert due_drafts(str(tmp_path), today="2026-06-01") == []


def test_a_filled_section_IS_due(tmp_path):
    """The mirror. A guard that never lets anything through is also broken."""
    from modeldrift.publish import due_drafts
    (tmp_path / "2026-01-01-x.md").write_text(
        _post("The baseline run graded half its calls, so the drop may be noise."))
    assert due_drafts(str(tmp_path), today="2026-06-01") == ["2026-01-01-x"]


def test_a_future_dated_post_is_not_due_however_complete(tmp_path):
    from modeldrift.publish import due_drafts
    # the DATE that matters is the front matter's, not the filename's
    (tmp_path / "2026-12-01-x.md").write_text(
        _post("A real caveat, written out.").replace("date: 2026-01-01", "date: 2026-12-01"))
    assert due_drafts(str(tmp_path), today="2026-06-01") == []
