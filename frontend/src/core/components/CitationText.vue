<!--
  src/core/components/CitationText.vue -- the ONE reusable place `row:<digits>` tokens inside any
  rendered statement/title/resolution text get turned into clickable citations (SPEC.md sec
  0/2.1: "hover synopsis everywhere"). Splits `text` on the row-token regex into plain-text and
  citation segments; plain segments render as-is, citation segments render via CitationLink.vue
  (the actual link + hover card). Every caller across the app (LedgerTab's statement column via
  DataRow.vue, ReviewGapTab.vue/QuestionsTab.vue's expanded statement, CommissionTab.vue's
  commission statement, ItemDetail.vue's own statement field) goes through this ONE component --
  no caller re-implements the regex or the link rendering itself.

  Plain-text segments (the ones NOT already a `row:<id>` citation) are further split against
  ../glossary.ts's internal-vocabulary table, wrapping any match (kernel-generation ids, ADR
  numbers, ...) in a native-`title` hover span -- this is the SAME one scan over each statement
  the citation split already does, just a second pass restricted to the leftover plain segments,
  not a parallel independent scan over the raw statement string.

  Also recognizes a bare `target <id>` phrase as a citation (violation-dispositions-queue,
  cycle-4 finding 10): `work_violation_disposition` ledger rows (e.g. "orphaned_by_retraction
  target 602 (retired)", composed by the `led` CLI, not this app) name their target purely as
  english prose, never a `row:<id>` token -- confirmed against this deployment's own live rows
  (498-502, 608) that `target_id` there always resolves against `ledger_current`. Rendered with
  its own original wording preserved as the link text (CitationLink's `label` prop) rather than
  rewritten to `row:<id>`, so a reader sees the same words the ledger actually recorded.
-->
<script setup lang="ts">
import { computed } from 'vue'
import CitationLink from './CitationLink.vue'
import { findGlossaryMatches } from '../glossary'

const props = defineProps<{ text: string | null | undefined }>()

const ROW_REF_RE = /row:(\d+)|\btarget (\d+)\b/g

interface Segment {
  key: number
  kind: 'text' | 'citation' | 'glossary'
  value: string
  rowId: number | null
  gloss?: string
}

let keyCounter = 0

// Splits a plain-text run against the glossary table, producing 'text' and 'glossary' segments.
function splitGlossary(text: string): Segment[] {
  const matches = findGlossaryMatches(text)
  if (matches.length === 0) return [{ key: keyCounter++, kind: 'text', value: text, rowId: null }]
  const out: Segment[] = []
  let last = 0
  for (const m of matches) {
    if (m.index > last) out.push({ key: keyCounter++, kind: 'text', value: text.slice(last, m.index), rowId: null })
    out.push({ key: keyCounter++, kind: 'glossary', value: m.label, rowId: null, gloss: m.gloss })
    last = m.index + m.length
  }
  if (last < text.length) out.push({ key: keyCounter++, kind: 'text', value: text.slice(last), rowId: null })
  return out
}

const segments = computed<Segment[]>(() => {
  const s = props.text ?? ''
  const out: Segment[] = []
  let last = 0
  keyCounter = 0
  for (const m of s.matchAll(ROW_REF_RE)) {
    const idx = m.index ?? 0
    if (idx > last) out.push(...splitGlossary(s.slice(last, idx)))
    out.push({ key: keyCounter++, kind: 'citation', value: m[0], rowId: Number(m[1] ?? m[2]) })
    last = idx + m[0].length
  }
  if (last < s.length) out.push(...splitGlossary(s.slice(last)))
  if (out.length === 0) out.push({ key: keyCounter++, kind: 'text', value: '', rowId: null })
  return out
})
</script>

<template>
  <span class="citation-text">
    <template v-for="seg in segments" :key="seg.key">
      <CitationLink v-if="seg.kind === 'citation'" :row-id="seg.rowId!" :label="seg.value" />
      <span v-else-if="seg.kind === 'glossary'" class="glossary-term" :title="seg.gloss">{{ seg.value }}</span>
      <span v-else>{{ seg.value }}</span>
    </template>
  </span>
</template>

<style scoped>
.glossary-term {
  border-bottom: 1px dotted var(--text-dim, #888);
  cursor: help;
}
</style>
