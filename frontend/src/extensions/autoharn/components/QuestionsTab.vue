<!--
  src/extensions/autoharn/components/QuestionsTab.vue -- autoharn-semantic (`question_status`
  kernel view). Backed by `GET /api/questions`. Same honest-narrow-columns note as
  ReviewGapTab.vue for the kernel VIEW's own columns (`question_id, question_kind, answered,
  first_answer_id, answers_target_not_a_question` -- still no actor/ts on the view itself);
  `statement` is NOT one of them -- backend/extensions/autoharn/ledger_read.py's
  question_status() joins it in from `ledger_current` (cycle-4 audit finding 11, work item
  questions-inline-text, row:633/659) so this table shows a snippet of the actual question text
  instead of requiring a click-through to learn what was asked.

  Truncate-with-expand convention mirrors LedgerTab.vue's STATEMENT_TRUNCATE_AT/displayStatement()
  pattern verbatim (same constant value, same slice+ellipsis+char-count hint) rather than
  inventing a second truncation convention (row:660/661's decisions). The one deliberate
  difference: the "expand" trigger is the SAME row-click DataTable already emits for this tab,
  which also fetches and renders the full ledger row (kind/actor/ts/full statement) below the
  table -- reusing that existing gesture instead of adding a second, independent per-cell toggle.
  `question_id` links to the ledger row via `/api/rows/{id}` on click, expanded in place (no
  elision once expanded).
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../../../core/services/api-client'
import type { Column } from '../../../core/components/DataTable.vue'
import DataTable from '../../../core/components/DataTable.vue'
import CitationText from '../../../core/components/CitationText.vue'
import { useLiveUpdates } from '../../../core/composables/useLiveUpdates'
import type { LedgerRow } from '../../../core/services/types'

const rows = ref<Record<string, unknown>[]>([])
const error = ref<string | null>(null)
const { tick } = useLiveUpdates()

const expanded = reactive<Record<number, LedgerRow | 'loading' | 'error'>>({})

// Same STATEMENT_TRUNCATE_AT convention as LedgerTab.vue (this file's own header comment) --
// truncate the question's own statement VALUE before it reaches DataTable (whose no-elision
// doctrine forbids clipping internally), with a char-count hint pointing at the row-click that
// already reveals the full text below.
const STATEMENT_TRUNCATE_AT = 240
const expandedIds = ref<Set<number>>(new Set())

function displayStatement(r: Record<string, unknown>): string {
  const text = typeof r.statement === 'string' ? r.statement : ''
  if (text.length <= STATEMENT_TRUNCATE_AT) return text
  const id = r.question_id as number
  if (expandedIds.value.has(id)) return `${text}  [see full ledger entry below]`
  return `${text.slice(0, STATEMENT_TRUNCATE_AT)}… [click row to expand -- ${text.length} chars total]`
}

const displayRows = computed(() => rows.value.map((r) => ({ ...r, statement: displayStatement(r) })))

const columns: Column[] = [
  { key: 'question_id', label: 'question row', mono: true, width: '8rem' },
  { key: 'question_kind', label: 'kind', width: '9rem' },
  { key: 'answered', label: 'answered', width: '6rem' },
  { key: 'first_answer_id', label: 'first answer row', mono: true, width: '10rem' },
  { key: 'answers_target_not_a_question', label: 'answers non-question target', width: '10rem' },
  { key: 'statement', label: 'question text', width: '3fr', richText: true },
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
  if (Number.isNaN(id)) return
  if (expandedIds.value.has(id)) expandedIds.value.delete(id)
  else expandedIds.value.add(id)
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
      Long question text is truncated by default -- click a row to expand it and load its full
      ledger entry (kind/actor/ts) below.
    </p>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <DataTable
      :columns="columns"
      :rows="displayRows"
      :row-key="(r) => r.question_id as number"
      empty-text="No open questions."
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
