"""tests/test_item_view.py -- pure, no-database proof for
`extensions.autoharn.ledger_read.parse_witness_refs`, added by build-item-view (SPEC.md sec
2.2). Live-DB proof for `reviews_for_row`/`item_witnesses`/the `GET /api/item/{row_id}/
obligations` route lives in the SEPARATE tests/test_item_view_live.py -- a module-level
`pytestmark` skipif (the same pattern test_cosign_live.py uses) applies to EVERY test in its
module, so the DB-needing tests cannot share a module with these pure ones without silently
skipping them too when no Postgres host is reachable.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from extensions.autoharn.ledger_read import parse_witness_refs  # noqa: E402


# Same RED/GREEN framing test_disposition.py uses for its sibling parser (parse_item_refs) --
# this one deliberately does NOT require a wrapping `panel-item:` token (that is the difference
# from parse_item_refs, and the whole reason it exists as its own function rather than reusing
# that one).

def test_empty_refs_yields_no_witnesses() -> None:
    assert parse_witness_refs(None) == []
    assert parse_witness_refs("") == []


def test_plain_row_and_work_tokens_no_wrapper_needed() -> None:
    assert parse_witness_refs("row:681 work:kr-titration-design-exploration") == [
        ("row", "681"),
        ("work", "kr-titration-design-exploration"),
    ]


def test_panel_item_token_itself_is_not_a_witness() -> None:
    # A `panel-item:...` token is a different grammar entirely (parse_item_refs's concern) --
    # this generic parser must not misread it as a row/work witness of its own.
    assert parse_witness_refs("panel-item:680:A1 row:681") == [("row", "681")]


def test_malformed_tokens_are_dropped_not_fabricated() -> None:
    assert parse_witness_refs("row:abc row: row:12x free prose work:") == []


def test_mixed_order_and_free_prose_around_tokens() -> None:
    assert parse_witness_refs("see also row:5 and work:my-slug per the discussion") == [
        ("row", "5"),
        ("work", "my-slug"),
    ]
