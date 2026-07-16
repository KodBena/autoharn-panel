"""extensions.autoharn.queue_views_reader -- `QueueViewsReader`, one of the four internal
collaborators `extensions/autoharn/ledger_adapter.py`'s former 1050-line/25-method god-class
(`PostgresAutoharnLedgerReader`) split into (work item autoharn-god-module-split, ledger row
935/1094; the 4-way split itself is row:926's assumption, "not the audit's literally-named 3").

Collaborator (d): the flat, read-only queue-view reads -- `autoharn_health`, `recent_ledger`,
`review_gap`, `work_violations`, `findings_and_snags`, `question_status`, `standing_decisions`
(7 of the Protocol's 25 methods). Each is a single SQL query (or, for `autoharn_health`, a single
armed-check) with no recursion, no cross-item composition, and no dependency on any other
collaborator -- the most self-contained of the four. Bodies are VERBATIM from the god-class
(ADR-0004 minimal-touch); only their file moved.

`PostgresAutoharnLedgerReader` (`ledger_adapter.py`) composes one `QueueViewsReader` instance and
delegates each of these 7 Protocol methods to it -- this class is never imported or constructed
directly by any route handler or test (routes.py/app.py/cosign.py all depend on the
`AutoharnLedgerPort` Protocol type, satisfied by the facade, never on this class).
"""
from __future__ import annotations

from typing import Any

from config import PanelConfig
from db import connect_unrestricted
from extensions.autoharn._shared import _fetch_jsonable_rows
from extensions.autoharn.ports import INDEPENDENCE_VALUES, VERDICTS


class QueueViewsReader:
    """Owns the flat, read-only queue-view reads -- no fields, no constructor arguments, exactly
    like the facade it composes into (see module docstring)."""

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
