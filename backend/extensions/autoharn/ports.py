"""extensions.autoharn.ports -- the AutoharnLedgerPort seam: one `typing.Protocol` covering the
entire DB-touching public surface of `extensions/autoharn/ledger_read.py` (backend structural
audit, docs/consults/2026-07-16-backend-structural-audit/2026-07-16-backend-structural-audit.md,
finding 2/recommendation 1; ledger row 894/959; work item ledger-ports-protocols, row 931).
Interface only -- no adapter body lives here. A future `PostgresAutoharnLedgerReader` (a
downstream work item, autoharn-adapter-acl-wrap) implements this Protocol by wrapping the existing
module-level functions in `extensions/autoharn/ledger_read.py` near-mechanically, SQL moved
verbatim (ADR-0004 minimal-touch); a `FakeAutoharnLedgerReader` (autoharn-ledger-fake) implements
it in-memory for tests. Route handlers depend on this Protocol type, never on a concrete module
import (ADR-0012 P2 seam/port discipline).

ENFORCEMENT MECHANISM (the omega precedent -- docs/omega-observatory/2026-07-15-structural-reap.md
entry 2, `backend/repositories/ports.py`'s own documented technique in the maintainer's private
omega checkout): "any class matching the method signatures satisfies the Protocol," and the
Dependency Rule is made mechanically checkable by inspecting THIS file's own imports alone --
everything below comes from `typing`, the stdlib, or this project's own `config` module. Nothing
from `psycopg`, nothing from this project's `db` module. A reviewer (or a script) can verify the
boundary holds by grepping this file's import block; no framework, no DI container, is needed to
assert it.

DATACLASS DUPLICATION (disclosed, not hidden -- ledger row 979): every dataclass below
(`ObligationNode`, `WitnessFacts`, `ResolvedWitness`, `ParsedItemRow`, `ResolvedItem`,
`AmbiguousItem`, `DecompositionItems`) is a field-for-field copy of its real current definition in
`extensions/autoharn/ledger_read.py` (or, for `WitnessFacts`, `extensions/autoharn/disposition.py`
-- its actual current home) -- not an import of it. Importing any of them would mean importing a
module that imports `db`, which imports `psycopg`, defeating the import-boundary this file exists
to hold. This Protocol's own copies are the frozen CONTRACT shape; a downstream item is expected to
make one location canonical and have the other alias/import it, collapsing the duplication once the
adapter exists.

VOCABULARY RELOCATION (ledger row 927/979): the six closed vocabularies below
(`COMMISSION_TRUST_LEVELS`, `VERDICTS`, `INDEPENDENCE_VALUES`, `DISCHARGE_GRADES`,
`STATUS_VALUES`, `DISCHARGE_STATES`) are today module constants in
`extensions/autoharn/ledger_read.py`, consumed by both it and `cosign.py`. Per row 927 they belong
here as CONTRACT vocabulary, not DB logic -- defined here now, value-identical to their current
definitions. This item's own scope is additive-only (it does not touch `ledger_read.py`/
`cosign.py`), so the two locations are a deliberate, temporary duplication until the downstream
item `autoharn-adapter-acl-wrap` (row 927's own "relocate ... in item 5") physically removes the
old copies and repoints their consumers at this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from config import PanelConfig

# ---------------------------------------------------------------------------------------------
# Closed vocabularies -- contract vocabulary (ledger row 927), value-identical to the module
# constants of the same name currently in extensions/autoharn/ledger_read.py.
# ---------------------------------------------------------------------------------------------

# design/USER-GPG-TRUST-LAYER-FAQ.md's ladder LAZY < FULL < SIGNED, plus two honest failure tiers.
COMMISSION_TRUST_LEVELS: tuple[str, ...] = ("lazy", "full", "signed", "forged", "unverifiable")

# The kernel's own closed vocabularies (bootstrap/templates/led.tmpl `led review` usage text,
# kernel/lineage/s15-schema.sql's `review_detail` check constraints).
VERDICTS: tuple[str, ...] = ("attest", "attest_with_reservations", "refuse")
INDEPENDENCE_VALUES: tuple[str, ...] = ("self-review", "technical", "managerial", "financial")

# review_detail.discharge_grade's own closed vocabulary (kernel/lineage's s29/s34) -- never
# writer-supplied, computed by a trigger from the review's own stamp facts.
DISCHARGE_GRADES: tuple[str, ...] = (
    "same-principal", "same-session", "distinct-session", "distinct-deployment",
)

# A decomposition item's live disposition.
STATUS_VALUES: tuple[str, ...] = ("OPEN", "WITNESSED", "PARTIAL", "COSIGNED", "AMBIGUOUS")

# The obligation/dependency AND-tree's red/green/amber/gray coloring vocabulary (SPEC.md sec 2.3).
DISCHARGE_STATES: tuple[str, ...] = ("undischarged", "discharged", "ambiguous-partial", "superseded")


# ---------------------------------------------------------------------------------------------
# Contract dataclasses -- field-for-field copies of their real current definitions (see module
# docstring's DATACLASS DUPLICATION note for why these are copies, not imports).
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WitnessFacts:
    """The live ledger facts for ONE decomposition-item witness. Mirrors
    `extensions/autoharn/disposition.py`'s own `WitnessFacts` (that pure module's actual current
    home) field-for-field.

    ref_kind / ref: the item row's own witness identity (a work slug, or a ledger row id as text).
    exists: the ref resolved to a real work item or ledger row at all.
    substantive: the resolved fact is strong enough to WITNESS the item.
    cosign_target_row: the ledger row id a co-sign against this witness would `regards`.
    maintainer_cosigned: a live, unsuperseded `review` row exists with `regards=cosign_target_row`,
        `verdict='attest'`, actor = the configured maintainer principal.
    """
    ref_kind: str
    ref: str
    exists: bool
    substantive: bool
    cosign_target_row: int | None
    maintainer_cosigned: bool


@dataclass(frozen=True)
class ObligationNode:
    """One node of the obligation/dependency AND-tree (Autoharn.idr sec 2b/3/4; SPEC.md sec 2.3),
    rooted at the slug `obligation_tree` was called with. A DAG diamond renders as more than one
    node -- the standard, harmless way to render a DAG as a tree."""
    slug: str
    title: str | None
    kind: str  # "composite" (discharges by conjunction of children) | "leaf" (own recorded act)
    discharge_state: str  # one of DISCHARGE_STATES
    state: str
    effective_state: str
    resolution: str | None
    row_id: int | None  # this slug's own work_opened row id -- the item-view click target
    children: tuple["ObligationNode", ...]


@dataclass(frozen=True)
class ResolvedWitness:
    """One witness token (`row:<id>` or `work:<slug>`), resolved against the ledger plus its
    co-sign fact."""
    ref_kind: str
    ref: str
    resolved: dict[str, Any] | None
    cosign_target_row: int | None
    cosign: dict[str, Any]
    facts: WitnessFacts


@dataclass(frozen=True)
class ParsedItemRow:
    """One decomposition-item ledger row, parsed under either convention this deployment's
    history carries (the PoC-era `panel-item:` token grammar, or the current bare `work_opened` +
    `row:<commission>` convention)."""
    row_id: int
    item_id: str
    witness_refs: tuple[tuple[str, str], ...]
    statement: str
    actor_name: str | None
    ts: str


@dataclass(frozen=True)
class ResolvedItem:
    """A decomposition item whose `item_id` resolved to exactly one ledger row."""
    item_id: str
    row_id: int
    label: str
    actor_name: str | None
    ts: str
    status: str  # one of STATUS_VALUES (never "AMBIGUOUS" -- that is AmbiguousItem's own case)
    item_cosign: dict[str, Any]
    witnesses: list[ResolvedWitness]


@dataclass(frozen=True)
class AmbiguousItem:
    """A decomposition item whose `item_id` collided across two or more ledger rows -- the
    identity-collision hazard SPEC.md sec 3 names; carried as data, never silently resolved to a
    winner."""
    item_id: str
    candidate_row_ids: tuple[int, ...]


Item = ResolvedItem | AmbiguousItem


@dataclass(frozen=True)
class DecompositionItems:
    """One commission row's full set of decomposition items, each either resolved or flagged
    ambiguous."""
    commission_row: int
    items: tuple[Item, ...]


class AutoharnLedgerPort(Protocol):
    """The DB-touching public surface of `extensions/autoharn/ledger_read.py`, as one seam
    (`ledger-ports-protocols`'s own "2 Protocols, not 6" mandate -- one per existing core/autoharn
    extension boundary, SPEC.md sec 4). Every method below takes `cfg: PanelConfig` as its own
    connection/config handle, exactly as the module-level functions it mirrors do today.

    NOT on this Protocol -- and deliberately so (ledger row 981): `parse_item_refs`,
    `parse_witness_refs`, and `parse_resource_fields`, the three PURE functions in
    `extensions/autoharn/ledger_read.py` that take no `cfg` and perform zero I/O. Forcing
    well-factored pure code onto a DB-swapping interface buys nothing -- they stay plain functions,
    callable directly by whatever adapter or test needs them, with no fake required to exercise
    them. `commission_trust`/`commission_trust_for_row` ARE on this Protocol despite issuing no SQL
    (they shell out to `verify-commission` and check a filesystem path instead) -- real,
    non-deterministic I/O a test double needs to fake exactly as much as a DB call, unlike the three
    excluded parsers.
    """

    def autoharn_health(self, cfg: PanelConfig) -> dict[str, Any]:
        """The autoharn-specific slice of `GET /api/health`: whether `stamp_secret` is armed, plus
        the `VERDICTS`/`INDEPENDENCE_VALUES` vocabularies for the frontend to render against."""
        ...

    def recent_ledger(self, cfg: PanelConfig, n: int) -> list[dict[str, Any]]:
        """The `n` most recent CURRENT ledger rows, newest first. Raises `ValueError` if
        `n < 1`."""
        ...

    def work_items(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """Every work item's current state (`work_item_current`), each augmented with its own
        `blocked_by` list (antecedent slugs off `work_edge_blocks_close`)."""
        ...

    def review_gap(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """The kernel's `review_gap` view (rows awaiting an independent co-sign), each with its
        `actor`/`assigned_by` principal ids resolved to names alongside the bare ids."""
        ...

    def work_violations(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """The kernel's `work_item_violations` view, filtered to violations with no
        `work_violation_disposition` yet -- every currently-live, undisposed decomposition-tree
        violation."""
        ...

    def obligation_tree(self, cfg: PanelConfig, root_slug: str) -> ObligationNode | None:
        """The obligation/dependency AND-tree rooted at `root_slug`, as a real recursive tree.
        Returns `None` if `root_slug` was never opened."""
        ...

    def findings_and_snags(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """`finding`/`snag` kind rows, newest first, one combined view (`kind` still selected so
        the frontend can badge the two apart)."""
        ...

    def question_status(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """The kernel's `question_status` view, each row joined to its own question `statement`
        text."""
        ...

    def standing_decisions(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """The kernel's `standing_decisions` view -- every in-force `decision`-kind row carrying a
        writer-supplied `grade`."""
        ...

    def ledger_row(self, cfg: PanelConfig, row_id: int) -> dict[str, Any] | None:
        """One CURRENT ledger row by id, or `None` if it does not exist (or is not current)."""
        ...

    def work_item(self, cfg: PanelConfig, slug: str) -> dict[str, Any] | None:
        """One work item's current state plus its own `closed_row_id` (the `work_closed` row id
        that closed it, if any). `None` if `slug` was never opened."""
        ...

    def maintainer_cosigned(self, cfg: PanelConfig, target_row_id: int) -> dict[str, Any] | None:
        """The most recent live `attest` review by the configured maintainer principal regarding
        `target_row_id`, or `None` if no such review exists."""
        ...

    def latest_review_id(self, cfg: PanelConfig, regards: int, actor_name: str) -> int | None:
        """The most recent live review row id by `actor_name` regarding `regards`, or `None`."""
        ...

    def resolve_witness(
        self, cfg: PanelConfig, ref_kind: str, ref: str
    ) -> tuple[WitnessFacts, dict[str, Any] | None]:
        """Resolves one witness token (`ref_kind` is `"work"` or `"row"`) against the ledger,
        returning its `WitnessFacts` plus the resolved record (`work_item`/`ledger_row`'s own
        payload), or `(facts-with-exists=False, None)` if it does not resolve. Raises `ValueError`
        for an unknown `ref_kind`."""
        ...

    def cosign_fact(self, cfg: PanelConfig, target_row_id: int) -> dict[str, Any]:
        """`{cosigned, by, review_id, verdict}` -- whether `target_row_id` has been
        maintainer-cosigned, and by whom."""
        ...

    def reviews_for_row(self, cfg: PanelConfig, row_id: int) -> list[dict[str, Any]]:
        """Every live `review` row regarding `row_id`, joined to its `review_detail` payload
        (`verdict`, `independence`, `discharge_grade`, `basis`) -- the item view's full
        review/co-sign history, not narrowed to maintainer/attest."""
        ...

    def resolve_item_witnesses(
        self, cfg: PanelConfig, witness_refs: tuple[tuple[str, str], ...]
    ) -> list[ResolvedWitness]:
        """`resolve_witness` plus `cosign_fact`, applied to each `(ref_kind, ref)` pair in
        `witness_refs`, in order."""
        ...

    def row_refs_text(self, cfg: PanelConfig, row_id: int) -> str | None:
        """The raw `refs` text of one CURRENT ledger row, or `None` if it does not exist."""
        ...

    def item_witnesses(self, cfg: PanelConfig, row_id: int) -> list[ResolvedWitness]:
        """`row_id`'s own `refs` text, parsed generically (`row:`/`work:` tokens) and resolved the
        same way a decomposition item's witnesses are."""
        ...

    def fetch_parsed_item_rows(
        self, cfg: PanelConfig, commission_row: int
    ) -> tuple[ParsedItemRow, ...]:
        """Decomposition items for `commission_row`, read under both conventions this deployment's
        history carries: the PoC-era `panel-item:<commission_row>:<item_id>` token on a `note` row,
        and the current bare `work_opened` row carrying a `row:<commission_row>` token."""
        ...

    def item_id_groups(self, cfg: PanelConfig, commission_row: int) -> dict[str, tuple[int, ...]]:
        """`item_id -> (row_id, ...)` for `commission_row`'s decomposition items -- a group of size
        >= 2 is the identity-collision signal `AmbiguousItem` carries."""
        ...

    def commission_trust(
        self, cfg: PanelConfig, row_id: int, actor_name: str | None, stamp_agent: str | None,
        statement: str,
    ) -> dict[str, Any]:
        """`{trust_level, trust_detail}` -- LAZY vs FULL signing mode off the row's own actor/
        stamp/statement-prefix facts, escalated to signed/forged/unverifiable by shelling out to
        this deployment's own `verify-commission` verb ONLY when a `.claude/commission-<id>.asc`
        is actually banked for `row_id`. Never reimplements GPG verification itself."""
        ...

    def commission_trust_for_row(
        self, cfg: PanelConfig, row_id: int, actor_name: str | None, statement: str,
    ) -> dict[str, Any]:
        """Same computation as `commission_trust`, for a caller that already has `actor_name`/
        `statement` off `ledger_row()` and needs only the one extra `stamp_agent` column fetched
        for it."""
        ...

    def commissions(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """Every `commission`-kind row, each augmented with its own decomposition `item_count` and
        `commission_trust` payload."""
        ...

    def decomposition_items(self, cfg: PanelConfig, commission_row: int) -> DecompositionItems:
        """`commission_row`'s decomposition items, each resolved to a `ResolvedItem` (with its
        witnesses and live `status`) or flagged an `AmbiguousItem` on an `item_id` collision."""
        ...
