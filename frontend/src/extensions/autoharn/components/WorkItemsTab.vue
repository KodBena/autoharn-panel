<!--
  src/extensions/autoharn/components/WorkItemsTab.vue -- autoharn-semantic (`work_item_current`,
  claimant/state/resolution vocabulary owned by the kernel, SPEC.md sec 4 extension boundary).
  Backed by `GET /api/work` (extensions.autoharn.routes) -- no superseded concept exposed by
  this view (work items are a derived "current" projection, not raw ledger rows), so no toggle
  here; virtualization + no-elision still apply via the shared DataTable.

  Filter/search/sort (row 440, rescoped by decision row 456): `work_item_current` carries only
  slug/title/state/resolution/witness/claimant_name -- no `kind`, no timestamp -- so this does
  NOT mirror LedgerTab.vue's kind/actor/date-range facets (those columns don't exist here). What
  IS real: a state dropdown, a claimant text filter, and free-text search over slug+title, plus
  sortable slug/state/claimant columns. `GET /api/work` takes no query params and the table is
  ~26 rows today, so all of this is client-side over the already-fetched `rows` (the derived
  `displayRows` below is what actually reaches DataTable) -- no change to DataTable.vue/DataRow.vue
  itself (that pair is in-flight scope for cycle2-ledger-row-truncation, left untouched here).

  Composite-parent/dependency surfacing (work-item-relations-api, consult cycle-4 findings 1+5):
  `GET /api/work` now also carries `effective_state` (the kernel's composite-discharge
  derivation -- a fully-closed-via-children parent shows `effective_state=discharged-by-
  obligations` while its raw `state` stays `open` by kernel design, `Autoharn.idr` s33),
  `parent_slug` (this item's parent, if any), and `blocked_by` (typed `work_edge_blocks_close`
  antecedent slugs -- distinct from parent/child). None of these get their own DataTable/DataRow
  change (still no richText/badge slot added there): `state_label`/`blocked_by_label` below are
  plain derived strings computed INTO `displayRows`, same technique the existing columns already
  use, so raw `state` stays available for the filter dropdown/sort untouched. `parent_slug` is
  shown as a plain mono label, not a link -- work items have no per-slug detail route (only
  ledger rows do, `/item/<row-id>`), and a graph/tree view is explicitly out of scope for this
  item.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../../../core/services/api-client'
import type { Column } from '../../../core/components/DataTable.vue'
import DataTable from '../../../core/components/DataTable.vue'
import { useLiveUpdates } from '../../../core/composables/useLiveUpdates'
import type { WorkItemRow } from '../services/types'

const rows = ref<WorkItemRow[]>([])
const error = ref<string | null>(null)
const { tick } = useLiveUpdates()

const stateFilter = ref('')
const claimantFilter = ref('')
const searchText = ref('')
const sortBy = ref<'slug' | 'state' | 'claimant_name'>('slug')
const sortDir = ref<'asc' | 'desc'>('asc')

// `effective_state` differs from raw `state` today only for a composite parent whose children
// have all discharged their obligations (kernel value `discharged-by-obligations`) -- the raw
// `state` column stays `open` forever by kernel design in that case (Autoharn.idr s33), so a
// reader seeing only `state` cannot tell "done via children" from "genuinely stalled" (consult
// cycle-4 finding 1). Falls back to a generic `raw -> effective` note for any future
// effective_state value this deployment doesn't special-case yet, rather than silently hiding it.
function stateLabel(r: WorkItemRow): string {
  const state = String(r.state ?? '')
  const effective = r.effective_state
  if (typeof effective === 'string' && effective && effective !== state) {
    if (effective === 'discharged-by-obligations') return `${state} — done via children`
    return `${state} → ${effective}`
  }
  return state
}

// `work_edge_blocks_close` antecedents this item's close is blocked on (consult cycle-4 finding
// 5) -- a typed dependency edge, distinct from `parent_slug`'s parent/child edge. Only 2 live
// edges in this deployment today, so a comma-joined plain label is proportionate; a dependency
// graph view is out of scope for this item.
function blockedByLabel(r: WorkItemRow): string {
  const v = r.blocked_by
  if (!Array.isArray(v) || v.length === 0) return ''
  return v.join(', ')
}

// Live state vocabulary for the dropdown, derived from the rows in hand (no facet-counts route
// exists for work items the way `/api/rows/facet-counts` does for the ledger -- ~26 rows makes
// deriving it client-side from the current page cheap and always in sync with what's shown).
const stateOptions = computed(() => {
  const s = new Set<string>()
  for (const r of rows.value) {
    const v = r.state
    if (typeof v === 'string' && v) s.add(v)
  }
  return [...s].sort()
})

const columns: Column[] = [
  { key: 'slug', label: 'slug', mono: true, width: '12rem', sortKey: 'slug' },
  { key: 'state_label', label: 'state', width: '11rem', sortKey: 'state' },
  { key: 'parent_slug', label: 'parent', mono: true, width: '9rem' },
  { key: 'claimant_name', label: 'claimant', width: '7rem', sortKey: 'claimant_name' },
  { key: 'blocked_by_label', label: 'blocked by', width: '9rem' },
  { key: 'resolution', label: 'resolution', width: '9rem', richText: true },
  { key: 'title', label: 'title', width: '3fr', richText: true },
]

function onSortChange(key: string): void {
  const k = key as 'slug' | 'state' | 'claimant_name'
  if (sortBy.value === k) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = k
    sortDir.value = 'asc'
  }
}

const displayRows = computed(() => {
  const needle = searchText.value.trim().toLowerCase()
  const claimantNeedle = claimantFilter.value.trim().toLowerCase()
  let out = rows.value.filter((r) => {
    if (stateFilter.value && r.state !== stateFilter.value) return false
    if (claimantNeedle) {
      const claimant = String(r.claimant_name ?? '').toLowerCase()
      if (!claimant.includes(claimantNeedle)) return false
    }
    if (needle) {
      const slug = String(r.slug ?? '').toLowerCase()
      const title = String(r.title ?? '').toLowerCase()
      if (!slug.includes(needle) && !title.includes(needle)) return false
    }
    return true
  })
  out = [...out].sort((a, b) => {
    const av = String(a[sortBy.value] ?? '').toLowerCase()
    const bv = String(b[sortBy.value] ?? '').toLowerCase()
    const cmp = av < bv ? -1 : av > bv ? 1 : 0
    return sortDir.value === 'asc' ? cmp : -cmp
  })
  // Derived display-only fields, computed here rather than added to the raw `rows` -- the
  // filter/sort logic above stays keyed on the real `state` column untouched.
  return out.map((r) => ({
    ...r,
    state_label: stateLabel(r),
    blocked_by_label: blockedByLabel(r),
  }))
})

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/work')
    if (err) throw err
    rows.value = (data ?? []) as unknown as WorkItemRow[]
    error.value = null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(load)
watch(tick, load)
defineExpose({ reload: load })
</script>

<template>
  <section class="panel">
    <h2>
      Work items
      <span class="refresh-row"><button @click="load">Refresh</button></span>
    </h2>
    <div class="commission-picker">
      <label for="wi-state-filter">state:</label>
      <select id="wi-state-filter" v-model="stateFilter" style="width: 8rem">
        <option value="">(any)</option>
        <option v-for="s in stateOptions" :key="s" :value="s">{{ s }}</option>
      </select>
      <label for="wi-claimant-filter">claimant:</label>
      <input id="wi-claimant-filter" v-model="claimantFilter" type="text" placeholder="(any)" style="width: 8rem" />
      <label for="wi-search">search:</label>
      <input id="wi-search" v-model="searchText" type="text" placeholder="slug or title" style="width: 12rem" />
    </div>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <DataTable
      :columns="columns"
      :rows="displayRows"
      :row-key="(r) => r.slug as string"
      :sort-by="sortBy"
      :sort-dir="sortDir"
      empty-text="No work items match this filter."
      @sort-change="onSortChange"
    />
  </section>
</template>
