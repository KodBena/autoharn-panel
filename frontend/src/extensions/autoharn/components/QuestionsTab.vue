<!--
  src/extensions/autoharn/components/QuestionsTab.vue -- autoharn-semantic (`question_status`
  kernel view). Backed by `GET /api/questions`. Same honest-narrow-columns note as
  ReviewGapTab.vue for the kernel VIEW's own columns (`question_id, question_kind, answered,
  first_answer_id, answers_target_not_a_question` -- still no actor/ts on the view itself);
  `statement` is NOT one of them -- backend/extensions/autoharn/ledger_read.py's
  question_status() joins it in from `ledger_current` (cycle-4 audit finding 11, work item
  questions-inline-text, row:633/659) so this table shows a snippet of the actual question text
  instead of requiring a click-through to learn what was asked.

  Thin wrapper over SimpleQueueTab.vue (work item tab-architecture-consolidation, row:748) --
  this tab uses BOTH composable modes at once: inline-truncate on `statement` (LedgerTab.vue's
  own STATEMENT_TRUNCATE_AT convention) AND fetch-detail-on-click (same gesture ReviewGapTab.vue/
  WorkViolationsTab.vue use), reusing the row-click DataTable already emits for both rather than
  adding a second, independent per-cell toggle. `question_id` links to the ledger row via
  `/api/rows/{id}` on click, expanded in place (no elision once expanded).
-->
<script setup lang="ts">
import type { Column } from '../../../core/components/DataTable.vue'
import SimpleQueueTab from '../../../core/components/SimpleQueueTab.vue'

const columns: Column[] = [
  { key: 'question_id', label: 'question row', mono: true, width: '8rem' },
  { key: 'question_kind', label: 'kind', width: '9rem' },
  { key: 'answered', label: 'answered', width: '6rem' },
  { key: 'first_answer_id', label: 'first answer row', mono: true, width: '10rem' },
  { key: 'answers_target_not_a_question', label: 'answers non-question target', width: '10rem' },
  { key: 'statement', label: 'question text', width: '3fr', richText: true },
]
</script>

<template>
  <SimpleQueueTab
    title="Questions"
    endpoint="/api/questions"
    :columns="columns"
    :get-row-id="(r) => r.question_id as number"
    truncate-column="statement"
    expand-on-fetch
    description="Long question text is truncated by default -- click a row to expand it and load its full ledger entry (kind/actor/ts) below."
    empty-text="No open questions."
  />
</template>
