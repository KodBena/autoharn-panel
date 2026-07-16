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
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from config import PanelConfig


@contextmanager
def connect(cfg: PanelConfig) -> Iterator[psycopg.Connection]:
    """One connection, autocommit (every read in this backend is a plain SELECT; the only write
    path is `extensions/autoharn/cosign.py`'s subprocess call to `LED_BIN`, which never uses this
    connection at all)."""
    conn = psycopg.connect(cfg.connection.conninfo(), row_factory=dict_row, autocommit=True)
    try:
        with conn.cursor() as cur:
            if cfg.role:
                cur.execute(f'SET ROLE "{cfg.role}"')
            cur.execute(f'SET search_path = "{cfg.schema}", "{cfg.kern_schema}"')
        yield conn
    finally:
        conn.close()


@contextmanager
def connect_unrestricted(cfg: PanelConfig) -> Iterator[psycopg.Connection]:
    """Same as `connect()` but deliberately never issues `SET ROLE` -- for the rare, deliberate
    case where a read needs to see past a REVOKE placed on the ordinary subject role on purpose.
    The one relation this deployment REVOKEs from `cfg.role` on purpose is
    `<kern_schema>.stamp_secret` (a cryptographic secret): `extensions/autoharn/ledger_read.py`'s
    `autoharn_health` armed-check and `core/backend_surface.py`'s relation-count introspection
    (spa-backend-surface-view, commission row:741) are this function's two callers, consolidated
    here rather than each carrying its own private `psycopg.connect` call -- this module's own
    header already claims to be "the ONE place this backend opens a Postgres connection"; before
    this function existed that claim was already quietly false (extensions/autoharn/
    ledger_read.py had its own module-local `_connect_unrestricted`), and a second caller needing
    the identical pattern is the point at which that gets consolidated rather than tripled.

    Still sets search_path (so unqualified relation names resolve the same way `connect()`'s
    callers expect); only the ROLE elevation/restriction step is skipped. This is a STRICTLY MORE
    privileged conduit than `connect()` -- every caller must keep reading metadata/counts only,
    never a row's own column values, regardless of which relation it reaches."""
    conn = psycopg.connect(cfg.connection.conninfo(), row_factory=dict_row, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f'SET search_path = "{cfg.schema}", "{cfg.kern_schema}"')
        yield conn
    finally:
        conn.close()


def jsonable(row: dict) -> dict:
    """Normalize the one type psycopg's dict_row hands back that a plain-dict FastAPI response
    does not already know how to serialize (datetime -> isoformat) -- the same helper the PoC's
    ledger_read.py carried, kept as a shared core utility so core and every extension use one
    implementation."""
    out: dict = {}
    for k, v in row.items():
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return out
