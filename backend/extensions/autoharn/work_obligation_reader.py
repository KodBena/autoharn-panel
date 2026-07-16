"""extensions.autoharn.work_obligation_reader -- `WorkObligationReader`, one of the four internal
collaborators `extensions/autoharn/ledger_adapter.py`'s former 1050-line/25-method god-class
(`PostgresAutoharnLedgerReader`) split into (work item autoharn-god-module-split, ledger row
935/1094; the 4-way split itself is row:926's assumption).

Collaborator (c): work-items + the obligation/dependency AND-tree -- `work_items` (the flat,
per-slug listing) and `obligation_tree` (the recursive tree build, SPEC.md sec 2.3 P0 feature)
plus the 8 private helpers the recursion needs. All 8 were confirmed by tracing their actual
callers in the pre-split god-class (not by textual proximity alone, per row:926's own note) to
have NO caller outside `work_items`/`obligation_tree` -- unlike `work_item` (singular) and
`ledger_row`, whose only real caller was witness resolution and which therefore moved to
`DecompositionReader` instead, despite `work_item`'s name suggesting this file.

Bodies are VERBATIM from the god-class (ADR-0004 minimal-touch); only their file moved.
`PostgresAutoharnLedgerReader` (`ledger_adapter.py`) composes one `WorkObligationReader` instance
and delegates `work_items`/`obligation_tree` to it.
"""
from __future__ import annotations

from typing import Any

from config import PanelConfig
from db import connect, jsonable
from extensions.autoharn.ports import ObligationNode


def _work_blocked_by(cfg: PanelConfig) -> dict[str, list[str]]:
    """`dependent_slug -> [antecedent_slug, ...]` from `work_edge_blocks_close` -- a typed,
    kernel-refused-if-cyclic dependency edge distinct from parent/child (`Autoharn.idr`'s
    `EdgeType.BlocksClose`; consult cycle-4 finding 5: this edge type existed in the kernel but
    reached no layer of the app). Read as one small table (2 live edges today), not joined
    per-row -- cheap enough that `work_items()` below just merges it in Python."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT dependent_slug, antecedent_slug FROM work_edge_blocks_close "
            "ORDER BY dependent_slug, antecedent_slug"
        )
        rows = cur.fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["dependent_slug"], []).append(r["antecedent_slug"])
    return out


def _work_items_by_slug(cfg: PanelConfig) -> dict[str, dict[str, Any]]:
    """Every `work_item_current` row, keyed by slug -- fetched once per tree build (a real
    deployment's whole work-item table is a handful of rows, cheap to hold in memory for the
    recursion below) rather than once per node."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute("SELECT slug, title, state, effective_state, resolution FROM work_item_current")
        rows = cur.fetchall()
    return {r["slug"]: r for r in rows}


def _work_opened_row_ids(cfg: PanelConfig) -> dict[str, int]:
    """`work_slug -> its own kind='work_opened' ledger row id`, one query for the whole tree build
    (same one-query-not-per-node shape as `_work_items_by_slug` above) -- the obligation tree's
    click-to-item-view target (obligation-tree-view, row:846 acceptance criterion 3), which the
    tree's own wire otherwise has no way to name: `ObligationNode` carries slug/title/state, not
    the ledger row that opened it. Mirrors `work_item()`'s existing `closed_row_id` sub-query
    (`decomposition_reader.py`, this module's sibling collaborator) but for the OPENING act rather
    than the closing one, and reads every slug at once rather than one row_id per slug (this one
    runs once per tree build, not once per node). A slug's `work_opened` row is unique by kernel
    construction (the opening trigger refuses a second open for the same slug,
    s29-pre-amendment.sql:390-391) -- `ORDER BY id` plus dict-building keeps the first (only) match
    if that invariant is ever violated, same defense-in-depth posture `obligation_tree`'s own
    `visiting` guard already takes."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT work_slug, id FROM ledger_current WHERE kind = 'work_opened' ORDER BY id"
        )
        rows = cur.fetchall()
    out: dict[str, int] = {}
    for r in rows:
        out.setdefault(r["work_slug"], r["id"])
    return out


def _work_obligation_adjacency(cfg: PanelConfig) -> dict[str, list[str]]:
    """`from_slug -> [to_slug, ...]` off `work_edge_obligation` (s32's single home of the IN-FORCE
    obligation-tree union: s28 parent edges + s30 blocks-close edges, already unioned and already
    filtered to in-force -- see that view's own header comment). Reads that ONE view rather than
    re-deriving its in-force join over work_edge_parent/work_edge_blocks_close a second time here."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute("SELECT from_slug, to_slug FROM work_edge_obligation ORDER BY from_slug, to_slug")
        rows = cur.fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["from_slug"], []).append(r["to_slug"])
    return out


def _work_composite_slugs(cfg: PanelConfig) -> set[str]:
    """Slugs whose own opening act declared `work_discharge = 'composite'` (s33 Element 1) -- the
    ONE flag that decides whether a node discharges by CONJUNCTION of its children (Autoharn.idr's
    `isComposite`, sec 3's STRICT-BY-TYPE rule) or by its own recorded act, regardless of whether it
    happens to carry child edges in the graph for some other reason (e.g. a plain blocks-close
    dependency with no auto-discharge intent). Read off `ledger_current` (this column is set
    exactly once, at opening, and never independently retracted, so a plain `kind='work_opened'`
    filter over the in-force view is already the right reading -- matches `isComposite`'s own
    fold)."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT work_slug FROM ledger_current WHERE kind = 'work_opened' AND work_discharge = 'composite'"
        )
        rows = cur.fetchall()
    return {r["work_slug"] for r in rows}


def _work_deferred_undischarged_slugs(cfg: PanelConfig) -> set[str]:
    """Slugs carrying an in-force `work_closed` row with `review_disposition = 'deferred'` and no
    un-superseded distinct-actor attest yet (`work_review_gap`, s29/s32's single home of exactly
    this fact -- the same leg Autoharn.idr's `deferredUndischarged` computes). One of the two real
    "recorded as closed, but not actually resolved" limbo facts the `ambiguous-partial` bucket below
    reads."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT slug FROM work_review_gap")
        rows = cur.fetchall()
    return {r["slug"] for r in rows}


def _work_tree_defeated_slugs(cfg: PanelConfig) -> set[str]:
    """Slugs with a LIVE (undisposed) `closed_but_tree_defeated` violation (s33 Element 5): a
    composite hand-closed while its own `work_item_strict_blockers` is still non-empty --
    `effective_state` reads 'open' while the raw `state` column still reads 'closed' for these. The
    other real "recorded as closed, but not actually resolved" limbo fact the `ambiguous-partial`
    bucket below reads."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT slug FROM work_item_violations WHERE violation = 'closed_but_tree_defeated'"
        )
        rows = cur.fetchall()
    return {r["slug"] for r in rows}


def _obligation_discharge_state(
    effective_state: str, resolution: str | None, deferred_undischarged: bool, tree_defeated: bool,
) -> str:
    """Classifies one work item's CURRENT discharge state into `ports.DISCHARGE_STATES`, using only
    facts the kernel itself already computes -- never re-deriving the sec-2b conjunction
    (`effective_state` already IS that read, Autoharn.idr sec 4) or the deferred-review/
    tree-defeated limbo facts (`work_review_gap`/`work_item_violations` already are those reads).
    Order is significant:
      1. `resolution == 'superseded'` (s22's closed work_resolution vocabulary) is the writer's own
         explicit final word on this item -- checked first, wins over any live tree state.
      2. `tree_defeated` or `deferred_undischarged` are both "recorded as done, but not actually
         resolved yet" limbo -- SPEC.md sec 2.3's own amber/ambiguous example.
      3. Otherwise `effective_state` decides plainly: closed/discharged-by-obligations => discharged,
         open => undischarged.
    """
    if resolution == "superseded":
        return "superseded"
    if tree_defeated or deferred_undischarged:
        return "ambiguous-partial"
    if effective_state in ("closed", "discharged-by-obligations"):
        return "discharged"
    return "undischarged"


class WorkObligationReader:
    """Owns work-item reads and the recursive obligation/dependency AND-tree -- no fields, no
    constructor arguments, exactly like the facade it composes into (see module docstring)."""

    def work_items(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT w.slug, w.title, w.state, w.effective_state, w.resolution, w.witness,
                       w.parent_slug, p.name AS claimant_name
                FROM work_item_current w LEFT JOIN principal p ON p.id = w.claimant
                ORDER BY w.slug
                """
            )
            rows = cur.fetchall()
        blocked_by = _work_blocked_by(cfg)
        out = []
        for r in rows:
            item = jsonable(r)
            item["blocked_by"] = blocked_by.get(item["slug"], [])
            out.append(item)
        return out

    def obligation_tree(self, cfg: PanelConfig, root_slug: str) -> ObligationNode | None:
        """The obligation/dependency AND-tree (Autoharn.idr sec 2b/3/4; SPEC.md sec 2.3), rooted at
        `root_slug`, as a real recursive tree -- not a flat edge list the frontend would have to
        reconstruct. Returns None if `root_slug` was never opened (the route layer 404s on that).

        A DAG diamond (a slug reachable from `root_slug` via more than one path -- e.g. two
        composites both blocks-close-depending on the same antecedent) renders as more than one
        node in the returned tree; that is the standard, harmless way to render a DAG as a tree, and
        matches this work item's own brief ("recursive tree structure ... the frontend needs a real
        tree/DAG to render"). The kernel structurally refuses a genuine CYCLE in either edge kind at
        write time (s28's work_parent_would_cycle, s30's work_depends_on_would_cycle), so the plain
        recursion below always terminates in normal operation; the `visiting` guard is defense in
        depth only (fail-loud-but-not-hanging if that invariant is ever violated), never expected to
        fire."""
        items = _work_items_by_slug(cfg)
        if root_slug not in items:
            return None
        adjacency = _work_obligation_adjacency(cfg)
        composite_slugs = _work_composite_slugs(cfg)
        deferred_slugs = _work_deferred_undischarged_slugs(cfg)
        tree_defeated_slugs = _work_tree_defeated_slugs(cfg)
        opened_row_ids = _work_opened_row_ids(cfg)

        def build(slug: str, visiting: frozenset[str]) -> ObligationNode:
            row = items.get(slug)
            row_id = opened_row_ids.get(slug)
            if row is None:
                # An edge reaches a slug with no work_item_current row -- should be unreachable
                # (every kind='work_opened' row IS a work_item_current row by construction), but
                # degrades to an honest stub rather than a KeyError if the graph and the projection
                # ever disagree.
                return ObligationNode(slug=slug, title=None, kind="leaf", discharge_state="undischarged",
                                       state="open", effective_state="open", resolution=None,
                                       row_id=row_id, children=())
            state = row["state"]
            effective_state = row["effective_state"]
            resolution = row["resolution"]
            discharge_state = _obligation_discharge_state(
                effective_state, resolution,
                deferred_undischarged=slug in deferred_slugs,
                tree_defeated=slug in tree_defeated_slugs,
            )
            kind = "composite" if slug in composite_slugs else "leaf"
            if slug in visiting:
                return ObligationNode(slug=slug, title=row["title"], kind=kind,
                                       discharge_state=discharge_state, state=state,
                                       effective_state=effective_state, resolution=resolution,
                                       row_id=row_id, children=())
            children = tuple(build(child, visiting | {slug}) for child in adjacency.get(slug, []))
            return ObligationNode(slug=slug, title=row["title"], kind=kind, discharge_state=discharge_state,
                                   state=state, effective_state=effective_state, resolution=resolution,
                                   row_id=row_id, children=children)

        return build(root_slug, frozenset())
