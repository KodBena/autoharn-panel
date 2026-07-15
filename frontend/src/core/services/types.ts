// src/core/services/types.ts -- hand-authored CORE-GENERIC wire shapes (ledger-generic:
// rows/kinds/refs/supersession/watermark/health), AUGMENTING the generated (loose) client.
//
// See api-client.ts's header comment for why hand types exist at all: the backend's routes
// return `dict[str, Any]`, so `schema.d.ts`'s generated response types carry little
// information. These shapes are read directly off `backend/core/routes.py` +
// `backend/core/ledger_read.py`. If the backend ever adds a Pydantic response_model, these can
// be deleted in favor of the generated ones; until then this file is the single place a core
// wire-shape drift would need to be reconciled by hand.
//
// Architecture-lint boundary (see scripts/lint-boundaries.mjs): wire shapes live ONLY inside a
// `services/` directory (this file, and its `extensions/autoharn/services/types.ts` sibling)
// plus the one client alias (`api-client.ts`) -- nothing outside a `services/` directory may
// import the generated `schema` types or `openapi-fetch` directly. Everything else consumes
// these hand types or calls through the shared `api` client export.

export interface LedgerRow {
  id: number
  kind: string
  statement: string
  ts: string | null
  refs: string | null
  supersedes: number | null
  actor_name: string | null
  // present only on /api/rows/{id} (core.routes.api_row enriches the base row with these)
  ref_row_ids?: number[]
  predecessors?: number[]
  successor?: number | null
}

export interface Watermark {
  max_id: number | null
  max_ts: string | null
  count: number
}

export interface FacetCounts {
  [kind: string]: number
}

export interface AutoharnHealth {
  stamp_secret_armed: boolean
  verdicts: string[]
  independence_values: string[]
}

export interface Health {
  ok: boolean
  config_source: string
  schema: string
  kern_schema: string
  read_only: boolean
  read_only_reason: 'locked' | 'no-write-conduit' | null
  extensions_enabled: string[]
  active_profile?: string | null
  available_profiles?: string[]
  autoharn?: AutoharnHealth
  maintainer_principal?: string
}

export interface LedgerChangeEvent {
  type: 'ledger-change'
  watermark: Watermark
}
