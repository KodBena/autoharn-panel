<!--
  src/extensions/autoharn/components/QuestionsTab.vue -- autoharn-semantic (`question_status`
  kernel view). Backed by `GET /api/questions`. Same honest-narrow-columns note as
  ReviewGapTab.vue: the live view's columns are `question_id, question_kind, answered,
  first_answer_id, answers_target_not_a_question` -- no statement/actor/ts. `question_id` links
  to the ledger row via `/api/rows/{id}` on click, expanded in place (no elision).
-->
<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { api } from '../../../core/services/api-client'
import type { Column } from '../../../core/components/DataTable.vue'
import DataTable from '../../../core/components/DataTable.vue'
import { useLiveUpdates } from '../../../core/composables/useLiveUpdates'
import type { LedgerRow } from '../../../core/services/types'

const rows = ref<Record<string, unknown>[]>([])
const error = ref<string | null>(null)
const { tick } = useLiveUpdates()

const expanded = reactive<Record<number, LedgerRow | 'loading' | 'error'>>({})

const columns: Column[] = [
  { key: 'question_id', label: 'question row', mono: true, width: '8rem' },
  { key: 'question_kind', label: 'kind', width: '9rem' },
  { key: 'answered', label: 'answered', width: '6rem' },
  { key: 'first_answer_id', label: 'first answer row', mono: true, width: '10rem' },
  { key: 'answers_target_not_a_question', label: 'answers non-question target', width: '10rem' },
]

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/questions')
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
      Questions
      <span class="refresh-row"><button @click="load">Refresh</button></span>
    </h2>
    <p class="muted" style="font-size: 0.8rem">
      Click a question row id to expand the ledger statement it belongs to (fetched on demand).
    </p>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <DataTable
      :columns="columns"
      :rows="rows"
      :row-key="(r) => r.question_id as number"
      empty-text="No open questions."
      @row-click="onRowClick"
    />
    <div v-for="(v, id) in expanded" :key="id" class="commission-text" style="margin-top: 0.5rem">
      <template v-if="v === 'loading'">loading row {{ id }}…</template>
      <template v-else-if="v === 'error'">could not load row {{ id }}</template>
      <template v-else>#{{ v.id }} · {{ v.kind }} · {{ v.actor_name || '(unknown actor)' }} — {{ v.statement }}</template>
    </div>
  </section>
</template>
