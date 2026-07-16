"""tests.fakes.fake_autoharn_ledger_reader -- `FakeAutoharnLedgerReader`, a plain in-memory
Python class structurally satisfying `extensions.autoharn.ports.AutoharnLedgerPort` (landed
619b95d; 25 methods), for tests that need real obligation-tree/decomposition-grouping/witness-
resolution semantics without a live Postgres connection (work item autoharn-ledger-fake, ledger
row 937 -- the highest-risk item in the backend-remediation decomposition, per that row's own
title: every downstream coverage test validates against THIS fake, so an unfaithful fake would
let those tests validate a lie).

FIDELITY, not stubbing: every method below is a genuine re-derivation of its real counterpart in
`extensions/autoharn/ledger_read.py`, computed from this class's own in-memory store (seeded via
the `add_*`/`open_work_item`/`seed_*` builder methods below) the same way the real function
computes it from SQL -- never a hardcoded per-test-case return value. The three parts the work
item's own brief named as highest-risk get that treatment explicitly:
  - `obligation_tree`: the SAME recursive `build()`/`visiting`-guard walk and
    `_obligation_discharge_state` classification as `ledger_read.obligation_tree`, sourcing
    adjacency/composite/limbo facts from this class's own dicts/sets instead of
    `_work_obligation_adjacency`/`_work_composite_slugs`/etc.'s SQL.
  - `decomposition_items`/`item_id_groups`: `fetch_parsed_item_rows` re-derives BOTH refs
    conventions (legacy `panel-item:` note tokens and the current `work_opened` `row:` token)
    from raw in-memory ledger rows, then feeds real `(item_id, row_id)` pairs into
    `extensions.autoharn.disposition.group_item_rows` (imported directly -- that module is pure,
    zero transitive DB-driver dependency, see IMPORT BOUNDARY below) -- a genuine collision in the
    in-memory data produces a genuine `AmbiguousItem`, never an injected one.
  - `resolve_witness`: the same two-branch (`work` / `row`) multi-hop resolution as
    `ledger_read.resolve_witness`, chaining through this class's own `work_item()` ->
    `closed_row_id` -> `maintainer_cosigned()` lookups exactly as the real function chains
    through the DB.

IMPORT BOUNDARY (mirrors `ports.py`'s own ENFORCEMENT MECHANISM paragraph): this file imports
only `re`/`typing`/`config`/`extensions.autoharn.ports`/`extensions.autoharn.disposition` --
nothing from this project's `db` module (or the Postgres driver package it wraps), and
deliberately NOT from `extensions.autoharn.ledger_read` itself (importing that module would
transitively import `db` and its driver -- reintroducing exactly the dependency this fake
exists to let tests avoid, even though the driver package's own name would not appear anywhere
in this file's own text). A reviewer (or `grep`) can verify the boundary holds by checking this
file's import block alone.

DUPLICATED PURE HELPERS (disclosed, not hidden -- same convention `ports.py` itself uses for its
DATACLASS DUPLICATION/VOCABULARY RELOCATION): `_PANEL_ITEM_TOKEN_RE`/`_ROW_TOKEN_RE`/
`_WORK_TOKEN_RE`/`_parse_item_refs`/`_parse_witness_refs`/`_row_token_matches` are byte-for-byte
copies of `ledger_read.py`'s own pure regex-token parsers (excluded from the Protocol itself
per that module's own docstring, precisely because they are pure and any caller -- including a
fake -- can call them directly; duplicated rather than imported here ONLY because the real
copies live in the driver-importing module). `_obligation_discharge_state` and
`_commission_signing_mode` are likewise logic-identical copies of their `ledger_read.py`
namesakes, needed by `obligation_tree`/`commission_trust` here. `_derive_status` is a
logic-identical copy of `disposition.derive_status`, duplicated ONLY to type its `witnesses`
parameter against `ports.WitnessFacts` (the frozen contract dataclass this file's public methods
return) rather than `disposition.WitnessFacts` (a distinct, field-identical class) -- avoiding a
cross-module type mismatch under mypy while still calling the pure, real `group_item_rows`
(imported, not duplicated -- it takes plain `(str, int)` tuples, no dataclass-typing conflict).
"""
from __future__ import annotations

import re
from typing import Any

from config import PanelConfig
from extensions.autoharn.disposition import group_item_rows
from extensions.autoharn.ports import (
    AmbiguousItem,
    DecompositionItems,
    INDEPENDENCE_VALUES,
    Item,
    ObligationNode,
    ParsedItemRow,
    ResolvedItem,
    ResolvedWitness,
    VERDICTS,
    WitnessFacts,
)

# ---------------------------------------------------------------------------------------------
# Duplicated pure helpers -- see module docstring's DUPLICATED PURE HELPERS note.
# ---------------------------------------------------------------------------------------------

_PANEL_ITEM_TOKEN_RE = re.compile(r"^panel-item:(?P<cid>\d+):(?P<iid>[A-Za-z0-9_-]+)$")
_ROW_TOKEN_RE = re.compile(r"^row:(?P<id>\d+)$")
_WORK_TOKEN_RE = re.compile(r"^work:(?P<slug>[A-Za-z0-9_.-]+)$")

_LAZY_DISCLOSURE_PREFIX = "(vicarious transcription by the implementer"


def _parse_witness_refs(refs_text: str | None) -> list[tuple[str, str]]:
    """Verbatim copy of `ledger_read.parse_witness_refs`."""
    out: list[tuple[str, str]] = []
    for tok in (refs_text or "").split():
        m = _ROW_TOKEN_RE.match(tok)
        if m:
            out.append(("row", m.group("id")))
            continue
        m = _WORK_TOKEN_RE.match(tok)
        if m:
            out.append(("work", m.group("slug")))
    return out


def _parse_item_refs(refs_text: str | None, commission_row: int) -> tuple[str | None, list[tuple[str, str]]]:
    """Verbatim copy of `ledger_read.parse_item_refs`."""
    tokens = (refs_text or "").split()
    matching_item_ids: list[str] = []
    witness_refs: list[tuple[str, str]] = []
    wanted_cid = str(commission_row)
    for tok in tokens:
        m = _PANEL_ITEM_TOKEN_RE.match(tok)
        if m:
            if m.group("cid") == wanted_cid:
                matching_item_ids.append(m.group("iid"))
            continue
        m = _ROW_TOKEN_RE.match(tok)
        if m:
            witness_refs.append(("row", m.group("id")))
            continue
        m = _WORK_TOKEN_RE.match(tok)
        if m:
            witness_refs.append(("work", m.group("slug")))
            continue
    if len(matching_item_ids) != 1:
        return None, []
    return matching_item_ids[0], witness_refs


def _row_token_matches(refs_text: str | None, commission_row: int) -> bool:
    """Verbatim copy of `ledger_read._row_token_matches`."""
    wanted = str(commission_row)
    for tok in (refs_text or "").split():
        m = _ROW_TOKEN_RE.match(tok)
        if m and m.group("id") == wanted:
            return True
    return False


def _obligation_discharge_state(
    effective_state: str, resolution: str | None, *, deferred_undischarged: bool, tree_defeated: bool,
) -> str:
    """Logic-identical copy of `ledger_read._obligation_discharge_state`."""
    if resolution == "superseded":
        return "superseded"
    if tree_defeated or deferred_undischarged:
        return "ambiguous-partial"
    if effective_state in ("closed", "discharged-by-obligations"):
        return "discharged"
    return "undischarged"


def _commission_signing_mode(actor_name: str | None, stamp_agent: str | None, statement: str) -> str:
    """Logic-identical copy of `ledger_read._commission_signing_mode`."""
    if statement.lstrip().startswith(_LAZY_DISCLOSURE_PREFIX):
        return "LAZY"
    if actor_name == "commissioner" and not stamp_agent:
        return "FULL"
    return "LAZY"


def _derive_status(item_row_cosigned: bool, witnesses: list[WitnessFacts]) -> str:
    """Logic-identical copy of `disposition.derive_status`, typed against `ports.WitnessFacts`
    (see module docstring)."""
    if item_row_cosigned:
        return "COSIGNED"
    substantive = [w for w in witnesses if w.exists and w.substantive]
    if not substantive:
        return "OPEN"
    cosigned = [w for w in substantive if w.maintainer_cosigned]
    if len(cosigned) == len(substantive):
        return "COSIGNED"
    if cosigned:
        return "PARTIAL"
    return "WITNESSED"


class FakeAutoharnLedgerReader:
    """In-memory `AutoharnLedgerPort`. No inheritance from the `Protocol` (deliberately -- see
    `ports.py`'s own ENFORCEMENT MECHANISM note: "any class matching the method signatures
    satisfies the Protocol"; a test asserting
    `reader: AutoharnLedgerPort = FakeAutoharnLedgerReader()` is the proof, structural not
    nominal). Construct empty, then build a scenario with the `add_*`/`open_work_item`/`seed_*`
    methods below before calling any Protocol method.
    """

    def __init__(self) -> None:
        self._rows: dict[int, dict[str, Any]] = {}
        self._review_detail: dict[int, dict[str, Any]] = {}
        self._work_items: dict[str, dict[str, Any]] = {}
        self._composite_slugs: set[str] = set()
        self._obligation_adjacency: dict[str, list[str]] = {}
        self._blocks_close: dict[str, list[str]] = {}
        self._deferred_undischarged_slugs: set[str] = set()
        self._tree_defeated_slugs: set[str] = set()
        self._stamp_secret_armed: bool = True
        self._banked_signatures: dict[int, dict[str, Any]] = {}
        self._review_gap_rows: list[dict[str, Any]] = []
        self._work_violations_rows: list[dict[str, Any]] = []
        self._question_status_rows: list[dict[str, Any]] = []
        self._standing_decisions_rows: list[dict[str, Any]] = []
        self._next_id = 1

    # -----------------------------------------------------------------------------------------
    # Scenario builders -- the fake's own "seed data" API, not part of the Protocol.
    # -----------------------------------------------------------------------------------------

    def _alloc_id(self, explicit: int | None) -> int:
        if explicit is not None:
            if explicit >= self._next_id:
                self._next_id = explicit + 1
            return explicit
        rid = self._next_id
        self._next_id += 1
        return rid

    def add_row(
        self, kind: str, statement: str, *, id: int | None = None, actor_name: str | None = None,
        ts: str = "2026-01-01T00:00:00+00:00", stamp_verified: bool = True, refs: str | None = None,
        work_slug: str | None = None, stamp_agent: str | None = None, regards: int | None = None,
        work_discharge: str | None = None,
    ) -> int:
        """A raw ledger row -- the source of truth every read method below queries against, same
        role `ledger_current` plays for the real reader."""
        rid = self._alloc_id(id)
        self._rows[rid] = {
            "id": rid, "kind": kind, "statement": statement, "actor_name": actor_name, "ts": ts,
            "stamp_verified": stamp_verified, "refs": refs, "work_slug": work_slug,
            "stamp_agent": stamp_agent, "regards": regards, "work_discharge": work_discharge,
        }
        return rid

    def open_work_item(
        self, slug: str, title: str, *, id: int | None = None, state: str = "open",
        effective_state: str | None = None, resolution: str | None = None, parent_slug: str | None = None,
        claimant_name: str | None = None, witness: str | None = None, composite: bool = False,
        refs: str | None = None, actor_name: str | None = None, ts: str = "2026-01-01T00:00:00+00:00",
    ) -> int:
        """A `work_opened` ledger act plus its `work_item_current` projection -- mirrors how a
        work item only ever exists in the real system via its own opening act."""
        rid = self.add_row(
            "work_opened", title, id=id, actor_name=actor_name, ts=ts, refs=refs, work_slug=slug,
            work_discharge="composite" if composite else None,
        )
        self._work_items[slug] = {
            "title": title, "state": state, "effective_state": effective_state or state,
            "resolution": resolution, "parent_slug": parent_slug, "claimant_name": claimant_name,
            "witness": witness,
        }
        if composite:
            self._composite_slugs.add(slug)
        return rid

    def close_work_item(
        self, slug: str, *, id: int | None = None, actor_name: str | None = None,
        ts: str = "2026-01-02T00:00:00+00:00", refs: str | None = None, resolution: str | None = None,
        new_state: str = "closed", new_effective_state: str = "closed",
    ) -> int:
        rid = self.add_row("work_closed", f"work_closed: {slug}", id=id, actor_name=actor_name, ts=ts,
                            refs=refs, work_slug=slug)
        wi = self._work_items[slug]
        wi["state"] = new_state
        wi["effective_state"] = new_effective_state
        if resolution is not None:
            wi["resolution"] = resolution
        return rid

    def add_obligation_edge(self, from_slug: str, to_slug: str) -> None:
        """One `work_edge_obligation` edge (already in-force, already union'd -- this fake does
        not re-derive parent/blocks-close union, same as the real reader reads the ONE already-
        unioned view rather than re-deriving it)."""
        self._obligation_adjacency.setdefault(from_slug, []).append(to_slug)

    def add_blocks_close_edge(self, dependent_slug: str, antecedent_slug: str) -> None:
        self._blocks_close.setdefault(dependent_slug, []).append(antecedent_slug)

    def mark_deferred_undischarged(self, slug: str) -> None:
        self._deferred_undischarged_slugs.add(slug)

    def mark_tree_defeated(self, slug: str) -> None:
        self._tree_defeated_slugs.add(slug)

    def add_review(
        self, regards: int, *, verdict: str, actor_name: str, id: int | None = None,
        independence: str | None = None, discharge_grade: str | None = None,
        ts: str = "2026-01-03T00:00:00+00:00", basis: str | None = None,
    ) -> int:
        rid = self.add_row("review", basis or f"review of row {regards}", id=id, actor_name=actor_name,
                            ts=ts, regards=regards)
        self._review_detail[rid] = {
            "verdict": verdict, "independence": independence, "discharge_grade": discharge_grade,
            "basis": basis,
        }
        return rid

    def add_panel_item_note(
        self, commission_row: int, item_id: str, statement: str, *, id: int | None = None,
        actor_name: str | None = None, ts: str = "2026-01-01T00:00:00+00:00", extra_refs: str = "",
    ) -> int:
        """The PoC-era `panel-item:<commission_row>:<item_id>` convention, on a `note` row --
        two calls with the same `commission_row`/`item_id` and different `id`s is the genuine
        way to seed an `AmbiguousItem` collision (`work_opened` slugs are unique by kernel
        construction; this legacy convention carries no such constraint, exactly like the real
        deployment's own historical data)."""
        refs = f"panel-item:{commission_row}:{item_id} {extra_refs}".strip()
        return self.add_row("note", statement, id=id, actor_name=actor_name, ts=ts, refs=refs)

    def add_commission(
        self, statement: str, *, id: int | None = None, actor_name: str | None = None,
        ts: str = "2026-01-01T00:00:00+00:00", stamp_agent: str | None = None,
    ) -> int:
        return self.add_row("commission", statement, id=id, actor_name=actor_name, ts=ts,
                             stamp_agent=stamp_agent)

    def seed_review_gap(self, rows: list[dict[str, Any]]) -> None:
        self._review_gap_rows = list(rows)

    def seed_work_violations(self, rows: list[dict[str, Any]]) -> None:
        self._work_violations_rows = list(rows)

    def seed_question_status(self, rows: list[dict[str, Any]]) -> None:
        self._question_status_rows = list(rows)

    def seed_standing_decisions(self, rows: list[dict[str, Any]]) -> None:
        self._standing_decisions_rows = list(rows)

    def set_stamp_secret_armed(self, armed: bool) -> None:
        self._stamp_secret_armed = armed

    def bank_signature(self, row_id: int, verdict: str, detail: str | None = None) -> None:
        """The in-memory substitute for a banked `.claude/commission-<id>.asc` plus its
        `verify-commission --json` verdict -- `commission_trust` below checks this dict instead
        of the filesystem + subprocess the real function shells out to, per `ports.py`'s own
        note that `commission_trust` "issues no SQL" but is still real I/O a fake must stand in
        for."""
        self._banked_signatures[row_id] = {"verdict": verdict, "detail": detail}

    # -----------------------------------------------------------------------------------------
    # AutoharnLedgerPort -- 25 methods, each a genuine re-derivation off the store above.
    # -----------------------------------------------------------------------------------------

    def autoharn_health(self, cfg: PanelConfig) -> dict[str, Any]:
        return {
            "stamp_secret_armed": self._stamp_secret_armed,
            "verdicts": list(VERDICTS),
            "independence_values": list(INDEPENDENCE_VALUES),
        }

    def _project_recent_row(self, row_id: int) -> dict[str, Any]:
        r = self._rows[row_id]
        return {
            "id": r["id"], "kind": r["kind"], "statement": r["statement"], "actor_name": r["actor_name"],
            "ts": r["ts"], "stamp_verified": r["stamp_verified"],
        }

    def recent_ledger(self, cfg: PanelConfig, n: int) -> list[dict[str, Any]]:
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")
        ids = sorted(self._rows, reverse=True)[:n]
        return [self._project_recent_row(i) for i in ids]

    def work_items(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for slug in sorted(self._work_items):
            wi = self._work_items[slug]
            out.append({
                "slug": slug, "title": wi["title"], "state": wi["state"],
                "effective_state": wi["effective_state"], "resolution": wi["resolution"],
                "witness": wi["witness"], "parent_slug": wi["parent_slug"],
                "claimant_name": wi["claimant_name"],
                "blocked_by": list(self._blocks_close.get(slug, [])),
            })
        return out

    def review_gap(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return [dict(r) for r in sorted(self._review_gap_rows, key=lambda r: r["id"])]

    def work_violations(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return [
            dict(r) for r in
            sorted(self._work_violations_rows, key=lambda r: (r["target_id"], r["violation"], r["slug"]))
        ]

    def _work_opened_row_id(self, slug: str) -> int | None:
        ids = [rid for rid, r in self._rows.items() if r["kind"] == "work_opened" and r["work_slug"] == slug]
        return min(ids) if ids else None

    def obligation_tree(self, cfg: PanelConfig, root_slug: str) -> ObligationNode | None:
        if root_slug not in self._work_items:
            return None

        def build(slug: str, visiting: frozenset[str]) -> ObligationNode:
            wi = self._work_items.get(slug)
            row_id = self._work_opened_row_id(slug)
            if wi is None:
                # Mirrors ledger_read.obligation_tree's own defensive stub for an edge reaching
                # a slug with no work_item_current row -- should be unreachable, degrades
                # honestly rather than KeyError'ing.
                return ObligationNode(slug=slug, title=None, kind="leaf", discharge_state="undischarged",
                                       state="open", effective_state="open", resolution=None,
                                       row_id=row_id, children=())
            state = wi["state"]
            effective_state = wi["effective_state"]
            resolution = wi["resolution"]
            discharge_state = _obligation_discharge_state(
                effective_state, resolution,
                deferred_undischarged=slug in self._deferred_undischarged_slugs,
                tree_defeated=slug in self._tree_defeated_slugs,
            )
            kind = "composite" if slug in self._composite_slugs else "leaf"
            if slug in visiting:
                return ObligationNode(slug=slug, title=wi["title"], kind=kind,
                                       discharge_state=discharge_state, state=state,
                                       effective_state=effective_state, resolution=resolution,
                                       row_id=row_id, children=())
            children = tuple(
                build(child, visiting | {slug}) for child in self._obligation_adjacency.get(slug, [])
            )
            return ObligationNode(slug=slug, title=wi["title"], kind=kind, discharge_state=discharge_state,
                                   state=state, effective_state=effective_state, resolution=resolution,
                                   row_id=row_id, children=children)

        return build(root_slug, frozenset())

    def findings_and_snags(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        ids = sorted((i for i, r in self._rows.items() if r["kind"] in ("finding", "snag")), reverse=True)
        return [self._project_recent_row(i) for i in ids]

    def question_status(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return [dict(r) for r in sorted(self._question_status_rows, key=lambda r: r["question_id"])]

    def standing_decisions(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        return [dict(r) for r in sorted(self._standing_decisions_rows, key=lambda r: r["id"])]

    def ledger_row(self, cfg: PanelConfig, row_id: int) -> dict[str, Any] | None:
        r = self._rows.get(row_id)
        if r is None:
            return None
        return {"id": r["id"], "kind": r["kind"], "statement": r["statement"], "ts": r["ts"],
                "actor_name": r["actor_name"]}

    def work_item(self, cfg: PanelConfig, slug: str) -> dict[str, Any] | None:
        wi = self._work_items.get(slug)
        if wi is None:
            return None
        closed_ids = [rid for rid, r in self._rows.items()
                      if r["kind"] == "work_closed" and r["work_slug"] == slug]
        closed_row_id = max(closed_ids) if closed_ids else None
        return {
            "slug": slug, "title": wi["title"], "state": wi["state"],
            "effective_state": wi["effective_state"], "resolution": wi["resolution"],
            "witness": wi["witness"], "parent_slug": wi["parent_slug"],
            "claimant_name": wi["claimant_name"], "closed_row_id": closed_row_id,
        }

    def maintainer_cosigned(self, cfg: PanelConfig, target_row_id: int) -> dict[str, Any] | None:
        candidates = [
            rid for rid, r in self._rows.items()
            if r["kind"] == "review" and r["regards"] == target_row_id
            and self._review_detail.get(rid, {}).get("verdict") == "attest"
            and r["actor_name"] == cfg.maintainer_principal
        ]
        if not candidates:
            return None
        rid = max(candidates)
        r = self._rows[rid]
        d = self._review_detail[rid]
        return {"review_id": rid, "verdict": d["verdict"], "actor_name": r["actor_name"]}

    def latest_review_id(self, cfg: PanelConfig, regards: int, actor_name: str) -> int | None:
        candidates = [
            rid for rid, r in self._rows.items()
            if r["kind"] == "review" and r["regards"] == regards and r["actor_name"] == actor_name
        ]
        return max(candidates) if candidates else None

    def resolve_witness(
        self, cfg: PanelConfig, ref_kind: str, ref: str,
    ) -> tuple[WitnessFacts, dict[str, Any] | None]:
        if ref_kind == "work":
            resolved = self.work_item(cfg, ref)
            if resolved is None:
                return WitnessFacts(ref_kind, ref, exists=False, substantive=False,
                                     cosign_target_row=None, maintainer_cosigned=False), None
            closed_row_id = resolved.get("closed_row_id")
            substantive = resolved.get("state") == "closed"
            cosigned = False
            if closed_row_id is not None:
                # Hop 2: the work item's own closing act's cosign fact.
                cosigned = self.maintainer_cosigned(cfg, closed_row_id) is not None
            facts = WitnessFacts(
                ref_kind, ref, exists=True, substantive=substantive,
                cosign_target_row=closed_row_id, maintainer_cosigned=cosigned,
            )
            return facts, resolved
        if ref_kind == "row":
            try:
                row_id = int(ref)
            except ValueError:
                return WitnessFacts(ref_kind, ref, exists=False, substantive=False,
                                     cosign_target_row=None, maintainer_cosigned=False), None
            resolved = self.ledger_row(cfg, row_id)
            if resolved is None:
                return WitnessFacts(ref_kind, ref, exists=False, substantive=False,
                                     cosign_target_row=None, maintainer_cosigned=False), None
            cosigned = self.maintainer_cosigned(cfg, row_id) is not None
            facts = WitnessFacts(
                ref_kind, ref, exists=True, substantive=True,
                cosign_target_row=row_id, maintainer_cosigned=cosigned,
            )
            return facts, resolved
        raise ValueError(f"unknown ref_kind {ref_kind!r} (expected 'work' or 'row')")

    def cosign_fact(self, cfg: PanelConfig, target_row_id: int) -> dict[str, Any]:
        disc = self.maintainer_cosigned(cfg, target_row_id)
        if disc:
            return {"cosigned": True, "by": disc["actor_name"], "review_id": disc["review_id"],
                     "verdict": disc["verdict"]}
        return {"cosigned": False, "by": None, "review_id": None, "verdict": None}

    def reviews_for_row(self, cfg: PanelConfig, row_id: int) -> list[dict[str, Any]]:
        ids = sorted(rid for rid, r in self._rows.items() if r["kind"] == "review" and r["regards"] == row_id)
        out: list[dict[str, Any]] = []
        for rid in ids:
            r = self._rows[rid]
            d = self._review_detail.get(rid, {})
            out.append({
                "review_id": rid, "ts": r["ts"], "actor_name": r["actor_name"],
                "verdict": d.get("verdict"), "independence": d.get("independence"),
                "discharge_grade": d.get("discharge_grade"), "basis": d.get("basis"),
            })
        return out

    def resolve_item_witnesses(
        self, cfg: PanelConfig, witness_refs: tuple[tuple[str, str], ...],
    ) -> list[ResolvedWitness]:
        out: list[ResolvedWitness] = []
        for ref_kind, ref in witness_refs:
            facts, resolved = self.resolve_witness(cfg, ref_kind, ref)
            cosign_info: dict[str, Any] = {"cosigned": False, "by": None, "review_id": None, "verdict": None}
            if facts.cosign_target_row is not None:
                cosign_info = self.cosign_fact(cfg, facts.cosign_target_row)
            out.append(ResolvedWitness(
                ref_kind=ref_kind, ref=ref, resolved=resolved,
                cosign_target_row=facts.cosign_target_row, cosign=cosign_info, facts=facts,
            ))
        return out

    def row_refs_text(self, cfg: PanelConfig, row_id: int) -> str | None:
        r = self._rows.get(row_id)
        return r["refs"] if r else None

    def item_witnesses(self, cfg: PanelConfig, row_id: int) -> list[ResolvedWitness]:
        witness_refs = tuple(_parse_witness_refs(self.row_refs_text(cfg, row_id)))
        return self.resolve_item_witnesses(cfg, witness_refs)

    def fetch_parsed_item_rows(self, cfg: PanelConfig, commission_row: int) -> tuple[ParsedItemRow, ...]:
        out: list[ParsedItemRow] = []
        for rid in sorted(self._rows):
            r = self._rows[rid]
            if r["kind"] != "note":
                continue
            item_id, witness_refs = _parse_item_refs(r["refs"], commission_row)
            if item_id is None:
                continue
            out.append(ParsedItemRow(row_id=rid, item_id=item_id, witness_refs=tuple(witness_refs),
                                      statement=r["statement"], actor_name=r["actor_name"], ts=r["ts"]))
        for rid in sorted(self._rows):
            r = self._rows[rid]
            if r["kind"] != "work_opened":
                continue
            if not _row_token_matches(r["refs"], commission_row):
                continue
            slug = r["work_slug"]
            if not slug:
                continue
            other_witnesses = [
                (k, v) for k, v in _parse_witness_refs(r["refs"])
                if not (k == "row" and v == str(commission_row))
            ]
            witness_refs2: list[tuple[str, str]] = [("work", slug), *other_witnesses]
            out.append(ParsedItemRow(row_id=rid, item_id=slug, witness_refs=tuple(witness_refs2),
                                      statement=r["statement"], actor_name=r["actor_name"], ts=r["ts"]))
        return tuple(out)

    def item_id_groups(self, cfg: PanelConfig, commission_row: int) -> dict[str, tuple[int, ...]]:
        return group_item_rows(
            tuple((r.item_id, r.row_id) for r in self.fetch_parsed_item_rows(cfg, commission_row))
        )

    def commission_trust(
        self, cfg: PanelConfig, row_id: int, actor_name: str | None, stamp_agent: str | None,
        statement: str,
    ) -> dict[str, Any]:
        mode = _commission_signing_mode(actor_name, stamp_agent, statement)
        banked = self._banked_signatures.get(row_id)
        if banked is None:
            return {"trust_level": mode.lower(), "trust_detail": None}
        verdict = banked.get("verdict")
        detail = banked.get("detail")
        if verdict == "VERIFIED":
            return {"trust_level": "signed", "trust_detail": detail}
        if verdict == "FORGED-OR-CORRUPT":
            return {"trust_level": "forged", "trust_detail": detail}
        if verdict in ("NO-COMMITTED-KEY", "GPG-UNAVAILABLE"):
            return {"trust_level": "unverifiable", "trust_detail": detail}
        return {"trust_level": mode.lower(), "trust_detail": detail}

    def commission_trust_for_row(
        self, cfg: PanelConfig, row_id: int, actor_name: str | None, statement: str,
    ) -> dict[str, Any]:
        r = self._rows.get(row_id)
        stamp_agent = r["stamp_agent"] if r else None
        return self.commission_trust(cfg, row_id, actor_name, stamp_agent, statement)

    def commissions(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for rid in sorted(self._rows):
            r = self._rows[rid]
            if r["kind"] != "commission":
                continue
            item_count = len(self.item_id_groups(cfg, rid))
            trust = self.commission_trust(cfg, rid, r["actor_name"], r["stamp_agent"], r["statement"])
            out.append({
                "row_id": rid, "statement": r["statement"], "actor_name": r["actor_name"], "ts": r["ts"],
                "item_count": item_count, "trust_level": trust["trust_level"],
                "trust_detail": trust["trust_detail"],
            })
        return out

    def decomposition_items(self, cfg: PanelConfig, commission_row: int) -> DecompositionItems:
        parsed_rows = self.fetch_parsed_item_rows(cfg, commission_row)
        groups = group_item_rows(tuple((r.item_id, r.row_id) for r in parsed_rows))
        by_row_id = {r.row_id: r for r in parsed_rows}
        items: list[Item] = []
        for item_id, row_ids in groups.items():
            if len(row_ids) == 1:
                r = by_row_id[row_ids[0]]
                resolved_witnesses = self.resolve_item_witnesses(cfg, r.witness_refs)
                item_row_cosigned = self.maintainer_cosigned(cfg, r.row_id) is not None
                status = _derive_status(item_row_cosigned, [rw.facts for rw in resolved_witnesses])
                items.append(ResolvedItem(
                    item_id=item_id, row_id=r.row_id, label=r.statement, actor_name=r.actor_name,
                    ts=r.ts, status=status, item_cosign=self.cosign_fact(cfg, r.row_id),
                    witnesses=resolved_witnesses,
                ))
            else:
                items.append(AmbiguousItem(item_id=item_id, candidate_row_ids=tuple(sorted(row_ids))))
        return DecompositionItems(commission_row=commission_row, items=tuple(items))
