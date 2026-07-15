"""tests/test_disposition.py -- both-polarity, no-database proof for
`extensions.autoharn.disposition` (`derive_status`, `group_item_rows`) and
`extensions.autoharn.ledger_read.parse_item_refs`. Ported from the autoharn PoC's
`seen-red/panel-disposition/run_fixtures.py` (same cases, same RED/GREEN framing in each test's
own docstring) into this repo's own pytest suite -- these three functions are pure (dataclasses,
tuples, strings in and out; no SQL, no connection, no subprocess), so this is plain pytest, no
fixtures/mocks needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from extensions.autoharn.disposition import WitnessFacts, derive_status, group_item_rows  # noqa: E402
from extensions.autoharn.ledger_read import parse_item_refs  # noqa: E402


# ---- RED-shaped cases: derive_status/group_item_rows/parse_item_refs must NOT misclassify ----

def test_a_open_no_witnesses() -> None:
    assert derive_status(False, []) == "OPEN"


def test_b_witnessed_none_cosigned() -> None:
    result = derive_status(False, [
        WitnessFacts("row", "681", True, True, 681, False),
        WitnessFacts("row", "716", True, True, 716, False),
    ])
    assert result == "WITNESSED"


def test_c_no_item_token_fail_closed() -> None:
    assert parse_item_refs("row:1 work:foo", 680) == (None, [])


def test_f_collision_carried_not_narrowed() -> None:
    assert group_item_rows((("A1", 812), ("A1", 815))) == {"A1": (812, 815)}


# ---- GREEN-shaped cases: the correct positive classification -----------------------------------

def test_d_item_row_fast_path() -> None:
    assert derive_status(True, []) == "COSIGNED"


def test_e_parse_full_refs_string() -> None:
    result = parse_item_refs("panel-item:680:A1 row:681 work:kr-titration-design-exploration", 680)
    assert result == ("A1", [("row", "681"), ("work", "kr-titration-design-exploration")])


def test_g_partial_one_of_two() -> None:
    result = derive_status(False, [
        WitnessFacts("row", "681", True, True, 681, True),
        WitnessFacts("row", "716", True, True, 716, False),
    ])
    assert result == "PARTIAL"


def test_h_cosigned_all_witnesses_equivalence() -> None:
    result = derive_status(False, [
        WitnessFacts("row", "681", True, True, 681, True),
        WitnessFacts("row", "716", True, True, 716, True),
    ])
    assert result == "COSIGNED"


def test_i_no_collision_distinct_items() -> None:
    assert group_item_rows((("A1", 812), ("A2", 900))) == {"A1": (812,), "A2": (900,)}


def test_j_prefix_adjacent_item_ids_distinct() -> None:
    """The anchored parser must distinguish a prefix-adjacent item-id pair: 'A1' is a literal
    substring of 'A10' -- this is the one case covering the read/write divergence class the
    autoharn PoC's round-3/round-4 findings named (the shared `parse_item_refs` function is
    what both the read path and the seed script call to answer "does refs carry item <iid>")."""
    item_id, witnesses = parse_item_refs("panel-item:680:A10 row:900", 680)
    assert item_id == "A10"
    assert item_id != "A1"
    assert witnesses == [("row", "900")]
