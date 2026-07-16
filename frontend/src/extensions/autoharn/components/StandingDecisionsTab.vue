<!--
  src/extensions/autoharn/components/StandingDecisionsTab.vue -- autoharn/kernel-semantic
  (`standing_decisions`, kernel/lineage/s36-decision-grade.sql's "decision-grade... in-force
  view"). Backed by `GET /api/standing-decisions`.

  Addresses cycle-4 audit finding 4 (SERIOUS, docs/consults/2026-07-16-spa-audit-4/): every
  `decision`-kind row carrying a writer-supplied `grade` (22+ live rows in this deployment, all
  currently `durable`) is real, kernel-supported governance state -- `./led standing` and
  `./pickup`'s own STANDING-DECISIONS section already surface it to a CLI operator -- but the
  SPA had no dedicated view at all: every decision row, durable or not, rendered identically in
  Recent Ledger, with no way to tell "this is meant to survive context loss/compaction" apart
  from an ordinary one-off note.

  Truncate-with-expand mirrors FindingsSnagsTab.vue's OWN inline convention byte-for-byte (same
  STATEMENT_TRUNCATE_AT value, same slice+ellipsis+char-count hint, same toggle-on-row-click) --
  not ReviewGapTab.vue/WorkViolationsTab.vue's separate-fetch-on-click pattern, since
  `standing_decisions` already returns the full statement text in the same payload (same shape
  as `findings_and_snags`); there is nothing narrower to fetch a second time.
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

const columns: Column[] = [
  { key: 'id', label: 'id', mono: true, width: '4.5rem' },
  { key: 'grade', label: 'grade', width: '7rem' },
  { key: 'statement', label: 'statement', width: '3fr', richText: true },
]

// Same convention as FindingsSnagsTab.vue/LedgerTab.vue (this file's own header comment):
// truncate the statement VALUE itself before handing it to DataTable (whose no-elision
// doctrine forbids clipping internally), and use the row-click DataTable already emits to
// toggle a per-row expanded state -- nothing is permanently hidden, every row's full text is
// one click away.
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

const displayRows = computed(() => rows.value.map((r) => ({ ...r, statement: displayStatement(r) })))

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/standing-decisions')
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
      Standing decisions
      <span class="refresh-row"><button @click="load">Refresh</button></span>
    </h2>
    <p class="muted" style="font-size: 0.8rem">
      Every in-force `decision`-kind row carrying a writer-supplied grade (kernel's own
      `standing_decisions` view) -- the same "survives context loss/compaction" governance state
      `./led standing` and `./pickup` already surface to a CLI operator, previously invisible in
      this SPA. Long statements are truncated by default -- click a row to expand or collapse
      its full text.
    </p>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <div class="expandable-ledger-table">
      <DataTable
        :columns="columns"
        :rows="displayRows"
        :row-key="(r) => r.id as number"
        empty-text="No standing decisions -- no in-force decision row currently carries a grade."
        @row-click="toggleExpand"
      />
    </div>
  </section>
</template>

<style scoped>
/* Local-only clickable-row affordance, same convention as FindingsSnagsTab.vue's own scoped
   block -- deep-scoped to reach DataRow.vue's <tr>/.vg-row markup without changing that shared
   file's default (non-interactive) cursor for every other tab. */
.expandable-ledger-table :deep(tr),
.expandable-ledger-table :deep(.vg-row) {
  cursor: pointer;
}
</style>
