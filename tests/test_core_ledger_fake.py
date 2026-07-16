"""tests/test_core_ledger_fake.py -- smoke tests for `tests.fakes.core_ledger_reader.
FakeCoreLedgerReader` itself (work item core-ledger-fake, ledger row 936; acceptance criteria
pre-registered at ledger row 1002). A fake with no tests of its own is not trustworthy: this
proves the fake's behavior against hand-built, multi-row in-memory fixtures -- especially the
`supersede_chain` walk and the `rows()` validation/filter/order semantics -- matches what
`backend/core/ledger_read.py`'s real, DB-backed functions do, not just that it returns SOME
dict.

Pure Python, no database, no fixtures/mocks needed -- the fake IS the double under test here.
"""
from __future__ import annotations

import sys
import typing
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from config import ConnectionFacts, PanelConfig  # noqa: E402
from core.ports import CoreLedgerPort  # noqa: E402
from fakes.core_ledger_reader import FakeCoreLedgerReader  # noqa: E402


def _cfg() -> PanelConfig:
    """A `PanelConfig` the fake never actually reads (every fake method ignores `cfg` -- see the
    fake's own docstring) -- constructed only because the Protocol's methods all take one, same
    shape `tests/test_cosign_live.py`'s own `build_cfg()` uses for its (live-DB) equivalent."""
    connection = ConnectionFacts(pg_uri=None, pg_host="unused", pg_port=None, pg_db="unused",
                                  pg_user=None, pg_password=None, source="fake-unused")
    return PanelConfig(
        repo_root=REPO, connection=connection, schema="experience", kern_schema="experience_kernel",
        role=None, led_bin=None, read_only_locked=False, bind_host="127.0.0.1", bind_port=8420,
        poll_interval=2.0, extensions=("autoharn",), config_source="fake-unused",
        maintainer_principal="maintainer", active_profile=None, available_profiles=(),
    )


def _row(id: int, kind: str, statement: str, ts: datetime, *, supersedes: int | None = None,
         actor_name: str | None = "alice", refs: str | None = None) -> dict:
    return {
        "id": id, "kind": kind, "statement": statement, "ts": ts, "refs": refs,
        "supersedes": supersedes, "actor_name": actor_name,
    }


def _ts(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 7, day, hour, 0, 0, tzinfo=timezone.utc)


CFG = _cfg()


# ---- acceptance criterion (1): no psycopg import in the fake source --------------------------

def test_fake_source_never_imports_psycopg() -> None:
    # Only checks actual import statements -- the file's own docstring legitimately DISCUSSES
    # psycopg in prose (explaining why it is deliberately not imported), so a bare substring
    # check over the whole file would false-positive on that very explanation.
    src = (REPO / "tests" / "fakes" / "core_ledger_reader.py").read_text(encoding="utf-8")
    import_lines = [ln.strip() for ln in src.splitlines() if ln.strip().startswith(("import ", "from "))]
    assert not any("psycopg" in ln for ln in import_lines), import_lines


# ---- acceptance criterion (2): structural conformance ----------------------------------------

def test_fake_implements_every_protocol_member() -> None:
    """Runtime companion to the module's own mypy-checked `_STRUCTURAL_CONFORMANCE_CHECK`
    assignment: every name `CoreLedgerPort` declares is a real callable attribute on
    `FakeCoreLedgerReader`."""
    members = typing.get_protocol_members(CoreLedgerPort)
    assert members  # sanity: the Protocol actually declares something
    fake = FakeCoreLedgerReader()
    for name in members:
        assert hasattr(fake, name), f"FakeCoreLedgerReader is missing protocol member {name!r}"
        assert callable(getattr(fake, name))


def test_fake_is_assignable_to_the_protocol_typed_variable() -> None:
    reader: CoreLedgerPort = FakeCoreLedgerReader()
    assert isinstance(reader, FakeCoreLedgerReader)


# ---- acceptance criterion (3): genuine multi-row supersede_chain walk -------------------------

def _chain_fixture() -> FakeCoreLedgerReader:
    # 10 (root) <- 11 <- 12 <- 13 (most recent); a 4th, unrelated row (20) sits alongside.
    return FakeCoreLedgerReader(rows_data=[
        _row(10, "note", "root", _ts(1)),
        _row(11, "note", "supersedes root", _ts(2), supersedes=10),
        _row(12, "note", "supersedes 11", _ts(3), supersedes=11),
        _row(13, "note", "supersedes 12, current", _ts(4), supersedes=12),
        _row(20, "note", "unrelated", _ts(5)),
    ])


def test_supersede_chain_multi_row_middle_of_chain() -> None:
    fake = _chain_fixture()
    chain = fake.supersede_chain(CFG, 12)
    assert chain.row_id == 12
    # Mirrors the REAL `ledger_read.supersede_chain`'s own walk order exactly: each hop appends
    # the row's OWN `supersedes` target before following it, so predecessors comes back
    # nearest-hop-first (11, then its own predecessor 10) -- this is the actual algorithm's
    # order, verified by tracing `core/ledger_read.py`'s loop by hand, not a guess.
    assert chain.predecessors == (11, 10)
    assert chain.successor == 13


def test_supersede_chain_multi_row_root_has_no_predecessors() -> None:
    fake = _chain_fixture()
    chain = fake.supersede_chain(CFG, 10)
    assert chain.predecessors == ()
    assert chain.successor == 11


def test_supersede_chain_tip_has_no_successor() -> None:
    fake = _chain_fixture()
    chain = fake.supersede_chain(CFG, 13)
    assert chain.predecessors == (12, 11, 10)
    assert chain.successor is None


def test_supersede_chain_unrelated_row_is_trivial() -> None:
    fake = _chain_fixture()
    chain = fake.supersede_chain(CFG, 20)
    assert chain.predecessors == ()
    assert chain.successor is None


def test_supersede_chain_guards_against_a_cycle() -> None:
    # Not data this deployment's schema should ever produce, but the REAL function's loop has an
    # explicit `in seen` guard against it -- replicate that guard, not just the happy path.
    fake = FakeCoreLedgerReader(rows_data=[
        _row(1, "note", "a", _ts(1), supersedes=2),
        _row(2, "note", "b", _ts(2), supersedes=1),
    ])
    chain = fake.supersede_chain(CFG, 1)
    assert chain.predecessors == (2, 1)  # terminates instead of looping forever


# ---- acceptance criterion (4): sort/limit/offset validation raises like the real function -----

def test_rows_rejects_unknown_sort_by() -> None:
    fake = FakeCoreLedgerReader()
    with pytest.raises(ValueError):
        fake.rows(CFG, sort_by="nope")


def test_rows_rejects_unknown_sort_dir() -> None:
    fake = FakeCoreLedgerReader()
    with pytest.raises(ValueError):
        fake.rows(CFG, sort_dir="sideways")


def test_rows_rejects_sub_one_limit() -> None:
    fake = FakeCoreLedgerReader()
    with pytest.raises(ValueError):
        fake.rows(CFG, limit=0)


def test_rows_rejects_negative_offset() -> None:
    fake = FakeCoreLedgerReader()
    with pytest.raises(ValueError):
        fake.rows(CFG, offset=-1)


def test_count_rows_has_no_sort_or_limit_kwargs() -> None:
    # count_rows's own Protocol signature carries no sort_by/limit/offset at all -- calling it
    # with one is a TypeError, proving the fake's signature matches the Protocol's, not a looser
    # one that would silently accept (and ignore) extra kwargs.
    fake = FakeCoreLedgerReader()
    with pytest.raises(TypeError):
        fake.count_rows(CFG, limit=5)  # type: ignore[call-arg]


# ---- acceptance criterion (5): filter/order semantics against hand-built multi-row data -------

def _rows_fixture() -> FakeCoreLedgerReader:
    rows = [
        _row(1, "decision", "first decision about widgets", _ts(1), actor_name="alice"),
        _row(2, "note", "a note about gadgets", _ts(2), actor_name="bob"),
        _row(3, "decision", "second decision, widgets again", _ts(3), actor_name="alice"),
        # 4 supersedes 3 -- 3 becomes non-current
        _row(4, "decision", "revised decision about widgets", _ts(4), actor_name="alice", supersedes=3),
        _row(5, "question", "what about gadgets", _ts(5), actor_name=None),  # no actor (LEFT JOIN NULL)
        # ties on kind, for the id-secondary-tiebreak proof
        _row(6, "note", "another note", _ts(6), actor_name="bob"),
    ]
    return FakeCoreLedgerReader(rows_data=rows)


def test_rows_default_excludes_superseded() -> None:
    fake = _rows_fixture()
    ids = {r["id"] for r in fake.rows(CFG, limit=200)}
    assert 3 not in ids  # superseded by 4
    assert 4 in ids


def test_rows_include_superseded_true_includes_everything() -> None:
    fake = _rows_fixture()
    ids = {r["id"] for r in fake.rows(CFG, include_superseded=True, limit=200)}
    assert ids == {1, 2, 3, 4, 5, 6}


def test_rows_filter_by_kind() -> None:
    fake = _rows_fixture()
    ids = {r["id"] for r in fake.rows(CFG, kind="decision", limit=200)}
    assert ids == {1, 4}  # 3 excluded (superseded), 2/5/6 wrong kind


def test_rows_filter_by_actor_name() -> None:
    fake = _rows_fixture()
    ids = {r["id"] for r in fake.rows(CFG, actor_name="bob", limit=200)}
    assert ids == {2, 6}


def test_rows_filter_by_q_is_case_insensitive_substring() -> None:
    fake = _rows_fixture()
    ids = {r["id"] for r in fake.rows(CFG, q="GADGETS", limit=200)}
    assert ids == {2, 5}


def test_rows_filter_by_since_id() -> None:
    fake = _rows_fixture()
    ids = {r["id"] for r in fake.rows(CFG, since_id=4, include_superseded=True, limit=200)}
    assert ids == {5, 6}


def test_rows_filter_by_since_and_until_date_range() -> None:
    fake = _rows_fixture()
    ids = {r["id"] for r in fake.rows(
        CFG, since="2026-07-02T00:00:00Z", until="2026-07-04T23:59:59Z",
        include_superseded=True, limit=200,
    )}
    assert ids == {2, 3, 4}  # ts days 2,3,4 inclusive on both ends


def test_rows_sort_by_id_desc_default() -> None:
    fake = _rows_fixture()
    ids = [r["id"] for r in fake.rows(CFG, include_superseded=True, limit=200)]
    assert ids == [6, 5, 4, 3, 2, 1]


def test_rows_sort_by_id_asc() -> None:
    fake = _rows_fixture()
    ids = [r["id"] for r in fake.rows(CFG, sort_by="id", sort_dir="asc", include_superseded=True, limit=200)]
    assert ids == [1, 2, 3, 4, 5, 6]


def test_rows_sort_by_kind_ties_broken_by_id_same_direction() -> None:
    fake = _rows_fixture()
    # kind=note rows are 2 and 6; ascending kind-sort should show them adjacent, ordered by id
    # ASC within the tie (same direction as the primary sort, per the real query's
    # `ORDER BY kind ASC, id ASC`).
    ordered = fake.rows(CFG, sort_by="kind", sort_dir="asc", include_superseded=True, limit=200)
    note_ids = [r["id"] for r in ordered if r["kind"] == "note"]
    assert note_ids == [2, 6]
    ordered_desc = fake.rows(CFG, sort_by="kind", sort_dir="desc", include_superseded=True, limit=200)
    note_ids_desc = [r["id"] for r in ordered_desc if r["kind"] == "note"]
    assert note_ids_desc == [6, 2]  # tie-break direction flips WITH the primary direction


def test_rows_sort_by_actor_nulls_last_ascending_first_descending() -> None:
    fake = _rows_fixture()
    # Row 5 has actor_name=None (mirrors a real LEFT JOIN NULL) -- Postgres's default NULLS
    # ordering puts it LAST on ASC, FIRST on DESC.
    asc = fake.rows(CFG, sort_by="actor", sort_dir="asc", include_superseded=True, limit=200)
    assert asc[-1]["id"] == 5
    desc = fake.rows(CFG, sort_by="actor", sort_dir="desc", include_superseded=True, limit=200)
    assert desc[0]["id"] == 5


def test_rows_limit_and_offset_paginate() -> None:
    fake = _rows_fixture()
    page1 = fake.rows(CFG, sort_by="id", sort_dir="asc", include_superseded=True, limit=2, offset=0)
    page2 = fake.rows(CFG, sort_by="id", sort_dir="asc", include_superseded=True, limit=2, offset=2)
    assert [r["id"] for r in page1] == [1, 2]
    assert [r["id"] for r in page2] == [3, 4]


def test_rows_result_ts_is_isoformat_string_not_datetime() -> None:
    fake = _rows_fixture()
    row = fake.rows(CFG, kind="decision", sort_by="id", sort_dir="asc", limit=1)[0]
    assert row["ts"] == _ts(1).isoformat()


def test_count_rows_matches_the_same_filter_rows_would_apply() -> None:
    fake = _rows_fixture()
    n = fake.count_rows(CFG, kind="decision")
    ids = {r["id"] for r in fake.rows(CFG, kind="decision", limit=200)}
    assert n == len(ids) == 2


def test_facet_counts_is_current_rows_only_by_kind() -> None:
    fake = _rows_fixture()
    assert fake.facet_counts(CFG) == {"decision": 2, "note": 2, "question": 1}


def test_row_by_id_found_including_a_superseded_row() -> None:
    fake = _rows_fixture()
    row3 = fake.row_by_id(CFG, 3)
    assert row3 is not None and row3["id"] == 3  # "any status, current or superseded"


def test_row_by_id_missing_is_none() -> None:
    fake = _rows_fixture()
    assert fake.row_by_id(CFG, 999) is None


def test_watermark_empty() -> None:
    fake = FakeCoreLedgerReader()
    assert fake.watermark(CFG) == {"max_id": None, "max_ts": None, "count": 0}


def test_watermark_non_empty() -> None:
    fake = _rows_fixture()
    wm = fake.watermark(CFG)
    assert wm["max_id"] == 6
    assert wm["count"] == 6
    assert wm["max_ts"] == _ts(6).isoformat()


# ---- generic_row_refs: pure parser, same grammar as core/ledger_read.py's own ------------------

def test_generic_row_refs_extracts_bare_row_tokens() -> None:
    fake = FakeCoreLedgerReader()
    assert fake.generic_row_refs("see row:5 and row:12") == [5, 12]


def test_generic_row_refs_ignores_other_token_shapes_and_never_raises() -> None:
    fake = FakeCoreLedgerReader()
    assert fake.generic_row_refs("work:my-slug panel-item:680:A1 row:abc row: free prose") == []


def test_generic_row_refs_empty_or_none() -> None:
    fake = FakeCoreLedgerReader()
    assert fake.generic_row_refs(None) == []
    assert fake.generic_row_refs("") == []


# ---- backend_surface / is_exposed_by_backend / relation_count ---------------------------------

def _surface_fixture() -> FakeCoreLedgerReader:
    return FakeCoreLedgerReader(
        relations=[
            {"schema": "experience", "name": "ledger", "kind": "table", "count": 6, "count_estimated": False, "exposed_by_api": True},
            {"schema": "experience", "name": "widget_orphan", "kind": "table", "count": 0, "count_estimated": False, "exposed_by_api": False},
        ],
        exposed_relation_names=frozenset({"ledger"}),
        relation_row_counts={("experience", "ledger"): 6, ("experience", "small_table"): 3},
    )


def test_backend_surface_returns_configured_relations_as_copies() -> None:
    fake = _surface_fixture()
    surface = fake.backend_surface(CFG)
    assert [r["name"] for r in surface] == ["ledger", "widget_orphan"]
    surface[0]["name"] = "mutated"
    assert fake.relations[0]["name"] == "ledger"  # caller mutation must not corrupt fixture state


def test_is_exposed_by_backend_true_and_false() -> None:
    fake = _surface_fixture()
    assert fake.is_exposed_by_backend(CFG, "ledger") is True
    assert fake.is_exposed_by_backend(CFG, "widget_orphan") is False


def test_relation_count_exact_branch_uses_configured_count() -> None:
    fake = _surface_fixture()
    count, estimated = fake.relation_count(CFG, "experience", "small_table", "r", 3.0)
    assert (count, estimated) == (3, False)


def test_relation_count_view_always_exact_even_with_huge_reltuples() -> None:
    # Views keep no `reltuples` statistic -- relkind == 'v' always takes the exact branch,
    # regardless of the (nonsensical for a view, but the real function still checks relkind
    # first) reltuples value passed in.
    fake = _surface_fixture()
    fake.relation_row_counts[("experience", "a_view")] = 2
    count, estimated = fake.relation_count(CFG, "experience", "a_view", "v", 999_999.0)
    assert (count, estimated) == (2, False)


def test_relation_count_estimate_branch_above_threshold_skips_exact_count() -> None:
    fake = _surface_fixture()
    # No entry in relation_row_counts for this relation at all -- proves the estimate branch
    # never even consults it.
    count, estimated = fake.relation_count(CFG, "experience", "huge_table", "r", 1_000_000.0)
    assert (count, estimated) == (1_000_000, True)


def test_relation_count_below_threshold_estimate_still_uses_exact_count() -> None:
    fake = _surface_fixture()
    count, estimated = fake.relation_count(CFG, "experience", "small_table", "r", 5.0)
    assert (count, estimated) == (3, False)  # below threshold -> exact branch, not the estimate
