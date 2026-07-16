<!--
  src/extensions/autoharn/components/ReviewGapTab.vue -- autoharn/kernel-semantic
  (`countersign_obligation`, review-gap vocabulary). Backed by `GET /api/review-gap`.

  Honest note on the live wire shape (see src/api/types.ts's ReviewGapRow comment): the
  kernel's `review_gap` view returns `id, actor, scope, assigned_by` -- `actor` is a bare
  principal id, not a joined name, and there is no statement/timestamp column at all. The
  vanilla PoC's app.js assumed richer columns that this view does not actually have; this tab
  renders the real columns rather than reproducing that assumption. `id` links to the ledger
  row via `/api/rows/{id}` on click (a lightweight, un-elided expansion in place, not a full
  item-view route -- SPEC.md sec 2.2's item view is out of this port's scope, see
  src/views/stubs/ItemView.stub.vue for its intended home).

  Thin wrapper over SimpleQueueTab.vue (work item tab-architecture-consolidation, row:748):
  this tab's fetch-on-click-expand shape is the SAME as WorkViolationsTab.vue's (row:745/747's
  own finding, confirmed by direct diff) -- migrated alongside it rather than left as a bespoke
  copy of a pattern the generic component already covers.
-->
<script setup lang="ts">
import type { Column } from '../../../core/components/DataTable.vue'
import SimpleQueueTab from '../../../core/components/SimpleQueueTab.vue'

const columns: Column[] = [
  { key: 'id', label: 'row', mono: true, width: '4.5rem' },
  { key: 'actor', label: 'actor (principal id)', mono: true, width: '10rem' },
  { key: 'scope', label: 'scope', width: '10rem' },
  { key: 'assigned_by', label: 'assigned by (principal id)', mono: true, width: '10rem' },
]
</script>

<template>
  <SimpleQueueTab
    title="Review gaps"
    endpoint="/api/review-gap"
    :columns="columns"
    :get-row-id="(r) => r.id as number"
    expand-on-fetch
    description="Click a row id to expand the ledger statement it belongs to (fetched on demand)."
    empty-text="No review gaps -- every countersign obligation is currently discharged."
  />
</template>
