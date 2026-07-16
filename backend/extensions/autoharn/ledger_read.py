"""extensions.autoharn.ledger_read -- every autoharn-semantic read this panel performs
(SPEC.md sec 4's extension boundary): commissions, decomposition items (the `panel-item:`
refs grammar), obligation/witness resolution, work items, review gaps, open questions, and the
kernel's own closed verdict/independence vocabularies. Ported from the autoharn PoC's
`panel/backend/ledger_read.py` with import paths adjusted for this repo's layout and its own
generic `db.connect`/`db.jsonable` (core's connection helper -- SET ROLE only if `cfg.role` is
set, SET search_path to `<schema>, <kern_schema>`).

Every function here depends on autoharn's own kernel lineage views (`ledger_current`,
`review_detail`, `work_item_current`, `review_gap`, `question_status`) and the `stamp_secret`
table -- none of which core (`backend/core/ledger_read.py`) knows about or requires. This is the
module the extension boundary test (`tests/test_core_bare_schema.py`) proves is NOT needed for
the core API to serve.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from config import PanelConfig
from db import connect, jsonable
from extensions.autoharn.disposition import WitnessFacts, derive_status, group_item_rows

# The kernel's own closed vocabularies (bootstrap/templates/led.tmpl `led review` usage text,
# kernel/lineage/s15-schema.sql's `review_detail` check constraints in the autoharn deployment
# this extension targets) -- named ONCE here so the API layer can 400 on an unrecognized value
# BEFORE shelling out, and so `GET /api/health` can serve them live to the frontend.
VERDICTS: tuple[str, ...] = ("attest", "attest_with_reservations", "refuse")
INDEPENDENCE_VALUES: tuple[str, ...] = ("self-review", "technical", "managerial", "financial")

# Status vocabulary a decomposition item's live disposition renders as.
STATUS_VALUES: tuple[str, ...] = ("OPEN", "WITNESSED", "PARTIAL", "COSIGNED", "AMBIGUOUS")


def _connect_unrestricted(cfg: PanelConfig) -> psycopg.Connection:
    """A connection that deliberately does NOT `SET ROLE` -- used only for the `stamp_secret`
    armed-check (that table is REVOKEd from the subject role on purpose; checking under `SET
    ROLE` would always raise `permission denied`, not report False). Caller must close it."""
    return psycopg.connect(cfg.connection.conninfo(), row_factory=dict_row, autocommit=True)


def autoharn_health(cfg: PanelConfig) -> dict[str, Any]:
    """The autoharn-specific slice of `GET /api/health` (mixed into core's health payload by
    `routes.py` only when this extension is enabled)."""
    conn = _connect_unrestricted(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(f'SET search_path = "{cfg.schema}", "{cfg.kern_schema}"')
            cur.execute(f'SELECT EXISTS (SELECT 1 FROM "{cfg.kern_schema}".stamp_secret) AS armed')
            armed = bool(cur.fetchone()["armed"])
    finally:
        conn.close()
    return {
        "stamp_secret_armed": armed,
        "verdicts": list(VERDICTS),
        "independence_values": list(INDEPENDENCE_VALUES),
    }


def recent_ledger(cfg: PanelConfig, n: int) -> list[dict[str, Any]]:
    # `n` feeds straight into a LIMIT clause below -- same vulnerability class as `/api/rows`'
    # `limit` (Postgres raises an unhandled 500 on a negative LIMIT; cycle-3 consult finding 2,
    # fixed for `rows()` in commit 0d9aa7e). Not currently called by the frontend, but validated
    # the same way (raise ValueError) so a future caller -- HTTP route or otherwise -- gets a
    # clean 400 rather than a raw DB error, matching `rows()`'s convention.
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.id, l.kind, l.statement, p.name AS actor_name, l.ts, l.stamp_verified
            FROM ledger_current l LEFT JOIN principal p ON p.id = l.actor
            ORDER BY l.id DESC LIMIT %s
            """,
            (n,),
        )
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


def work_items(cfg: PanelConfig) -> list[dict[str, Any]]:
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


def review_gap(cfg: PanelConfig) -> list[dict[str, Any]]:
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM review_gap ORDER BY id")
        rows = cur.fetchall()
    return [jsonable(r) for r in rows]


def work_violations(cfg: PanelConfig) -> list[dict[str, Any]]:
    """`work_item_violations` -- the kernel's own live "what's currently wrong right now" signal
    (cycle-4 audit finding 10, SERIOUS): every currently-unresolved decomposition-tree violation
    (duplicate opens, dangling dependency/parent refs, dependency/parent/blocks-close cycles, a
    shipped close with no witness, an opening act orphaned by a later retraction, or a composite
    closed while its own child tree still blocks it) that has NOT already been disposed of via a
    `work_violation_disposition` row -- the view's own definition filters those out via a
    `disposition_basis_holds` join, so every row this returns is a live, undisposed violation, not
    a historical one. Empty in this deployment today, same honest-narrow-columns shape as
    `review_gap`/`question_status` above: the view carries only `violation, slug, detail,
    target_id`, no id/ts/actor of its own. `target_id` is always populated (the view's own final
    SELECT inner-joins it against `ledger_current`) and doubles as this tab's row-click target
    (mirroring `review_gap`'s `id` column serving the same role in ReviewGapTab.vue) -- ordered by
    it so the same violation instance holds a stable position across polls, there being no id
    column of the view's own to order by."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT violation, slug, detail, target_id FROM work_item_violations "
            "ORDER BY target_id, violation, slug"
        )
        rows = cur.fetchall()
    return [jsonable(r) for r in rows]


def question_status(cfg: PanelConfig) -> list[dict[str, Any]]:
    """`question_status` (the kernel view) plus each question row's own `statement` text, joined
    in here from `ledger_current` rather than widening the kernel view itself -- that view ships
    from autoharn's own kernel lineage SQL, applied once at --new-world scaffold time, and is not
    owned by this repo (row:660's decision). `question_id` always resolves against
    `ledger_current` because the view's own definition selects `question_id` FROM
    `ledger_current` in the first place, so this join can never silently drop a row. Addresses
    cycle-4 audit finding 11 (MINOR): the Questions tab's table showed no snippet of the actual
    question TEXT, forcing a click-through just to learn what was asked (work item
    questions-inline-text, row:633)."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT qs.*, l.statement
            FROM question_status qs
            JOIN ledger_current l ON l.id = qs.question_id
            ORDER BY qs.question_id
            """
        )
        rows = cur.fetchall()
    return [jsonable(r) for r in rows]


def ledger_row(cfg: PanelConfig, row_id: int) -> dict[str, Any] | None:
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


def work_item(cfg: PanelConfig, slug: str) -> dict[str, Any] | None:
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


def maintainer_cosigned(cfg: PanelConfig, target_row_id: int) -> dict[str, Any] | None:
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


def latest_review_id(cfg: PanelConfig, regards: int, actor_name: str) -> int | None:
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


def resolve_witness(cfg: PanelConfig, ref_kind: str, ref: str) -> tuple[WitnessFacts, dict[str, Any] | None]:
    if ref_kind == "work":
        resolved = work_item(cfg, ref)
        if resolved is None:
            return WitnessFacts(ref_kind, ref, exists=False, substantive=False,
                                 cosign_target_row=None, maintainer_cosigned=False), None
        closed_row_id = resolved.get("closed_row_id")
        substantive = resolved.get("state") == "closed"
        cosigned = False
        if closed_row_id is not None:
            cosigned = maintainer_cosigned(cfg, closed_row_id) is not None
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
        resolved = ledger_row(cfg, row_id)
        if resolved is None:
            return WitnessFacts(ref_kind, ref, exists=False, substantive=False,
                                 cosign_target_row=None, maintainer_cosigned=False), None
        cosigned = maintainer_cosigned(cfg, row_id) is not None
        facts = WitnessFacts(
            ref_kind, ref, exists=True, substantive=True,
            cosign_target_row=row_id, maintainer_cosigned=cosigned,
        )
        return facts, resolved
    raise ValueError(f"unknown ref_kind {ref_kind!r} (expected 'work' or 'row')")


def cosign_fact(cfg: PanelConfig, target_row_id: int) -> dict[str, Any]:
    disc = maintainer_cosigned(cfg, target_row_id)
    if disc:
        return {"cosigned": True, "by": disc["actor_name"], "review_id": disc["review_id"], "verdict": disc["verdict"]}
    return {"cosigned": False, "by": None, "review_id": None, "verdict": None}


def reviews_for_row(cfg: PanelConfig, row_id: int) -> list[dict[str, Any]]:
    """The item view's "review/co-sign history with actor + independence badges"
    (SPEC.md sec 2.2): every live `review` row whose `regards` points at `row_id`, joined to its
    typed `review_detail` payload -- NOT narrowed to maintainer/attest the way `maintainer_cosigned`
    is, since the item view renders the full history, not just the discharge-relevant fact."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id AS review_id, r.ts, p.name AS actor_name,
                   d.verdict, d.independence, d.basis
            FROM ledger_current r
            JOIN review_detail d ON d.ledger_id = r.id
            LEFT JOIN principal p ON p.id = r.actor
            WHERE r.kind = 'review' AND r.regards = %s
            ORDER BY r.id
            """,
            (row_id,),
        )
        rows = cur.fetchall()
    return [jsonable(r) for r in rows]


@dataclass(frozen=True)
class ResolvedWitness:
    ref_kind: str
    ref: str
    resolved: dict[str, Any] | None
    cosign_target_row: int | None
    cosign: dict[str, Any]
    facts: WitnessFacts


def resolve_item_witnesses(cfg: PanelConfig, witness_refs: tuple[tuple[str, str], ...]) -> list[ResolvedWitness]:
    out: list[ResolvedWitness] = []
    for ref_kind, ref in witness_refs:
        facts, resolved = resolve_witness(cfg, ref_kind, ref)
        cosign_info: dict[str, Any] = {"cosigned": False, "by": None, "review_id": None, "verdict": None}
        if facts.cosign_target_row is not None:
            cosign_info = cosign_fact(cfg, facts.cosign_target_row)
        out.append(
            ResolvedWitness(
                ref_kind=ref_kind, ref=ref, resolved=resolved,
                cosign_target_row=facts.cosign_target_row, cosign=cosign_info, facts=facts,
            )
        )
    return out


# ---------------------------------------------------------------------------------------------
# Decomposition-row reading (the frozen `panel-item:<commission_row>:<item_id>` refs grammar).
# `parse_item_refs` is the ONE anchored parser of that grammar in this tree.
# ---------------------------------------------------------------------------------------------

_PANEL_ITEM_TOKEN_RE = re.compile(r"^panel-item:(?P<cid>\d+):(?P<iid>[A-Za-z0-9_-]+)$")
_ROW_TOKEN_RE = re.compile(r"^row:(?P<id>\d+)$")
_WORK_TOKEN_RE = re.compile(r"^work:(?P<slug>[A-Za-z0-9_.-]+)$")


def row_refs_text(cfg: PanelConfig, row_id: int) -> str | None:
    """The raw `refs` text of ONE ledger row -- `ledger_row`/`work_item` above deliberately don't
    select it (they answer narrower questions), so the item view's generic witness-ref reader
    gets its own minimal query rather than widening either of those."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute("SELECT refs FROM ledger_current WHERE id = %s", (row_id,))
        row = cur.fetchone()
    return row["refs"] if row else None


def parse_witness_refs(refs_text: str | None) -> list[tuple[str, str]]:
    """Generic `row:<id>` / `work:<slug>` witness-token extraction from ANY row's `refs` text --
    unlike `parse_item_refs`, this does NOT require a wrapping `panel-item:<commission>:...`
    token. Used by the item view (SPEC.md sec 2.2's "disposition/witness edges") to show
    witness/co-sign edges for an arbitrary ledger row, not just a decomposition item row."""
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


def item_witnesses(cfg: PanelConfig, row_id: int) -> list[ResolvedWitness]:
    """`row_id`'s own `refs` text, read generically (`parse_witness_refs`) and resolved the same
    way a decomposition item's witnesses are (`resolve_item_witnesses`) -- the item view's witness
    panel for an arbitrary row, e.g. a `work_closed` row's `--witness row:<n>` token."""
    witness_refs = tuple(parse_witness_refs(row_refs_text(cfg, row_id)))
    return resolve_item_witnesses(cfg, witness_refs)


def parse_item_refs(refs_text: str | None, commission_row: int) -> tuple[str | None, list[tuple[str, str]]]:
    """PURE, anchored, fail-closed parser (see disposition.py's module docstring for the full
    rationale, ported unchanged from the autoharn PoC): a `refs` string that does not carry
    EXACTLY ONE well-formed `panel-item:<commission_row>:...` token returns `(None, [])`."""
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


@dataclass(frozen=True)
class ParsedItemRow:
    row_id: int
    item_id: str
    witness_refs: tuple[tuple[str, str], ...]
    statement: str
    actor_name: str | None
    ts: str


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


def fetch_parsed_item_rows(cfg: PanelConfig, commission_row: int) -> tuple[ParsedItemRow, ...]:
    """Decomposition items for `commission_row`, read under BOTH conventions this deployment's
    history carries (CLAUDE.md point 1 antecedent-audit finding, row:249):

    1. The PoC-era `panel-item:<commission_row>:<item_id>` token grammar on a `note` row
       (unchanged -- kept for any historical data that used it).
    2. This deployment's actual, documented convention: a plain `work_opened` row whose `refs`
       carries a bare `row:<commission_row>` token (`./led work open <slug> <title> --refs
       row:<commission>`, CLAUDE.md point 1). Its `item_id` is the work item's own `work_slug`
       (already unique-by-construction -- kernel/lineage's `work_opened` trigger refuses a second
       opening act for the same slug, s29-pre-amendment.sql:390-391), and its implied witness is
       the work item itself (`("work", work_slug)`) PLUS any other `row:`/`work:` witness tokens
       already in its `refs` text (excluding the `row:<commission_row>` token itself, which names
       the item's parent commission, not something that witnesses the item's own completion).
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


def item_id_groups(cfg: PanelConfig, commission_row: int) -> dict[str, tuple[int, ...]]:
    return group_item_rows(tuple((r.item_id, r.row_id) for r in fetch_parsed_item_rows(cfg, commission_row)))


@dataclass(frozen=True)
class ResolvedItem:
    item_id: str
    row_id: int
    label: str
    actor_name: str | None
    ts: str
    status: str
    item_cosign: dict[str, Any]
    witnesses: list[ResolvedWitness]


@dataclass(frozen=True)
class AmbiguousItem:
    item_id: str
    candidate_row_ids: tuple[int, ...]


Item = ResolvedItem | AmbiguousItem


@dataclass(frozen=True)
class DecompositionItems:
    commission_row: int
    items: tuple[Item, ...]


def commissions(cfg: PanelConfig) -> list[dict[str, Any]]:
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.id, l.statement, l.ts, p.name AS actor_name
            FROM ledger_current l LEFT JOIN principal p ON p.id = l.actor
            WHERE l.kind = 'commission'
            ORDER BY l.id
            """
        )
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        row_id = row["id"]
        item_count = len(item_id_groups(cfg, row_id))
        ts = row["ts"]
        out.append(
            {
                "row_id": row_id,
                "statement": row["statement"],
                "actor_name": row["actor_name"],
                "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
                "item_count": item_count,
            }
        )
    return out


def decomposition_items(cfg: PanelConfig, commission_row: int) -> DecompositionItems:
    parsed_rows = fetch_parsed_item_rows(cfg, commission_row)
    groups = group_item_rows(tuple((r.item_id, r.row_id) for r in parsed_rows))
    by_row_id = {r.row_id: r for r in parsed_rows}
    items: list[Item] = []
    for item_id, row_ids in groups.items():
        if len(row_ids) == 1:
            r = by_row_id[row_ids[0]]
            resolved_witnesses = resolve_item_witnesses(cfg, r.witness_refs)
            item_row_cosigned = maintainer_cosigned(cfg, r.row_id) is not None
            status = derive_status(item_row_cosigned, [rw.facts for rw in resolved_witnesses])
            items.append(
                ResolvedItem(
                    item_id=item_id,
                    row_id=r.row_id,
                    label=r.statement,
                    actor_name=r.actor_name,
                    ts=r.ts,
                    status=status,
                    item_cosign=cosign_fact(cfg, r.row_id),
                    witnesses=resolved_witnesses,
                )
            )
        else:
            items.append(AmbiguousItem(item_id=item_id, candidate_row_ids=tuple(sorted(row_ids))))
    return DecompositionItems(commission_row=commission_row, items=tuple(items))
