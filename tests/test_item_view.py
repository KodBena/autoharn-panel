"""tests/test_item_view.py -- pure, no-database proof for
`extensions.autoharn.ledger_adapter.parse_witness_refs`, added by build-item-view (SPEC.md sec
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

from extensions.autoharn.ledger_adapter import parse_resource_fields, parse_witness_refs  # noqa: E402


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


# Same RED/GREEN framing as parse_witness_refs above, for the sibling `resource:` statement
# grammar (design/USER-BLESSED-TABLE-TEMPLATE.md's "statement grammars" section, cycle-4 audit
# finding 6, SERIOUS: the item view rendered these as one undifferentiated prose blob, no parsed
# tier badge or labeled fields). This IS the same parser pickup.tmpl's own `resources()` uses
# (byte-for-byte, per parse_resource_fields's own docstring), so these specimens exercise that
# grammar directly, not a rephrased one.

def test_not_a_resource_statement_yields_none() -> None:
    assert parse_resource_fields("just an ordinary decision statement") is None
    assert parse_resource_fields("") is None


def test_well_formed_resource_statement_parses_all_six_fields() -> None:
    stmt = (
        "resource: makespan-scheduler | library | import:makespan_scheduler | "
        "minimum-makespan schedule proof | reach for ordering 3+ work items | "
        "blessed: ordering three or more claimed work items"
    )
    parsed = parse_resource_fields(stmt)
    assert parsed == {
        "name": "makespan-scheduler",
        "class_": "library",
        "reach": "import:makespan_scheduler",
        "what_it_proves": "minimum-makespan schedule proof",
        "guidance": "reach for ordering 3+ work items",
        "tier": "blessed: ordering three or more claimed work items",
        "tier_kind": "blessed",
    }


def test_malformed_field_count_yields_none_not_a_fabricated_shape() -> None:
    # Only five '|'-separated fields (GUIDANCE/TIER collapsed into one) -- must not be silently
    # coerced into six; the caller's job on None is to fall back to plain prose, never guess.
    assert parse_resource_fields("resource: name | class | reach | proves | guidance-and-tier") is None


def test_leading_whitespace_before_the_resource_prefix_is_tolerated() -> None:
    # Mirrors the SQL filter's `^[[:space:]]*resource:` admission (the coherence-partner contract
    # with led.tmpl's own write-side validator) -- an indented prefix still parses.
    stmt = "   resource: n | c | r | p | g | available"
    parsed = parse_resource_fields(stmt)
    assert parsed is not None
    assert parsed["name"] == "n"
    assert parsed["tier_kind"] == "available"


def test_embedded_newline_is_collapsed_before_field_split() -> None:
    # The run12 witness fix (design/USER-BLESSED-TABLE-TEMPLATE.md's "statement grammars"
    # section): a paste reflowed by a terminal's line wrap must not shred a field's own text or
    # the field count.
    stmt = "resource: n | c | a reach\nwrapped mid-word | proves | guidance | available"
    parsed = parse_resource_fields(stmt)
    assert parsed is not None
    assert parsed["reach"] == "a reach wrapped mid-word"


def test_tier_kind_classification_for_each_of_the_four_tiers() -> None:
    for tier, expected in [
        ("available", "available"),
        ("blessed: some task shape", "blessed"),
        ("mandated: some task shape", "mandated"),
        ("forbidden: some task shape", "forbidden"),
        ("an unrecognized tier word", "available"),  # catch-all, matches pickup.tmpl's own sort
    ]:
        stmt = f"resource: n | c | r | p | g | {tier}"
        parsed = parse_resource_fields(stmt)
        assert parsed is not None
        assert parsed["tier_kind"] == expected, f"tier={tier!r}"
        assert parsed["tier"] == tier  # the full raw field is never lost to the coarser class
