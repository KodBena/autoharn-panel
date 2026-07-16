<!--
  src/core/components/CitationLink.vue -- ONE `row:<id>` citation, rendered as a router-link to
  the item view (`/item/<id>`, SPEC.md sec 2.2) with a hover synopsis card (statement excerpt,
  actor, age -- SPEC.md sec 0/2.1's "hover synopsis everywhere"). CORE-GENERIC: row:N citations
  are ledger-generic syntax (any kind's `statement` can contain one), not autoharn vocabulary, so
  this lives under core/ same as the citations it renders (scripts/lint-boundaries.mjs RULE 2).

  Not rendered standalone -- CitationText.vue is the entry point every statement-rendering
  caller uses; this is its one-citation leaf, split out so CitationText's segment loop stays a
  plain v-for over plain-text-or-CitationLink, no inline hover-state logic duplicated per segment.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRowSynopsis } from '../composables/useRowSynopsis'
import { truncate } from '../../utils/format'

const props = defineProps<{ rowId: number }>()

const { ensureLoaded, get } = useRowSynopsis()
const hovering = ref(false)

function onHover(): void {
  hovering.value = true
  ensureLoaded(props.rowId)
}
function onLeave(): void {
  hovering.value = false
}

const entry = computed(() => get(props.rowId))

// Deliberately coarse (minute/hour/day buckets only) -- this is a glanceable hover synopsis, not
// a precise timestamp (fmtTs already renders the exact ts, one click away on the item view).
function ageOf(ts: string | null | undefined): string {
  if (!ts) return ''
  const then = new Date(ts).getTime()
  if (Number.isNaN(then)) return ''
  const mins = Math.max(0, Math.floor((Date.now() - then) / 60000))
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}
</script>

<template>
  <span class="citation-wrap" @mouseenter="onHover" @mouseleave="onLeave">
    <router-link :to="`/item/${rowId}`" class="citation-link" @click.stop>row:{{ rowId }}</router-link>
    <div v-if="hovering" class="citation-card" role="tooltip">
      <template v-if="entry === undefined || entry === 'loading'">loading row:{{ rowId }}…</template>
      <template v-else-if="entry === 'error'">could not load row:{{ rowId }}</template>
      <template v-else>
        <div class="citation-card-head">
          #{{ entry.id }} · {{ entry.kind }} · {{ entry.actor_name || '(unknown actor)' }} · {{ ageOf(entry.ts) }}
        </div>
        <div class="citation-card-body">{{ truncate(entry.statement, 220) }}</div>
      </template>
    </div>
  </span>
</template>

<style scoped>
.citation-wrap {
  position: relative;
  display: inline-block;
}
.citation-link {
  color: var(--accent);
  text-decoration: underline dotted;
}
.citation-card {
  position: absolute;
  bottom: 100%;
  left: 0;
  z-index: 50;
  min-width: 14rem;
  max-width: 22rem;
  margin-bottom: 0.25rem;
  padding: 0.4rem 0.55rem;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
  font-size: 0.76rem;
  white-space: normal;
  overflow-wrap: anywhere;
}
.citation-card-head {
  font-weight: 600;
  color: var(--text-dim);
  margin-bottom: 0.2rem;
}
</style>
