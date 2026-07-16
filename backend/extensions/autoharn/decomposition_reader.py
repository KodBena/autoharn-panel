"""extensions.autoharn.decomposition_reader -- `DecompositionReader`, one of the four internal
collaborators `extensions/autoharn/ledger_adapter.py`'s former 1050-line/25-method god-class
(`PostgresAutoharnLedgerReader`) split into (work item autoharn-god-module-split, ledger row
935/1094; the 4-way split itself is row:926's assumption).

Collaborator (b): decomposition-item parsing plus witness/cosign resolution -- 13 of the
Protocol's 25 methods: `ledger_row`, `work_item`, `maintainer_cosigned`, `latest_review_id`,
`resolve_witness`, `cosign_fact`, `reviews_for_row`, `resolve_item_witnesses`, `row_refs_text`,
`item_witnesses`, `fetch_parsed_item_rows`, `item_id_groups`, `decomposition_items`. This is the
one genuinely internally-coupled cluster in the original god-class (`decomposition_items` calls
`fetch_parsed_item_rows`/`resolve_item_witnesses`/`maintainer_cosigned`/`cosign_fact`;
`resolve_item_witnesses` calls `resolve_witness`/`cosign_fact`; `resolve_witness` calls
`work_item`/`ledger_row`/`maintainer_cosigned`) -- row:959's countersign review specifically
concluded this cluster should NOT be split further even though it is the largest of the four,
since further splitting would leave intermediate PRs in a still-P3-violating half-split state.

`work_item` (singular) and `ledger_row` live here, not in `work_obligation_reader.py` despite
their work-item/ledger-row-sounding names: tracing their ACTUAL callers in the pre-split
god-class (not textual proximity) shows `work_item`'s only caller anywhere is `resolve_witness`
below -- `work_items` (plural) and `obligation_tree` each run their own bulk queries
(`_work_items_by_slug` et al, now in `work_obligation_reader.py`) and never call `work_item`.
`ledger_row` is also called directly by `routes.py`, but its only INTERNAL caller is likewise
`resolve_witness`. Both are the two primitive single-record resolvers witness resolution is
built on, so they belong to this collaborator's concern (row:926's own antecedent-audit note,
verified in this item).

Bodies are VERBATIM from the god-class (ADR-0004 minimal-touch); only their file moved.
`PostgresAutoharnLedgerReader` (`ledger_adapter.py`) composes one `DecompositionReader` instance
and delegates all 13 of these Protocol methods to it; `ledger_adapter.py`'s own `CommissionReader`
collaborator also holds a reference to this class solely to call `item_id_groups` when computing
each commission's `item_count` (the one place collaborator (a) genuinely needs (b)'s result).
"""
from __future__ import annotations

from typing import Any

from config import PanelConfig
from db import connect, jsonable
from extensions.autoharn._shared import _fetch_jsonable_rows
from extensions.autoharn.disposition import group_item_rows
from extensions.autoharn.parsers import _row_token_matches, parse_item_refs, parse_witness_refs
from extensions.autoharn.ports import (
    AmbiguousItem,
    DecompositionItems,
    Item,
    ParsedItemRow,
    ResolvedItem,
    ResolvedWitness,
    WitnessFacts,
)


def _derive_status(item_row_cosigned: bool, witnesses: list[WitnessFacts]) -> str:
    """Logic-identical copy of `disposition.derive_status` (see the former god-class's own module
    docstring's DATACLASS DUPLICATION section for why: it is typed against `ports.WitnessFacts`
    here rather than `disposition.WitnessFacts`, mirroring `tests/fakes/fake_autoharn_ledger_reader.py`'s
    own identical `_derive_status` copy and identical reason). Rules (spec sec 5, restated exactly):

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


class DecompositionReader:
    """Owns decomposition-item parsing and witness/cosign resolution -- no fields, no constructor
    arguments, exactly like the facade it composes into (see module docstring)."""

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
