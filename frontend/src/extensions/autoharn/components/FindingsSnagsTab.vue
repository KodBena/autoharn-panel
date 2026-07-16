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

  Thin wrapper over SimpleQueueTab.vue (work item tab-architecture-consolidation, row:748) --
  inline-truncate mode on `statement` (LedgerTab.vue's own convention byte-for-byte, same
  STATEMENT_TRUNCATE_AT), not the separate-fetch-on-click pattern
  ReviewGapTab.vue/QuestionsTab.vue/WorkViolationsTab.vue use, since `findings_and_snags()`
  already returns the full statement text in the same payload; there is nothing narrower to
  fetch a second time.
-->
<script setup lang="ts">
import type { Column } from '../../../core/components/DataTable.vue'
import SimpleQueueTab from '../../../core/components/SimpleQueueTab.vue'
import { fmtTs } from '../../../utils/format'

const columns: Column[] = [
  { key: 'id', label: 'id', mono: true, width: '4.5rem' },
  { key: 'kind', label: 'kind', width: '6rem' },
  { key: 'actor_name', label: 'actor', width: '9rem' },
  { key: 'ts_fmt', label: 'ts', mono: true, width: '11rem' },
  { key: 'statement', label: 'statement', width: '3fr', richText: true },
]

function rowTransform(r: Record<string, unknown>): Record<string, unknown> {
  return { ...r, ts_fmt: fmtTs(r.ts as string | null) }
}
</script>

<template>
  <SimpleQueueTab
    title="Findings &amp; snags"
    endpoint="/api/findings-snags"
    :columns="columns"
    :get-row-id="(r) => r.id as number"
    truncate-column="statement"
    :row-transform="rowTransform"
    description="Every recorded `finding`/`snag` row -- the ledger's own recorded-defect/observation prose, surfaced here directly rather than only reachable via Recent Ledger's generic kind filter. Long statements are truncated by default -- click a row to expand or collapse its full text."
    empty-text="No finding or snag rows recorded yet."
  />
</template>
