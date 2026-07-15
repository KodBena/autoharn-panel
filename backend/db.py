"""backend.db -- the ONE place this backend opens a Postgres connection (core AND extensions
alike import this, never `psycopg.connect` a second time elsewhere -- mirrors the single-home
discipline the autoharn PoC's own `ledger_read.py` documented for itself).

Schema-generic by design (SPEC.md sec 4's extension boundary): `connect()` only ever issues
`SET search_path` (to `<schema>, <kern_schema>`), and issues `SET ROLE` ONLY if `cfg.role` is
set -- a bare/self-owned scratch schema with no distinct subject role configures `LEDGER_ROLE`
unset and this module skips that statement rather than failing on a role that does not exist.
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


def jsonable(row: dict) -> dict:
    """Normalize the one type psycopg's dict_row hands back that a plain-dict FastAPI response
    does not already know how to serialize (datetime -> isoformat) -- the same helper the PoC's
    ledger_read.py carried, kept as a shared core utility so core and every extension use one
    implementation."""
    out: dict = {}
    for k, v in row.items():
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return out
