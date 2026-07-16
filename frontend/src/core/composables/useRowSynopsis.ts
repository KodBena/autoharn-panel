// src/core/composables/useRowSynopsis.ts -- backs the hover synopsis every `row:<id>` citation
// link shows (SPEC.md sec 0/2.1: "hover synopsis everywhere"). A MODULE-LEVEL reactive cache,
// not a per-component ref: the same row:N token routinely appears in more than one statement on
// a single view (a decomposition's items all citing the same commission row, a witness chain
// citing the same predecessor row twice) -- without a shared cache, hovering each citation
// independently would re-fire an identical `GET /api/rows/{id}` fetch every time. First hover
// fetches and caches; every later hover of the same row id (from any citation, in any component)
// reads the cache instantly.
//
// Reuses core's existing `GET /api/rows/{row_id}` (already used by ItemDetail.vue,
// ReviewGapTab.vue, QuestionsTab.vue) rather than adding a new backend route: that endpoint
// already returns exactly what a synopsis needs (statement, actor_name, ts) plus more, and this
// app has no per-view cache of its own to piggyback on (SPEC.md sec 0: "stores nothing
// derivable"), so a small on-demand fetch is the honest shape here, not a missed optimization.
import { reactive } from 'vue'
import { api } from '../services/api-client'
import type { LedgerRow } from '../services/types'

export type RowSynopsisEntry = LedgerRow | 'loading' | 'error'

// Shared across every CitationLink instance mounted anywhere in the app.
const cache = reactive<Record<number, RowSynopsisEntry>>({})

export function useRowSynopsis() {
  function ensureLoaded(rowId: number): void {
    const existing = cache[rowId]
    if (existing && existing !== 'error') return
    cache[rowId] = 'loading'
    api
      .GET('/api/rows/{row_id}', { params: { path: { row_id: rowId } } })
      .then(({ data, error }) => {
        cache[rowId] = !error && data ? (data as unknown as LedgerRow) : 'error'
      })
      .catch(() => {
        cache[rowId] = 'error'
      })
  }

  function get(rowId: number): RowSynopsisEntry | undefined {
    return cache[rowId]
  }

  return { ensureLoaded, get }
}
