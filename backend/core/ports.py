"""backend.core.ports -- the CoreLedgerPort seam: one `typing.Protocol` covering the entire
DB-touching public surface that USED TO live as module-level functions across `core/ledger_read.py`
AND `core/backend_surface.py` (backend structural audit, docs/consults/2026-07-16-backend-
structural-audit/2026-07-16-backend-structural-audit.md, finding 2/recommendation 1; ledger row
894/959; work item ledger-ports-protocols, row 931). Interface only -- no adapter body lives here.
`PostgresCoreLedgerReader` (work item core-ledger-adapter, row 933) now IS the sole implementation
of this Protocol, at `core/ledger_adapter.py` -- both `core/ledger_read.py` and
`core/backend_surface.py` are gone, their SQL relocated verbatim into that one class (ADR-0004
minimal-touch); a `FakeCoreLedgerReader` (core-ledger-fake) implements it in-memory for tests.
Route handlers depend on this Protocol type, never on a concrete module import (ADR-0012 P2
seam/port discipline).

ENFORCEMENT MECHANISM (the omega precedent -- docs/omega-observatory/2026-07-15-structural-reap.md
entry 2, `backend/repositories/ports.py`'s own documented technique in the maintainer's private
omega checkout): "any class matching the method signatures satisfies the Protocol," and the
Dependency Rule is made mechanically checkable by inspecting THIS file's own imports alone --
everything below comes from `typing`, the stdlib, or this project's own `config` module. Nothing
from `psycopg`, nothing from this project's `db` module. A reviewer (or a script) can verify the
boundary holds by grepping this file's import block; no framework, no DI container, is needed to
assert it.

DATACLASS DUPLICATION -- COLLAPSED (was disclosed at ledger row 979, resolved at row 933): this was
originally a field-for-field copy of `core/ledger_read.py`'s own `SupersedeChain`, kept separate
because importing that module would have meant importing `db`, which imports `psycopg`, defeating
the import-boundary this file exists to hold. `core-ledger-adapter` (row 933) did exactly what this
note originally invited: `core/ledger_read.py` is gone, and `SupersedeChain` below is now the ONE
canonical definition -- `core/ledger_adapter.py`'s `PostgresCoreLedgerReader.supersede_chain`
imports it directly from here rather than carrying its own copy.

SIGNATURE NOTE -- `relation_count` (ledger row 980): `core/ledger_adapter.py`'s private
`_count_relation(cur: Cursor, schema, name, relkind, reltuples)` (formerly `core/backend_surface.py`'s
`_relation_count`, before that file was deleted at row 933) takes a live `psycopg.Cursor` as
its first argument -- unrepresentable here under the import ban above. This Protocol states the
CONTRACT (count a relation, given the config to reach it), not the transaction-plumbing choice of
any one concrete adapter, so the first parameter is `cfg: PanelConfig` instead, matching every
other method on this Protocol. The Postgres adapter is free to reuse one open cursor across
multiple relations internally; that is an implementation detail this Protocol does not pin down.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from config import PanelConfig


@dataclass(frozen=True)
class SupersedeChain:
    """One row's supersede chain, both directions -- the ONE canonical definition (see this
    module's docstring, DATACLASS DUPLICATION section, on the now-collapsed former copy in the
    since-deleted `core/ledger_read.py`). `predecessors` walks `supersedes` back to the root
    (oldest first); `successor` is the row (if any) whose OWN `supersedes` points at this one."""
    row_id: int
    predecessors: tuple[int, ...]
    successor: int | None


class CoreLedgerPort(Protocol):
    """The DB-touching public surface that USED TO be split across `core/ledger_read.py` and
    `core/backend_surface.py` (both deleted at `core-ledger-adapter`, row 933 -- their SQL now
    lives in `core/ledger_adapter.py`'s `PostgresCoreLedgerReader`, this Protocol's sole
    implementation), as one seam (`ledger-ports-protocols`'s own "2 Protocols, not 6" mandate --
    one per existing core/autoharn extension boundary, SPEC.md sec 4 -- folds `backend_surface.py`'s
    former functions in here rather than minting a 3rd Protocol, per ledger row 925). Every method
    below takes `cfg: PanelConfig` as its own connection/config handle, exactly as
    `PostgresCoreLedgerReader`'s methods do; a conforming adapter/fake needs no other shared state.

    `generic_row_refs` is the one PURE, no-I/O method folded in anyway (ledger row 925): the
    audit's own 7-method list named it explicitly alongside the six DB-touching reads, so it is
    treated as this Protocol's contract surface rather than left a bare module function -- unlike
    `extensions/autoharn/ports.py`'s `parse_item_refs`/`parse_witness_refs`/`parse_resource_fields`,
    which stay plain functions with no antecedent
    licensing their inclusion here.
    """

    def watermark(self, cfg: PanelConfig) -> dict[str, Any]:
        """`{max_id, max_ts, count}` over the whole `ledger` table -- the live-update poll's own
        cheap "has anything changed" probe."""
        ...

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
        """The Board view's one query home (SPEC.md sec 2.1) -- every facet (kind, actor,
        date-range, free-text, since-id tailing, column-sort) as a WHERE/ORDER-BY clause on the
        same query. Raises `ValueError` on an unrecognized `sort_by`/`sort_dir` or an out-of-range
        `limit`/`offset`, which the route layer turns into a 400/422."""
        ...

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
        count."""
        ...

    def facet_counts(self, cfg: PanelConfig) -> dict[str, int]:
        """Counts by `kind`, over CURRENT rows only -- the Board view's kind-facet counts."""
        ...

    def row_by_id(self, cfg: PanelConfig, row_id: int) -> dict[str, Any] | None:
        """One ledger row (any status, current or superseded) by id, or `None` if it does not
        exist."""
        ...

    def supersede_chain(self, cfg: PanelConfig, row_id: int) -> SupersedeChain:
        """`row_id`'s full supersede chain: every predecessor it supersedes (oldest first) and its
        own direct successor, if any."""
        ...

    def generic_row_refs(self, refs_text: str | None) -> list[int]:
        """PURE. The one core-generic ref token this Protocol's grammar parses out of a row's
        `refs` text: bare `row:<id>` witness tokens. Any other token shape (`work:...`,
        `panel-item:...`, free prose) is left untouched -- never raises on an unrecognized token,
        it simply extracts nothing from it. Folded onto this Protocol despite being pure (no
        `cfg`, no I/O) per ledger row 925 -- the audit's own 7-method list named it explicitly."""
        ...

    def backend_surface(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """Every relation (table/view/matview) in either of this deployment's two configured
        schemas, each with schema/name/kind, an (exact-or-estimated) row count, and whether this
        backend's own source exposes it (`exposed_by_api`, see `is_exposed_by_backend`). Never
        selects a single row's own column values from any relation, regardless of schema --
        metadata/`count(*)` only, for every relation, unconditionally (the `stamp_secret` safety
        property this surface exists to uphold)."""
        ...

    def is_exposed_by_backend(self, cfg: PanelConfig, relation_name: str) -> bool:
        """True iff `relation_name` appears as a FROM/JOIN target anywhere in this backend's own
        Python source (core + every currently-enabled extension) -- live-derived from the files on
        disk (subject to a short cache in the concrete adapter), never a hand-maintained list."""
        ...

    def relation_count(
        self, cfg: PanelConfig, schema: str, name: str, relkind: str, reltuples: float | None
    ) -> tuple[int, bool]:
        """Returns `(count, estimated)` for one relation. A view (`relkind == 'v'`) always gets an
        exact count (Postgres keeps no `reltuples` statistic for a relation with no storage of its
        own); a base table/matview whose own `reltuples` ESTIMATE already clears the adapter's
        exact-count threshold skips the exact `count(*)` entirely and reports `estimated=True`.
        SIGNATURE NOTE: mirrors `core/ledger_adapter.py`'s private `_count_relation` in every
        respect except its first parameter -- `cfg: PanelConfig` here instead of a live
        `psycopg.Cursor`, since a `Cursor` type cannot appear in this file under the import-boundary
        rule this module's own docstring states (ledger row 980)."""
        ...
