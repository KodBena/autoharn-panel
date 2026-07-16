"""tests/test_db_pool.py -- regression/mechanics proof for db-connection-pool (ledger row:932),
the CRITICAL fix for row:894's finding: `backend/db.py`'s `connect()`/`connect_unrestricted()`
used to open a brand-new synchronous `psycopg.connect()` on every call, no pooling anywhere.

This tests `backend/db.py` DIRECTLY (its own entry points, not through the FastAPI app or any
route) -- per the reviewer's own antecedent-fact audit (ledger row:956): "a concurrent-call test
demonstrating N calls through db.py's entry point do NOT open N new physical connections."
Deliberately does NOT depend on a sibling `autoharn` checkout's kernel lineage (unlike
tests/test_cosign_live.py, tests/test_item_view_live.py, tests/test_commission_decomposition.py)
-- db.py's pooling behavior is generic across schema/role, so a minimal hand-rolled scratch
schema+role (same spirit as tests/test_core_boundary.py's scratch/core-bare-schema.sql, but this
file also needs a distinct, grantable ROLE, which that DDL deliberately omits) is enough.

Two-tier live-DB proof, same skipif convention as every other live test in this tree (SKIPPED,
not failed, without a reachable Postgres host):

1. `test_pool_bounds_concurrent_connection_count` -- the acceptance-criteria (row:988) MUST test:
   N (> the pool's own configured max_size) concurrent calls through `db.connect()` are proven to
   NOT open N new physical connections, two independent ways: (a) the set of DISTINCT
   `pg_backend_pid()` values observed across all N calls is bounded well below N -- the
   deterministic, race-free proof; (b) a live `pg_stat_activity` snapshot taken mid-burst (tagged
   by the pool's own distinguishing `application_name`, so it can't be confused with unrelated
   sessions on a shared dev Postgres) shows MORE than one simultaneously-live connection --
   ruling out the degenerate alternative explanation that the small distinct-pid count is an
   artifact of accidental full serialization rather than genuine bounded concurrency.
2. `test_connect_unrestricted_never_leaks_connect_role` -- the other MUST the task brief calls
   out by name: since a pooled connection is reused across logically distinct callers, a
   `connect()` caller's `SET ROLE` must never leak into a later `connect_unrestricted()` caller
   that happens to pull the SAME physical connection back out of the pool. Uses its OWN
   dedicated pool, monkeypatched to `min_size=max_size=1` (a real, empirically-checked finding
   during this test's development: `psycopg_pool` round-robins through ALL idle connections
   under sequential single-threaded checkout rather than reusing the most-recently-returned one
   -- confirmed by direct probe -- so sharing `scratch["cfg"]`'s pool, already populated with
   ~40 idle connections by the concurrency test above, made physical reuse take dozens of
   iterations to occur by chance instead of every single time; a size-1 pool makes reuse
   unconditional and deterministic instead of a statistical accident of run order). Asserts the
   role invariant on every pair AND that physical reuse (matching `pg_backend_pid()`) actually
   happened -- so this is a proof under REAL reuse, not merely "never happened to collide."
3. `test_connect_signature_and_role_none_skip_branch` -- signature/behavior preservation: still a
   contextmanager yielding a `psycopg.Connection`, still `dict_row` rows, still `autocommit=True`,
   and `cfg.role=None` still skips the `SET ROLE` statement entirely under pooling (the same
   branch tests/test_core_boundary.py's bare-schema fixture exercises through the app, exercised
   here directly against db.py).

Every existing skipif-gated live-Postgres test (test_core_boundary.py, test_cosign_live.py,
test_item_view_live.py, test_commission_decomposition.py) transitively exercises db.py's
connect()/connect_unrestricted() already, through core/extensions ledger_read.py -- their
continuing to pass unmodified is this change's regression proof; nothing in this new file
touches any of them.
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import db  # noqa: E402
from config import ConnectionFacts, PanelConfig  # noqa: E402

PGHOST = os.environ.get("EPISTEMIC_PGHOST") or os.environ.get("PGHOST")
PGDB = os.environ.get("PANEL_TEST_PGDATABASE", "toy")
SCHEMA, KERN, ROLE = "pdbpool", "pdbpool_kernel", "pdbpool_rw"
APP_NAME = "autoharn-panel-pool"  # must match db.py's own kwargs["application_name"]

pytestmark = pytest.mark.skipif(
    not PGHOST,
    reason="db-connection-pool test needs a reachable Postgres host (EPISTEMIC_PGHOST/PGHOST) -- SKIPPED, not failed.",
)


def sh(args: list[str], **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, **kw)


def psql(sql: str) -> subprocess.CompletedProcess[str]:
    return sh(["psql", "-h", PGHOST, "-d", PGDB, "-v", "ON_ERROR_STOP=1", "-tA", "-q", "-c", sql])


def teardown_scratch() -> None:
    psql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE; DROP SCHEMA IF EXISTS {KERN} CASCADE;")
    psql(f"DROP ROLE IF EXISTS {ROLE};")


@pytest.fixture(scope="module")
def scratch():
    """Fresh scratch schema/kernel-schema + a NOLOGIN role granted to the connecting user (so
    `SET ROLE` succeeds the same way it does against this deployment's real `experience_rw`).
    Also closes every pool this module's own cfgs created, at teardown, so these connections
    don't linger open (still pointed at a since-dropped schema/role) for the rest of a pytest
    session -- db.py's module-level cache has no other lifecycle hook, by design (row:924's
    accepted tradeoff), so a test module that wants tidy teardown calls `db.close_all_pools()`
    itself."""
    teardown_scratch()
    psql(f"CREATE ROLE {ROLE} NOLOGIN;")
    r = psql(f"GRANT {ROLE} TO CURRENT_USER;")
    assert r.returncode == 0, f"GRANT {ROLE} TO CURRENT_USER failed: {r.stderr}"
    psql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA};")
    psql(f"CREATE SCHEMA IF NOT EXISTS {KERN};")

    base_user = psql("SELECT current_user;").stdout.strip()
    assert base_user, "could not resolve the ambient connecting Postgres user"

    connection = ConnectionFacts(pg_uri=None, pg_host=PGHOST, pg_port=None, pg_db=PGDB,
                                  pg_user=None, pg_password=None, source="test-scratch-pool")
    cfg = PanelConfig(
        repo_root=REPO, connection=connection, schema=SCHEMA, kern_schema=KERN, role=ROLE,
        led_bin=None, read_only_locked=True, bind_host="127.0.0.1", bind_port=8423,
        poll_interval=2.0, extensions=("autoharn",), config_source="test-scratch-pool",
        maintainer_principal="maintainer", active_profile=None, available_profiles=(),
    )
    cfg_no_role = PanelConfig(
        repo_root=REPO, connection=connection, schema=SCHEMA, kern_schema=KERN, role=None,
        led_bin=None, read_only_locked=True, bind_host="127.0.0.1", bind_port=8424,
        poll_interval=2.0, extensions=("autoharn",), config_source="test-scratch-pool-norole",
        maintainer_principal="maintainer", active_profile=None, available_profiles=(),
    )
    yield {"cfg": cfg, "cfg_no_role": cfg_no_role, "base_user": base_user}
    db.close_all_pools()
    teardown_scratch()


def test_pool_bounds_concurrent_connection_count(scratch) -> None:
    cfg = scratch["cfg"]
    pool = db._pool_for(cfg)
    max_size = pool.get_stats()["pool_max"]
    assert max_size == db._POOL_MAX_SIZE  # sanity: this cfg really did get db.py's real sizing
    n = max_size + 10  # deliberately MORE concurrent calls than the pool can physically satisfy

    pids: list[int] = []
    pids_lock = threading.Lock()

    def worker() -> None:
        with db.connect(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_backend_pid() AS pid, pg_sleep(0.5)")
                pid = cur.fetchone()["pid"]
        with pids_lock:
            pids.append(pid)

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(worker) for _ in range(n)]
        # mid-burst, independently cross-check via a live pg_stat_activity snapshot -- a
        # SEPARATE, unpooled psql connection, tagged only by the pool's own application_name so
        # unrelated sessions on this shared dev Postgres can't pollute the count.
        time.sleep(0.2)
        r = psql(f"SELECT count(*) FROM pg_stat_activity WHERE application_name = '{APP_NAME}';")
        assert r.returncode == 0, f"pg_stat_activity snapshot query failed: {r.stderr}"
        live_during_burst = int(r.stdout.strip())
        for f in futures:
            f.result(timeout=30)

    assert len(pids) == n, "not every worker completed"
    distinct_pids = set(pids)
    assert len(distinct_pids) <= max_size, (
        f"{len(distinct_pids)} distinct physical connections were used for {n} concurrent "
        f"calls, exceeding the pool's own configured max_size={max_size} -- pooling is not "
        f"actually bounding physical connection count."
    )
    assert len(distinct_pids) < n, (
        f"{len(distinct_pids)} distinct physical connections for {n} concurrent calls -- "
        f"expected meaningfully fewer than {n} (the whole point of pooling)."
    )
    assert live_during_burst > 1, (
        f"pg_stat_activity showed only {live_during_burst} live autoharn-panel-pool connection(s) "
        f"mid-burst -- the bounded distinct-pid count above could otherwise be explained by "
        f"accidental full serialization (one connection reused one-at-a-time) rather than "
        f"genuine bounded CONCURRENCY, which is what pooling is actually supposed to buy."
    )


def test_connect_unrestricted_never_leaks_connect_role(scratch, monkeypatch) -> None:
    # A DEDICATED pool (a fresh cache key, via a distinct config_source), forced to exactly one
    # physical connection -- see the module docstring's tier-2 note for why sharing
    # scratch["cfg"]'s pool (left with ~40 idle connections by the concurrency test above) made
    # physical reuse a statistical accident rather than a guarantee. min_size/max_size are only
    # read at pool-CONSTRUCTION time, so the monkeypatch must land before this cfg's first use.
    monkeypatch.setattr(db, "_POOL_MIN_SIZE", 1)
    monkeypatch.setattr(db, "_POOL_MAX_SIZE", 1)
    cfg = dataclasses.replace(scratch["cfg"], config_source="test-scratch-pool-solo")
    base_user = scratch["base_user"]
    saw_physical_reuse = False

    for _ in range(5):
        with db.connect(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_user AS u, pg_backend_pid() AS pid")
                row = cur.fetchone()
                restricted_user, restricted_pid = row["u"], row["pid"]
        assert restricted_user == ROLE, (
            f"connect() should observe current_user={ROLE!r} (SET ROLE reissued on checkout), "
            f"got {restricted_user!r}"
        )

        with db.connect_unrestricted(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_user AS u, pg_backend_pid() AS pid")
                row = cur.fetchone()
                unrestricted_user, unrestricted_pid = row["u"], row["pid"]
        assert unrestricted_user != ROLE, (
            f"connect_unrestricted() observed current_user={ROLE!r} -- a prior connect() "
            f"caller's SET ROLE leaked into this checkout of a shared pooled connection "
            f"(pid match: {restricted_pid == unrestricted_pid}). This is exactly the silent "
            f"correctness bug the pooling change must not introduce."
        )
        assert unrestricted_user == base_user, (
            f"connect_unrestricted() should observe the base connecting user {base_user!r}, "
            f"got {unrestricted_user!r}"
        )

        if restricted_pid == unrestricted_pid:
            saw_physical_reuse = True

    assert saw_physical_reuse, (
        "never observed the SAME physical connection (pg_backend_pid) handed to both connect() "
        "and connect_unrestricted() across 5 sequential pairs -- the role-leak assertions above "
        "would then only prove 'never happened to collide', not 'proven safe under actual "
        "physical connection reuse'."
    )


def test_connect_signature_and_role_none_skip_branch(scratch) -> None:
    cfg_no_role = scratch["cfg_no_role"]

    with db.connect(cfg_no_role) as conn:
        assert isinstance(conn, psycopg.Connection)
        assert conn.autocommit is True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS one")
            row = cur.fetchone()
            assert row == {"one": 1}  # dict_row factory preserved

            # cfg.role is None -> connect() must skip SET ROLE entirely, exactly as it did
            # pre-pooling; current_user must be whatever this session ambiently authenticated as,
            # never ROLE (nothing here ever asked for it).
            cur.execute("SELECT current_user AS u")
            assert cur.fetchone()["u"] != ROLE
