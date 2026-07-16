"""tests.fakes.core_ledger_reader -- FakeCoreLedgerReader: an in-memory, structurally-conformant
implementation of `core.ports.CoreLedgerPort` (backend/core/ports.py) for tests. Faithfully
replicates the semantics that matter -- not canned dicts:

  - `supersede_chain`'s predecessor/successor walk, over real hand-constructed row data (mirrors
    `core/ledger_read.py`'s own `supersede_chain`: walks `supersedes` back to the root, oldest
    first, and separately finds the row -- if any -- whose OWN `supersedes` points back at this
    one).
  - `rows()`'s sort_by/sort_dir closed-vocabulary validation (raises `ValueError` on an
    unrecognized value, exactly as `core/ledger_read.py`'s `rows()` does) and its filter/order
    semantics (kind, actor_name, `q` substring, since_id, since/until date range,
    include_superseded's "current row only" default, and the same `sort_by` x `sort_dir`, id-
    as-secondary-tiebreak ordering `core/ledger_read.py` builds).
  - `rows()`'s limit/offset validation (`ValueError` on limit < 1 or offset < 0, same as the
    real function).
  - `relation_count`'s exact-vs-estimate threshold branch (`core/backend_surface.py`'s own
    `_relation_count`).

Deliberately does NOT import `db` or `psycopg` (this file's whole reason to exist is a DB-free
test double) -- only `core.ports`/`config` (typing/dataclasses/stdlib only, no psycopg -- see
those modules' own docstrings) and the stdlib. A grep for `psycopg` over this file must come
back empty; that is one of this work item's own pre-registered acceptance criteria (ledger row
1002).

DATACLASS/HELPER DUPLICATION (same disclosed pattern `core/ports.py` itself uses for
`SupersedeChain`, ledger row 979): this file re-implements a tiny `_jsonable` helper rather than
importing `db.jsonable` -- importing `db` would pull in `psycopg`, defeating the point of a
psycopg-free fake.

STRUCTURAL CONFORMANCE: `_STRUCTURAL_CONFORMANCE_CHECK` at the bottom of this file is a
permanent, mypy-checked assignment of a `FakeCoreLedgerReader` instance to a `CoreLedgerPort`-
typed variable -- not a throwaway script, so any FUTURE drift between this fake and the
Protocol's signatures is caught the next time mypy runs over this file, not just once at
write-time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from config import PanelConfig
from core.ports import CoreLedgerPort, SupersedeChain

_SORT_COLUMNS = ("id", "ts", "kind", "actor")
_SORT_DIRS = ("asc", "desc")

# Mirrors `core/backend_surface.py`'s own `_EXACT_COUNT_ABOVE_ESTIMATE` threshold exactly, so
# `relation_count`'s branch logic below is a faithful replica, not a re-derived guess.
_EXACT_COUNT_ABOVE_ESTIMATE = 50_000


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Mirrors `backend/db.py`'s own `jsonable`: datetimes -> isoformat, everything else passed
    through untouched. Duplicated here (not imported) because `db` imports `psycopg` -- see this
    module's own docstring."""
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}


def _parse_ts(value: str) -> datetime:
    """The same common ISO-8601 shapes Postgres's own `timestamptz` input accepts for what this
    backend actually sends as `since`/`until` query params -- a bare date or a full timestamp,
    optionally `Z`-suffixed. Not a general libpq-input-parser replica; a fake's job is the
    semantics that matter (SPEC.md sec 4, this work item's own instruction), not every corner of
    Postgres's date parser."""
    return datetime.fromisoformat(value)


@dataclass
class FakeCoreLedgerReader:
    """An in-memory stand-in for the DB-backed `core.ledger_read`/`core.backend_surface` module
    functions, structurally satisfying `CoreLedgerPort` (see `backend/core/ports.py`) -- a
    variable of type `CoreLedgerPort` may be assigned an instance of this class directly, with no
    inheritance relationship required (Protocols are structural; see
    `_STRUCTURAL_CONFORMANCE_CHECK` below).

    Construct with the ledger rows this fake should answer from (`rows_data`, one dict per row --
    each dict must supply `id`, `kind`, `statement`, `ts` (a `datetime`), `refs`, `supersedes`
    (an `int | None`), `actor_name`), plus optionally the `backend_surface`-shaped fixtures
    (`relations`, `exposed_relation_names`, `relation_row_counts`) that back this Protocol's 3
    metadata methods. Every `cfg: PanelConfig` parameter is accepted (to match the Protocol's own
    signatures exactly) and otherwise ignored -- this fake answers purely from its own
    constructor state, never from the passed-in config."""

    rows_data: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    exposed_relation_names: frozenset[str] = frozenset()
    relation_row_counts: dict[tuple[str, str], int] = field(default_factory=dict)

    # -- core.ledger_read mirror -------------------------------------------------------------

    def watermark(self, cfg: PanelConfig) -> dict[str, Any]:
        if not self.rows_data:
            return {"max_id": None, "max_ts": None, "count": 0}
        max_id = max(r["id"] for r in self.rows_data)
        max_ts = max(r["ts"] for r in self.rows_data)
        return {
            "max_id": max_id,
            "max_ts": max_ts.isoformat() if hasattr(max_ts, "isoformat") else max_ts,
            "count": len(self.rows_data),
        }

    def _is_current(self, row_id: int) -> bool:
        """Mirrors `_CURRENT_FILTER`'s `NOT EXISTS (... s.supersedes = l.id)`: a row is current
        iff no OTHER row's `supersedes` points at it."""
        return not any(r["supersedes"] == row_id for r in self.rows_data)

    def _filtered(
        self,
        *,
        kind: str | None,
        actor_name: str | None,
        q: str | None,
        include_superseded: bool,
        since_id: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        out = list(self.rows_data)
        if not include_superseded:
            out = [r for r in out if self._is_current(r["id"])]
        if kind is not None:
            out = [r for r in out if r["kind"] == kind]
        if actor_name is not None:
            out = [r for r in out if r["actor_name"] == actor_name]
        if q is not None:
            needle = q.lower()
            out = [r for r in out if needle in (r["statement"] or "").lower()]
        if since_id is not None:
            out = [r for r in out if r["id"] > since_id]
        if since is not None:
            since_ts = _parse_ts(since)
            out = [r for r in out if r["ts"] >= since_ts]
        if until is not None:
            until_ts = _parse_ts(until)
            out = [r for r in out if r["ts"] <= until_ts]
        return out

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
        if sort_by not in _SORT_COLUMNS:
            raise ValueError(f"unknown sort_by {sort_by!r}; must be one of {sorted(_SORT_COLUMNS)}")
        if sort_dir not in _SORT_DIRS:
            raise ValueError(f"unknown sort_dir {sort_dir!r}; must be one of {sorted(_SORT_DIRS)}")
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")

        matched = self._filtered(
            kind=kind, actor_name=actor_name, q=q, include_superseded=include_superseded,
            since_id=since_id, since=since, until=until,
        )

        sort_field = {"id": "id", "ts": "ts", "kind": "kind", "actor": "actor_name"}[sort_by]
        reverse = sort_dir == "desc"

        def key(r: dict[str, Any]) -> tuple[Any, ...]:
            value = r[sort_field]
            if sort_field == "id":
                # `l.id` alone is the ORDER BY when sort_by == "id" -- no secondary key needed,
                # and id is never NULL.
                return (value,)
            # Mirrors Postgres's default NULLS ordering (NULLS LAST ascending, NULLS FIRST
            # descending) for the one nullable sort column (`actor`): pairing `(is_none, value)`
            # and reversing the WHOLE key for DESC reproduces that automatically. `id` is
            # appended as the same-direction secondary tiebreak, matching
            # `f"{order_col} {order_dir}, l.id {order_dir}"` in the real query.
            is_none = value is None
            return (is_none, value if not is_none else "", r["id"])

        ordered = sorted(matched, key=key, reverse=reverse)
        page = ordered[offset:offset + limit]
        return [_jsonable(r) for r in page]

    def facet_counts(self, cfg: PanelConfig) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows_data:
            if self._is_current(r["id"]):
                out[r["kind"]] = out.get(r["kind"], 0) + 1
        return out

    def row_by_id(self, cfg: PanelConfig, row_id: int) -> dict[str, Any] | None:
        for r in self.rows_data:
            if r["id"] == row_id:
                return _jsonable(r)
        return None

    def supersede_chain(self, cfg: PanelConfig, row_id: int) -> SupersedeChain:
        by_id = {r["id"]: r for r in self.rows_data}
        predecessors: list[int] = []
        current = row_id
        seen: set[int] = set()
        while True:
            row = by_id.get(current)
            supersedes = row["supersedes"] if row is not None else None
            if supersedes is None or supersedes in seen:
                break
            predecessors.append(supersedes)
            seen.add(supersedes)
            current = supersedes
        successor = next((r["id"] for r in self.rows_data if r["supersedes"] == row_id), None)
        return SupersedeChain(row_id=row_id, predecessors=tuple(predecessors), successor=successor)

    def generic_row_refs(self, refs_text: str | None) -> list[int]:
        out: list[int] = []
        for tok in (refs_text or "").split():
            if tok.startswith("row:"):
                candidate = tok[len("row:"):]
                if candidate.isdigit():
                    out.append(int(candidate))
        return out

    # -- core.backend_surface mirror ---------------------------------------------------------

    def backend_surface(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return [dict(r) for r in self.relations]

    def is_exposed_by_backend(self, cfg: PanelConfig, relation_name: str) -> bool:
        return relation_name in self.exposed_relation_names

    def relation_count(
        self, cfg: PanelConfig, schema: str, name: str, relkind: str, reltuples: float | None
    ) -> tuple[int, bool]:
        # Mirrors `core/backend_surface.py`'s own `_relation_count` threshold branch exactly: a
        # non-view relation whose ESTIMATE already clears the threshold reports the estimate
        # without ever touching a real per-row count.
        if relkind != "v" and reltuples is not None and reltuples >= 0 and reltuples > _EXACT_COUNT_ABOVE_ESTIMATE:
            return int(reltuples), True
        return self.relation_row_counts.get((schema, name), 0), False


# A permanent, mypy-checked proof of structural conformance (see this module's own docstring) --
# NOT a runtime `isinstance` check (CoreLedgerPort is not `@runtime_checkable`, and structural
# Protocol conformance is a static-typing property, not a runtime one).
_STRUCTURAL_CONFORMANCE_CHECK: CoreLedgerPort = FakeCoreLedgerReader()
