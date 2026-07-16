"""backend.core.backend_surface -- introspects the deployment's ACTUAL Postgres surface (both
schemas this deployment names, `cfg.schema`/`cfg.kern_schema` -- never hardcoded, read the same
way every other module in this backend reads them) and cross-references it, live, against this
backend's OWN source to answer: does our code even bother to query this relation at all?

Two distinct gaps this backs (spa-backend-surface-view, commission row:741 -- the maintainer's
own refinement, replying to the original ask: "there are actually TWO gaps to show ... the
second gap is negligence on our part, distinct from the first"):
  1. DB schema vs SPA tab -- a coarser, best-effort judgment the FRONTEND makes (a small,
     explicitly hand-maintained mapping, disclosed as such in the component's own comment; not
     derived here).
  2. DB schema vs OUR OWN backend API -- `exposed_by_api` below, LIVE-derived by grepping this
     backend's own source for the relation name as a FROM/JOIN target. Never a hand-maintained
     list of "which relations are exposed" -- that is exactly the staleness bug class a sibling
     work item this same session fixed for a hand-maintained tab count in a comment; this module
     re-reads the real .py files every refresh (subject to a short cache, see `_SOURCE_CACHE_TTL_S`)
     rather than writing any relation name down as exposed/unexposed by hand.

CORE-GENERIC (SPEC.md sec 4): reads only `cfg.schema`/`cfg.kern_schema`/`cfg.extensions`/
`cfg.repo_root` -- all core-generic `PanelConfig` fields, no ledger/autoharn kind vocabulary, no
kernel-specific relation name hardcoded anywhere in this module. Works the same against a bare
ledger schema (SPEC.md's own minimal boundary test) as any other core module: a bare deployment
just has fewer relations to list, and `cfg.extensions` empty just means no extension source gets
grepped.

SAFETY (non-negotiable -- the ONE property this module must never regress, called out by name in
this work item for `<kern_schema>.stamp_secret`, a cryptographic secret): every query in this
file is either `pg_catalog` metadata or a bare `count(*)` against a relation identified via
`psycopg.sql.Identifier` (never string-interpolated). There is no `SELECT *`, no projection of a
single column, no row content of any kind, read or returned, anywhere in this file, for any
relation, regardless of which schema or table it is.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from psycopg import sql
from psycopg.cursor import Cursor

from config import PanelConfig
from db import connect_unrestricted

# `connect_unrestricted` (not `connect`) is used throughout this module rather than the ordinary
# `SET ROLE`'d connection: this deployment REVOKEs `<kern_schema>.stamp_secret` from the ordinary
# subject role on purpose (confirmed live: `SELECT count(*)` against it under `SET ROLE
# experience_rw` raises `permission denied for table stamp_secret`), so a plain `connect(cfg)`
# would make the WHOLE relation listing fail the moment it reached that one table. Reading past
# that REVOKE is exactly what `db.connect_unrestricted` exists for (same precedent as
# `extensions/autoharn/ledger_read.py`'s `autoharn_health` armed-check) -- still metadata/count
# only, per this module's own safety contract above.

# Above this many ESTIMATED rows (`pg_class.reltuples`, base tables/matviews only -- a view has
# no such statistic, Postgres keeps none for a relation with no storage of its own), an exact
# `SELECT count(*)` would be a real table scan for no real benefit to this power-user surface
# view; below it, every relation in this deployment today is small enough (largest live count:
# `ledger` itself, low hundreds) that an exact count costs nothing. Chosen well above this
# deployment's actual sizes so today every relation still gets an EXACT count -- this threshold
# only starts mattering if a relation genuinely grows large.
_EXACT_COUNT_ABOVE_ESTIMATE = 50_000

# Cache TTL for the live source-grep -- NOT a hand-maintained list of exposed relations (see the
# module docstring), just a cheap re-read throttle so a burst of requests doesn't re-read/
# re-scan the same handful of small .py files on every single one. Short enough that an in-
# session source edit (this repo's own `run-dev.sh --reload` workflow) is visible within one
# manual refresh click.
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
    `_SOURCE_CACHE_TTL_S`. A cache, never a parallel hand-maintained mapping -- see this module's
    own docstring and the work item's own instruction against that bug class."""
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


def is_exposed_by_backend(cfg: PanelConfig, relation_name: str) -> bool:
    """True iff `relation_name` appears as a FROM/JOIN target anywhere in this backend's own
    Python source (core + every currently-enabled extension) -- LIVE, derived fresh from the
    files on disk (subject to the short cache above), never a hand-maintained mapping.

    This is a regex heuristic over source TEXT, not a SQL parser: it can in principle be fooled
    by a relation name mentioned only in a comment/docstring that never actually executes as a
    query. Checked by hand against this deployment's real source when this module was written --
    every relation this currently reports as exposed does have a genuine FROM/JOIN in executable
    SQL, not merely a comment -- but a future source edit could in principle introduce that false
    positive. It can never silently go STALE the way a hand-written list would, since it re-reads
    the real source every refresh; that is the property this work item asked for."""
    return _exposure_pattern(relation_name).search(_source_text(cfg)) is not None


def _relation_count(
    cur: Cursor, schema: str, name: str, relkind: str, reltuples: float | None
) -> tuple[int, bool]:
    """Returns (count, estimated). Views (`relkind == 'v'`) always get an exact count -- Postgres
    keeps no `reltuples` statistic for a relation with no storage of its own, and a view's row
    count is bounded by whatever already-small base tables this deployment's kernel views join
    over. A base table/matview whose own `reltuples` ESTIMATE already clears the threshold skips
    the exact count entirely -- the one path that avoids ever running a real `count(*)` against a
    relation "large enough that it would matter", per this work item's own instruction.

    Every identifier here is quoted via `psycopg.sql.Identifier`, never string-interpolated --
    `schema`/`name` come from this module's own prior `pg_class`/`pg_namespace` query (trusted
    metadata, not request input), but this is still the safe, standard way to reference an
    identifier psycopg cannot bind as a parameter."""
    if relkind != "v" and reltuples is not None and reltuples >= 0 and reltuples > _EXACT_COUNT_ABOVE_ESTIMATE:
        return int(reltuples), True
    cur.execute(sql.SQL("SELECT count(*) AS n FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(name)))
    return cur.fetchone()["n"], False


def backend_surface(cfg: PanelConfig) -> list[dict[str, Any]]:
    """The full three-layer surface (DB -> our API; the SPA-tab layer is the frontend's own
    best-effort addition on top of this): every relation (table/view/matview) in EITHER of this
    deployment's two configured schemas, each with:
      - schema/name/kind (pg_catalog metadata only)
      - count / count_estimated (see `_relation_count`)
      - exposed_by_api (see `is_exposed_by_backend` -- LIVE-derived, never hand-maintained)

    Ordered by schema then name for a stable, groupable display. Never selects a single row's own
    column values from any relation, regardless of schema -- the `stamp_secret` safety property
    this work item names explicitly holds by construction here: nothing in this function's SQL
    ever names one of that table's own columns, only `count(*)`."""
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
            count, estimated = _relation_count(cur, r["schema"], r["name"], r["relkind"], r["reltuples"])
            out.append(
                {
                    "schema": r["schema"],
                    "name": r["name"],
                    "kind": _RELKIND_LABEL.get(r["relkind"], r["relkind"]),
                    "count": count,
                    "count_estimated": estimated,
                    "exposed_by_api": is_exposed_by_backend(cfg, r["name"]),
                }
            )
    return out
