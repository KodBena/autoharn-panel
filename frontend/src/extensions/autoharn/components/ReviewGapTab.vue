<!--
  src/extensions/autoharn/components/ReviewGapTab.vue -- autoharn/kernel-semantic
  (`countersign_obligation`, review-gap vocabulary). Backed by `GET /api/review-gap`.

  Honest note on the live wire shape (see src/extensions/autoharn/services/types.ts's
  ReviewGapRow comment): the kernel's `review_gap` view itself returns only `id, actor, scope,
  assigned_by` -- no joined name, no statement/timestamp column at all. The vanilla PoC's app.js
  assumed richer columns that this view does not actually have; this tab renders the real
  columns rather than reproducing that assumption. `actor_name`/`assigned_by_name` ARE shown
  below despite not being view columns: `ledger_read.review_gap()` (backend/extensions/autoharn/
  ledger_read.py) joins them in from `principal`, same pattern every other tab's query already
  uses (cycle-5 audit finding 9, MINOR -- this was the one tab left rendering raw ids). `id`
  links to the ledger row via `/api/rows/{id}` on click (a lightweight, un-elided expansion in
  place, not a navigation to the full item view -- a real one exists at `/item/:id`,
  src/ItemView.vue, SPEC.md sec 2.2 -- kept as inline-expand rather than a row-click navigation
  because this component is a thin wrapper over the shared SimpleQueueTab.vue below, whose
  fetch-on-click-expand behavior is shared verbatim by 4 other tabs; switching only this one to
  navigate would mean forking that shared behavior, a larger change than cycle-5 finding 10's
  stale-comment fix warranted -- left as a follow-up if a future session wants it).

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
  { key: 'actor_name', label: 'actor', width: '10rem' },
  { key: 'scope', label: 'scope', width: '10rem' },
  { key: 'assigned_by_name', label: 'assigned by', width: '10rem' },
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
