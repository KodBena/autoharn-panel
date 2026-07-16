<!--
  src/core/components/CitationText.vue -- the ONE reusable place `row:<digits>` tokens inside any
  rendered statement/title/resolution text get turned into clickable citations (SPEC.md sec
  0/2.1: "hover synopsis everywhere"). Splits `text` on the row-token regex into plain-text and
  citation segments; plain segments render as-is, citation segments render via CitationLink.vue
  (the actual link + hover card). Every caller across the app (LedgerTab's statement column via
  DataRow.vue, ReviewGapTab.vue/QuestionsTab.vue's expanded statement, CommissionTab.vue's
  commission statement, ItemDetail.vue's own statement field) goes through this ONE component --
  no caller re-implements the regex or the link rendering itself.
-->
<script setup lang="ts">
import { computed } from 'vue'
import CitationLink from './CitationLink.vue'

const props = defineProps<{ text: string | null | undefined }>()

const ROW_REF_RE = /row:(\d+)/g

interface Segment {
  key: number
  kind: 'text' | 'citation'
  value: string
  rowId: number | null
}

const segments = computed<Segment[]>(() => {
  const s = props.text ?? ''
  const out: Segment[] = []
  let last = 0
  let key = 0
  for (const m of s.matchAll(ROW_REF_RE)) {
    const idx = m.index ?? 0
    if (idx > last) out.push({ key: key++, kind: 'text', value: s.slice(last, idx), rowId: null })
    out.push({ key: key++, kind: 'citation', value: m[0], rowId: Number(m[1]) })
    last = idx + m[0].length
  }
  if (last < s.length || out.length === 0) out.push({ key: key++, kind: 'text', value: s.slice(last), rowId: null })
  return out
})
</script>

<template>
  <span class="citation-text">
    <template v-for="seg in segments" :key="seg.key">
      <CitationLink v-if="seg.kind === 'citation'" :row-id="seg.rowId!" />
      <span v-else>{{ seg.value }}</span>
    </template>
  </span>
</template>
