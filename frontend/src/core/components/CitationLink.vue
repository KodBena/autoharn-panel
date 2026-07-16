<!--
  src/core/components/CitationLink.vue -- ONE `row:<id>` citation, rendered as a router-link to
  the item view (`/item/<id>`, SPEC.md sec 2.2) with a hover synopsis card (statement excerpt,
  actor, age -- SPEC.md sec 0/2.1's "hover synopsis everywhere"). CORE-GENERIC: row:N citations
  are ledger-generic syntax (any kind's `statement` can contain one), not autoharn vocabulary, so
  this lives under core/ same as the citations it renders (scripts/lint-boundaries.mjs RULE 2).

  Not rendered standalone -- CitationText.vue is the entry point every statement-rendering
  caller uses; this is its one-citation leaf, split out so CitationText's segment loop stays a
  plain v-for over plain-text-or-CitationLink, no inline hover-state logic duplicated per segment.

  The card is `<Teleport to="body">`d and positioned with `position: fixed` (viewport coordinates,
  same space `getBoundingClientRect()` returns) instead of `position: absolute` inside this span's
  own inline-flow ancestor. Root cause this works around (citation-hover-preview investigation,
  cycle-4 audit finding 9): DataTable.vue's >200-row windowed path renders rows inside
  `.virtual-viewport`, which sets `overflow-y: auto` (required for the windowing itself) -- any
  descendant popping upward past that ancestor's own top edge is clipped from view even though the
  DOM node exists and mounts correctly (a shallow visibility check, e.g. Playwright's `isVisible()`,
  does not catch this: it does not test ancestor scroll-clipping). The plain small-N `<table>` path
  never actually clipped (its `.scroll-x` wrapper has no fixed height), which is why the bug reads
  as "the feature is fully implemented and works" on casual reading/small-N testing, yet a reader
  scrolled into a large virtualized list sees nothing. Teleporting escapes every scroll-clipping
  ancestor unconditionally, so this fix is not narrowly scoped to the virtualized path alone.
-->
<script setup lang="ts">
import { computed, ref, nextTick } from 'vue'
import { useRowSynopsis } from '../composables/useRowSynopsis'
import { truncate } from '../../utils/format'

const props = defineProps<{
  rowId: number
  /** Display text for the link -- defaults to `row:<id>`. Set by CitationText.vue's `target
   * <id>` recognition (violation-dispositions-queue, cycle-4 finding 10) so a statement like
   * "orphaned_by_retraction target 602 (retired)" keeps rendering its own original wording
   * ("target 602") as the clickable text instead of being rewritten to "row:602". */
  label?: string
}>()

const { ensureLoaded, get } = useRowSynopsis()
const hovering = ref(false)
const wrapEl = ref<HTMLElement | null>(null)

const CARD_MAX_WIDTH = 352 // px -- matches this file's own `max-width: 22rem` at a 16px root font
const MIN_SPACE_ABOVE = 140 // px -- rough floor for the card's own rendered height

const cardTop = ref(0)
const cardLeft = ref(0)
const openDown = ref(false)

// Computed once per hover (not tracked continuously against scroll/resize) -- this is a
// transient, mouseleave-dismissed tooltip, same lightweight-on-purpose shape as the rest of this
// component; re-deriving position continuously would be tracking state no other hover affordance
// in this app maintains.
function positionCard(): void {
  const el = wrapEl.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  openDown.value = rect.top < MIN_SPACE_ABOVE
  cardTop.value = openDown.value ? rect.bottom + 4 : rect.top - 4
  cardLeft.value = Math.max(8, Math.min(rect.left, window.innerWidth - CARD_MAX_WIDTH - 8))
}

function onHover(): void {
  hovering.value = true
  ensureLoaded(props.rowId)
  nextTick(positionCard)
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
  <span ref="wrapEl" class="citation-wrap" @mouseenter="onHover" @mouseleave="onLeave">
    <router-link :to="`/item/${rowId}`" class="citation-link" @click.stop>{{ label ?? `row:${rowId}` }}</router-link>
    <Teleport to="body">
      <div
        v-if="hovering"
        class="citation-card"
        :class="{ 'citation-card--down': openDown }"
        role="tooltip"
        :style="{ top: cardTop + 'px', left: cardLeft + 'px' }"
      >
        <template v-if="entry === undefined || entry === 'loading'">loading row:{{ rowId }}…</template>
        <template v-else-if="entry === 'error'">could not load row:{{ rowId }}</template>
        <template v-else>
          <div class="citation-card-head">
            #{{ entry.id }} · {{ entry.kind }} · {{ entry.actor_name || '(unknown actor)' }} · {{ ageOf(entry.ts) }}
          </div>
          <div class="citation-card-body">{{ truncate(entry.statement, 220) }}</div>
        </template>
      </div>
    </Teleport>
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
  position: fixed;
  z-index: 50;
  min-width: 14rem;
  max-width: 22rem;
  padding: 0.4rem 0.55rem;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
  font-size: 0.76rem;
  white-space: normal;
  overflow-wrap: anywhere;
  /* default: card's bottom edge anchored 4px above the link, growing upward -- matches the
     original bottom:100% behavior without needing the card's height known in advance. */
  transform: translateY(-100%);
}
.citation-card--down {
  /* insufficient room above (near the viewport's own top edge) -- grow downward instead. */
  transform: none;
}
.citation-card-head {
  font-weight: 600;
  color: var(--text-dim);
  margin-bottom: 0.2rem;
}
</style>
