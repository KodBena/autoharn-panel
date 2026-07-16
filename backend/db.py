"""backend.db -- the ONE place this backend opens a Postgres connection (core AND extensions
alike import this, never `psycopg.connect` a second time elsewhere -- mirrors the single-home
discipline the autoharn PoC's own `ledger_read.py` documented for itself).

Schema-generic by design (SPEC.md sec 4's extension boundary): `connect()` only ever issues
`SET search_path` (to `<schema>, <kern_schema>`), and issues `SET ROLE` ONLY if `cfg.role` is
set -- a bare/self-owned scratch schema with no distinct subject role configures `LEDGER_ROLE`
unset and this module skips that statement rather than failing on a role that does not exist.

`connect_unrestricted()` below is the one deliberate exception to "always `SET ROLE`": a strictly
MORE privileged conduit than `connect()`, for the rare case where a caller needs to read past a
REVOKE placed on the ordinary subject role on purpose (today: `<kern_schema>.stamp_secret`'s
metadata/count, never its content) -- see that function's own docstring.

POOLING (row:894 CRITICAL finding, row:932): both functions below are backed by a
`psycopg_pool.ConnectionPool`, one per distinct `PanelConfig`, cached in the module-level
`_POOLS` dict below -- deliberately NOT on `app.state`/`AppState` (row:924's ledgered
assumption: keeps every one of this module's ~30+ call sites unchanged, and avoids a
file-conflict with sibling remediation items that also touch `app.py`'s lifespan wiring).
`PanelConfig` is a frozen, all-hashable dataclass, so two independently-constructed but
value-equal configs (e.g. a fresh `load_config()` per process vs. a test fixture's own
`PanelConfig(...)` literal) correctly land on the SAME cached pool.

Because a pooled connection is reused across logically distinct callers, `SET ROLE`/
`SET search_path` (and `connect_unrestricted()`'s `RESET ROLE`) are reissued on EVERY checkout
below, never only once at physical-connection creation time -- otherwise a connection a prior
`connect()` caller left elevated via `SET ROLE` could leak that elevation into a later
`connect_unrestricted()` caller (or vice versa) pulling the same physical connection back out of
the pool. Reissuing costs one more round-trip per checkout, not a fresh TCP+auth handshake, so
this keeps the pooling win intact.

Pool size: `_POOL_MIN_SIZE = 4` (psycopg_pool's own library default -- a small warm baseline for
a mostly-idle panel, well below max so an idle deployment doesn't reserve capacity it isn't
using). `_POOL_MAX_SIZE = 41`: the audit (row:894) confirmed, against installed anyio source,
that Starlette's `run_in_threadpool` (every route handler here is a plain `def`) is served by a
`CapacityLimiter` hard-capped at 40 concurrent OS threads process-wide -- no more than 40
request-handling threads can ever be inside a `db.py` call at once, and each holds at most ONE
connection at a time (calls within one handler are sequential, e.g. `commissions()`'s own
~1+3C connect cycles run one after another, never concurrently) -- so 40 exactly covers request
traffic. The `+1` covers `app.py`'s background `_poll_loop`, which reaches this module via
`asyncio.to_thread` -- a SEPARATE stdlib `ThreadPoolExecutor`, not gated by anyio's 40-slot
limiter, so it can hold a connection concurrently with all 40 request threads at full
saturation. Sizing the pool any larger would just reserve idle Postgres connection slots: any
additional concurrent DB-reaching caller is already queued waiting for an anyio thread slot
before it can ever reach this module, per the audit's own diagnosed queueing mechanism.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import PanelConfig

_POOL_MIN_SIZE = 4
_POOL_MAX_SIZE = 41  # 40 (anyio run_in_threadpool CapacityLimiter cap) + 1 (the background
                      # poll loop's separate asyncio.to_thread executor) -- see module docstring.

_POOLS: dict[PanelConfig, ConnectionPool] = {}
_POOLS_LOCK = threading.Lock()


def _pool_for(cfg: PanelConfig) -> ConnectionPool:
    """The module-level pool cache, keyed by the whole `PanelConfig` (see module docstring for
    why not `app.state`). Double-checked locking: the common case (pool already exists) never
    takes the lock; only the first caller for a given `cfg` pays the lock + pool-construction
    cost, and `open=True` makes construction itself fail loudly (ADR-0002) if the target
    Postgres is unreachable, the same way a bad `psycopg.connect()` call always has here."""
    pool = _POOLS.get(cfg)
    if pool is not None:
        return pool
    with _POOLS_LOCK:
        pool = _POOLS.get(cfg)
        if pool is None:
            pool = ConnectionPool(
                cfg.connection.conninfo(),
                kwargs={
                    "row_factory": dict_row,
                    "autocommit": True,
                    # distinguishes this pool's connections in pg_stat_activity -- both an
                    # operational diagnostic and what tests/test_db_pool.py's own concurrency
                    # assertion filters on, so ambient/unrelated sessions on a shared dev
                    # Postgres can't pollute the count.
                    "application_name": "autoharn-panel-pool",
                },
                min_size=_POOL_MIN_SIZE,
                max_size=_POOL_MAX_SIZE,
                open=True,
            )
            _POOLS[cfg] = pool
    return pool


def close_all_pools() -> None:
    """Close and evict every cached pool. Not called by production code (the process simply
    exits) -- this exists for test/fixture hygiene, so a scratch schema/role's pooled
    connections don't linger, open, for the rest of a pytest session after that schema/role is
    dropped. Safe to call at any time; a no-op if no pools exist."""
    with _POOLS_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        pool.close()


@contextmanager
def connect(cfg: PanelConfig) -> Iterator[psycopg.Connection]:
    """One pooled connection, autocommit (every read in this backend is a plain SELECT; the only
    write path is `extensions/autoharn/cosign.py`'s subprocess call to `LED_BIN`, which never
    uses this connection at all). `SET ROLE`/`SET search_path` are reissued on every checkout --
    see module docstring for why that matters once connections are reused."""
    with _pool_for(cfg).connection() as conn:
        with conn.cursor() as cur:
            if cfg.role:
                cur.execute(f'SET ROLE "{cfg.role}"')
            cur.execute(f'SET search_path = "{cfg.schema}", "{cfg.kern_schema}"')
        yield conn


@contextmanager
def connect_unrestricted(cfg: PanelConfig) -> Iterator[psycopg.Connection]:
    """Same as `connect()` but deliberately never issues `SET ROLE` -- for the rare, deliberate
    case where a read needs to see past a REVOKE placed on the ordinary subject role on purpose.
    The one relation this deployment REVOKEs from `cfg.role` on purpose is
    `<kern_schema>.stamp_secret` (a cryptographic secret): `extensions/autoharn/ledger_adapter.py`'s
    `PostgresAutoharnLedgerReader.autoharn_health` armed-check and `core/ledger_adapter.py`'s
    `PostgresCoreLedgerReader.backend_surface`/`relation_count` relation-count introspection
    (spa-backend-surface-view, commission row:741) are this function's two callers today --
    consolidated here rather than each carrying its own private `psycopg.connect` call, this
    module's own header already claims to be "the ONE place this backend opens a Postgres
    connection". (Corrected 2026-07-16, autoharn-adapter-acl-wrap row 934, per row:1041's flagged
    hazard: this paragraph previously named `extensions/autoharn/ledger_read.py` and
    `core/backend_surface.py`, both since deleted -- their SQL relocated verbatim into the two
    `*_adapter.py` classes named above.)

    Still sets search_path (so unqualified relation names resolve the same way `connect()`'s
    callers expect); only the ROLE elevation/restriction step is skipped. This is a STRICTLY MORE
    privileged conduit than `connect()` -- every caller must keep reading metadata/counts only,
    never a row's own column values, regardless of which relation it reaches.

    Shares `connect()`'s pool (same `cfg` -> same cache entry), so a physical connection this
    function hands out may previously have been `SET ROLE`-elevated by a `connect()` caller --
    `RESET ROLE` is reissued unconditionally on every checkout (always safe/idempotent, even
    when no role was ever set) to guarantee this conduit is never accidentally still-restricted
    by a prior caller's leftover role."""
    with _pool_for(cfg).connection() as conn:
        with conn.cursor() as cur:
            cur.execute("RESET ROLE")
            cur.execute(f'SET search_path = "{cfg.schema}", "{cfg.kern_schema}"')
        yield conn


def jsonable(row: dict) -> dict:
    """Normalize the one type psycopg's dict_row hands back that a plain-dict FastAPI response
    does not already know how to serialize (datetime -> isoformat) -- the same helper the PoC's
    ledger_read.py carried, kept as a shared core utility so core and every extension use one
    implementation."""
    out: dict = {}
    for k, v in row.items():
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return out
