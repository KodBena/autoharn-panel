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

  Thin wrapper over SimpleQueueTab.vue (work item tab-architecture-consolidation, row:748) --
  inline-truncate mode on `statement`, byte-for-byte the same convention as
  FindingsSnagsTab.vue (same STATEMENT_TRUNCATE_AT), since `standing_decisions` already returns
  the full statement text in the same payload (same shape as `findings_and_snags`); there is
  nothing narrower to fetch a second time.
-->
<script setup lang="ts">
import type { Column } from '../../../core/components/DataTable.vue'
import SimpleQueueTab from '../../../core/components/SimpleQueueTab.vue'

const columns: Column[] = [
  { key: 'id', label: 'id', mono: true, width: '4.5rem' },
  { key: 'grade', label: 'grade', width: '7rem' },
  { key: 'statement', label: 'statement', width: '3fr', richText: true },
]
</script>

<template>
  <SimpleQueueTab
    title="Standing decisions"
    endpoint="/api/standing-decisions"
    :columns="columns"
    :get-row-id="(r) => r.id as number"
    truncate-column="statement"
    description="Every in-force `decision`-kind row carrying a writer-supplied grade (kernel's own `standing_decisions` view) -- the same &quot;survives context loss/compaction&quot; governance state `./led standing` and `./pickup` already surface to a CLI operator, previously invisible in this SPA. Long statements are truncated by default -- click a row to expand or collapse its full text."
    empty-text="No standing decisions -- no in-force decision row currently carries a grade."
  />
</template>
