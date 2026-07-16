<!--
  src/extensions/autoharn/components/ReviewGapTab.vue -- autoharn/kernel-semantic
  (`countersign_obligation`, review-gap vocabulary). Backed by `GET /api/review-gap`.

  Honest note on the live wire shape (see src/api/types.ts's ReviewGapRow comment): the
  kernel's `review_gap` view returns `id, actor, scope, assigned_by` -- `actor` is a bare
  principal id, not a joined name, and there is no statement/timestamp column at all. The
  vanilla PoC's app.js assumed richer columns that this view does not actually have; this tab
  renders the real columns rather than reproducing that assumption. `id` links to the ledger
  row via `/api/rows/{id}` on click (a lightweight, un-elided expansion in place, not a full
  item-view route -- SPEC.md sec 2.2's item view is out of this port's scope, see
  src/views/stubs/ItemView.stub.vue for its intended home).
-->
<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { api } from '../../../core/services/api-client'
import type { Column } from '../../../core/components/DataTable.vue'
import DataTable from '../../../core/components/DataTable.vue'
import CitationText from '../../../core/components/CitationText.vue'
import { useLiveUpdates } from '../../../core/composables/useLiveUpdates'
import type { LedgerRow } from '../../../core/services/types'

const rows = ref<Record<string, unknown>[]>([])
const error = ref<string | null>(null)
const { tick } = useLiveUpdates()

// row-id -> its fetched statement, expanded in place on click (no elision: once fetched, the
// full statement is shown, never clipped).
const expanded = reactive<Record<number, LedgerRow | 'loading' | 'error'>>({})

const columns: Column[] = [
  { key: 'id', label: 'row', mono: true, width: '4.5rem' },
  { key: 'actor', label: 'actor (principal id)', mono: true, width: '10rem' },
  { key: 'scope', label: 'scope', width: '10rem' },
  { key: 'assigned_by', label: 'assigned by (principal id)', mono: true, width: '10rem' },
]

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/review-gap')
    if (err) throw err
    rows.value = (data ?? []) as Record<string, unknown>[]
    error.value = null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function onRowClick(rowId: string | number): Promise<void> {
  const id = Number(rowId)
  if (expanded[id] && expanded[id] !== 'error') return
  expanded[id] = 'loading'
  try {
    const { data, error: err } = await api.GET('/api/rows/{row_id}', { params: { path: { row_id: id } } })
    if (err) throw err
    expanded[id] = data as unknown as LedgerRow
  } catch {
    expanded[id] = 'error'
  }
}

onMounted(load)
watch(tick, load)
defineExpose({ reload: load })
</script>

<template>
  <section class="panel">
    <h2>
      Review gaps
      <span class="refresh-row"><button @click="load">Refresh</button></span>
    </h2>
    <p class="muted" style="font-size: 0.8rem">
      Click a row id to expand the ledger statement it belongs to (fetched on demand).
    </p>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <DataTable
      :columns="columns"
      :rows="rows"
      :row-key="(r) => r.id as number"
      empty-text="No review gaps -- every countersign obligation is currently discharged."
      @row-click="onRowClick"
    />
    <div v-for="(v, id) in expanded" :key="id" class="commission-text" style="margin-top: 0.5rem">
      <template v-if="v === 'loading'">loading row {{ id }}…</template>
      <template v-else-if="v === 'error'">could not load row {{ id }}</template>
      <template v-else
        >#{{ v.id }} · {{ v.kind }} · {{ v.actor_name || '(unknown actor)' }} — <CitationText :text="v.statement"
      /></template>
    </div>
  </section>
</template>
