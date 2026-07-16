<!--
  src/core/components/SimpleQueueTab.vue -- the ONE generic "simple queue" tab: fetch a list from
  an endpoint, render it through DataTable.vue, click a row to expand more detail. CORE-GENERIC
  (SPEC.md sec 4): no autoharn vocabulary lives here, only the shared shape every queue-style tab
  in this app was independently re-authoring.

  Factored out per work item tab-architecture-consolidation (row:748, countersigned finding
  row:745/747): WorkViolationsTab.vue/ReviewGapTab.vue were near-verbatim copies of the same
  "fetch-on-click, expand the full ledger row below" pattern, and FindingsSnagsTab.vue/
  StandingDecisionsTab.vue were ~90% line-for-line copies of the same "truncate a statement
  column inline, click to expand/collapse in place" pattern (LedgerTab.vue's own convention).
  QuestionsTab.vue turned out to be simply both patterns at once (row:decision, this work item) --
  so this component exposes the two patterns as independently composable, opt-in props rather
  than one rigid shape, and all 5 tabs migrate to a thin wrapper over it (CommissionTab.vue and
  WorkItemsTab.vue do NOT -- they are multi-field forms/actions, not a plain fetch+render queue,
  a genuinely different shape, not an unexamined one).

  Two composable modes, either or both may be enabled by a caller:
    - `truncateColumn` (inline-truncate): the named column's text is clipped at `truncateAt`
      chars with a "click row to expand" hint; clicking toggles it back and forth in place. No
      elision doctrine preserved (DataTable.vue's own header comment) -- nothing is ever
      permanently hidden, the full text is one click away.
    - `expandOnFetch` (fetch-detail): clicking a row additionally fetches its full ledger row via
      `GET /api/rows/{id}` (kind/actor/ts/full statement, via CitationText.vue) and renders it
      below the table, cached once fetched.
  `getRowId` is the one function needed to key both DataTable's own `row-key` prop AND this
  component's internal expand-state maps -- necessary because the "id" column differs by
  endpoint (`id`, `target_id`, `question_id`, ...), same as each original tab's own `rowKey`.
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../services/api-client'
import type { Column } from './DataTable.vue'
import DataTable from './DataTable.vue'
import CitationText from './CitationText.vue'
import { useLiveUpdates } from '../composables/useLiveUpdates'
import type { LedgerRow } from '../services/types'

// The literal set of endpoints this component's 5 current callers pass -- kept as a union
// (rather than widening to `string`) so `api.GET(props.endpoint)` below stays checked against
// openapi-fetch's generated `paths` type instead of losing type safety at the one call site
// every caller shares.
export type QueueEndpoint =
  | '/api/work-violations'
  | '/api/review-gap'
  | '/api/questions'
  | '/api/findings-snags'
  | '/api/standing-decisions'

const props = withDefaults(
  defineProps<{
    title: string
    endpoint: QueueEndpoint
    columns: Column[]
    getRowId: (row: Record<string, unknown>) => number
    description?: string
    emptyText?: string
    /** column key to truncate/expand inline (LedgerTab.vue's STATEMENT_TRUNCATE_AT convention).
     * Omitted entirely = no inline truncation for this tab (its columns are already narrow). */
    truncateColumn?: string
    truncateAt?: number
    /** click a row to also fetch its full ledger row (GET /api/rows/{id}) and render it below. */
    expandOnFetch?: boolean
    /** optional per-row derivation (e.g. FindingsSnagsTab's `ts_fmt` from raw `ts`), applied
     * before truncation so a transformed field can itself be the truncated column. */
    rowTransform?: (row: Record<string, unknown>) => Record<string, unknown>
  }>(),
  { emptyText: 'No rows.', truncateAt: 240, expandOnFetch: false },
)

const rows = ref<Record<string, unknown>[]>([])
const error = ref<string | null>(null)
const { tick } = useLiveUpdates()

// Inline-truncate expand state (toggled by row click when `truncateColumn` is set).
const expandedIds = ref<Set<number>>(new Set())
// Fetch-detail cache (populated by row click when `expandOnFetch` is set) -- row id -> its
// fetched ledger row, 'loading' while in flight, 'error' on failure. Never cleared once
// resolved: once fetched, the full statement stays visible, same as the tabs this replaces.
const expanded = reactive<Record<number, LedgerRow | 'loading' | 'error'>>({})

function displayStatement(r: Record<string, unknown>): string {
  const col = props.truncateColumn as string
  const text = typeof r[col] === 'string' ? (r[col] as string) : ''
  if (text.length <= props.truncateAt) return text
  const id = props.getRowId(r)
  if (expandedIds.value.has(id)) {
    // QuestionsTab.vue's own wording when a second, fetched panel exists to point at;
    // FindingsSnagsTab.vue/StandingDecisionsTab.vue's plain "click row to collapse" otherwise --
    // preserved verbatim per-mode rather than picking one and losing the other's meaning.
    return props.expandOnFetch ? `${text}  [see full ledger entry below]` : `${text}  [click row to collapse]`
  }
  return `${text.slice(0, props.truncateAt)}… [click row to expand -- ${text.length} chars total]`
}

const displayRows = computed(() =>
  rows.value.map((r) => {
    const base = props.rowTransform ? props.rowTransform(r) : r
    if (!props.truncateColumn) return base
    return { ...base, [props.truncateColumn]: displayStatement(base) }
  }),
)

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET(props.endpoint)
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
  if (props.truncateColumn) {
    if (expandedIds.value.has(id)) expandedIds.value.delete(id)
    else expandedIds.value.add(id)
  }
  if (props.expandOnFetch) {
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
}

onMounted(load)
watch(tick, load)
defineExpose({ reload: load })
</script>

<template>
  <section class="panel">
    <h2>
      {{ title }}
      <span class="refresh-row"><button @click="load">Refresh</button></span>
    </h2>
    <p v-if="description" class="muted" style="font-size: 0.8rem">{{ description }}</p>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <div class="expandable-ledger-table">
      <DataTable
        :columns="columns"
        :rows="displayRows"
        :row-key="(r) => getRowId(r)"
        :empty-text="emptyText"
        @row-click="onRowClick"
      />
    </div>
    <template v-if="expandOnFetch">
      <div v-for="(v, id) in expanded" :key="id" class="commission-text" style="margin-top: 0.5rem">
        <template v-if="v === 'loading'">loading row {{ id }}…</template>
        <template v-else-if="v === 'error'">could not load row {{ id }}</template>
        <template v-else
          >#{{ v.id }} · {{ v.kind }} · {{ v.actor_name || '(unknown actor)' }} — <CitationText :text="v.statement"
        /></template>
      </div>
    </template>
  </section>
</template>

<style scoped>
/* Every row in this family is clickable (either inline-truncate or fetch-detail, sometimes
   both) -- always show the pointer affordance, unlike the two fetch-detail-only originals
   (ReviewGapTab.vue/WorkViolationsTab.vue) which never had this hint despite being clickable;
   a small, deliberate consistency fix that falls out of consolidation. Deep-scoped to reach
   DataRow.vue's own <tr>/.vg-row markup without changing that shared file's default cursor for
   any tab NOT built on this component. */
.expandable-ledger-table :deep(tr),
.expandable-ledger-table :deep(.vg-row) {
  cursor: pointer;
}
</style>
