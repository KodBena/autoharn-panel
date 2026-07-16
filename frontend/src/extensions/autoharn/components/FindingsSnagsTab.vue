<!--
  src/extensions/autoharn/components/FindingsSnagsTab.vue -- autoharn/kernel-semantic
  (`ledger_current`, narrowed to kind IN ('finding','snag')). Backed by `GET /api/findings-snags`.

  Addresses cycle-4 audit finding 8 (MODERATE, docs/consults/2026-07-16-spa-audit-4/): every
  ledger prose kind (assumption, decision, question, verification, finding, snag, revision,
  note) is modeled symmetrically by autoharn's own `Autoharn.idr` sum type, but only
  question/review_gap got a dedicated tab so far -- finding/snag rows (exactly the recorded-
  defect/observation content an audit-conscious reader most wants surfaced distinctly) had
  nothing beyond the generic `kind:` dropdown filter every row type shares in Recent Ledger.

  ONE combined view for both kinds, not two separate tabs (row:704's decision, made after
  reading this deployment's own live rows: 26 finding + 10 snag = 36 total at decision time --
  modest, comparable volume that would not justify doubling the tab-bar footprint). The `kind`
  column is still carried per-row so a finding is visually distinguishable from a snag without a
  second query or a second tab.

  Truncate-with-expand mirrors LedgerTab.vue's OWN inline convention byte-for-byte (same
  STATEMENT_TRUNCATE_AT value, same slice+ellipsis+char-count hint, same toggle-on-row-click) --
  not the separate-fetch-on-click pattern ReviewGapTab.vue/QuestionsTab.vue/WorkViolationsTab.vue
  use, since `findings_and_snags()` already returns the full statement text in the same payload;
  there is nothing narrower to fetch a second time.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../../../core/services/api-client'
import type { Column } from '../../../core/components/DataTable.vue'
import DataTable from '../../../core/components/DataTable.vue'
import { useLiveUpdates } from '../../../core/composables/useLiveUpdates'
import { fmtTs } from '../../../utils/format'

const rows = ref<Record<string, unknown>[]>([])
const error = ref<string | null>(null)
const { tick } = useLiveUpdates()

const columns: Column[] = [
  { key: 'id', label: 'id', mono: true, width: '4.5rem' },
  { key: 'kind', label: 'kind', width: '6rem' },
  { key: 'actor_name', label: 'actor', width: '9rem' },
  { key: 'ts_fmt', label: 'ts', mono: true, width: '11rem' },
  { key: 'statement', label: 'statement', width: '3fr', richText: true },
]

// Same convention as LedgerTab.vue/QuestionsTab.vue (this file's own header comment): truncate
// the statement VALUE itself before handing it to DataTable (whose no-elision doctrine forbids
// clipping internally), and use the row-click DataTable already emits to toggle a per-row
// expanded state -- nothing is permanently hidden, every row's full text is one click away.
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

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/findings-snags')
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
      Findings &amp; snags
      <span class="refresh-row"><button @click="load">Refresh</button></span>
    </h2>
    <p class="muted" style="font-size: 0.8rem">
      Every recorded `finding`/`snag` row -- the ledger's own recorded-defect/observation prose,
      surfaced here directly rather than only reachable via Recent Ledger's generic kind filter.
      Long statements are truncated by default -- click a row to expand or collapse its full text.
    </p>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <div class="expandable-ledger-table">
      <DataTable
        :columns="columns"
        :rows="displayRows"
        :row-key="(r) => r.id as number"
        empty-text="No finding or snag rows recorded yet."
        @row-click="toggleExpand"
      />
    </div>
  </section>
</template>

<style scoped>
/* Local-only clickable-row affordance, same convention as LedgerTab.vue's own scoped block --
   deep-scoped to reach DataRow.vue's <tr>/.vg-row markup without changing that shared file's
   default (non-interactive) cursor for every other tab. */
.expandable-ledger-table :deep(tr),
.expandable-ledger-table :deep(.vg-row) {
  cursor: pointer;
}
</style>
