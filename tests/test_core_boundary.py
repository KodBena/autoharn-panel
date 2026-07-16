"""tests/test_core_boundary.py -- the extension-boundary WITNESS SPEC.md sec 4 requires: with
the `autoharn` extension disabled, the core API must serve against a BARE ledger schema --
just the `ledger` table (+ a `principal` table for actor names), no kernel views
(`ledger_current`, `review_detail`, `work_item_current`, `review_gap`, `question_status`), no
`stamp_secret`, no `commission`/`work_item` kind vocabulary. If core needed any of that to
answer a request, that would be a boundary defect to fix, not to document -- this test is the
proof it does not.

The bare schema below is NOT autoharn's kernel lineage (kernel/lineage/s15-schema.sql etc,
which this standalone repo does not depend on or ship) -- it is the minimal, generic subset
`backend/core/ledger_adapter.py`'s `PostgresCoreLedgerReader` itself requires: a `ledger` table with
(id, ts, kind, statement, refs, supersedes, actor) and a `principal(id, name)` table, no CHECK
constraint narrowing `kind`, no distinct subject role (this test also exercises `db.connect`'s
role-skip branch: `cfg.role = None`).
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

# `app` (this repo's own backend.app) is deliberately NOT imported at module top-level: its
# module-level code resolves config (`create_app()`'s own `load_config()` call) at IMPORT time,
# so this file's fixture must set the controlling env vars (monkeypatch) BEFORE app's first
# import -- the one place in this whole repo where a deferred import is the correct tool
# (not a footprint-hiding shortcut: the alternative, importing at collection time, would
# resolve against whatever the ambient environment happens to be instead of this test's own
# controlled one).

PGHOST = os.environ.get("EPISTEMIC_PGHOST") or os.environ.get("PGHOST")
PGDB = os.environ.get("PANEL_TEST_PGDATABASE", "toy")
SCHEMA, KERN = "pcorebndry", "pcorebndry_kernel"

pytestmark = pytest.mark.skipif(
    not PGHOST,
    reason="core-boundary test needs a reachable Postgres host (EPISTEMIC_PGHOST/PGHOST) -- SKIPPED, not failed.",
)

_BARE_SCHEMA_SQL = REPO / "scratch" / "core-bare-schema.sql"


def sh(args: list[str], **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, **kw)


def psql(sql: str) -> subprocess.CompletedProcess[str]:
    return sh(["psql", "-h", PGHOST, "-d", PGDB, "-v", "ON_ERROR_STOP=1", "-tA", "-q", "-c", sql])


def teardown() -> None:
    psql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE; DROP SCHEMA IF EXISTS {KERN} CASCADE;")


@pytest.fixture(scope="module")
def bare_schema():
    """Applies `scratch/core-bare-schema.sql` -- the ONE home for this schema's DDL (also
    usable standalone by an operator, `psql ... -f scratch/core-bare-schema.sql`), never a
    second, independently-hand-copied DDL string living only in this test."""
    teardown()
    r = sh(["psql", "-h", PGHOST, "-d", PGDB, "-v", "ON_ERROR_STOP=1",
            "-v", f"schema={SCHEMA}", "-v", f"kern={KERN}", "-f", str(_BARE_SCHEMA_SQL)])
    assert r.returncode == 0, f"bare schema DDL failed: {r.stdout[-500:]} {r.stderr[-500:]}"
    r = psql(f"INSERT INTO {KERN}.principal (name) VALUES ('author') ON CONFLICT DO NOTHING;")
    assert r.returncode == 0
    yield
    teardown()


@pytest.fixture
def bare_app(bare_schema, monkeypatch):
    """Build the FastAPI app with `PANEL_EXTENSIONS=` (empty -- autoharn explicitly disabled)
    against the bare schema above, no LED_BIN (read-only)."""
    monkeypatch.setenv("LEDGER_PG_URI", f"host={PGHOST} dbname={PGDB}")
    monkeypatch.setenv("LEDGER_SCHEMA", SCHEMA)
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", KERN)
    monkeypatch.setenv("PANEL_EXTENSIONS", "")
    monkeypatch.delenv("LED_BIN", raising=False)
    monkeypatch.delenv("LEDGER_ROLE", raising=False)

    import app as app_module
    importlib.reload(app_module)  # re-read env with monkeypatched values
    return app_module.create_app()


def test_bare_schema_core_reads_work_with_no_rows(bare_app) -> None:
    with TestClient(bare_app) as client:
        health = client.get("/api/health").json()
        assert health["ok"] is True
        assert health["read_only"] is True
        assert health["extensions_enabled"] == []
        assert "autoharn" not in health

        rows = client.get("/api/rows").json()
        assert rows == []

        watermark = client.get("/api/watermark").json()
        assert watermark["count"] == 0

        # the autoharn-only route must not exist at all when the extension is disabled
        resp = client.get("/api/commissions")
        assert resp.status_code == 404

        # spa-backend-surface-view (commission row:741): GET /api/backend-surface is CORE, so it
        # must serve against this bare schema too -- just `ledger`(SCHEMA)+`principal`(KERN), no
        # kernel views, no stamp_secret. Every relation's name/kind/count is real metadata (not
        # hand-listed), and both known relations here are genuinely queried by core, so both must
        # report exposed_by_api True.
        surface = client.get("/api/backend-surface").json()
        by_key = {(r["schema"], r["name"]): r for r in surface}
        assert (SCHEMA, "ledger") in by_key
        assert (KERN, "principal") in by_key
        assert by_key[(SCHEMA, "ledger")]["kind"] == "table"
        assert by_key[(SCHEMA, "ledger")]["count"] == 0
        assert by_key[(SCHEMA, "ledger")]["exposed_by_api"] is True
        assert by_key[(KERN, "principal")]["exposed_by_api"] is True
        # nothing beyond these two relations exists in this bare schema
        assert {s for s, _ in by_key} <= {SCHEMA, KERN}


def test_bare_schema_core_reads_a_written_row(bare_app) -> None:
    author_id_r = psql(f"SELECT id FROM {KERN}.principal WHERE name='author';")
    author_id = int(author_id_r.stdout.strip())
    ins = psql(
        f"INSERT INTO {SCHEMA}.ledger (kind, statement, refs, actor) VALUES "
        f"('note', 'a bare-schema specimen row', 'row:1', {author_id}) RETURNING id;"
    )
    assert ins.returncode == 0
    row_id = int(ins.stdout.strip())

    with TestClient(bare_app) as client:
        rows = client.get("/api/rows").json()
        assert any(r["id"] == row_id and r["actor_name"] == "author" for r in rows)

        detail = client.get(f"/api/rows/{row_id}").json()
        assert detail["statement"] == "a bare-schema specimen row"
        assert detail["predecessors"] == []
        assert detail["successor"] is None

        facets = client.get("/api/rows/facet-counts").json()
        assert facets.get("note") == 1


def test_bare_schema_rows_actor_and_date_range_facets(bare_app) -> None:
    """The recent-ledger-navigability facets (SPEC.md sec 2.1): `actor` already worked before
    this item; `since`/`until` (date-range) and `sort_by`/`sort_dir` (column-sort) are what this
    item adds -- exercised here against the SAME bare, core-only schema the rest of this file
    proves the extension boundary against."""
    author_id_r = psql(f"SELECT id FROM {KERN}.principal WHERE name='author';")
    author_id = int(author_id_r.stdout.strip())
    psql(f"INSERT INTO {KERN}.principal (name) VALUES ('other') ON CONFLICT DO NOTHING;")
    other_id_r = psql(f"SELECT id FROM {KERN}.principal WHERE name='other';")
    other_id = int(other_id_r.stdout.strip())

    ins_old = psql(
        f"INSERT INTO {SCHEMA}.ledger (kind, statement, actor, ts) VALUES "
        f"('note', 'an old row', {author_id}, now() - interval '10 days') RETURNING id;"
    )
    old_id = int(ins_old.stdout.strip())
    ins_new = psql(
        f"INSERT INTO {SCHEMA}.ledger (kind, statement, actor, ts) VALUES "
        f"('note', 'a fresh row', {other_id}, now()) RETURNING id;"
    )
    new_id = int(ins_new.stdout.strip())
    # the cutoff between the two rows, computed server-side (never a hardcoded calendar date --
    # this test must stay correct regardless of when it runs) then read back as a plain ISO
    # string, the same shape a UI date-range input would send.
    cutoff = psql("SELECT (now() - interval '5 days')::text;").stdout.strip()

    with TestClient(bare_app) as client:
        # actor facet
        by_actor = client.get("/api/rows", params={"actor": "other"}).json()
        assert [r["id"] for r in by_actor] == [new_id]

        # date-range facet: `since` excludes the old row, `until` excludes the new one. `since`/
        # `until` are passed straight through to Postgres as parametrized values (an ISO date
        # string Postgres's own `timestamptz` input parser accepts), never interpolated SQL text.
        only_old = client.get("/api/rows", params={"until": cutoff}).json()
        assert all(r["id"] != new_id for r in only_old)
        assert any(r["id"] == old_id for r in only_old)

        only_new = client.get("/api/rows", params={"since": cutoff}).json()
        assert any(r["id"] == new_id for r in only_new)
        assert all(r["id"] != old_id for r in only_new)

        # sort-by-column facet: closed vocabulary, ascending id puts the oldest bare-schema row
        # first (row ids are monotonically increasing on insert order)
        asc = client.get("/api/rows", params={"sort_by": "id", "sort_dir": "asc"}).json()
        ids = [r["id"] for r in asc]
        assert ids == sorted(ids)

        bad_sort = client.get("/api/rows", params={"sort_by": "statement"})
        assert bad_sort.status_code == 400


def test_bare_schema_supersede_chain_real_multi_row_walk(bare_app) -> None:
    """core-coverage-tests (row:938, acceptance criteria row:1091, refs row:894): the ONLY
    existing supersede_chain coverage against the REAL `PostgresCoreLedgerReader` (as opposed to
    `tests/fakes/core_ledger_reader.py`'s own already-thorough multi-row fake tests) was
    `test_bare_schema_core_reads_a_written_row`'s single unsuperseded row -- predecessors=[],
    successor=None, the trivial case row:894's audit flagged as insufficient. This proves the
    REAL adapter's multi-hop walk (`core/ledger_adapter.py`'s `supersede_chain`, reached here via
    `GET /api/rows/{row_id}`, exactly as `core/routes.py`'s `api_row` calls it) against a genuine
    4-row chain in actual Postgres: root <- mid1 <- mid2 <- tip. Mirrors
    `tests/test_core_ledger_fake.py`'s own `_chain_fixture`/`test_supersede_chain_multi_row_*`
    tests structurally, over real inserted rows instead of hand-built dicts."""
    author_id_r = psql(f"SELECT id FROM {KERN}.principal WHERE name='author';")
    author_id = int(author_id_r.stdout.strip())

    def insert_row(statement: str, *, supersedes: int | None) -> int:
        supersedes_sql = str(supersedes) if supersedes is not None else "NULL"
        ins = psql(
            f"INSERT INTO {SCHEMA}.ledger (kind, statement, actor, supersedes) VALUES "
            f"('note', '{statement}', {author_id}, {supersedes_sql}) RETURNING id;"
        )
        assert ins.returncode == 0, ins.stderr
        return int(ins.stdout.strip())

    root_id = insert_row("chain root", supersedes=None)
    mid1_id = insert_row("chain mid1, supersedes root", supersedes=root_id)
    mid2_id = insert_row("chain mid2, supersedes mid1", supersedes=mid1_id)
    tip_id = insert_row("chain tip, supersedes mid2, current", supersedes=mid2_id)

    with TestClient(bare_app) as client:
        root = client.get(f"/api/rows/{root_id}").json()
        assert root["predecessors"] == []
        assert root["successor"] == mid1_id

        # nearest-hop-first order (mid1, then root) -- the real adapter's own loop appends each
        # hop's OWN `supersedes` target before following it, same walk order the fake replicates.
        mid1 = client.get(f"/api/rows/{mid1_id}").json()
        assert mid1["predecessors"] == [root_id]
        assert mid1["successor"] == mid2_id

        mid2 = client.get(f"/api/rows/{mid2_id}").json()
        assert mid2["predecessors"] == [mid1_id, root_id]
        assert mid2["successor"] == tip_id

        tip = client.get(f"/api/rows/{tip_id}").json()
        assert tip["predecessors"] == [mid2_id, mid1_id, root_id]
        assert tip["successor"] is None

        # the default Board view (superseded hidden) must show only the tip of this chain
        current_ids = {r["id"] for r in client.get("/api/rows").json()}
        assert tip_id in current_ids
        assert root_id not in current_ids and mid1_id not in current_ids and mid2_id not in current_ids
