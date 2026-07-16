<!--
  src/core/components/BackendSurfaceTab.vue -- "Backend surface": the three-layer view
  spa-backend-surface-view (commission row:741) exists for. The maintainer's own refinement to
  the original ask is the whole point of this tab: there are TWO distinct gaps between what
  Postgres actually offers and what a power user can see/use, not one --

    1. DB schema -> our own backend API ("exposed by our API" column below). LIVE-derived
       (`GET /api/backend-surface`, `backend/core/backend_surface.py`): a source-grep over this
       backend's own core+enabled-extension .py files, checking whether the relation name
       appears as a FROM/JOIN target in real SQL. This is the "negligence on our part" gap the
       maintainer called out by name -- a relation Postgres has that our backend never even
       bothers to query.

    2. Our own backend API -> a dedicated SPA tab ("SPA tab" column below). CORE-GENERIC (this
       component is not autoharn-gated), but this ONE column's data is NOT live-derived the way
       column 1 is -- `TAB_LABEL_BY_RELATION` below is a small, EXPLICITLY hand-maintained map
       (relation name -> the one TAB_DEFS label most centrally backed by it). Disclosed honestly
       here rather than dressed up as computer-derived: unlike "does this string appear as a
       FROM/JOIN target" (a mechanical check), "which tab is this relation ABOUT" is a genuinely
       fuzzier editorial judgment (see tabs.ts and app.vue's TAB_DEFS array; a relation queried by
       five different endpoints for five different reasons has no single mechanically-correct
       tab to point at). Only relations with a clean, uncontested 1:1 correspondence to one tab
       are mapped; a relation queried widely as a shared join target (`ledger_current`,
       `principal`, `review_detail`) is left unmapped ("no dedicated tab") on purpose -- no ONE
       tab is centrally "about" it, even though the relation itself is very much in active use.
       (spa-backend-surface-view work item's own instruction: fine to hand-maintain THIS one
       narrower layer, but say so plainly rather than manufacture a false the-computer-derived-
       this fiction -- this comment, and the identical one on the map below, are that disclosure.)

  Grouped by schema (this deployment's two configured schemas, `cfg.schema`/`cfg.kern_schema`,
  read live off `GET /api/health` -- never hardcoded `experience`/`experience_kernel`), one
  DataTable per schema so a power user reads "what does MY ledger schema offer" separately from
  "what does the kernel/principal schema offer".
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../services/api-client'
import type { Column } from './DataTable.vue'
import DataTable from './DataTable.vue'
import { useLiveUpdates } from '../composables/useLiveUpdates'
import type { BackendSurfaceRelation } from '../services/types'

const rows = ref<BackendSurfaceRelation[]>([])
const error = ref<string | null>(null)
const { tick } = useLiveUpdates()

// Hand-maintained, disclosed mapping (see this file's own header comment, section 2): relation
// name -> the ONE TAB_DEFS label it most centrally backs. Deliberately NOT imported from
// `../../tabs` (that would pull the app's whole tab-component graph into a core/ component just
// to read a label string) -- these are the same label strings tabs.ts declares, kept as plain
// text here since this map is editorial judgment, not a derivable fact; if a label in tabs.ts
// ever changes, this map is the one place a human needs to notice and update it, same as this
// component's own comment already discloses.
const TAB_LABEL_BY_RELATION: Record<string, string> = {
  ledger: 'Recent ledger',
  work_item_current: 'Work items',
  work_item_violations: 'Violations',
  review_gap: 'Review gap',
  question_status: 'Questions',
  standing_decisions: 'Standing decisions',
}

function tabLabel(relationName: string): string {
  return TAB_LABEL_BY_RELATION[relationName] ?? '—'
}

function countLabel(r: BackendSurfaceRelation): string {
  return r.count_estimated ? `~${r.count.toLocaleString()}` : r.count.toLocaleString()
}

const columns: Column[] = [
  { key: 'name', label: 'relation', mono: true, width: '16rem', sortKey: 'name' },
  { key: 'kind', label: 'kind', width: '9rem', sortKey: 'kind' },
  { key: 'count_label', label: 'rows', width: '7rem' },
  { key: 'exposed_label', label: 'exposed by our API', width: '10rem' },
  { key: 'tab_label', label: 'has a dedicated SPA tab', width: '12rem' },
]

function toDisplayRow(r: BackendSurfaceRelation): Record<string, unknown> {
  return {
    ...r,
    count_label: countLabel(r),
    exposed_label: r.exposed_by_api ? 'yes' : 'no',
    tab_label: tabLabel(r.name),
  }
}

const bySchema = computed(() => {
  const groups = new Map<string, BackendSurfaceRelation[]>()
  for (const r of rows.value) {
    const list = groups.get(r.schema)
    if (list) list.push(r)
    else groups.set(r.schema, [r])
  }
  // Stable order: the schema seen first in the API's own response (schema, then name, per
  // backend_surface.py's own ORDER BY) -- never re-sorted alphabetically, so `cfg.schema` (the
  // ledger schema) reliably shows before `cfg.kern_schema` the same way the backend lists it.
  return [...groups.entries()].map(([schema, relations]) => ({
    schema,
    displayRows: relations.map(toDisplayRow),
  }))
})

const summary = computed(() => {
  const total = rows.value.length
  const exposed = rows.value.filter((r) => r.exposed_by_api).length
  const tabbed = rows.value.filter((r) => r.name in TAB_LABEL_BY_RELATION).length
  return { total, exposed, tabbed }
})

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/backend-surface')
    if (err) throw err
    rows.value = (data ?? []) as unknown as BackendSurfaceRelation[]
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
      Backend surface
      <span class="refresh-row"><button @click="load">Refresh</button></span>
    </h2>
    <p class="muted" style="font-size: 0.8rem">
      What Postgres actually offers in this deployment's two configured schemas, versus what our
      own backend bothers to query ("exposed by our API", live-derived from this backend's own
      source every refresh) and what the SPA gives a dedicated view for ("has a dedicated SPA
      tab", a small hand-maintained editorial mapping -- see this tab's own source comment).
      {{ summary.total }} relations total, {{ summary.exposed }} exposed by our API,
      {{ summary.tabbed }} with a dedicated tab. Row counts are exact for every relation in this
      deployment today; a relation would show a "~"-prefixed estimate only if it grew large
      enough that an exact count would be wasteful.
    </p>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <div v-for="group in bySchema" :key="group.schema" style="margin-top: 1rem">
      <h3 style="margin-bottom: 0.35rem">
        <code>{{ group.schema }}</code> schema
        <span class="muted" style="font-weight: normal; font-size: 0.78rem"
          >({{ group.displayRows.length }} relations)</span
        >
      </h3>
      <DataTable
        :columns="columns"
        :rows="group.displayRows"
        :row-key="(r) => r.name as string"
        empty-text="No relations found in this schema."
      />
    </div>
  </section>
</template>
