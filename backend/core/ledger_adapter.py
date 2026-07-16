"""backend.core.ledger_adapter -- `PostgresCoreLedgerReader`, the ONE concrete implementation of
`core.ports.CoreLedgerPort` (work item `core-ledger-adapter`, ledger row 933; Protocol landed at
row 931/619b95d). Every method's SQL body is relocated VERBATIM (ADR-0004 minimal-touch; this file
is the "downstream item" `core/ports.py`'s own docstring named as expected to do exactly this) from
what were, until this item, two separate module-level-function files: `core/ledger_read.py` (the
7 ledger-generic reads: `watermark`, `rows`, `count_rows`, `facet_counts`, `row_by_id`,
`supersede_chain`, `generic_row_refs`) and `core/backend_surface.py` (the 3 DB-surface-introspection
reads: `backend_surface`, `is_exposed_by_backend`, `relation_count`). Both source files are GONE as
of this item -- nothing else in this repo imported their module-level functions directly (grep-
confirmed against the whole `backend/`/`tests/` tree before deleting them: only `core/routes.py`
and `app.py` did, and both are repointed at this class in the same commit), so this is a genuine
relocation, not a duplication left for a later item to collapse (unlike the AutoharnLedgerPort side,
`extensions/autoharn/ledger_read.py`, which stays a separate, much larger god-module for a later
`autoharn-god-module-split` item to carve up).

Stateless by design, exactly as `core/ports.py`'s own docstring specifies ("a conforming adapter/
fake needs no other shared state"): every method takes `cfg: PanelConfig` as its own connection/
config handle, so one `PostgresCoreLedgerReader()` (no constructor arguments) is constructed once,
at app startup, and shared across every request (see `app.py`'s `AppState.reader`).

CORE-GENERIC (SPEC.md sec 4): this module still knows nothing about `commission`/`work_item` kinds,
the `panel-item:` refs grammar, or any kernel extension view -- the same boundary
`core/ledger_read.py`/`core/backend_surface.py` held before their logic moved here.

SAFETY (non-negotiable, inherited from `core/backend_surface.py`'s own former module docstring --
the ONE property this module must never regress): every query touching `backend_surface`/
`relation_count`'s surface is either `pg_catalog` metadata or a bare `count(*)` against a relation
identified via `psycopg.sql.Identifier` (never string-interpolated). There is no `SELECT *`, no
projection of a single column, no row content of any kind, read or returned, anywhere in this file,
for any relation, regardless of schema.

CONNECTION-REUSE NOTE (flagged by an independent reviewer while this item was in flight, row 1006):
`CoreLedgerPort.relation_count`'s signature takes `cfg: PanelConfig`, not a shared cursor (row 980's
already-disclosed, deliberate choice -- a live `psycopg.Cursor` cannot appear in `core/ports.py`
under its own import-boundary rule). Naively implementing `relation_count` as "open a fresh
connection every call" and then having `backend_surface()` call `self.relation_count(...)` in a loop
would silently regress the real former behavior -- `core/backend_surface.py`'s own `backend_surface()`
opened exactly ONE connection/cursor and reused it across every relation it counted, which matters
doubly now that `db-connection-pool` (a sibling in-flight item) is working to cut connection churn.
Preserved here via `_count_relation(cur, ...)`, a private module-level helper both public methods
route through: `relation_count()` (the Protocol's own standalone, cfg-only entry point) opens one
connection for its single relation; `backend_surface()` opens exactly one connection/cursor and
calls the SAME helper once per relation over that one open cursor, unchanged from the original.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from psycopg import sql
from psycopg.cursor import Cursor

from config import PanelConfig
from core.ports import SupersedeChain
from db import connect, connect_unrestricted, jsonable

# ---------------------------------------------------------------------------------------------
# Moved verbatim from core/ledger_read.py
# ---------------------------------------------------------------------------------------------

_CURRENT_FILTER = "NOT EXISTS (SELECT 1 FROM ledger s WHERE s.supersedes = l.id)"

# The sort-by-column facet (SPEC.md sec 2.1's "Board (browsing view)") is a closed vocabulary,
# never a raw column name interpolated from the request -- an open `sort_by` string would be a
# SQL-injection surface (params can't parametrize an identifier). Every value here maps to a
# fixed, literal ORDER BY clause.
_SORT_COLUMNS: dict[str, str] = {
    "id": "l.id",
    "ts": "l.ts",
    "kind": "l.kind",
    "actor": "p.name",
}
_SORT_DIRS = {"asc": "ASC", "desc": "DESC"}

_ROW_TOKEN_PREFIX = "row:"

# ---------------------------------------------------------------------------------------------
# Moved verbatim from core/backend_surface.py
# ---------------------------------------------------------------------------------------------

# Above this many ESTIMATED rows (`pg_class.reltuples`, base tables/matviews only -- a view has
# no such statistic, Postgres keeps none for a relation with no storage of its own), an exact
# `SELECT count(*)` would be a real table scan for no real benefit to this power-user surface
# view; below it, every relation in this deployment today is small enough (largest live count:
# `ledger` itself, low hundreds) that an exact count costs nothing. Chosen well above this
# deployment's actual sizes so today every relation still gets an EXACT count -- this threshold
# only starts mattering if a relation genuinely grows large.
_EXACT_COUNT_ABOVE_ESTIMATE = 50_000

# Cache TTL for the live source-grep -- NOT a hand-maintained list of exposed relations, just a
# cheap re-read throttle so a burst of requests doesn't re-read/re-scan the same handful of small
# .py files on every single one. Short enough that an in-session source edit (this repo's own
# `run-dev.sh --reload` workflow) is visible within one manual refresh click.
_SOURCE_CACHE_TTL_S = 5.0

_RELKIND_LABEL: dict[str, str] = {"r": "table", "v": "view", "m": "materialized view"}

_source_cache: dict[str, Any] = {"ts": 0.0, "repo_root": None, "text": ""}


def _source_files(cfg: PanelConfig) -> list[Path]:
    """`backend/core/*.py` (always) plus `backend/extensions/<name>/*.py` for every extension
    THIS deployment currently has enabled (`cfg.extensions`, read fresh each call -- never a
    hardcoded `autoharn` literal, so a future second extension is covered with no code change
    here)."""
    backend_dir = cfg.repo_root / "backend"
    files = sorted((backend_dir / "core").glob("*.py"))
    for ext_name in cfg.extensions:
        ext_dir = backend_dir / "extensions" / ext_name
        if ext_dir.is_dir():
            files += sorted(ext_dir.glob("*.py"))
    return files


def _source_text(cfg: PanelConfig) -> str:
    """The combined text of every file `_source_files` names, refreshed at most once per
    `_SOURCE_CACHE_TTL_S`. A cache, never a parallel hand-maintained mapping."""
    now = time.monotonic()
    if _source_cache["repo_root"] == cfg.repo_root and (now - _source_cache["ts"]) < _SOURCE_CACHE_TTL_S:
        return _source_cache["text"]
    text = "\n".join(f.read_text(encoding="utf-8") for f in _source_files(cfg) if f.is_file())
    _source_cache["ts"] = now
    _source_cache["repo_root"] = cfg.repo_root
    _source_cache["text"] = text
    return text


_exposure_pattern_cache: dict[str, re.Pattern[str]] = {}


def _exposure_pattern(relation_name: str) -> re.Pattern[str]:
    pattern = _exposure_pattern_cache.get(relation_name)
    if pattern is None:
        # `FROM`/`JOIN`, optional schema-qualification (a literal `"schema".` or an f-string
        # interpolation like `"{cfg.kern_schema}".` -- `autoharn_health`'s own stamp_secret
        # armed-check is written exactly this way), optional quoting, the exact relation name,
        # then a word boundary so e.g. bare `ledger` does not match inside `ledger_current`.
        pattern = re.compile(rf'(?i)\b(?:from|join)\s+(?:\S*\.)?"?{re.escape(relation_name)}"?\b')
        _exposure_pattern_cache[relation_name] = pattern
    return pattern


def _count_relation(
    cur: Cursor, schema: str, name: str, relkind: str, reltuples: float | None
) -> tuple[int, bool]:
    """Returns (count, estimated). Views (`relkind == 'v'`) always get an exact count -- Postgres
    keeps no `reltuples` statistic for a relation with no storage of its own, and a view's row
    count is bounded by whatever already-small base tables this deployment's kernel views join
    over. A base table/matview whose own `reltuples` ESTIMATE already clears the threshold skips
    the exact count entirely -- the one path that avoids ever running a real `count(*)` against a
    relation "large enough that it would matter".

    Every identifier here is quoted via `psycopg.sql.Identifier`, never string-interpolated --
    `schema`/`name` come from a prior `pg_class`/`pg_namespace` query (trusted metadata, not
    request input), but this is still the safe, standard way to reference an identifier psycopg
    cannot bind as a parameter.

    Takes an already-open cursor deliberately (see this module's own CONNECTION-REUSE NOTE): the
    two public callers below -- `PostgresCoreLedgerReader.relation_count` (one relation, one fresh
    connection, per `CoreLedgerPort`'s own `cfg`-only signature) and
    `PostgresCoreLedgerReader.backend_surface` (every relation in the deployment, ONE connection
    reused across all of them, matching the real former behavior) -- both route through this same
    helper so the counting SQL itself has exactly one home."""
    if relkind != "v" and reltuples is not None and reltuples >= 0 and reltuples > _EXACT_COUNT_ABOVE_ESTIMATE:
        return int(reltuples), True
    cur.execute(sql.SQL("SELECT count(*) AS n FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(name)))
    return cur.fetchone()["n"], False


@dataclass(frozen=True)
class PostgresCoreLedgerReader:
    """The Postgres-backed `CoreLedgerPort` implementation. No fields, no constructor arguments --
    every method is handed its own `cfg: PanelConfig` (see module docstring); `frozen=True` for the
    same reason `PanelConfig` itself is frozen (a stateless collaborator should be trivially safe
    to share across requests/threads, and a dataclass with no fields costs nothing to declare this
    way over a plain class)."""

    def watermark(self, cfg: PanelConfig) -> dict[str, Any]:
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute("SELECT max(id) AS max_id, max(ts) AS max_ts, count(*) AS count FROM ledger")
            row = cur.fetchone()
        return {
            "max_id": row["max_id"],
            "max_ts": row["max_ts"].isoformat() if row["max_ts"] else None,
            "count": row["count"],
        }

    def rows(
        self,
        cfg: PanelConfig,
        *,
        kind: str | None = None,
        actor_name: str | None = None,
        q: str | None = None,
        since_id: int | None = None,
        since: str | None = None,
        until: str | None = None,
        include_superseded: bool = False,
        sort_by: str = "id",
        sort_dir: str = "desc",
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """The Board view's one query home (SPEC.md sec 2.1): every facet (kind, actor, date-range,
        free-text, since-id for live-update tailing) is a WHERE clause added to the SAME query that
        also supplies the facet's own count -- callers wanting a count call this with `limit` large
        enough, or call `count_rows` below with the identical filter arguments; there is no second,
        independently-derived counting query.

        `since`/`until` are the date-range facet (SPEC.md sec 2.1): ISO-8601 timestamps (any form
        Postgres's `timestamptz` input parser accepts -- a bare date like `2026-07-01` works too),
        inclusive on both ends (`l.ts >= since`, `l.ts <= until`), applied as ordinary parametrized
        WHERE clauses rather than a string-interpolated date literal. `sort_by`/`sort_dir` are the
        column-sort facet: `sort_by` is validated against the closed `_SORT_COLUMNS` map (never a
        raw identifier from the request) and raises `ValueError` on an unknown value, which the
        route layer turns into a 422 rather than either silently falling back or building an
        injectable query."""
        if sort_by not in _SORT_COLUMNS:
            raise ValueError(f"unknown sort_by {sort_by!r}; must be one of {sorted(_SORT_COLUMNS)}")
        if sort_dir not in _SORT_DIRS:
            raise ValueError(f"unknown sort_dir {sort_dir!r}; must be one of {sorted(_SORT_DIRS)}")
        # `limit`/`offset` feed straight into a LIMIT/OFFSET clause below -- Postgres itself rejects
        # a negative value there with an unhandled 500 (caught live: GET /api/rows?limit=-5 --
        # cycle-3 consult finding 2, CRITICAL), so both are validated here the same way
        # sort_by/sort_dir are: raise ValueError, which the route layer turns into a 400 with a
        # field-level message.
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        where = ["1=1"] if include_superseded else [_CURRENT_FILTER]
        params: list[Any] = []
        if kind is not None:
            where.append("l.kind = %s")
            params.append(kind)
        if actor_name is not None:
            where.append("p.name = %s")
            params.append(actor_name)
        if q is not None:
            where.append("l.statement ILIKE %s")
            params.append(f"%{q}%")
        if since_id is not None:
            where.append("l.id > %s")
            params.append(since_id)
        if since is not None:
            where.append("l.ts >= %s")
            params.append(since)
        if until is not None:
            where.append("l.ts <= %s")
            params.append(until)
        order_col = _SORT_COLUMNS[sort_by]
        order_dir = _SORT_DIRS[sort_dir]
        # `l.id` as a secondary key makes the order stable (and deterministic across pages) when
        # the primary sort column has ties -- `ts`/`kind`/`actor` all can.
        order_by = f"{order_col} {order_dir}, l.id {order_dir}" if order_col != "l.id" else f"l.id {order_dir}"
        sql_text = (
            "SELECT l.id, l.kind, l.statement, l.ts, l.refs, l.supersedes, p.name AS actor_name "
            "FROM ledger l LEFT JOIN principal p ON p.id = l.actor "
            f"WHERE {' AND '.join(where)} ORDER BY {order_by} LIMIT %s OFFSET %s"
        )
        params.extend([limit, offset])
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(sql_text, params)
            result = cur.fetchall()
        return [jsonable(r) for r in result]

    def count_rows(
        self,
        cfg: PanelConfig,
        *,
        kind: str | None = None,
        actor_name: str | None = None,
        q: str | None = None,
        include_superseded: bool = False,
    ) -> int:
        """The SAME filter `rows()` applies, projected to `count(*)` -- one home for a facet's
        count, per SPEC.md sec 2.1's own "one home per count" rule."""
        where = ["1=1"] if include_superseded else [_CURRENT_FILTER]
        params: list[Any] = []
        if kind is not None:
            where.append("l.kind = %s")
            params.append(kind)
        if actor_name is not None:
            where.append("p.name = %s")
            params.append(actor_name)
        if q is not None:
            where.append("l.statement ILIKE %s")
            params.append(f"%{q}%")
        sql_text = f"SELECT count(*) AS n FROM ledger l LEFT JOIN principal p ON p.id = l.actor WHERE {' AND '.join(where)}"
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(sql_text, params)
            return cur.fetchone()["n"]

    def facet_counts(self, cfg: PanelConfig) -> dict[str, int]:
        """Counts by kind, over CURRENT rows only -- the Board view's kind-facet counts, computed
        by one grouped query (still the single query family `rows`/`count_rows` share, not a
        third independently-derived path)."""
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(f"SELECT kind, count(*) AS n FROM ledger l WHERE {_CURRENT_FILTER} GROUP BY kind")
            result = cur.fetchall()
        return {r["kind"]: r["n"] for r in result}

    def row_by_id(self, cfg: PanelConfig, row_id: int) -> dict[str, Any] | None:
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.id, l.kind, l.statement, l.ts, l.refs, l.supersedes, p.name AS actor_name
                FROM ledger l LEFT JOIN principal p ON p.id = l.actor
                WHERE l.id = %s
                """,
                (row_id,),
            )
            row = cur.fetchone()
        return jsonable(row) if row else None

    def supersede_chain(self, cfg: PanelConfig, row_id: int) -> SupersedeChain:
        """Returns `core.ports.SupersedeChain` (the CONTRACT dataclass, imported directly -- this
        item collapses the disclosed, temporary duplication `core/ports.py`'s own docstring named
        (ledger row 979): there is now exactly one `SupersedeChain`, defined in `core/ports.py`,
        and this adapter is its one real producer)."""
        predecessors: list[int] = []
        with connect(cfg) as conn, conn.cursor() as cur:
            current = row_id
            seen: set[int] = set()
            while True:
                cur.execute("SELECT supersedes FROM ledger WHERE id = %s", (current,))
                r = cur.fetchone()
                if r is None or r["supersedes"] is None or r["supersedes"] in seen:
                    break
                predecessors.append(r["supersedes"])
                seen.add(r["supersedes"])
                current = r["supersedes"]
            cur.execute("SELECT id FROM ledger WHERE supersedes = %s", (row_id,))
            succ = cur.fetchone()
        return SupersedeChain(
            row_id=row_id, predecessors=tuple(predecessors), successor=succ["id"] if succ else None
        )

    def generic_row_refs(self, refs_text: str | None) -> list[int]:
        """PURE. The one core-generic ref token this module parses: `row:<id>` (a bare witness
        pointing at another ledger row -- SPEC.md sec 3's hover-synopsis mechanism needs at least
        this much to resolve a link from any row's `refs` text). Any other token shape
        (`work:...`, `panel-item:...`, free prose) is autoharn-specific or simply not this
        grammar's concern, and is left untouched -- this method never raises on an unrecognized
        token, it just does not extract one from it."""
        out: list[int] = []
        for tok in (refs_text or "").split():
            if tok.startswith(_ROW_TOKEN_PREFIX):
                candidate = tok[len(_ROW_TOKEN_PREFIX):]
                if candidate.isdigit():
                    out.append(int(candidate))
        return out

    def backend_surface(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """The full three-layer surface (DB -> our API; the SPA-tab layer is the frontend's own
        best-effort addition on top of this): every relation (table/view/matview) in EITHER of
        this deployment's two configured schemas, each with schema/name/kind (pg_catalog metadata
        only), count/count_estimated (see `_count_relation`), and exposed_by_api (see
        `is_exposed_by_backend` -- LIVE-derived, never hand-maintained).

        ONE connection/cursor, reused across every relation counted (see this module's own
        CONNECTION-REUSE NOTE) -- unchanged from the real former behavior. Never selects a single
        row's own column values from any relation, regardless of schema -- the `stamp_secret`
        safety property holds by construction here: nothing in this method's SQL ever names one
        of that table's own columns, only `count(*)`."""
        with connect_unrestricted(cfg) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT n.nspname AS schema, c.relname AS name, c.relkind AS relkind,
                       c.reltuples AS reltuples
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'v', 'm')
                ORDER BY n.nspname, c.relname
                """,
                ([cfg.schema, cfg.kern_schema],),
            )
            relations = cur.fetchall()

            out: list[dict[str, Any]] = []
            for r in relations:
                count, estimated = _count_relation(cur, r["schema"], r["name"], r["relkind"], r["reltuples"])
                out.append(
                    {
                        "schema": r["schema"],
                        "name": r["name"],
                        "kind": _RELKIND_LABEL.get(r["relkind"], r["relkind"]),
                        "count": count,
                        "count_estimated": estimated,
                        "exposed_by_api": self.is_exposed_by_backend(cfg, r["name"]),
                    }
                )
        return out

    def is_exposed_by_backend(self, cfg: PanelConfig, relation_name: str) -> bool:
        """True iff `relation_name` appears as a FROM/JOIN target anywhere in this backend's own
        Python source (core + every currently-enabled extension) -- LIVE, derived fresh from the
        files on disk (subject to the short cache above), never a hand-maintained mapping.

        This is a regex heuristic over source TEXT, not a SQL parser: it can in principle be
        fooled by a relation name mentioned only in a comment/docstring that never actually
        executes as a query. Checked by hand against this deployment's real source when this
        logic was first written -- every relation this currently reports as exposed does have a
        genuine FROM/JOIN in executable SQL, not merely a comment -- but a future source edit
        could in principle introduce that false positive. It can never silently go STALE the way
        a hand-written list would, since it re-reads the real source every refresh."""
        return _exposure_pattern(relation_name).search(_source_text(cfg)) is not None

    def relation_count(
        self, cfg: PanelConfig, schema: str, name: str, relkind: str, reltuples: float | None
    ) -> tuple[int, bool]:
        """The Protocol's own standalone, `cfg`-only entry point for one relation's count (see
        `core/ports.py`'s SIGNATURE NOTE on why this takes `cfg` rather than a live `Cursor`, and
        this module's own CONNECTION-REUSE NOTE on why `backend_surface()` above does NOT call
        this method internally in a loop -- it routes through the same `_count_relation` helper
        over its own single reused cursor instead, to avoid a connection-per-relation regression)."""
        with connect_unrestricted(cfg) as conn, conn.cursor() as cur:
            return _count_relation(cur, schema, name, relkind, reltuples)
