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

// Commission attribution strength (cycle-4 audit finding 7, MODERATE; design/USER-GPG-TRUST-
// LAYER-FAQ.md's ladder LAZY < FULL < SIGNED) -- `lazy`/`full`/`signed` are the three rungs, plus
// two honest failure tiers a real deployment can hit once a signature IS banked: `forged` (a
// checkable cryptographic mismatch -- LOUD, never silently shown as a lesser trust level) and
// `unverifiable` (a signature is claimed but nothing can check it here -- no committed key, or
// gpg unavailable). Backend: extensions.autoharn.ledger_read.commission_trust.
export type CommissionTrustLevel = 'lazy' | 'full' | 'signed' | 'forged' | 'unverifiable'

export interface Commission {
  row_id: number
  statement: string
  actor_name: string | null
  ts: string | null
  item_count: number
  trust_level: CommissionTrustLevel
  trust_detail: string | null
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
  trust_level: CommissionTrustLevel | null
  trust_detail: string | null
}

// work_item_current (joined with `principal` for claimant_name, plus `blocked_by` merged in
// from work_edge_blocks_close): extensions.autoharn.ledger_read.work_items, GET /api/work.
// `effective_state`/`parent_slug`/`blocked_by` added by work-item-relations-api (commit
// 0a0e869) -- this interface was left stale vs the wire until now (compliance-review finding
// row:745 item 5, countersigned row:747). `effective_state` is the kernel's composite-discharge
// derivation (Autoharn.idr s33): differs from raw `state` only for a fully-closed-via-children
// parent (value `discharged-by-obligations`) whose own `state` column stays `open` by kernel
// design. `blocked_by` is always an array (work_items() defaults it to `[]` via a dict .get
// fallback in Python), never null/undefined.
export interface WorkItemRow {
  slug: string
  title: string | null
  state: string | null
  effective_state: string | null
  resolution: string | null
  witness: string | null
  parent_slug: string | null
  claimant_name: string | null
  blocked_by: string[]
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

// work_item_violations: the kernel's own live "what's currently wrong right now" signal (cycle-4
// audit finding 10, SERIOUS) -- every currently-unresolved decomposition-tree violation not yet
// disposed of via a work_violation_disposition row. Same honest-narrow-columns note as
// ReviewGapRow/QuestionRow above: no id/ts/actor of its own. `target_id` is always populated (the
// view's own final SELECT inner-joins it against ledger_current) and doubles as the row-click
// target this tab expands, mirroring review_gap's own `id` column.
export interface WorkViolationRow {
  violation: string
  slug: string
  detail: string | null
  target_id: number
}

// GET /api/findings-snags (extensions.autoharn.ledger_read.findings_and_snags): kind='finding'
// or kind='snag' rows, the SAME id/kind/statement/actor_name/ts/stamp_verified shape
// recent_ledger() returns (core.LedgerRow doesn't quite fit -- it has no stamp_verified field
// and its `refs`/`supersedes` are absent from this narrower query), narrowed by kind. ONE
// combined view for both kinds rather than two (row:704's decision) -- `kind` is still carried
// per-row so the tab can render a distinguishing badge.
export interface FindingSnagRow {
  id: number
  kind: 'finding' | 'snag'
  statement: string
  actor_name: string | null
  ts: string | null
  stamp_verified: boolean
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

// A `resource:`-prefixed decision statement's six pipe-delimited fields (design/USER-BLESSED-
// TABLE-TEMPLATE.md's "statement grammars" section), parsed server-side by
// `extensions.autoharn.ledger_read.parse_resource_fields` and carried on `ItemObligations` below
// -- `null` for any row that isn't a `resource:` statement, or is one but doesn't parse cleanly
// (cycle-4 audit finding 6, SERIOUS: the item view rendered every statement, including these, as
// one undifferentiated prose blob). `tier_kind` is the normalized badge class the backend
// derives from `tier`'s leading word (`available | blessed | mandated | forbidden`); `tier`
// itself keeps the full raw field (e.g. `blessed: <task-shape>`) so the task-shape detail is
// never lost to the badge's coarser classification.
export type ResourceTierKind = 'available' | 'blessed' | 'mandated' | 'forbidden'

export interface ResourceFields {
  name: string
  class_: string
  reach: string
  what_it_proves: string
  guidance: string
  tier: string
  tier_kind: ResourceTierKind
}

export interface ItemObligations {
  row_id: number
  cosign: CosignInfo
  reviews: ReviewRecord[]
  witnesses: Witness[]
  resource_fields: ResourceFields | null
}
