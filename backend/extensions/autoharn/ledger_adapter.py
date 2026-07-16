"""extensions.autoharn.ledger_adapter -- `PostgresAutoharnLedgerReader`, the ONE concrete
implementation of `extensions.autoharn.ports.AutoharnLedgerPort` (work item
autoharn-adapter-acl-wrap, ledger row 934; Protocol landed at row 931/619b95d). Every method's SQL
body is relocated VERBATIM (ADR-0004 minimal-touch; this file is the "downstream item" `ports.py`'s
own docstring named as expected to do exactly this) from `extensions/autoharn/ledger_read.py`, now
GONE -- grep-confirmed before deletion: only `routes.py` and `cosign.py` imported its module-level
DB-touching functions directly, and both are repointed at this class in the same commit. Its three
PURE, no-I/O parsers -- `parse_item_refs`, `parse_witness_refs`, `parse_resource_fields` -- and
their supporting regexes/private helpers move here too, as plain module functions, exactly as
`ports.py`'s own docstring specified they should stay: NOT Protocol methods (forcing well-factored
pure code onto a DB-swapping interface buys nothing), callable directly by any caller or test with
no fake required.

Stateless by design, exactly as `core/ledger_adapter.py` (the sibling core-side item, row 933)
established for its own `PostgresCoreLedgerReader`: every method takes `cfg: PanelConfig` as its own
connection/config handle, so one `PostgresAutoharnLedgerReader()` (no constructor arguments) is
constructed once, at app startup, and shared across every request (see `app.py`'s
`AppState.autoharn_reader`).

DATACLASS DUPLICATION -- COLLAPSED for six of the seven (was disclosed at ledger row 979, resolved
here at row 934): `ObligationNode`, `ResolvedWitness`, `ParsedItemRow`, `ResolvedItem`,
`AmbiguousItem`, `DecompositionItems` (and the `Item` alias) are no longer redefined in this file --
it imports them directly from `ports.py`, now their one canonical home, since `ledger_read.py`'s own
former copies are gone (mirrors `core/ledger_adapter.py` importing `SupersedeChain` from
`core/ports.py` for the identical reason). `WitnessFacts` is the one exception, deliberately NOT
collapsed by this item: its real, permanent home is `extensions/autoharn/disposition.py` (a
separate, pure module this item does not touch), so `ports.py`'s own frozen copy remains a second,
pre-existing duplicate of THAT module's `WitnessFacts` -- orthogonal to `ledger_read.py`'s deletion
and out of this item's scope. This module imports `ports.WitnessFacts` (not
`disposition.WitnessFacts`) so its own method bodies type-check against the Protocol's own declared
signatures -- mirroring `tests/fakes/fake_autoharn_ledger_reader.py`'s own already-shipped precedent
(work item autoharn-ledger-fake, row 937) of doing exactly this for exactly this reason. Because
`disposition.derive_status` is typed against `disposition.WitnessFacts`, this module carries its own
`_derive_status`, a logic-identical copy typed against `ports.WitnessFacts` instead -- again
mirroring the fake's own disclosed `_derive_status` copy -- while still importing and calling the
REAL `disposition.group_item_rows` directly (it takes plain `(str, int)` tuples, so no
dataclass-typing conflict arises there).

VOCABULARY RELOCATION -- COMPLETED (ledger row 927/979): `ledger_read.py`'s own module-constant
copies of `COMMISSION_TRUST_LEVELS`/`VERDICTS`/`INDEPENDENCE_VALUES`/`DISCHARGE_GRADES`/
`STATUS_VALUES`/`DISCHARGE_STATES` are gone along with that file; `ports.py` is now their sole home.
Only `VERDICTS`/`INDEPENDENCE_VALUES` are actually read at runtime by a method body below
(`autoharn_health`'s own return payload) -- the other four were always documentary-only in
`ledger_read.py` (named once for readers, never branched on in that module's own logic), so this
file has no reason to import them just to re-export them.

CORE-GENERIC BOUNDARY, unchanged: like `ledger_read.py` before it, this module depends on autoharn's
own kernel lineage views (`ledger_current`, `review_detail`, `work_item_current`, `review_gap`,
`question_status`, the `work_edge_*` obligation views) and the `stamp_secret` table -- none of which
core (`backend/core/ledger_adapter.py`) knows about or requires. This is still the module the
extension boundary test (`tests/test_core_boundary.py`) proves is NOT needed for the core API to
serve.

GOD-MODULE, DELIBERATELY NOT SPLIT (row 894 finding 3, deliberately deferred): this item wraps
`ledger_read.py`'s ~1050 lines as ONE class behind ONE Protocol, resolving finding 2 (no ACL) only.
A later item, `autoharn-god-module-split`, is chartered to reorganize this file's internals; this
item does not attempt that reorganization -- the section layout below (private helpers grouped
before the class, all 25 Protocol methods inside one contiguous class body) is the minimum
restructuring Python's own syntax requires to turn module-level functions into class methods, not a
substantive reorganization of the god-module's own internal boundaries.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from config import PanelConfig
from db import connect, connect_unrestricted, jsonable
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

# CLAUDE.md point 11's disclosure prefix: every LAZY-mode commission's statement carries this
# marker (possibly with more clauses after a semicolon -- row 374 is a live specimen), so a
# simple prefix check is a robust, sufficient signal -- no fixed-marker-phrase parser needed
# (commission-trust-badge, row:720 assumption).
_LAZY_DISCLOSURE_PREFIX = "(vicarious transcription by the implementer"


# ---------------------------------------------------------------------------------------------
# Private helpers -- module-level, not Protocol methods, grouped together (Python cannot reopen
# a class body once dedented out of it, so every helper a method below calls must be defined
# before the class starts). Verbatim bodies from `ledger_read.py`; only their position in the
# file moved, per this module's own GOD-MODULE note above.
# ---------------------------------------------------------------------------------------------


def _fetch_jsonable_rows(
    cfg: PanelConfig, sql: str, params: tuple[Any, ...] | None = None
) -> list[dict[str, Any]]:
    """Shared connect/execute/fetchall/jsonable-map plumbing for several methods below whose only
    real difference is which SQL they run (compliance-review finding 2, row:745/747):
    `recent_ledger`, `review_gap`, `work_violations`, `findings_and_snags`, `question_status`,
    `standing_decisions`, and `reviews_for_row` were each independently open-coding this exact
    four-step shape. Pure de-duplication of the plumbing -- every caller keeps its own SQL/column
    selection exactly as it was, so this changes nothing about what any endpoint returns.

    Deliberately NOT used by `ledger_row`/`work_item`/`maintainer_cosigned`/`latest_review_id`/
    `row_refs_text`/`commission_trust_for_row` (a `fetchone` single-row shape, not this one, or
    `work_item`'s two-query-in-one-connection shape), nor by `work_items`/`commissions` (fetchall
    plus per-row Python augmentation beyond a bare jsonable map) -- those are genuinely different
    shapes and are left as they were."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [jsonable(r) for r in rows]


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
    the ledger row that opened it. Mirrors `work_item()`'s existing `closed_row_id` sub-query (same
    file) but for the OPENING act rather than the closing one, and reads every slug at once rather
    than one row_id per slug (this one runs once per tree build, not once per node). A slug's
    `work_opened` row is unique by kernel construction (the opening trigger refuses a second open
    for the same slug, s29-pre-amendment.sql:390-391) -- `ORDER BY id` plus dict-building keeps the
    first (only) match if that invariant is ever violated, same defense-in-depth posture
    `obligation_tree`'s own `visiting` guard already takes."""
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


# ---------------------------------------------------------------------------------------------
# Pure, no-I/O functions and their supporting regexes -- deliberately NOT Protocol methods
# (`ports.py`'s own docstring: `parse_item_refs`/`parse_witness_refs`/`parse_resource_fields`
# stay plain functions, callable directly by whatever adapter or test needs them, with no fake
# required to exercise them).
# ---------------------------------------------------------------------------------------------

_PANEL_ITEM_TOKEN_RE = re.compile(r"^panel-item:(?P<cid>\d+):(?P<iid>[A-Za-z0-9_-]+)$")
_ROW_TOKEN_RE = re.compile(r"^row:(?P<id>\d+)$")
_WORK_TOKEN_RE = re.compile(r"^work:(?P<slug>[A-Za-z0-9_.-]+)$")


def parse_witness_refs(refs_text: str | None) -> list[tuple[str, str]]:
    """Generic `row:<id>` / `work:<slug>` witness-token extraction from ANY row's `refs` text --
    unlike `parse_item_refs`, this does NOT require a wrapping `panel-item:<commission>:...` token.
    Used by the item view (SPEC.md sec 2.2's "disposition/witness edges") to show witness/co-sign
    edges for an arbitrary ledger row, not just a decomposition item row."""
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


# The six fields a `resource:`-prefixed decision statement carries, in order (design/USER-
# BLESSED-TABLE-TEMPLATE.md's "statement grammars" section -- the ONE documented home of this
# grammar, also transcribed by autoharn's own `./pickup` RESOURCES section,
# `bootstrap/templates/pickup.tmpl`'s `_RESOURCE_FIELDS`/`resources()`). `parse_resource_fields`
# below is a SECOND reader of the same convention (the item view's per-row enrichment, not
# session-hydration display), so it is deliberately kept field-for-field consistent with that one
# rather than inventing its own shape.
_RESOURCE_STATEMENT_RE = re.compile(r"^\s*resource:")


def _resource_tier_kind(tier: str) -> str:
    """Normalizes a TIER field's leading word to one of the four fixed tier classes a frontend
    badge keys off of -- same `startswith` precedence pickup.tmpl's `_resource_tier_rank` sorts by
    (forbidden outranks mandated outranks blessed, design/ORCH-SPEC-RESOURCE-ACCOUNTING.md §3), just
    returning a class name here instead of a sort rank. An unrecognized tier string (or a bare
    `available`) maps to 'available', matching that function's own catch-all -- sorting/badging
    degrades gracefully, it never errors on a tier word this module doesn't happen to recognize."""
    t = tier.strip().lower()
    if t.startswith("forbidden"):
        return "forbidden"
    if t.startswith("mandated"):
        return "mandated"
    if t.startswith("blessed"):
        return "blessed"
    return "available"


def parse_resource_fields(statement: str) -> dict[str, Any] | None:
    """Parses a `resource:`-prefixed decision statement into its six pipe-delimited fields
    (NAME | CLASS | REACH | WHAT-IT-PROVES | GUIDANCE | TIER) for the item view's structured display
    (cycle-4 audit finding 6, SERIOUS: the item detail view rendered the whole statement as one
    undifferentiated prose blob, no parsed tier badge or labeled fields). Returns `None` for
    anything that isn't a `resource:` statement, or is one but doesn't carry exactly six
    '|'-separated fields (a malformed row) -- the caller's job in either case is to fall back to the
    plain-prose rendering core's own item view already does unconditionally, never to hide or
    replace the original statement text.

    Mirrors `bootstrap/templates/pickup.tmpl`'s `resources()` byte-for-byte in the two respects that
    matter for staying the SAME parser as that one (design/USER-BLESSED-TABLE-TEMPLATE.md's
    "statement grammars" section: "these are NOT the same parser" is a hazard only when two parsers
    of the same grammar silently diverge, not when the grammar is genuinely mirrored): an embedded
    newline (a paste reflowed by a terminal's line wrap) is collapsed to a single space BEFORE the
    field split, the run12 witness fix that section documents; and the prefix is stripped by
    splitting on the FIRST colon in the (now newline-normalized) statement, not a literal
    `len("resource:")` slice, so `resource:` arriving with no space before the first field still
    splits correctly."""
    normalized = re.sub(r"[\n\r]+[ \t]*", " ", statement).lstrip()
    if not _RESOURCE_STATEMENT_RE.match(normalized):
        return None
    body = normalized.split(":", 1)[1] if ":" in normalized else ""
    fields = [f.strip() for f in body.split("|")]
    if len(fields) != 6:
        return None
    name, cls, reach, proves, guidance, tier = fields
    return {
        "name": name,
        "class_": cls,
        "reach": reach,
        "what_it_proves": proves,
        "guidance": guidance,
        "tier": tier,
        "tier_kind": _resource_tier_kind(tier),
    }


def parse_item_refs(refs_text: str | None, commission_row: int) -> tuple[str | None, list[tuple[str, str]]]:
    """PURE, anchored, fail-closed parser (see disposition.py's module docstring for the full
    rationale, ported unchanged from the autoharn PoC): a `refs` string that does not carry EXACTLY
    ONE well-formed `panel-item:<commission_row>:...` token returns `(None, [])`."""
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
    """True iff `refs_text` carries a well-formed, EXACT `row:<commission_row>` token -- the same
    anchored-token discipline `_PANEL_ITEM_TOKEN_RE`/`_ROW_TOKEN_RE` use elsewhere in this module,
    so a LIKE prefilter (`row:24` matching `row:247`) never survives into the returned set."""
    wanted = str(commission_row)
    for tok in (refs_text or "").split():
        m = _ROW_TOKEN_RE.match(tok)
        if m and m.group("id") == wanted:
            return True
    return False


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


def _derive_status(item_row_cosigned: bool, witnesses: list[WitnessFacts]) -> str:
    """Logic-identical copy of `disposition.derive_status` (see module docstring's DATACLASS
    DUPLICATION section for why: it is typed against `ports.WitnessFacts` here rather than
    `disposition.WitnessFacts`, mirroring `tests/fakes/fake_autoharn_ledger_reader.py`'s own
    identical `_derive_status` copy and identical reason). Rules (spec sec 5, restated exactly):

    0. The item's OWN ledger row has been maintainer-cosigned (`item_row_cosigned`) -> COSIGNED,
       regardless of witnesses.
    - No witnesses, or every witness resolves to something not-yet-substantive -> OPEN.
    - >=1 substantive witness, none co-signed by the maintainer -> WITNESSED.
    - Some but not all substantive witnesses co-signed -> PARTIAL.
    - Every substantive witness co-signed -> COSIGNED.

    A non-existent (dangling) witness ref is dropped from consideration entirely. `AMBIGUOUS` is
    never produced here -- see `disposition.derive_status`'s own full docstring for the complete
    rationale (unchanged by this copy)."""
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


class PostgresAutoharnLedgerReader:
    """The Postgres-backed `AutoharnLedgerPort` implementation. No fields, no constructor
    arguments -- every method is handed its own `cfg: PanelConfig` (see module docstring); a
    stateless collaborator, constructed once at app startup and shared across every request (see
    `app.py`'s `AppState.autoharn_reader`), same convention `core/ledger_adapter.py`'s
    `PostgresCoreLedgerReader` established for its own sibling seam."""

    def autoharn_health(self, cfg: PanelConfig) -> dict[str, Any]:
        """The autoharn-specific slice of `GET /api/health` (mixed into core's health payload by
        `routes.py` only when this extension is enabled). Uses `db.connect_unrestricted` (does NOT
        `SET ROLE`) for the `stamp_secret` armed-check -- that table is REVOKEd from the subject
        role on purpose, so checking under the ordinary `SET ROLE`'d `db.connect` would always raise
        `permission denied` rather than report False."""
        with connect_unrestricted(cfg) as conn, conn.cursor() as cur:
            cur.execute(f'SELECT EXISTS (SELECT 1 FROM "{cfg.kern_schema}".stamp_secret) AS armed')
            armed = bool(cur.fetchone()["armed"])
        return {
            "stamp_secret_armed": armed,
            "verdicts": list(VERDICTS),
            "independence_values": list(INDEPENDENCE_VALUES),
        }

    def recent_ledger(self, cfg: PanelConfig, n: int) -> list[dict[str, Any]]:
        # `n` feeds straight into a LIMIT clause below -- same vulnerability class as `/api/rows`'
        # `limit` (Postgres raises an unhandled 500 on a negative LIMIT; cycle-3 consult finding 2,
        # fixed for `rows()` in commit 0d9aa7e). Not currently called by the frontend, but validated
        # the same way (raise ValueError) so a future caller -- HTTP route or otherwise -- gets a
        # clean 400 rather than a raw DB error, matching `rows()`'s convention.
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")
        return _fetch_jsonable_rows(
            cfg,
            """
            SELECT l.id, l.kind, l.statement, p.name AS actor_name, l.ts, l.stamp_verified
            FROM ledger_current l LEFT JOIN principal p ON p.id = l.actor
            ORDER BY l.id DESC LIMIT %s
            """,
            (n,),
        )

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

    def review_gap(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """`review_gap` (kernel view: `id, actor, scope, assigned_by`, s15/re-issued s32) plus each
        row's `actor`/`assigned_by` principal ids resolved to names -- two LEFT JOINs against
        `principal`, one per id column, the same join-in-a-name pattern every other tab's query
        already uses (`work_items`' `claimant_name`, `recent_ledger`/`commissions`' `actor_name`).
        Addresses cycle-5 audit finding 9 (MINOR): this was the one remaining read in this module
        still surfacing bare principal ids instead of names, because the view itself carries no
        join of its own. Keeps the original `id, actor, scope, assigned_by` columns verbatim
        (nothing reading those bare ids breaks) and ADDS `actor_name`/`assigned_by_name` alongside
        them, same additive-column convention as the tabs above."""
        return _fetch_jsonable_rows(
            cfg,
            """
            SELECT rg.id, rg.actor, pa.name AS actor_name, rg.scope,
                   rg.assigned_by, pb.name AS assigned_by_name
            FROM review_gap rg
            LEFT JOIN principal pa ON pa.id = rg.actor
            LEFT JOIN principal pb ON pb.id = rg.assigned_by
            ORDER BY rg.id
            """,
        )

    def work_violations(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """`work_item_violations` -- the kernel's own live "what's currently wrong right now"
        signal (cycle-4 audit finding 10, SERIOUS): every currently-unresolved decomposition-tree
        violation (duplicate opens, dangling dependency/parent refs, dependency/parent/blocks-close
        cycles, a shipped close with no witness, an opening act orphaned by a later retraction, or a
        composite closed while its own child tree still blocks it) that has NOT already been
        disposed of via a `work_violation_disposition` row -- the view's own definition filters
        those out via a `disposition_basis_holds` join, so every row this returns is a live,
        undisposed violation, not a historical one. Empty in this deployment today, same
        honest-narrow-columns shape as `review_gap`/`question_status`: the view carries only
        `violation, slug, detail, target_id`, no id/ts/actor of its own. `target_id` is always
        populated (the view's own final SELECT inner-joins it against `ledger_current`) and doubles
        as this tab's row-click target (mirroring `review_gap`'s `id` column serving the same role
        in ReviewGapTab.vue) -- ordered by it so the same violation instance holds a stable position
        across polls, there being no id column of the view's own to order by."""
        return _fetch_jsonable_rows(
            cfg,
            "SELECT violation, slug, detail, target_id FROM work_item_violations "
            "ORDER BY target_id, violation, slug",
        )

    def obligation_tree(self, cfg: PanelConfig, root_slug: str) -> ObligationNode | None:
        """The obligation/dependency AND-tree (Autoharn.idr sec 2b/3/4; SPEC.md sec 2.3) rooted at
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

    def findings_and_snags(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """`finding`/`snag` rows -- exactly the "recorded-defect/observation" prose content the
        kernel's `Autoharn.idr` sum type already treats symmetrically with every other ledger kind,
        but which (unlike `question`/`review_gap`) got no dedicated browsing surface of its own
        before now (cycle-4 audit finding 8, MODERATE). ONE combined view, not two separate ones
        (row:704's decision, made after reading this deployment's own live rows: 26 finding + 10
        snag = 36 total at decision time -- modest, comparable volume that does not warrant doubling
        the tab-bar footprint for two near-empty views); `kind` is still selected here so the
        frontend can render a per-row badge distinguishing the two without a second query.

        Same query shape as `recent_ledger` above (`ledger_current` LEFT JOIN `principal`, same
        column list) narrowed by a `kind IN (...)` filter -- reusing that established pattern rather
        than inventing a new one, per CLAUDE.md point 2's tool-reuse discipline."""
        return _fetch_jsonable_rows(
            cfg,
            """
            SELECT l.id, l.kind, l.statement, p.name AS actor_name, l.ts, l.stamp_verified
            FROM ledger_current l LEFT JOIN principal p ON p.id = l.actor
            WHERE l.kind IN ('finding', 'snag')
            ORDER BY l.id DESC
            """,
        )

    def question_status(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """`question_status` (the kernel view) plus each question row's own `statement` text,
        joined in here from `ledger_current` rather than widening the kernel view itself -- that
        view ships from autoharn's own kernel lineage SQL, applied once at --new-world scaffold
        time, and is not owned by this repo (row:660's decision). `question_id` always resolves
        against `ledger_current` because the view's own definition selects `question_id` FROM
        `ledger_current` in the first place, so this join can never silently drop a row. Addresses
        cycle-4 audit finding 11 (MINOR): the Questions tab's table showed no snippet of the actual
        question TEXT, forcing a click-through just to learn what was asked (work item
        questions-inline-text, row:633)."""
        return _fetch_jsonable_rows(
            cfg,
            """
            SELECT qs.*, l.statement
            FROM question_status qs
            JOIN ledger_current l ON l.id = qs.question_id
            ORDER BY qs.question_id
            """,
        )

    def standing_decisions(self, cfg: PanelConfig) -> list[dict[str, Any]]:
        """`standing_decisions` (kernel/lineage/s36-decision-grade.sql) -- every in-force
        `decision`-kind row carrying a writer-supplied `grade`, currently 22+ live rows in this
        deployment (cycle-4 audit finding 4, SERIOUS): real, kernel-supported governance state
        (`./led standing`, `./pickup`'s own STANDING-DECISIONS section already surface it to a CLI
        operator) that the SPA had no dedicated view for at all -- every decision row, durable or
        not, rendered identically in Recent Ledger.

        Same honest-narrow-columns shape as `review_gap`/`work_violations` above: the view itself
        carries only `id, grade, statement` (a CURRENT-TRUTH reader factored through
        `ledger_current`, per s36's own comment -- a row drops out the moment it leaves
        ledger_current, e.g. superseded/retracted), no actor/ts of its own; the full `statement`
        text is already in the payload (same as `findings_and_snags`), so the frontend needs no
        second fetch to render it in full. Ordered by id, same convention as `review_gap`."""
        return _fetch_jsonable_rows(cfg, "SELECT id, grade, statement FROM standing_decisions ORDER BY id")

    def ledger_row(self, cfg: PanelConfig, row_id: int) -> dict[str, Any] | None:
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.id, l.kind, l.statement, l.ts, p.name AS actor_name
                FROM ledger_current l LEFT JOIN principal p ON p.id = l.actor
                WHERE l.id = %s
                """,
                (row_id,),
            )
            row = cur.fetchone()
        return jsonable(row) if row else None

    def work_item(self, cfg: PanelConfig, slug: str) -> dict[str, Any] | None:
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT w.slug, w.title, w.state, w.effective_state, w.resolution, w.witness,
                       w.parent_slug, p.name AS claimant_name
                FROM work_item_current w LEFT JOIN principal p ON p.id = w.claimant
                WHERE w.slug = %s
                """,
                (slug,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                """
                SELECT id FROM ledger_current
                WHERE kind = 'work_closed' AND work_slug = %s
                ORDER BY id DESC LIMIT 1
                """,
                (slug,),
            )
            closed = cur.fetchone()
        result = jsonable(row)
        result["closed_row_id"] = closed["id"] if closed else None
        return result

    def maintainer_cosigned(self, cfg: PanelConfig, target_row_id: int) -> dict[str, Any] | None:
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.id AS review_id, d.verdict, p.name AS actor_name
                FROM ledger_current r
                JOIN review_detail d ON d.ledger_id = r.id
                JOIN principal p ON p.id = r.actor
                WHERE r.kind = 'review' AND r.regards = %s AND d.verdict = 'attest'
                  AND p.name = %s
                ORDER BY r.id DESC LIMIT 1
                """,
                (target_row_id, cfg.maintainer_principal),
            )
            row = cur.fetchone()
        return jsonable(row) if row else None

    def latest_review_id(self, cfg: PanelConfig, regards: int, actor_name: str) -> int | None:
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.id FROM ledger_current r
                JOIN principal p ON p.id = r.actor
                WHERE r.kind = 'review' AND r.regards = %s AND p.name = %s
                ORDER BY r.id DESC LIMIT 1
                """,
                (regards, actor_name),
            )
            row = cur.fetchone()
        return row["id"] if row else None

    def resolve_witness(
        self, cfg: PanelConfig, ref_kind: str, ref: str
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
            return {"cosigned": True, "by": disc["actor_name"], "review_id": disc["review_id"], "verdict": disc["verdict"]}
        return {"cosigned": False, "by": None, "review_id": None, "verdict": None}

    def reviews_for_row(self, cfg: PanelConfig, row_id: int) -> list[dict[str, Any]]:
        """The item view's "review/co-sign history with actor + independence badges" (SPEC.md sec
        2.2): every live `review` row whose `regards` points at `row_id`, joined to its typed
        `review_detail` payload -- NOT narrowed to maintainer/attest the way `maintainer_cosigned`
        is, since the item view renders the full history, not just the discharge-relevant fact.

        `discharge_grade` (cycle-5 audit finding 2, CRITICAL) rides alongside the writer-supplied
        `independence` value here: unlike `independence` (asserted by whoever wrote the review --
        `technical`/`managerial`/`financial`/`self-review`, any of which a reviewer can simply
        type), `discharge_grade` is computed by `validate_independence()`'s trigger from the
        review's own stamp facts compared against the target row's, and a writer literally cannot
        supply or override it (s34's refusal). Confirmed live in this deployment: every review to
        date grades `same-principal` or `same-session` -- the two weakest rungs of
        `ports.DISCHARGE_GRADES` -- while many of those same rows self-declare
        `independence: technical`. Exposing both side-by-side lets a reader see when a review's
        self-declared independence outruns what the kernel can actually verify, rather than trusting
        the self-declaration alone."""
        return _fetch_jsonable_rows(
            cfg,
            """
            SELECT r.id AS review_id, r.ts, p.name AS actor_name,
                   d.verdict, d.independence, d.discharge_grade, d.basis
            FROM ledger_current r
            JOIN review_detail d ON d.ledger_id = r.id
            LEFT JOIN principal p ON p.id = r.actor
            WHERE r.kind = 'review' AND r.regards = %s
            ORDER BY r.id
            """,
            (row_id,),
        )

    def resolve_item_witnesses(
        self, cfg: PanelConfig, witness_refs: tuple[tuple[str, str], ...]
    ) -> list[ResolvedWitness]:
        out: list[ResolvedWitness] = []
        for ref_kind, ref in witness_refs:
            facts, resolved = self.resolve_witness(cfg, ref_kind, ref)
            cosign_info: dict[str, Any] = {"cosigned": False, "by": None, "review_id": None, "verdict": None}
            if facts.cosign_target_row is not None:
                cosign_info = self.cosign_fact(cfg, facts.cosign_target_row)
            out.append(
                ResolvedWitness(
                    ref_kind=ref_kind, ref=ref, resolved=resolved,
                    cosign_target_row=facts.cosign_target_row, cosign=cosign_info, facts=facts,
                )
            )
        return out

    def row_refs_text(self, cfg: PanelConfig, row_id: int) -> str | None:
        """The raw `refs` text of ONE ledger row -- `ledger_row`/`work_item` above deliberately
        don't select it (they answer narrower questions), so the item view's generic witness-ref
        reader gets its own minimal query rather than widening either of those."""
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute("SELECT refs FROM ledger_current WHERE id = %s", (row_id,))
            row = cur.fetchone()
        return row["refs"] if row else None

    def item_witnesses(self, cfg: PanelConfig, row_id: int) -> list[ResolvedWitness]:
        """`row_id`'s own `refs` text, read generically (`parse_witness_refs`) and resolved the
        same way a decomposition item's witnesses are (`resolve_item_witnesses`) -- the item view's
        witness panel for an arbitrary row, e.g. a `work_closed` row's `--witness row:<n>` token."""
        witness_refs = tuple(parse_witness_refs(self.row_refs_text(cfg, row_id)))
        return self.resolve_item_witnesses(cfg, witness_refs)

    def fetch_parsed_item_rows(self, cfg: PanelConfig, commission_row: int) -> tuple[ParsedItemRow, ...]:
        """Decomposition items for `commission_row`, read under BOTH conventions this deployment's
        history carries (CLAUDE.md point 1 antecedent-audit finding, row:249):

        1. The PoC-era `panel-item:<commission_row>:<item_id>` token grammar on a `note` row
           (unchanged -- kept for any historical data that used it).
        2. This deployment's actual, documented convention: a plain `work_opened` row whose `refs`
           carries a bare `row:<commission_row>` token (`./led work open <slug> <title> --refs
           row:<commission>`, CLAUDE.md point 1). Its `item_id` is the work item's own `work_slug`
           (already unique-by-construction -- kernel/lineage's `work_opened` trigger refuses a
           second opening act for the same slug, s29-pre-amendment.sql:390-391), and its implied
           witness is the work item itself (`("work", work_slug)`) PLUS any other `row:`/`work:`
           witness tokens already in its `refs` text (excluding the `row:<commission_row>` token
           itself, which names the item's parent commission, not something that witnesses the
           item's own completion).
        """
        out: list[ParsedItemRow] = []

        pattern = f"%panel-item:{commission_row}:%"
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.id, l.refs, l.statement, l.ts, p.name AS actor_name
                FROM ledger_current l LEFT JOIN principal p ON p.id = l.actor
                WHERE l.kind = 'note' AND l.refs LIKE %s
                ORDER BY l.id
                """,
                (pattern,),
            )
            rows = cur.fetchall()
        for row in rows:
            item_id, witness_refs = parse_item_refs(row["refs"], commission_row)
            if item_id is None:
                continue
            ts = row["ts"]
            out.append(
                ParsedItemRow(
                    row_id=row["id"],
                    item_id=item_id,
                    witness_refs=tuple(witness_refs),
                    statement=row["statement"],
                    actor_name=row["actor_name"],
                    ts=ts.isoformat() if hasattr(ts, "isoformat") else ts,
                )
            )

        pattern = f"%row:{commission_row}%"
        with connect(cfg) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.id, l.refs, l.statement, l.ts, p.name AS actor_name, l.work_slug
                FROM ledger_current l LEFT JOIN principal p ON p.id = l.actor
                WHERE l.kind = 'work_opened' AND l.refs LIKE %s
                ORDER BY l.id
                """,
                (pattern,),
            )
            rows = cur.fetchall()
        for row in rows:
            if not _row_token_matches(row["refs"], commission_row):
                continue
            slug = row["work_slug"]
            if not slug:
                continue
            other_witnesses = [
                (kind, ref)
                for kind, ref in parse_witness_refs(row["refs"])
                if not (kind == "row" and ref == str(commission_row))
            ]
            witness_refs = [("work", slug), *other_witnesses]
            ts = row["ts"]
            out.append(
                ParsedItemRow(
                    row_id=row["id"],
                    item_id=slug,
                    witness_refs=tuple(witness_refs),
                    statement=row["statement"],
                    actor_name=row["actor_name"],
                    ts=ts.isoformat() if hasattr(ts, "isoformat") else ts,
                )
            )

        return tuple(out)

    def item_id_groups(self, cfg: PanelConfig, commission_row: int) -> dict[str, tuple[int, ...]]:
        return group_item_rows(
            tuple((r.item_id, r.row_id) for r in self.fetch_parsed_item_rows(cfg, commission_row))
        )

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
            item_count = len(self.item_id_groups(cfg, row_id))
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
                items.append(
                    ResolvedItem(
                        item_id=item_id,
                        row_id=r.row_id,
                        label=r.statement,
                        actor_name=r.actor_name,
                        ts=r.ts,
                        status=status,
                        item_cosign=self.cosign_fact(cfg, r.row_id),
                        witnesses=resolved_witnesses,
                    )
                )
            else:
                items.append(AmbiguousItem(item_id=item_id, candidate_row_ids=tuple(sorted(row_ids))))
        return DecompositionItems(commission_row=commission_row, items=tuple(items))
