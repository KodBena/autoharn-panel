"""tests/test_core_ledger_adapter.py -- direct coverage for `backend/core/ledger_adapter.py`'s
`PostgresCoreLedgerReader`, the REAL `CoreLedgerPort` implementation (work item
`core-coverage-tests`, ledger row 938; acceptance criteria row 1091, refs row 894).

`tests/test_core_ledger_fake.py` already proves `FakeCoreLedgerReader`'s behavior in depth --
including its own replica of the exact-vs-estimate threshold branch. That fake replica is a
SEPARATE implementation of the same logic (see that fake's own module docstring), so it can never
prove the REAL branch code in this module actually runs correctly. This file closes that gap for
the three methods row 894's audit named with zero prior coverage of any kind:
`backend_surface`/`is_exposed_by_backend`/`relation_count`.

Two tiers:

  1. Fast, no-database tests -- `is_exposed_by_backend()` against this repo's OWN real
     `backend/core/*.py` source (no mocking of the file-glob/regex/cache pipeline itself; `cfg`
     is built with `extensions=()` deliberately, so these tests never depend on
     `backend/extensions/autoharn/*.py`'s content while a sibling work item is actively rewriting
     it) plus one synthetic-text case (monkeypatched `_source_text`) proving the word-boundary
     guard specifically; `_count_relation()`'s three branches against a minimal stub cursor
     (never a live connection) -- fast enough to run in this tree's ordinary no-Postgres
     environment.
  2. Live-Postgres-gated (`skipif`, same convention as `tests/test_core_boundary.py` and
     `tests/test_db_pool.py`) -- `relation_count()` as the Protocol's own standalone, `cfg`-only
     entry point (`core/ports.py`'s SIGNATURE NOTE, ledger row 980) against a real relation,
     proving it round-trips through actual Postgres correctly on its OWN, distinct from
     `backend_surface()`'s internal single-cursor-reused-across-every-relation loop (already
     covered live, via HTTP, in `tests/test_core_boundary.py`).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import core.ledger_adapter as ledger_adapter  # noqa: E402
import db  # noqa: E402
from config import ConnectionFacts, PanelConfig  # noqa: E402
from core.ledger_adapter import PostgresCoreLedgerReader, _count_relation  # noqa: E402

PGHOST = os.environ.get("EPISTEMIC_PGHOST") or os.environ.get("PGHOST")
PGDB = os.environ.get("PANEL_TEST_PGDATABASE", "toy")
SCHEMA, KERN = "pcoreadapter", "pcoreadapter_kernel"


def _cfg(**overrides: Any) -> PanelConfig:
    connection = ConnectionFacts(pg_uri=None, pg_host=PGHOST or "unused", pg_port=None,
                                  pg_db=PGDB, pg_user=None, pg_password=None, source="test")
    fields: dict[str, Any] = dict(
        repo_root=REPO, connection=connection, schema=SCHEMA, kern_schema=KERN, role=None,
        led_bin=None, read_only_locked=False, bind_host="127.0.0.1", bind_port=8425,
        poll_interval=2.0, extensions=(), config_source="test",
        maintainer_principal="maintainer", active_profile=None, available_profiles=(),
    )
    fields.update(overrides)
    return PanelConfig(**fields)


# ---- is_exposed_by_backend(): real source-text regex over real files, no DB needed ------------

def test_is_exposed_by_backend_true_for_a_relation_this_backend_really_queries() -> None:
    # `core/ledger_adapter.py`'s own watermark()/rows()/etc all issue `FROM ledger l` -- a real
    # positive against this repo's actual, current, on-disk source (cfg.extensions=() so only
    # backend/core/*.py is scanned), not a synthetic fixture standing in for it.
    reader = PostgresCoreLedgerReader()
    assert reader.is_exposed_by_backend(_cfg(), "ledger") is True


def test_is_exposed_by_backend_false_for_a_relation_no_source_file_queries() -> None:
    reader = PostgresCoreLedgerReader()
    assert reader.is_exposed_by_backend(_cfg(), "definitely_not_a_real_relation_name_xyz") is False


def test_is_exposed_by_backend_word_boundary_excludes_a_longer_containing_name(monkeypatch) -> None:
    """`_exposure_pattern`'s own word-boundary guard (this module's docstring: "so e.g. bare
    `ledger` does not match inside `ledger_current`"). Synthetic source text, monkeypatched onto
    `_source_text` directly, so this proves the regex's own boundary behavior deterministically
    rather than depending on whether a real file happens to contain a suitable substring pair
    today."""
    monkeypatch.setattr(ledger_adapter, "_source_text", lambda cfg: 'cur.execute("SELECT * FROM ledger_current")')
    reader = PostgresCoreLedgerReader()
    # the FULL longer name is genuinely queried...
    assert reader.is_exposed_by_backend(_cfg(), "ledger_current") is True
    # ...but the shorter name it merely CONTAINS is not -- a loose (non-word-boundary) regex
    # would wrongly report this True.
    assert reader.is_exposed_by_backend(_cfg(), "ledger") is False


def test_is_exposed_by_backend_matches_schema_qualified_and_quoted_forms(monkeypatch) -> None:
    """Mirrors the module docstring's own named case: an f-string-interpolated schema
    qualification like `"{cfg.kern_schema}".stamp_secret` (`autoharn_health`'s own armed-check
    style) must still match, quoted or not."""
    monkeypatch.setattr(
        ledger_adapter, "_source_text", lambda cfg: 'cur.execute(f\'SELECT count(*) FROM "{cfg.kern_schema}".stamp_secret\')'
    )
    reader = PostgresCoreLedgerReader()
    assert reader.is_exposed_by_backend(_cfg(), "stamp_secret") is True


# ---- _count_relation(): the exact-vs-estimate threshold branch, via a stub cursor -------------

class _StubCursor:
    """A minimal stand-in for `psycopg.cursor.Cursor` -- only the two methods `_count_relation`
    itself calls. `raise_on_execute=True` makes the ESTIMATE branch's own claim ("skips the exact
    `count(*)` entirely") a proven fact rather than an inference from the returned value alone: if
    that branch ever regressed into issuing a query anyway, this stub would raise instead of
    silently succeeding."""

    def __init__(self, fetchone_result: dict[str, Any] | None = None, *, raise_on_execute: bool = False) -> None:
        self._fetchone_result = fetchone_result
        self._raise_on_execute = raise_on_execute
        self.executed = False

    def execute(self, *args: Any, **kwargs: Any) -> None:
        if self._raise_on_execute:
            raise AssertionError("execute() must not be called on this branch")
        self.executed = True

    def fetchone(self) -> dict[str, Any] | None:
        return self._fetchone_result


def test_exact_count_above_estimate_constant_is_50_000() -> None:
    # Locks in the real constant's name and value this work item's task brief named explicitly --
    # a silent future change here would silently change every branch test below's own meaning.
    assert ledger_adapter._EXACT_COUNT_ABOVE_ESTIMATE == 50_000


def test_count_relation_estimate_branch_short_circuits_without_querying() -> None:
    cur = _StubCursor(raise_on_execute=True)
    count, estimated = _count_relation(cur, "schema", "big_table", "r", 100_000.0)
    assert (count, estimated) == (100_000, True)
    assert cur.executed is False


def test_count_relation_view_always_exact_even_above_threshold() -> None:
    # Views keep no `reltuples` statistic -- relkind == 'v' takes the exact branch regardless of
    # the (nonsensical for a view, but the real function checks relkind first) reltuples value.
    cur = _StubCursor(fetchone_result={"n": 7})
    count, estimated = _count_relation(cur, "schema", "a_view", "v", 999_999.0)
    assert (count, estimated) == (7, False)
    assert cur.executed is True


def test_count_relation_below_threshold_uses_exact_count() -> None:
    cur = _StubCursor(fetchone_result={"n": 3})
    count, estimated = _count_relation(cur, "schema", "small_table", "r", 5.0)
    assert (count, estimated) == (3, False)
    assert cur.executed is True


def test_count_relation_reltuples_none_uses_exact_count() -> None:
    # A brand-new/never-analyzed relation reports reltuples=NULL from pg_class -- must not be
    # mistaken for "huge, skip the real count".
    cur = _StubCursor(fetchone_result={"n": 0})
    count, estimated = _count_relation(cur, "schema", "brand_new_table", "r", None)
    assert (count, estimated) == (0, False)
    assert cur.executed is True


def test_count_relation_negative_reltuples_uses_exact_count() -> None:
    # Postgres reports reltuples=-1 for a relation that has never been ANALYZEd -- the real
    # function's own `reltuples >= 0` guard must route this to the exact branch too, not treat
    # -1 as "huge".
    cur = _StubCursor(fetchone_result={"n": 2})
    count, estimated = _count_relation(cur, "schema", "never_analyzed", "r", -1.0)
    assert (count, estimated) == (2, False)
    assert cur.executed is True


# ---- relation_count(): the Protocol's own standalone entry point, live against real Postgres --

_LIVE_SKIP = pytest.mark.skipif(
    not PGHOST,
    reason="core-ledger-adapter relation_count live test needs a reachable Postgres host "
           "(EPISTEMIC_PGHOST/PGHOST) -- SKIPPED, not failed.",
)


def sh(args: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, **kw)


def psql(sql: str) -> subprocess.CompletedProcess[str]:
    return sh(["psql", "-h", PGHOST, "-d", PGDB, "-v", "ON_ERROR_STOP=1", "-tA", "-q", "-c", sql])


def _teardown_live_schema() -> None:
    psql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE; DROP SCHEMA IF EXISTS {KERN} CASCADE;")


@pytest.fixture(scope="module")
def live_schema():
    """The SAME `scratch/core-bare-schema.sql` DDL `tests/test_core_boundary.py` uses (one home
    for this DDL, per that file's own docstring) -- a fresh, uniquely-named schema pair so this
    file's live test cannot collide with any other test file's own schema on this shared dev
    Postgres host."""
    _teardown_live_schema()
    r = sh(["psql", "-h", PGHOST, "-d", PGDB, "-v", "ON_ERROR_STOP=1",
            "-v", f"schema={SCHEMA}", "-v", f"kern={KERN}", "-f",
            str(REPO / "scratch" / "core-bare-schema.sql")])
    assert r.returncode == 0, f"bare schema DDL failed: {r.stdout[-500:]} {r.stderr[-500:]}"
    yield
    db.close_all_pools()  # tidy teardown (tests/test_db_pool.py's own convention) -- don't leave
    # a pooled connection open against a schema this fixture is about to drop.
    _teardown_live_schema()


@_LIVE_SKIP
def test_relation_count_standalone_entry_point_against_real_postgres(live_schema) -> None:
    """`relation_count()` is the Protocol's own standalone, `cfg`-only entry point (`core/ports.py`'s
    SIGNATURE NOTE, ledger row 980) -- distinct from `backend_surface()`'s internal loop, which
    opens exactly ONE connection/cursor and reuses it across every relation (see this module's own
    CONNECTION-REUSE NOTE). Calling `relation_count()` directly here proves it opens its own
    connection and returns a real exact count against genuine Postgres on its own, not merely as a
    code path only ever reachable through `backend_surface()`'s loop (that loop already gets live,
    HTTP-level coverage in `tests/test_core_boundary.py`)."""
    for i in range(3):
        r = psql(f"INSERT INTO {SCHEMA}.ledger (kind, statement) VALUES ('note', 'row {i}');")
        assert r.returncode == 0, r.stderr

    reader = PostgresCoreLedgerReader()
    count, estimated = reader.relation_count(_cfg(), SCHEMA, "ledger", "r", None)
    assert (count, estimated) == (3, False)
