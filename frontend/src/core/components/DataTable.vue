<!--
  src/core/components/DataTable.vue -- the ONE list-rendering component every tab in this app
  uses (Board-ish tabs: ledger, work items, review gaps, questions, commission items). Two of
  the three maintainer verdicts this port must carry (SPEC.md sec 0/2.1) live here so every
  view gets them for free rather than each tab re-implementing its own table:

    1. No-elision: every cell wraps (`overflow-wrap: anywhere` in style.css's `td` rule), no
       cell is ever ellipsis-clipped. There is no "show more" affordance because nothing is
       hidden in the first place.
    2. Virtualization above 200 rows (SPEC.md sec 3 perf budget): below the threshold this
       renders a plain, fully-native `<table>` (simplest, most accessible option, and the
       omega-reap sheet's Don't-do #9 warns against a perf harness -- or a design -- that only
       ever exercises small N; but a fully native table for a genuinely small list is exactly
       right, not a missed optimization). Above it, rows are windowed with
       `@tanstack/vue-virtual` inside a CSS-grid-row-shaped div list (a native `<table>` can't
       have absent middle rows without breaking column alignment, so the virtualized path
       trades table semantics for windowing -- same visual column layout, `role="table"` ARIA
       restores the semantics lost by dropping the real element).

  Row rendering is a separate leaf component (`DataRow.vue`) taking `row`/`columns` as props and
  emitting its own row-id on click, per the omega speed-reap sheet's Don't-do #2: no
  `@click="fn(row)"` inline closure bound inside this component's `v-for` -- `on-row-click`
  below is ONE stable handler reference, not redefined per iteration.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import DataRow from './DataRow.vue'

export interface Column {
  key: string
  label: string
  mono?: boolean
  width?: string // CSS grid track, e.g. "5rem" or "1fr"
}

const props = withDefaults(
  defineProps<{
    columns: Column[]
    rows: Record<string, unknown>[]
    rowKey: (row: Record<string, unknown>) => string | number
    /** ids considered superseded -- dimmed, never hidden-with-no-toggle (SPEC.md sec 2.1) */
    supersededIds?: Set<string | number>
    emptyText?: string
    rowHeightPx?: number
  }>(),
  { supersededIds: () => new Set(), emptyText: 'No rows.', rowHeightPx: 34 },
)

const emit = defineEmits<{ (e: 'row-click', rowId: string | number): void }>()

const VIRTUALIZE_ABOVE = 200

const gridTemplate = computed(() =>
  props.columns.map((c) => c.width ?? '1fr').join(' '),
)

const scrollParent = ref<HTMLElement | null>(null)
const shouldVirtualize = computed(() => props.rows.length > VIRTUALIZE_ABOVE)

const virtualizer = useVirtualizer(
  computed(() => ({
    count: props.rows.length,
    getScrollElement: () => scrollParent.value,
    estimateSize: () => props.rowHeightPx,
    overscan: 12,
  })),
)

// A single stable handler reference passed to every DataRow instance -- never recreated per
// item, so DataRow's own prop identity stays stable across re-renders (omega Don't-do #2).
function onRowClick(rowId: string | number): void {
  emit('row-click', rowId)
}

function isSuperseded(row: Record<string, unknown>): boolean {
  return props.supersededIds.has(props.rowKey(row))
}
</script>

<template>
  <div class="scroll-x">
    <p v-if="rows.length === 0" class="empty-note">{{ emptyText }}</p>

    <!-- small-N path: a plain native table, full accessibility, no windowing machinery -->
    <table v-else-if="!shouldVirtualize">
      <thead>
        <tr>
          <th v-for="col in columns" :key="col.key">{{ col.label }}</th>
        </tr>
      </thead>
      <tbody>
        <DataRow
          v-for="row in rows"
          :key="rowKey(row)"
          :row="row"
          :columns="columns"
          :superseded="isSuperseded(row)"
          :on-click="onRowClick"
        />
      </tbody>
    </table>

    <!-- large-N path: windowed rendering, div/grid-row shaped, role=table for a11y -->
    <div
      v-else
      ref="scrollParent"
      class="virtual-viewport"
      role="table"
      :style="{ maxHeight: '480px' }"
    >
      <div class="virtual-grid-head" :style="{ display: 'grid', gridTemplateColumns: gridTemplate }" role="row">
        <div v-for="col in columns" :key="col.key" role="columnheader" class="vg-cell vg-head">{{ col.label }}</div>
      </div>
      <div class="virtual-inner" :style="{ height: virtualizer.getTotalSize() + 'px' }">
        <div
          v-for="vrow in virtualizer.getVirtualItems()"
          :key="vrow.index"
          class="virtual-row"
          :style="{ transform: `translateY(${vrow.start}px)`, height: vrow.size + 'px' }"
        >
          <DataRow
            :row="rows[vrow.index]"
            :columns="columns"
            :superseded="isSuperseded(rows[vrow.index])"
            :on-click="onRowClick"
            as-grid
            :grid-template="gridTemplate"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.vg-cell {
  padding: 0.3rem 0.5rem;
  overflow-wrap: anywhere;
  font-size: 0.82rem;
}
.vg-head {
  color: var(--text-dim);
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  background: var(--panel-bg);
}
</style>
