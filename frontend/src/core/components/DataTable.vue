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

  Below ~800px viewport width, the plain `<table>` path (the `stack-on-narrow` class below)
  degrades to a stacked-card layout via CSS alone (see style.css's `@media (max-width: 800px)`
  block) -- each `<td>` becomes its own labeled line (`data-label`, set in DataRow.vue, supplies
  the label text through a `::before` pseudo-element) instead of compressing every column into
  an unreadably thin strip. Desktop behavior above the breakpoint is untouched. The virtualized
  (>200 row) grid path is unaffected by this consult item -- it already uses its own grid
  layout, not the compressing-columns table shape the finding was about.

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
  /** server-side sort key this column maps to (e.g. actor_name column -> `actor` API param) --
   * a column is clickable-to-sort only when this is set; omitted entirely for columns whose
   * meaning does not map to a single server column (e.g. `statement`). */
  sortKey?: string
  /** true for a column whose value is free-authored ledger prose that may embed `row:<id>`
   * citations (a `statement`/`title`/`resolution`-shaped column) -- DataRow.vue renders it
   * through CitationText.vue instead of a plain interpolation. Never set for a column whose
   * value is a plain scalar (id/kind/actor/ts/etc.); a rich-text render on a non-prose column
   * would just cost a component mount for nothing to link. */
  richText?: boolean
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
    /** current sort state, for the header's active-column indicator -- purely cosmetic, the
     * actual sorting happens server-side (the caller re-fetches on `sort-change`). */
    sortBy?: string | null
    sortDir?: 'asc' | 'desc'
  }>(),
  { supersededIds: () => new Set(), emptyText: 'No rows.', rowHeightPx: 34, sortBy: null, sortDir: 'desc' },
)

const emit = defineEmits<{
  (e: 'row-click', rowId: string | number): void
  (e: 'sort-change', sortKey: string): void
}>()

function onHeaderClick(col: Column): void {
  if (col.sortKey) emit('sort-change', col.sortKey)
}

function sortIndicator(col: Column): string {
  if (!col.sortKey || props.sortBy !== col.sortKey) return ''
  return props.sortDir === 'asc' ? ' ▲' : ' ▼'
}

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
    // rowHeightPx is only an ESTIMATE for the initial layout pass -- real ledger statements
    // vary wildly in length and wrap to multiple lines, so a fixed height here was the root
    // cause of the >200-row overlap (cycle3-ledger-virtualization-overflow): every row was
    // absolutely positioned via `translateY` at a multiple of this constant regardless of how
    // tall its wrapped text actually rendered, so long-statement rows spilled into the next
    // row's slot. `measureElement` (wired via the `data-index`+ref callback below) has the
    // virtualizer re-measure each row's real DOM height after mount/update and re-derive every
    // subsequent row's offset from actual sizes, same pattern as tanstack/virtual's own
    // dynamic-size-list example.
    estimateSize: () => props.rowHeightPx,
    overscan: 12,
  })),
)

function measureRow(el: Element | { $el: Element } | null): void {
  if (!el) return
  virtualizer.value.measureElement(el as Element)
}

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
    <table v-else-if="!shouldVirtualize" class="stack-on-narrow">
      <thead>
        <tr>
          <th
            v-for="col in columns"
            :key="col.key"
            :class="{ sortable: col.sortKey }"
            @click="onHeaderClick(col)"
          >{{ col.label }}{{ sortIndicator(col) }}</th>
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
        <div
          v-for="col in columns"
          :key="col.key"
          role="columnheader"
          class="vg-cell vg-head"
          :class="{ sortable: col.sortKey }"
          @click="onHeaderClick(col)"
        >{{ col.label }}{{ sortIndicator(col) }}</div>
      </div>
      <div class="virtual-inner" :style="{ height: virtualizer.getTotalSize() + 'px' }">
        <div
          v-for="vrow in virtualizer.getVirtualItems()"
          :key="vrow.index"
          :ref="measureRow"
          :data-index="vrow.index"
          class="virtual-row"
          :style="{ transform: `translateY(${vrow.start}px)` }"
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
th.sortable,
.vg-head.sortable {
  cursor: pointer;
  user-select: none;
}
th.sortable:hover,
.vg-head.sortable:hover {
  color: var(--text);
}
</style>
