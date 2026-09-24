"""The A/B log is not in git and has no undo, so these are the guards.

Each test is a way the filler could corrupt a 22KB document that holds findings,
a pre-registration and a running tally alongside the data rows.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import ab_fill as A

H = A.HEADER
DOC = f"""# doc
## Log
{H}
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-07-21 | dev.to | Tue | 4PM | a | | | | n |
| 2 | 2026-07-21 | LinkedIn | Tue | 4PM | a | | | | n |
| 3 | 2026-08-14 | dev.to | Thu | 9AM | b | | | | n |
| 4 | 2026-09-01 | dev.to | Tue | 9AM | c | 99 | 1% | | already |

## A DIFFERENT TABLE
{H}
|---|---|---|---|---|---|---|---|---|---|
| 9 | 2026-07-21 | dev.to | Tue | 4PM | z | | | | must stay blank |
"""
IDX = {
 "2026-07-21": [{"id": 1, "page_views_count": 25, "public_reactions_count": 0, "comments_count": 2}],
 "2026-08-14": [{"id": 2, "page_views_count": 10, "public_reactions_count": 1, "comments_count": 0},
                {"id": 3, "page_views_count": 20, "public_reactions_count": 2, "comments_count": 0}],
}
rows = lambda t: [l for l in t.split("\n")
                  if l.startswith("|") and not l.startswith("|---") and "Platform" not in l]


def test_fills_a_blank_devto_row():
    assert rows(A.fill(DOC, IDX)[0])[0].split("|")[7].strip() == "25"


def test_leaves_other_platforms_alone():
    assert rows(A.fill(DOC, IDX)[0])[1].split("|")[7].strip() == ""


def test_refuses_an_ambiguous_date():
    """Two articles on one day. Guessing either is a fabricated measurement."""
    out, notes = A.fill(DOC, IDX)
    assert rows(out)[2].split("|")[7].strip() == ""
    assert any("2 articles match" in n for n in notes)


def test_never_overwrites_a_filled_row():
    assert "99" in rows(A.fill(DOC, IDX)[0])[3]


def test_stops_at_the_end_of_its_own_table():
    """The file holds findings and a pre-registration below the Log table. A
    tool that wandered into those would be rewriting conclusions."""
    assert rows(A.fill(DOC, IDX)[0])[4].split("|")[7].strip() == ""


def test_refuses_when_the_header_is_gone():
    """If the document's shape changed, the safe move is to do nothing."""
    out, notes = A.fill(DOC.replace(H, "| totally | different |"), IDX)
    assert out == DOC.replace(H, "| totally | different |")
    assert any("refusing to guess" in n for n in notes)


def test_skips_a_row_with_zero_views():
    """Zero views is too early to measure, not a measurement of zero."""
    out, _ = A.fill(DOC, {"2026-07-21": [{"id": 1, "page_views_count": 0,
                                          "public_reactions_count": 0, "comments_count": 0}]})
    assert rows(out)[0].split("|")[7].strip() == ""
