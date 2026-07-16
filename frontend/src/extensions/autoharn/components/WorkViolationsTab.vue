<!--
  src/extensions/autoharn/components/WorkViolationsTab.vue -- autoharn/kernel-semantic
  (`work_item_violations`, the kernel's own live "what's currently wrong right now" signal).
  Backed by `GET /api/work-violations`. Mirrors ReviewGapTab.vue's pattern closely (cycle-4 audit
  finding 10, SERIOUS: this view got no dedicated UI treatment despite being exactly the same
  shape of "live obligation queue" Review gap already gets) -- same honest-narrow-columns note:
  the kernel view carries only `violation, slug, detail, target_id`, no id/ts/actor of its own.

  `target_id` doubles as this tab's row-click target (mirroring `review_gap`'s own `id` column
  serving that role in ReviewGapTab.vue): clicking a row expands the SAME lightweight, un-elided
  ledger-row view in place via `GET /api/rows/{row_id}`, not a full item-view navigation.
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

// target_id -> its fetched ledger row, expanded in place on click (no elision: once fetched, the
// full statement is shown, never clipped) -- same convention as ReviewGapTab.vue/QuestionsTab.vue.
const expanded = reactive<Record<number, LedgerRow | 'loading' | 'error'>>({})

const columns: Column[] = [
  { key: 'violation', label: 'violation', width: '12rem' },
  { key: 'slug', label: 'work item slug', mono: true, width: '12rem' },
  { key: 'detail', label: 'detail', width: '3fr' },
  { key: 'target_id', label: 'target row', mono: true, width: '7rem' },
]

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/work-violations')
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
      Violations
      <span class="refresh-row"><button @click="load">Refresh</button></span>
    </h2>
    <p class="muted" style="font-size: 0.8rem">
      Every currently-unresolved decomposition-tree violation the kernel's own `work_item_violations`
      view reports (duplicate opens, dangling refs, cycles, a shipped close with no witness, ...)
      that has not already been disposed of via a work_violation_disposition row. Click a row's
      target row id to expand the ledger statement it names (fetched on demand).
    </p>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <DataTable
      :columns="columns"
      :rows="rows"
      :row-key="(r) => r.target_id as number"
      empty-text="No violations -- the decomposition tree currently has none unresolved."
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
