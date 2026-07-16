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
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../../../core/services/api-client'
import type { Column } from '../../../core/components/DataTable.vue'
import DataTable from '../../../core/components/DataTable.vue'
import { useLiveUpdates } from '../../../core/composables/useLiveUpdates'

const rows = ref<Record<string, unknown>[]>([])
const error = ref<string | null>(null)
const { tick } = useLiveUpdates()

const stateFilter = ref('')
const claimantFilter = ref('')
const searchText = ref('')
const sortBy = ref<'slug' | 'state' | 'claimant_name'>('slug')
const sortDir = ref<'asc' | 'desc'>('asc')

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
  { key: 'slug', label: 'slug', mono: true, width: '14rem', sortKey: 'slug' },
  { key: 'state', label: 'state', width: '6rem', sortKey: 'state' },
  { key: 'claimant_name', label: 'claimant', width: '8rem', sortKey: 'claimant_name' },
  { key: 'resolution', label: 'resolution', width: '10rem', richText: true },
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
  return out
})

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/work')
    if (err) throw err
    rows.value = (data ?? []) as Record<string, unknown>[]
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
