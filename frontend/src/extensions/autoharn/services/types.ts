// src/extensions/autoharn/services/types.ts -- hand-authored AUTOHARN-SEMANTIC wire shapes
// (obligation/commission/cosign/kernel vocabularies) -- SPEC.md sec 4 extension boundary: these
// concepts do not exist in core. Read directly off `backend/extensions/autoharn/routes.py` +
// `backend/extensions/autoharn/ledger_read.py` + `backend/extensions/autoharn/cosign.py` (the
// vanilla PoC's `app.js` documented these as "frozen wire shapes" in its own header comment --
// restated here for the Vue app, not invented).
//
// Same lint-boundary confinement as core/services/types.ts: this is the ONE place autoharn
// wire shapes are declared; nothing outside a `services/` directory may reach for the generated
// schema types or `openapi-fetch` directly (see scripts/lint-boundaries.mjs).

import type { LedgerRow } from '../../../core/services/types'

export interface Commission {
  row_id: number
  statement: string
  actor_name: string | null
  ts: string | null
  item_count: number
}

export type ItemStatus = 'OPEN' | 'WITNESSED' | 'PARTIAL' | 'COSIGNED' | 'AMBIGUOUS'

export interface CosignInfo {
  cosigned: boolean
  by: string | null
  review_id: number | null
  verdict: string | null
}

export interface Witness {
  ref_kind: string
  ref: string
  resolved: boolean
  substantive: boolean
  cosign_target_row: number | null
  cosign: CosignInfo | null
}

export interface DecompositionItem {
  row_id: number | null
  item_id: string
  label: string | null
  status: ItemStatus
  cosign: CosignInfo | null
  witnesses: Witness[]
  ambiguous_row_ids: number[] | null
}

export interface CommissionDetail {
  commission_row: number
  commission: LedgerRow | null
  items: DecompositionItem[]
}

export interface WorkItemRow {
  slug: string
  title: string | null
  state: string | null
  resolution: string | null
  witness: string | null
  claimant_name: string | null
}

// review_gap: the live kernel view this route selects from (kernel/lineage s15-schema.sql at
// the time of this port) does NOT carry statement/ts/actor_name -- the vanilla PoC's app.js
// assumed it did (a stale assumption in that file, not reproduced here). Its real, narrower
// columns:
export interface ReviewGapRow {
  id: number // the ledger row (the statement) the countersign obligation is against
  actor: number // principal id owing the countersign -- NOT joined to a name by this view
  scope: string
  assigned_by: number
}

// question_status: the kernel view itself carries only question_id/question_kind/answered/
// first_answer_id/answers_target_not_a_question (same narrow-columns note as ReviewGapRow
// above -- ts/actor_name are still absent). `statement` below is NOT one of the view's own
// columns: backend/extensions/autoharn/ledger_read.py's question_status() joins it in from
// ledger_current (cycle-4 audit finding 11, work item questions-inline-text) so the Questions
// tab can show a snippet of the actual question text instead of a click-through.
export interface QuestionRow {
  question_id: number
  question_kind: string
  answered: boolean
  first_answer_id: number | null
  answers_target_not_a_question: boolean
  statement: string
}

export interface CosignRequest {
  row_id: number
  verdict: string
  independence: string
  basis: string
}

export interface CosignResponse {
  ok: boolean
  exit_code: number
  stdout: string
  stderr: string
  review_id: number | null
}

// GET /api/item/{row_id}/obligations (backend/extensions/autoharn/routes.py's
// api_item_obligations) -- the item view's (SPEC.md sec 2.2) autoharn-semantic enrichment of a
// core ledger row: review/co-sign history, whether the row itself is maintainer-cosigned, and
// its own `refs` resolved generically as witness tokens (same `Witness` shape the commission
// decomposition view already uses).
export interface ReviewRecord {
  review_id: number
  ts: string | null
  actor_name: string | null
  verdict: string
  independence: string
  basis: string
}

export interface ItemObligations {
  row_id: number
  cosign: CosignInfo
  reviews: ReviewRecord[]
  witnesses: Witness[]
}
