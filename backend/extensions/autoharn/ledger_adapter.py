"""extensions.autoharn.ledger_adapter -- `PostgresAutoharnLedgerReader`, the ONE concrete
implementation of `extensions.autoharn.ports.AutoharnLedgerPort` (work item
autoharn-adapter-acl-wrap, ledger row 934; Protocol landed at row 931/619b95d).

GOD-MODULE SPLIT (work item autoharn-god-module-split, ledger row 935/1094; the 4-way split
itself is row:926's assumption, "not the audit's literally-named 3"): this class used to carry
all 25 Protocol methods and ~1050 lines of SQL/logic directly (row 934's own deliberate,
disclosed deferral -- "the minimum restructuring Python's own syntax requires ... not a
substantive reorganization"). It is now a thin FACADE composing four internal, single-concern
collaborators, each in its own module, and delegating every Protocol method to exactly one of
them with a one-line forward:

  - `extensions.autoharn.decomposition_reader.DecompositionReader` (b) -- decomposition-item
    parsing plus witness/cosign resolution (13 methods): `ledger_row`, `work_item`,
    `maintainer_cosigned`, `latest_review_id`, `resolve_witness`, `cosign_fact`,
    `reviews_for_row`, `resolve_item_witnesses`, `row_refs_text`, `item_witnesses`,
    `fetch_parsed_item_rows`, `item_id_groups`, `decomposition_items`.
  - `extensions.autoharn.work_obligation_reader.WorkObligationReader` (c) -- work-items plus the
    recursive obligation/dependency AND-tree (2 methods): `work_items`, `obligation_tree`.
  - `extensions.autoharn.queue_views_reader.QueueViewsReader` (d) -- the flat, read-only queue
    views (7 methods): `autoharn_health`, `recent_ledger`, `review_gap`, `work_violations`,
    `findings_and_snags`, `question_status`, `standing_decisions`.
  - `CommissionReader` (a), defined below in THIS file rather than a fifth module -- commission
    reads plus trust verification (3 methods): `commission_trust`, `commission_trust_for_row`,
    `commissions`. Kept here (not split further out) because `tests/test_commission_trust.py`
    monkeypatches `ledger_adapter.subprocess` directly at three call sites; keeping the real
    `subprocess.run` call site physically in this file makes that monkeypatch direct rather than
    relying on `subprocess` being a cross-file singleton module object (correct in principle, but
    avoidable cleverness this refactor does not need to introduce for a test back-compat
    concern). `CommissionReader.commissions` holds a constructor-injected reference to a
    `DecompositionReader` solely to call `item_id_groups` for each commission's `item_count` --
    the one place collaborator (a) genuinely needs (b)'s result.

CRITICAL CONSTRAINT HONORED BY CONSTRUCTION: `AutoharnLedgerPort` (`ports.py`) and the route/
cosign wiring `autoharn-adapter-acl-wrap` established do NOT change -- `PostgresAutoharnLedgerReader`
keeps its same import path (`extensions.autoharn.ledger_adapter`), same no-arg constructor, and
still satisfies the Protocol as the single class `app.py`'s `AppState.autoharn_reader` and
`cosign.py`'s `AutoharnLedgerPort`-typed parameter depend on. This is also why the facade shape
(rather than `AppState` holding 4 separate reader objects) was chosen: five existing test files
this item does not touch (`test_commission_trust.py`, `test_commission_decomposition.py`,
`test_cosign_validation.py`, `test_cosign_live.py`, `test_item_view_live.py`) construct
`PostgresAutoharnLedgerReader()` directly and call methods spanning more than one collaborator on
that ONE instance -- see ledger row 1094's acceptance-criteria decision for the full reasoning.

Every method's SQL body was relocated VERBATIM (ADR-0004 minimal-touch) from the god-class into
its owning collaborator; nothing about what any endpoint returns changed. Its three PURE, no-I/O
parsers -- `parse_item_refs`, `parse_witness_refs`, `parse_resource_fields` -- now live in
`extensions.autoharn.parsers` (their own dependency-free module, so `decomposition_reader.py` can
import them with no circular import back to this file) and are re-exported here by name for
existing test/route imports that reach them via `extensions.autoharn.ledger_adapter`
(`routes.py`'s `parse_resource_fields` import; `tests/test_item_view.py`,
`tests/test_disposition.py`).

Stateless by design, exactly as `core/ledger_adapter.py` established for its own
`PostgresCoreLedgerReader`: every method takes `cfg: PanelConfig` as its own connection/config
handle, so one `PostgresAutoharnLedgerReader()` (no constructor arguments) is constructed once, at
app startup, and shared across every request (see `app.py`'s `AppState.autoharn_reader`).

DATACLASS DUPLICATION -- COLLAPSED for six of the seven (was disclosed at ledger row 979, resolved
at row 934, unchanged by this split): `ObligationNode`, `ResolvedWitness`, `ParsedItemRow`,
`ResolvedItem`, `AmbiguousItem`, `DecompositionItems` (and the `Item` alias) are defined once, in
`ports.py`, imported directly by whichever collaborator needs them -- never redefined. `WitnessFacts`
is the one exception, deliberately NOT collapsed: its real, permanent home is
`extensions/autoharn/disposition.py`; `ports.py`'s own frozen copy remains a second, pre-existing
duplicate of THAT module's `WitnessFacts`, orthogonal to this split. `decomposition_reader.py`
imports `ports.WitnessFacts` (not `disposition.WitnessFacts`) so its method bodies type-check
against the Protocol's own declared signatures -- mirroring `tests/fakes/fake_autoharn_ledger_reader.py`'s
own already-shipped precedent of doing exactly this for exactly this reason. Because
`disposition.derive_status` is typed against `disposition.WitnessFacts`, `decomposition_reader.py`
carries its own `_derive_status`, a logic-identical copy typed against `ports.WitnessFacts` instead.

VOCABULARY RELOCATION -- COMPLETED (ledger row 927/979, unchanged by this split): `ports.py` is
the sole home of `COMMISSION_TRUST_LEVELS`/`VERDICTS`/`INDEPENDENCE_VALUES`/`DISCHARGE_GRADES`/
`STATUS_VALUES`/`DISCHARGE_STATES`. `VERDICTS`/`INDEPENDENCE_VALUES` are imported by
`queue_views_reader.py` (the only collaborator that actually reads them at runtime, in
`autoharn_health`'s own return payload).

CORE-GENERIC BOUNDARY, unchanged: like the pre-split god-class, this extension's collaborators
depend on autoharn's own kernel lineage views (`ledger_current`, `review_detail`,
`work_item_current`, `review_gap`, `question_status`, the `work_edge_*` obligation views) and the
`stamp_secret` table -- none of which core (`backend/core/ledger_adapter.py`) knows about or
requires. This is still the module the extension boundary test (`tests/test_core_boundary.py`)
proves is NOT needed for the core API to serve.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from config import PanelConfig
from db import connect
from extensions.autoharn.decomposition_reader import DecompositionReader
from extensions.autoharn.parsers import (  # noqa: F401 -- re-exported, see comment below
    parse_item_refs,
    parse_resource_fields,
    parse_witness_refs,
)
from extensions.autoharn.ports import DecompositionItems, ObligationNode, ParsedItemRow, ResolvedWitness, WitnessFacts
from extensions.autoharn.queue_views_reader import QueueViewsReader
from extensions.autoharn.work_obligation_reader import WorkObligationReader

# `parse_item_refs`/`parse_resource_fields`/`parse_witness_refs` are imported above (from their
# real home, `extensions.autoharn.parsers`) purely to RE-EXPORT them under this module's own name
# for existing importers that reach them via `extensions.autoharn.ledger_adapter` rather than
# `extensions.autoharn.parsers` -- `routes.py`'s `parse_resource_fields` import;
# `tests/test_item_view.py`'s `parse_resource_fields`/`parse_witness_refs`;
# `tests/test_disposition.py`'s `parse_item_refs`. Not otherwise called in this file.

# CLAUDE.md point 11's disclosure prefix: every LAZY-mode commission's statement carries this
# marker (possibly with more clauses after a semicolon -- row 374 is a live specimen), so a
# simple prefix check is a robust, sufficient signal -- no fixed-marker-phrase parser needed
# (commission-trust-badge, row:720 assumption).
_LAZY_DISCLOSURE_PREFIX = "(vicarious transcription by the implementer"


def _commission_signing_mode(actor_name: str | None, stamp_agent: str | None, statement: str) -> str:
    """LAZY vs FULL -- mirrors autoharn's `bootstrap/templates/verify-commission.tmpl`
    `signing_mode()` exactly: FULL iff the row's actor is literally the 'commissioner' principal AND
    it carries no interception stamp (a bare-shell, no-live-session write); LAZY otherwise.
    Deliberately the SAME two-signal test that verb uses (never re-derived a second, potentially-
    diverging way -- commission-trust-badge, row:720 assumption), checked defensively against the
    CLAUDE.md point 11 disclosure prefix first, so a stamped-but-differently-actor-named row is
    never misreported FULL just because its own prose already discloses vicarious transcription."""
    if statement.lstrip().startswith(_LAZY_DISCLOSURE_PREFIX):
        return "LAZY"
    if actor_name == "commissioner" and not stamp_agent:
        return "FULL"
    return "LAZY"


class CommissionReader:
    """Owns commission-kind ledger reads and their LAZY/FULL/signed/forged/unverifiable trust
    verification -- collaborator (a) of the god-module split (see module docstring). Depends on a
    `DecompositionReader`, injected at construction, purely to compute each commission's own
    `item_count` via `item_id_groups` -- the one place this collaborator's "commission reads"
    concern genuinely needs another collaborator's decomposition-parsing result, composed rather
    than recomputed."""

    def __init__(self, items: DecompositionReader) -> None:
        self._items = items

    def commission_trust(
        self, cfg: PanelConfig, row_id: int, actor_name: str | None, stamp_agent: str | None,
        statement: str,
    ) -> dict[str, Any]:
        """`trust_level` (one of `ports.COMMISSION_TRUST_LEVELS`) + a human `trust_detail` string
        (None for the ordinary unsigned case). The common, today-universal case (every commission in
        this deployment is LAZY, none has a banked signature) costs zero subprocess calls:
        `stamp_agent`/`actor_name`/the disclosure prefix alone decide lazy-vs-full. A signature is
        only actually checked -- by shelling out to THIS deployment's own `verify-commission` verb,
        never by reimplementing GPG verification here a second time (commission-trust-badge,
        row:720 assumption) -- when a `.claude/commission-<id>.asc` is actually banked for this
        row."""
        mode = _commission_signing_mode(actor_name, stamp_agent, statement)
        asc_path = cfg.repo_root / ".claude" / f"commission-{row_id}.asc"
        if not asc_path.exists():
            return {"trust_level": mode.lower(), "trust_detail": None}

        verify_bin = cfg.repo_root / "verify-commission"
        try:
            proc = subprocess.run(
                [str(verify_bin), "--id", str(row_id), "--json"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except Exception as e:  # noqa: BLE001 -- a broken verify-commission invocation degrades to an
            # honest "can't tell" tier, never a crash and never a silently-guessed level.
            return {"trust_level": "unverifiable", "trust_detail": f"verify-commission invocation failed: {e}"}

        verdict = payload.get("verdict") or payload.get("refusal")
        detail = payload.get("detail")
        if verdict == "VERIFIED":
            return {"trust_level": "signed", "trust_detail": detail}
        if verdict == "FORGED-OR-CORRUPT":
            return {"trust_level": "forged", "trust_detail": detail}
        if verdict in ("NO-COMMITTED-KEY", "GPG-UNAVAILABLE"):
            return {"trust_level": "unverifiable", "trust_detail": detail}
        # Defensive fallback: an unrecognized payload shape (a future verify-commission verdict this
        # backend doesn't know about yet) degrades to the ledger-only signal rather than guessing.
        return {"trust_level": mode.lower(), "trust_detail": detail}

    def commission_trust_for_row(
        self, cfg: PanelConfig, row_id: int, actor_name: str | None, statement: str,
    ) -> dict[str, Any]:
        """Same computation as `commission_trust`, for a caller (the single-commission detail
        route) that already has `actor_name`/`statement` off `ledger_row()` -- which does NOT
        select `stamp_agent` (a commission-specific concern `ledger_row()` itself, shared by
        non-commission obligation/witness reads, has no reason to carry). Fetches that one extra
        column with its own tiny query rather than widening that shared method's SELECT."""
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute("SELECT stamp_agent FROM ledger_current WHERE id = %s", (row_id,))
            stamp_row = cur.fetchone()
        stamp_agent = stamp_row["stamp_agent"] if stamp_row else None
        return self.commission_trust(cfg, row_id, actor_name, stamp_agent, statement)

    def commissions(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.id, l.statement, l.ts, p.name AS actor_name, l.stamp_agent
                FROM ledger_current l LEFT JOIN principal p ON p.id = l.actor
                WHERE l.kind = 'commission'
                ORDER BY l.id
                """
            )
            rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            row_id = row["id"]
            item_count = len(self._items.item_id_groups(cfg, row_id))
            ts = row["ts"]
            trust = self.commission_trust(cfg, row_id, row["actor_name"], row["stamp_agent"], row["statement"])
            out.append(
                {
                    "row_id": row_id,
                    "statement": row["statement"],
                    "actor_name": row["actor_name"],
                    "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
                    "item_count": item_count,
                    "trust_level": trust["trust_level"],
                    "trust_detail": trust["trust_detail"],
                }
            )
        return out


class PostgresAutoharnLedgerReader:
    """The Postgres-backed `AutoharnLedgerPort` implementation. No fields of its own beyond its
    four composed collaborators, no constructor arguments -- constructed once at app startup and
    shared across every request (see `app.py`'s `AppState.autoharn_reader`), same convention
    `core/ledger_adapter.py`'s `PostgresCoreLedgerReader` established for its own sibling seam.
    Every method below is a one-line forward to exactly one collaborator (see module docstring for
    which collaborator owns which method and why)."""

    def __init__(self) -> None:
        self._decomposition = DecompositionReader()
        self._commission = CommissionReader(items=self._decomposition)
        self._work = WorkObligationReader()
        self._queues = QueueViewsReader()

    # -- collaborator (d): QueueViewsReader -----------------------------------------------------

    def autoharn_health(self, cfg: PanelConfig) -> dict[str, Any]:
        return self._queues.autoharn_health(cfg)

    def recent_ledger(self, cfg: PanelConfig, n: int) -> list[dict[str, Any]]:
        return self._queues.recent_ledger(cfg, n)

    def review_gap(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return self._queues.review_gap(cfg)

    def work_violations(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return self._queues.work_violations(cfg)

    def findings_and_snags(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return self._queues.findings_and_snags(cfg)

    def question_status(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return self._queues.question_status(cfg)

    def standing_decisions(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return self._queues.standing_decisions(cfg)

    # -- collaborator (c): WorkObligationReader -------------------------------------------------

    def work_items(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return self._work.work_items(cfg)

    def obligation_tree(self, cfg: PanelConfig, root_slug: str) -> ObligationNode | None:
        return self._work.obligation_tree(cfg, root_slug)

    # -- collaborator (b): DecompositionReader --------------------------------------------------

    def ledger_row(self, cfg: PanelConfig, row_id: int) -> dict[str, Any] | None:
        return self._decomposition.ledger_row(cfg, row_id)

    def work_item(self, cfg: PanelConfig, slug: str) -> dict[str, Any] | None:
        return self._decomposition.work_item(cfg, slug)

    def maintainer_cosigned(self, cfg: PanelConfig, target_row_id: int) -> dict[str, Any] | None:
        return self._decomposition.maintainer_cosigned(cfg, target_row_id)

    def latest_review_id(self, cfg: PanelConfig, regards: int, actor_name: str) -> int | None:
        return self._decomposition.latest_review_id(cfg, regards, actor_name)

    def resolve_witness(
        self, cfg: PanelConfig, ref_kind: str, ref: str
    ) -> tuple[WitnessFacts, dict[str, Any] | None]:
        return self._decomposition.resolve_witness(cfg, ref_kind, ref)

    def cosign_fact(self, cfg: PanelConfig, target_row_id: int) -> dict[str, Any]:
        return self._decomposition.cosign_fact(cfg, target_row_id)

    def reviews_for_row(self, cfg: PanelConfig, row_id: int) -> list[dict[str, Any]]:
        return self._decomposition.reviews_for_row(cfg, row_id)

    def resolve_item_witnesses(
        self, cfg: PanelConfig, witness_refs: tuple[tuple[str, str], ...]
    ) -> list[ResolvedWitness]:
        return self._decomposition.resolve_item_witnesses(cfg, witness_refs)

    def row_refs_text(self, cfg: PanelConfig, row_id: int) -> str | None:
        return self._decomposition.row_refs_text(cfg, row_id)

    def item_witnesses(self, cfg: PanelConfig, row_id: int) -> list[ResolvedWitness]:
        return self._decomposition.item_witnesses(cfg, row_id)

    def fetch_parsed_item_rows(self, cfg: PanelConfig, commission_row: int) -> tuple[ParsedItemRow, ...]:
        return self._decomposition.fetch_parsed_item_rows(cfg, commission_row)

    def item_id_groups(self, cfg: PanelConfig, commission_row: int) -> dict[str, tuple[int, ...]]:
        return self._decomposition.item_id_groups(cfg, commission_row)

    def decomposition_items(self, cfg: PanelConfig, commission_row: int) -> DecompositionItems:
        return self._decomposition.decomposition_items(cfg, commission_row)

    # -- collaborator (a): CommissionReader -----------------------------------------------------

    def commission_trust(
        self, cfg: PanelConfig, row_id: int, actor_name: str | None, stamp_agent: str | None,
        statement: str,
    ) -> dict[str, Any]:
        return self._commission.commission_trust(cfg, row_id, actor_name, stamp_agent, statement)

    def commission_trust_for_row(
        self, cfg: PanelConfig, row_id: int, actor_name: str | None, statement: str,
    ) -> dict[str, Any]:
        return self._commission.commission_trust_for_row(cfg, row_id, actor_name, statement)

    def commissions(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return self._commission.commissions(cfg)
