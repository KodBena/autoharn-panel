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
const limit = ref(200)

const { tick } = useLiveUpdates()

const columns: Column[] = [
  { key: 'id', label: 'id', mono: true, width: '4.5rem' },
  { key: 'kind', label: 'kind', width: '8rem' },
  { key: 'actor_name', label: 'actor', width: '9rem' },
  { key: 'ts_fmt', label: 'ts', mono: true, width: '11rem' },
  { key: 'statement', label: 'statement', width: '3fr' },
]

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

const displayRows = computed(() =>
  rows.value.map((r) => ({ ...r, ts_fmt: fmtTs(r.ts as string | null) })),
)

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/rows', {
      params: {
        query: {
          include_superseded: includeSuperseded.value,
          kind: kindFilter.value || undefined,
          limit: limit.value,
        },
      },
    })
    if (err) throw err
    rows.value = (data ?? []) as Record<string, unknown>[]
    error.value = null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(load)
watch([includeSuperseded, kindFilter, limit], load)
// This tab is mounted only while its own tab panel is visible (App.vue uses v-if per tab), so
// watching the shared `tick` here refetches only THIS view's data, on ledger change -- no other
// tab does extra work because this one is open (SPEC.md sec 3: "no view refetches more than its
// own visible data").
watch(tick, load)

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
      <input id="kind-filter" v-model="kindFilter" type="text" placeholder="(any)" style="width: 8rem" />
      <label class="toggle-row">
        <input v-model="includeSuperseded" type="checkbox" />
        show superseded rows
      </label>
      <label for="row-limit">limit:</label>
      <input id="row-limit" v-model.number="limit" type="number" min="1" style="width: 5.5rem" />
    </div>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <DataTable
      :columns="columns"
      :rows="displayRows"
      :row-key="(r) => r.id as number"
      :superseded-ids="supersededIds"
      empty-text="No ledger rows match this filter."
    />
  </section>
</template>
