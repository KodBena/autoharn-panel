<!--
  src/core/components/LedgerTab.vue -- "recent ledger" tab, CORE-GENERIC (SPEC.md sec 4
  extension boundary: rows/kinds/refs/supersession only, no autoharn vocabulary). Built on
  `GET /api/rows` (core.routes) rather than the extension's `/api/ledger/recent` -- that
  extension route selects from `ledger_current` (supersede-filtered with NO way to ask for the
  superseded rows back), so it cannot carry the mandated superseded-toggle (SPEC.md sec 2.1).
  `/api/rows` already supports `include_superseded` + `kind`/`q` filters, i.e. it IS this app's
  reduced-scope stand-in for the Board view (SPEC.md sec 2.1) -- generalizing this tab a little
  (a kind filter, free-text search) was cheaper and more spec-faithful than reproducing the
  extension route's narrower, toggle-incapable shape.

  This is also the one tab exercising all three "cheap maintainer verdicts" at once: no-elision
  (DataTable's cell styling), the superseded toggle (below), and virtualization above 200 rows
  (DataTable switches automatically -- raise `limit` past 200 to see it exercised).
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../services/api-client'
import type { Column } from './DataTable.vue'
import DataTable from './DataTable.vue'
import { useLiveUpdates } from '../composables/useLiveUpdates'
import { fmtTs } from '../../utils/format'

const rows = ref<Record<string, unknown>[]>([])
const error = ref<string | null>(null)
const includeSuperseded = ref(false)
const kindFilter = ref('')
// Live kind vocabulary for the dropdown below -- fetched from the backend's own facet-counts
// query (SPEC.md sec 0 forbids a hand-copied kind enum in the frontend: the vocabulary lives in
// the ledger, not in this file). Counts are over CURRENT rows only (ledger_read.facet_counts),
// so a kind that only ever appears superseded won't show here -- an acceptable narrowing for a
// filter dropdown, not a correctness bug: filtering TO a kind only superseded rows carry is not
// a scenario the "show superseded rows" toggle changes the *available kinds* for anyway.
const kindOptions = ref<string[]>([])
const actorFilter = ref('')
const sinceFilter = ref('')
const untilFilter = ref('')
const limit = ref(200)
const offset = ref(0)
const sortBy = ref<'id' | 'ts' | 'kind' | 'actor'>('id')
const sortDir = ref<'asc' | 'desc'>('desc')

const { tick } = useLiveUpdates()

const columns: Column[] = [
  { key: 'id', label: 'id', mono: true, width: '4.5rem', sortKey: 'id' },
  { key: 'kind', label: 'kind', width: '8rem', sortKey: 'kind' },
  { key: 'actor_name', label: 'actor', width: '9rem', sortKey: 'actor' },
  { key: 'ts_fmt', label: 'ts', mono: true, width: '11rem', sortKey: 'ts' },
  { key: 'statement', label: 'statement', width: '3fr', richText: true },
]

// A full page (rows.length === limit) means there MAY be a next page -- this endpoint has no
// total-count field to compare against, so "has more" is inferred the same way any offset/limit
// API without a count does: fetch one page, and if it's full, offer Next (the Next fetch itself
// will come back short/empty when there truly is nothing further).
const hasNextPage = computed(() => rows.value.length === limit.value)
const hasPrevPage = computed(() => offset.value > 0)
const pageNumber = computed(() => Math.floor(offset.value / limit.value) + 1)

// limit=0 is valid REST-wise (the API correctly returns zero rows) but reads as a genuine
// no-matches result unless called out -- a fat-fingered 0 in the limit field otherwise looks
// identical to an over-narrow kind/actor/date filter.
const emptyText = computed(() =>
  limit.value === 0
    ? 'Limit is set to 0 -- increase it to see rows.'
    : 'No ledger rows match this filter.',
)

function goToNextPage(): void {
  if (hasNextPage.value) offset.value += limit.value
}
function goToPrevPage(): void {
  offset.value = Math.max(0, offset.value - limit.value)
}
function onSortChange(key: string): void {
  const k = key as 'id' | 'ts' | 'kind' | 'actor'
  if (sortBy.value === k) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = k
    sortDir.value = 'desc'
  }
}

// Rows whose id appears as some OTHER row's `supersedes` value, within the currently fetched
// page, are superseded -- this endpoint does not stamp that fact onto the row itself, so it is
// derived client-side from the page in hand (a known, documented limitation: a row superseded
// by a row outside the current page/limit window will not be recognized as such here).
const supersededIds = computed(() => {
  const s = new Set<string | number>()
  for (const r of rows.value) {
    const sup = (r as Record<string, unknown>).supersedes
    if (typeof sup === 'number') s.add(sup)
  }
  return s
})

// cycle-2 consult finding 3 (row:437, rescoped by row:456): the unfiltered default view
// measured 54,842px scrollHeight because long free-text `statement` values render in full, with
// no truncation anywhere upstream. DataTable.vue/DataRow.vue carry an explicit no-elision
// commitment shared by EVERY tab (see DataTable.vue's own header comment), so this cannot be
// fixed by changing those shared files -- the fix has to live entirely in this tab: truncate the
// `statement` VALUE itself before it is handed to DataTable, and use the row-click emit (already
// wired by DataTable/DataRow but left unused by this tab until now) to toggle a per-row expanded
// state. Nothing is permanently hidden -- every row's full text is one click away, and the
// toggle is local prop/state, not a DataTable/DataRow behavior change.
const STATEMENT_TRUNCATE_AT = 240
const expandedIds = ref<Set<number>>(new Set())

function toggleExpand(rowId: string | number): void {
  const id = Number(rowId)
  if (Number.isNaN(id)) return
  if (expandedIds.value.has(id)) expandedIds.value.delete(id)
  else expandedIds.value.add(id)
}

function displayStatement(r: Record<string, unknown>): string {
  const text = typeof r.statement === 'string' ? r.statement : ''
  if (text.length <= STATEMENT_TRUNCATE_AT) return text
  const id = r.id as number
  if (expandedIds.value.has(id)) return `${text}  [click row to collapse]`
  return `${text.slice(0, STATEMENT_TRUNCATE_AT)}… [click row to expand -- ${text.length} chars total]`
}

const displayRows = computed(() =>
  rows.value.map((r) => ({ ...r, ts_fmt: fmtTs(r.ts as string | null), statement: displayStatement(r) })),
)

async function loadKindOptions(): Promise<void> {
  const { data, error: err } = await api.GET('/api/rows/facet-counts')
  if (err || !data) return
  kindOptions.value = Object.keys(data).sort()
}

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/rows', {
      params: {
        query: {
          include_superseded: includeSuperseded.value,
          kind: kindFilter.value || undefined,
          actor: actorFilter.value || undefined,
          since: sinceFilter.value || undefined,
          until: untilFilter.value || undefined,
          sort_by: sortBy.value,
          sort_dir: sortDir.value,
          limit: limit.value,
          offset: offset.value,
        },
      },
    })
    if (err) throw err
    rows.value = (data ?? []) as Record<string, unknown>[]
    error.value = null
    updatesAvailable.value = false
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

// Any facet/sort change re-queries from the first page -- an offset carried over from a
// DIFFERENT filter's result set would silently show a nonsensical page (e.g. "page 3" of a
// filter that only has one page), so every filter/sort input resets `offset` before reloading.
// Pagination (`goToNextPage`/`goToPrevPage`) is the only path that changes `offset` on purpose;
// `offset` itself is watched separately below (last, or the reset here would fight the load).
watch([includeSuperseded, kindFilter, actorFilter, sinceFilter, untilFilter, limit, sortBy, sortDir], () => {
  offset.value = 0
  load()
})
watch(offset, load)

onMounted(() => {
  loadKindOptions()
  load()
})
// This tab is mounted only while its own tab panel is visible (App.vue uses v-if per tab), so
// watching the shared `tick` here would refetch only THIS view's data, on ledger change -- no
// other tab does extra work because this one is open (SPEC.md sec 3: "no view refetches more
// than its own visible data").
//
// It used to call `load()` directly on every tick (silent full refetch/rerender under an
// actively-reading operator, no toast, no way to opt out -- the consult's live-update-UX
// finding). Instead, a tick now only raises a discrete "updates available" banner; the refetch
// itself is deferred until the operator clicks it. This is the row:247 decision's chosen
// affordance (banner over pause-on-scroll): LedgerTab has no row-expansion/scroll-position state
// to pause against, just a flat paginated table, so "click to load" is the smaller change that
// fits the tab's existing manual-refresh pattern.
const updatesAvailable = ref(false)
watch(tick, () => {
  updatesAvailable.value = true
})
async function applyPendingUpdates(): Promise<void> {
  updatesAvailable.value = false
  await load()
}

defineExpose({ reload: load })
</script>

<template>
  <section class="panel">
    <h2>
      Recent ledger
      <span class="refresh-row">
        <button @click="load">Refresh</button>
      </span>
    </h2>
    <div class="commission-picker">
      <label for="kind-filter">kind:</label>
      <select id="kind-filter" v-model="kindFilter" style="width: 8rem">
        <option value="">(any)</option>
        <option v-for="k in kindOptions" :key="k" :value="k">{{ k }}</option>
      </select>
      <label for="actor-filter">actor:</label>
      <input id="actor-filter" v-model="actorFilter" type="text" placeholder="(any)" style="width: 8rem" />
      <label for="since-filter">since:</label>
      <input id="since-filter" v-model="sinceFilter" type="date" style="width: 9.5rem" />
      <label for="until-filter">until:</label>
      <input id="until-filter" v-model="untilFilter" type="date" style="width: 9.5rem" />
      <label class="toggle-row">
        <input v-model="includeSuperseded" type="checkbox" />
        show superseded rows
      </label>
      <label for="row-limit">limit:</label>
      <input id="row-limit" v-model.number="limit" type="number" min="1" style="width: 5.5rem" />
    </div>
    <p class="muted" style="font-size: 0.8rem">
      Long statements are truncated by default -- click a row to expand or collapse its full text.
    </p>
    <div class="live-update-banner" role="status" aria-live="polite">
      <button v-if="updatesAvailable" type="button" class="live-update-banner__btn" @click="applyPendingUpdates">
        Updates available -- click to load
      </button>
    </div>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <div class="expandable-ledger-table">
      <DataTable
        :columns="columns"
        :rows="displayRows"
        :row-key="(r) => r.id as number"
        :superseded-ids="supersededIds"
        :sort-by="sortBy"
        :sort-dir="sortDir"
        :empty-text="emptyText"
        @sort-change="onSortChange"
        @row-click="toggleExpand"
      />
    </div>
    <div class="commission-picker pagination-row">
      <button :disabled="!hasPrevPage" @click="goToPrevPage">Prev</button>
      <span class="muted">page {{ pageNumber }} (offset {{ offset }})</span>
      <button :disabled="!hasNextPage" @click="goToNextPage">Next</button>
    </div>
  </section>
</template>

<style scoped>
/* Local-only affordance for the truncate/expand toggle above -- a cursor hint that ledger rows
   are clickable in THIS tab. Deep-scoped to reach DataRow.vue's own <tr>/.vg-row markup, but the
   selector and rule live entirely in this file's own scoped style block; DataRow.vue's file and
   its default (non-interactive) cursor for every other tab are untouched. */
.expandable-ledger-table :deep(tr),
.expandable-ledger-table :deep(.vg-row) {
  cursor: pointer;
}
</style>
