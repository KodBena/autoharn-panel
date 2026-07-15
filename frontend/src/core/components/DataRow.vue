<!--
  src/core/components/DataRow.vue -- the leaf row component DataTable.vue's `v-for` mounts.
  Takes `row`/`columns` as props and a STABLE `on-click` function reference (bound once by the
  parent, not a fresh closure per item -- omega speed-reap Don't-do #2); this component itself
  reads its own `row.id`/`row_id` and calls `onClick(id)` on click, so the parent's `v-for`
  template never writes `@click="fn(row)"`.
-->
<script setup lang="ts">
import { computed } from 'vue'
import type { Column } from './DataTable.vue'

const props = defineProps<{
  row: Record<string, unknown>
  columns: Column[]
  superseded: boolean
  onClick: (rowId: string | number) => void
  asGrid?: boolean
  gridTemplate?: string
}>()

const rowId = computed(() => {
  const r = props.row as Record<string, unknown>
  return (r.id ?? r.row_id ?? r.slug ?? r.question_id ?? '') as string | number
})

function cellText(col: Column): string {
  const v = props.row[col.key]
  if (v === null || v === undefined) return ''
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  return String(v)
}

function handleClick(): void {
  if (rowId.value !== '') props.onClick(rowId.value)
}
</script>

<template>
  <tr v-if="!asGrid" :class="{ 'superseded-row': superseded }" @click="handleClick">
    <td v-for="col in columns" :key="col.key" :class="{ mono: col.mono }">{{ cellText(col) }}</td>
  </tr>
  <div
    v-else
    class="vg-row"
    :class="{ 'superseded-row': superseded }"
    :style="{ display: 'grid', gridTemplateColumns: gridTemplate }"
    role="row"
    @click="handleClick"
  >
    <div v-for="col in columns" :key="col.key" class="vg-cell" :class="{ mono: col.mono }" role="cell">
      {{ cellText(col) }}
    </div>
  </div>
</template>

<style scoped>
tr { cursor: default; }
.vg-row { border-bottom: 1px solid var(--border); }
.vg-cell { padding: 0.3rem 0.5rem; overflow-wrap: anywhere; font-size: 0.82rem; }
</style>
