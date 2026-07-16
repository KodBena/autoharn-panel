<!--
  src/extensions/autoharn/components/WorkViolationsTab.vue -- autoharn/kernel-semantic
  (`work_item_violations`, the kernel's own live "what's currently wrong right now" signal).
  Backed by `GET /api/work-violations`. Same honest-narrow-columns note as before: the kernel
  view carries only `violation, slug, detail, target_id`, no id/ts/actor of its own.

  Thin wrapper over SimpleQueueTab.vue (work item tab-architecture-consolidation, row:748) --
  `target_id` doubles as this tab's row-click target (mirroring `review_gap`'s own `id` column
  serving the same role in ReviewGapTab.vue), so this uses the fetch-detail mode
  (`expand-on-fetch`) with no inline truncation, same as ReviewGapTab.vue.
-->
<script setup lang="ts">
import type { Column } from '../../../core/components/DataTable.vue'
import SimpleQueueTab from '../../../core/components/SimpleQueueTab.vue'

const columns: Column[] = [
  { key: 'violation', label: 'violation', width: '12rem' },
  { key: 'slug', label: 'work item slug', mono: true, width: '12rem' },
  { key: 'detail', label: 'detail', width: '3fr' },
  { key: 'target_id', label: 'target row', mono: true, width: '7rem' },
]
</script>

<template>
  <SimpleQueueTab
    title="Violations"
    endpoint="/api/work-violations"
    :columns="columns"
    :get-row-id="(r) => r.target_id as number"
    expand-on-fetch
    description="Every currently-unresolved decomposition-tree violation the kernel's own `work_item_violations` view reports (duplicate opens, dangling refs, cycles, a shipped close with no witness, ...) that has not already been disposed of via a work_violation_disposition row. Click a row's target row id to expand the ledger statement it names (fetched on demand)."
    empty-text="No violations -- the decomposition tree currently has none unresolved."
  />
</template>
