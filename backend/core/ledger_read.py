"""backend.core.ledger_read -- the CORE, ledger-generic reads (SPEC.md sec 4's extension
boundary): rows, kinds, refs, supersession. Nothing here knows about `commission`/`work_item`
kinds, the `panel-item:` refs grammar, obligation/independence vocabularies, or any kernel
extension view (`review_detail`, `work_item_current`, `review_gap`, `question_status`) -- those
all live in `extensions/autoharn/ledger_read.py`.

Every "current" filter here is computed directly against the base `ledger` table
(`NOT EXISTS (SELECT 1 FROM ledger s WHERE s.supersedes = l.id)`), never a pre-existing
`ledger_current` view -- so this module runs against a bare schema that has only the `ledger`
table itself (plus `<kern>.principal`), the literal minimal subset SPEC.md sec 4 names as the
boundary test. (Autoharn's own deployment DOES define a `ledger_current` view with this exact
WHERE clause, per its kernel lineage -- this module simply does not depend on that view
existing, so it works whether or not it does.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db import connect, jsonable
from config import PanelConfig

# The minimal, ledger-generic kind vocabulary this module itself imposes: NONE. Core does not
# validate `kind` against a closed list at all -- an unrecognized kind is just a string a facet
# filter can select on; only an extension (or the ledger's own CHECK constraint) may narrow the
# vocabulary. This is deliberate (SPEC.md sec 0 "derive, don't duplicate" -- core has no
# authority to invent a kind vocabulary the ledger's own schema does not assert).

_CURRENT_FILTER = "NOT EXISTS (SELECT 1 FROM ledger s WHERE s.supersedes = l.id)"


def watermark(cfg: PanelConfig) -> dict[str, Any]:
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute("SELECT max(id) AS max_id, max(ts) AS max_ts, count(*) AS count FROM ledger")
        row = cur.fetchone()
    return {
        "max_id": row["max_id"],
        "max_ts": row["max_ts"].isoformat() if row["max_ts"] else None,
        "count": row["count"],
    }


def rows(
    cfg: PanelConfig,
    *,
    kind: str | None = None,
    actor_name: str | None = None,
    q: str | None = None,
    since_id: int | None = None,
    include_superseded: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """The Board view's one query home (SPEC.md sec 2.1): every facet (kind, actor, free-text,
    since-id for live-update tailing) is a WHERE clause added to the SAME query that also
    supplies the facet's own count -- callers wanting a count call this with `limit` large
    enough, or call `count_rows` below with the identical filter arguments; there is no second,
    independently-derived counting query."""
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
    sql = (
        "SELECT l.id, l.kind, l.statement, l.ts, l.refs, l.supersedes, p.name AS actor_name "
        "FROM ledger l LEFT JOIN principal p ON p.id = l.actor "
        f"WHERE {' AND '.join(where)} ORDER BY l.id DESC LIMIT %s OFFSET %s"
    )
    params.extend([limit, offset])
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        result = cur.fetchall()
    return [jsonable(r) for r in result]


def count_rows(
    cfg: PanelConfig,
    *,
    kind: str | None = None,
    actor_name: str | None = None,
    q: str | None = None,
    include_superseded: bool = False,
) -> int:
    """The SAME filter `rows()` applies, projected to `count(*)` -- one home for a facet's count,
    per SPEC.md sec 2.1's own "one home per count" rule (the PoC's round-4 lesson, carried
    forward for the generalized core)."""
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
    sql = f"SELECT count(*) AS n FROM ledger l LEFT JOIN principal p ON p.id = l.actor WHERE {' AND '.join(where)}"
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()["n"]


def facet_counts(cfg: PanelConfig) -> dict[str, int]:
    """Counts by kind, over CURRENT rows only -- the Board view's kind-facet counts, computed by
    one grouped query (still the single query family `rows`/`count_rows` share, not a
    third independently-derived path)."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT kind, count(*) AS n FROM ledger l WHERE {_CURRENT_FILTER} GROUP BY kind")
        result = cur.fetchall()
    return {r["kind"]: r["n"] for r in result}


def row_by_id(cfg: PanelConfig, row_id: int) -> dict[str, Any] | None:
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


@dataclass(frozen=True)
class SupersedeChain:
    """One row's supersede chain, both directions: `predecessors` walks `supersedes` back to the
    root (oldest first); `successor` is the row (if any) whose OWN `supersedes` points at this
    one -- a row can have at most one direct successor (each row supersedes at most one target),
    though a chain can be arbitrarily long."""
    row_id: int
    predecessors: tuple[int, ...]
    successor: int | None


def supersede_chain(cfg: PanelConfig, row_id: int) -> SupersedeChain:
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
    return SupersedeChain(row_id=row_id, predecessors=tuple(predecessors), successor=succ["id"] if succ else None)


_ROW_TOKEN_PREFIX = "row:"


def generic_row_refs(refs_text: str | None) -> list[int]:
    """The ONE core-generic ref token this module parses: `row:<id>` (a bare witness pointing at
    another ledger row -- SPEC.md sec 3's hover-synopsis mechanism needs at least this much to
    resolve a link from any row's `refs` text). Any other token shape (`work:...`,
    `panel-item:...`, free prose) is autoharn-specific or simply not this grammar's concern, and
    is left untouched -- this function never raises on an unrecognized token, it just does not
    extract one from it."""
    out: list[int] = []
    for tok in (refs_text or "").split():
        if tok.startswith(_ROW_TOKEN_PREFIX):
            candidate = tok[len(_ROW_TOKEN_PREFIX):]
            if candidate.isdigit():
                out.append(int(candidate))
    return out
