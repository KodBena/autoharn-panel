"""extensions.autoharn._shared -- the one genuinely cross-collaborator DB-plumbing helper split
out of `extensions/autoharn/ledger_adapter.py`'s former god-class (work item
autoharn-god-module-split, ledger row 935/1094): `_fetch_jsonable_rows`.

NOT one of the four internal collaborators (`CommissionReader`/`DecompositionReader`/
`WorkObligationReader`/`QueueViewsReader`) -- it carries no business meaning of its own, only
shared connect/execute/fetchall/jsonable plumbing, so per ADR-0012 P1 (single source of truth)
it gets its own tiny home rather than being owned by whichever collaborator happens to call it
most (`QueueViewsReader`, 6 of 7 call sites) while a second collaborator
(`DecompositionReader.reviews_for_row`, the 7th call site) either duplicates it or reaches into a
file that isn't really its concern either. A leading underscore on the module name signals
internal-only plumbing (not part of any Protocol surface), same convention the private
`_word_helpers`-shaped names used inside the original god-class.
"""
from __future__ import annotations

from typing import Any

from config import PanelConfig
from db import connect, jsonable


def _fetch_jsonable_rows(
    cfg: PanelConfig, sql: str, params: tuple[Any, ...] | None = None
) -> list[dict[str, Any]]:
    """Shared connect/execute/fetchall/jsonable-map plumbing for several methods across two
    collaborators whose only real difference is which SQL they run (compliance-review finding 2,
    row:745/747): `QueueViewsReader`'s `recent_ledger`, `review_gap`, `work_violations`,
    `findings_and_snags`, `question_status`, `standing_decisions`, and `DecompositionReader`'s
    `reviews_for_row` were each independently open-coding this exact four-step shape. Pure
    de-duplication of the plumbing -- every caller keeps its own SQL/column selection exactly as
    it was, so this changes nothing about what any endpoint returns.

    Deliberately NOT used by `ledger_row`/`work_item`/`maintainer_cosigned`/`latest_review_id`/
    `row_refs_text`/`commission_trust_for_row` (a `fetchone` single-row shape, not this one, or
    `work_item`'s two-query-in-one-connection shape), nor by `work_items`/`commissions` (fetchall
    plus per-row Python augmentation beyond a bare jsonable map) -- those are genuinely different
    shapes and are left as they were."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [jsonable(r) for r in rows]
