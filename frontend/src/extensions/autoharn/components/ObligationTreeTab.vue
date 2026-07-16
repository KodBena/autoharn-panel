<!--
  src/extensions/autoharn/components/ObligationTreeTab.vue -- the obligation/dependency AND-tree
  rendered as a real layered-DAG graph (SPEC.md sec 2.3, P0; cycle-5 audit finding 1, CRITICAL;
  work item obligation-tree-view, acceptance criteria row:846). Backed by
  `GET /api/obligation-tree/{slug}` (extensions.autoharn.routes/ledger_read, commit 9b20033,
  row_id field added by this item's own row:908/909 decision).

  Navigation placement (row:910's decision): a NEW tab with an in-tab slug picker, rejecting a
  per-row "view tree" link embedded in WorkItemsTab.vue's DataTable -- see that decision row for
  the full rejected-alternative reasoning (DataTable/DataRow has no per-row action-link slot
  today, and a picker reaches any slug in the deployment independent of whatever page of Work
  Items happens to be showing).

  Layout: a hand-rolled layered layout (utils/obligationTreeLayout.ts), explicitly sanctioned at
  this item's own scope over reaching for a graph library (row:909's decision) -- plain SVG,
  one <g> per node, one line per edge. A DAG diamond renders as more than one node instance (the
  backend's own `obligation_tree()` doc comment: "the standard, harmless way to render a DAG as
  a tree"); this view does not attempt to de-duplicate those instances.

  Live recolor on SSE (acceptance criterion 4): `tick` (useLiveUpdates, the app's one shared SSE
  connection) triggers a plain refetch, same pattern every other tab already uses -- no separate
  recolor plumbing needed, since color is derived straight from the freshly-fetched `tree` ref on
  every render.

  Hover synopsis (acceptance criterion 3): a lightweight equivalent of CitationLink.vue's
  Teleport-to-body, fixed-position hover card (same technique, so it never gets scroll-clipped by
  an ancestor the way that component's own header comment documents) -- populated directly from
  the node data already in hand (no extra fetch: the tree response already carries title/kind/
  discharge_state/state/resolution, so re-fetching a row synopsis per node would be a pure,
  avoidable N+1 at the 500-node scale target).

  Click (acceptance criterion 3): navigates to `/item/<row_id>` -- this slug's own `work_opened`
  ledger row, resolved server-side (row:908/909's decision on why that lookup lives in the tree
  endpoint's own wire rather than a second route). A node with no row_id (the backend's
  should-be-unreachable stub case) is not clickable.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../../core/services/api-client'
import { useLiveUpdates } from '../../../core/composables/useLiveUpdates'
import { truncate } from '../../../utils/format'
import type { ObligationNode } from '../services/types'
import type { WorkItemRow } from '../services/types'
import {
  layoutObligationTree,
  NODE_WIDTH,
  NODE_HEIGHT,
  type LayoutNode,
  type ObligationTreeLayout,
} from '../utils/obligationTreeLayout'

const router = useRouter()
const { tick } = useLiveUpdates()

const workItems = ref<WorkItemRow[]>([])
const slugInput = ref('')
const tree = ref<ObligationNode | null>(null)
const error = ref<string | null>(null)
const notFound = ref(false)

const DISCHARGE_LEGEND: { state: string; label: string }[] = [
  { state: 'undischarged', label: 'undischarged' },
  { state: 'discharged', label: 'discharged' },
  { state: 'ambiguous-partial', label: 'ambiguous / partial' },
  { state: 'superseded', label: 'superseded' },
]

const slugOptions = computed(() => [...workItems.value].sort((a, b) => a.slug.localeCompare(b.slug)))

async function loadWorkItems(): Promise<void> {
  const { data, error: err } = await api.GET('/api/work')
  if (err) throw err
  workItems.value = (data ?? []) as unknown as WorkItemRow[]
  if (!slugInput.value && workItems.value.length > 0) {
    slugInput.value = workItems.value[0].slug
  }
}

// Monotonic request counter: `loadTree` can be triggered twice in quick succession for two
// DIFFERENT slugs (the mount-time default-slug assignment fires the `slugInput` watcher once,
// then `loadAll`'s own explicit call fires again; a caller changing the slug again before the
// first fetch resolves compounds this further) -- without a guard, an EARLIER fetch for a
// no-longer-current slug can resolve AFTER a later one and silently clobber `tree` with stale
// data under the current slug's own label. Each call captures its own ticket; a response is
// applied only if its ticket is still the most recently issued one when it arrives.
let loadTreeTicket = 0

async function loadTree(): Promise<void> {
  const slug = slugInput.value.trim()
  const ticket = ++loadTreeTicket
  if (!slug) {
    tree.value = null
    notFound.value = false
    return
  }
  const { data, error: err, response } = await api.GET('/api/obligation-tree/{slug}', {
    params: { path: { slug } },
  })
  if (ticket !== loadTreeTicket) return // a newer loadTree() call has since superseded this one
  if (err) {
    if (response?.status === 404) {
      tree.value = null
      notFound.value = true
      error.value = null
      return
    }
    throw err
  }
  tree.value = (data ?? null) as unknown as ObligationNode | null
  notFound.value = false
}

async function loadAll(): Promise<void> {
  try {
    await loadWorkItems()
    await loadTree()
    error.value = null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(loadAll)
watch(slugInput, loadTree)
// Live recolor (acceptance criterion 4): an SSE ledger-change tick refetches the tree; discharge
// coloring below is derived straight from the freshly-fetched `tree` ref, so a color change
// reaches the screen on Vue's next render with no extra wiring.
watch(tick, loadTree)
defineExpose({ reload: loadAll })

const layout = computed<ObligationTreeLayout | null>(() => (tree.value ? layoutObligationTree(tree.value) : null))

// --- hover synopsis (CitationLink.vue's Teleport/fixed-position technique, lightweight
// equivalent -- populated from data already in hand, no per-node fetch) -------------------------
const hovered = ref<LayoutNode | null>(null)
const cardTop = ref(0)
const cardLeft = ref(0)
const CARD_MAX_WIDTH = 300

function onHover(ln: LayoutNode, ev: MouseEvent): void {
  hovered.value = ln
  cardTop.value = ev.clientY + 14
  cardLeft.value = Math.max(8, Math.min(ev.clientX + 10, window.innerWidth - CARD_MAX_WIDTH - 8))
}
function onLeave(): void {
  hovered.value = null
}

function onClick(ln: LayoutNode): void {
  if (ln.node.row_id === null) return
  router.push(`/item/${ln.node.row_id}`)
}

function nodeTitle(node: ObligationNode): string {
  return node.title ?? '(no title)'
}
</script>

<template>
  <section class="panel">
    <h2>
      Obligation tree
      <span class="refresh-row"><button @click="loadAll">Refresh</button></span>
    </h2>
    <div class="commission-picker">
      <label for="otree-slug">work item slug:</label>
      <input
        id="otree-slug"
        v-model="slugInput"
        type="text"
        list="otree-slug-options"
        placeholder="slug"
        style="width: 16rem"
      />
      <datalist id="otree-slug-options">
        <option v-for="w in slugOptions" :key="w.slug" :value="w.slug">{{ w.title }}</option>
      </datalist>
      <span class="otree-legend">
        <span v-for="l in DISCHARGE_LEGEND" :key="l.state" class="otree-legend-item">
          <span class="otree-swatch" :class="`otree-swatch--${l.state}`" />{{ l.label }}
        </span>
      </span>
    </div>

    <div v-if="error" class="error-banner">{{ error }}</div>
    <p v-else-if="notFound" class="empty-note">No work item '{{ slugInput }}' was ever opened.</p>
    <p v-else-if="!slugInput" class="empty-note">Enter or pick a work item slug above.</p>

    <div v-else-if="layout" class="otree-canvas" role="img" :aria-label="`obligation tree rooted at ${slugInput}`">
      <svg :width="layout.width" :height="layout.height">
        <g v-for="(e, i) in layout.edges" :key="i" class="otree-edge">
          <line
            :x1="e.from.x + NODE_WIDTH / 2"
            :y1="e.from.y + NODE_HEIGHT"
            :x2="e.to.x + NODE_WIDTH / 2"
            :y2="e.to.y"
          />
        </g>
        <g
          v-for="ln in layout.nodes"
          :key="ln.id"
          class="otree-node"
          :class="[`otree-node--${ln.node.discharge_state}`, `otree-node--${ln.node.kind}`, { 'otree-node--clickable': ln.node.row_id !== null }]"
          :transform="`translate(${ln.x}, ${ln.y})`"
          tabindex="0"
          role="button"
          :aria-label="`${ln.node.slug}: ${ln.node.discharge_state}`"
          @mouseenter="onHover(ln, $event)"
          @mousemove="onHover(ln, $event)"
          @mouseleave="onLeave"
          @click="onClick(ln)"
          @keydown.enter="onClick(ln)"
        >
          <title>{{ ln.node.slug }} -- {{ ln.node.discharge_state }}</title>
          <rect :width="NODE_WIDTH" :height="NODE_HEIGHT" rx="6" />
          <text x="8" y="18" class="otree-node-slug">{{ truncate(ln.node.slug, 22) }}</text>
          <text x="8" y="34" class="otree-node-title">{{ truncate(nodeTitle(ln.node), 26) }}</text>
        </g>
      </svg>
    </div>

    <Teleport to="body">
      <div v-if="hovered" class="otree-hover-card" :style="{ top: cardTop + 'px', left: cardLeft + 'px' }" role="tooltip">
        <div class="otree-hover-head">
          <span class="tag">{{ hovered.node.slug }}</span>
          <span class="badge" :class="`otree-badge--${hovered.node.discharge_state}`">{{ hovered.node.discharge_state }}</span>
        </div>
        <div class="otree-hover-body">{{ nodeTitle(hovered.node) }}</div>
        <div class="otree-hover-meta">
          {{ hovered.node.kind }} · state {{ hovered.node.state }} · effective {{ hovered.node.effective_state }}
          <template v-if="hovered.node.resolution"> · resolution {{ hovered.node.resolution }}</template>
        </div>
        <div v-if="hovered.node.row_id === null" class="muted">(no ledger row to navigate to)</div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.otree-legend {
  display: inline-flex;
  gap: 0.75rem;
  margin-left: 0.75rem;
  font-size: 0.76rem;
  color: var(--text-dim);
}
.otree-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}
.otree-swatch {
  display: inline-block;
  width: 0.7rem;
  height: 0.7rem;
  border-radius: 2px;
  border: 1px solid var(--border);
}
.otree-swatch--undischarged { background: var(--danger-bg); border-color: var(--danger); }
.otree-swatch--discharged { background: var(--ok-bg); border-color: var(--ok-text); }
.otree-swatch--ambiguous-partial { background: var(--warn-bg); border-color: var(--warn-text); }
.otree-swatch--superseded { background: var(--open-bg); border-color: var(--border); }

.otree-canvas {
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 4px;
  max-height: 70vh;
  padding: 0.5rem;
}

.otree-edge line {
  stroke: var(--border);
  stroke-width: 1.5;
}

.otree-node rect {
  stroke-width: 1.5;
}
.otree-node text {
  fill: var(--text);
  font-size: 0.72rem;
  font-family: var(--sans);
}
.otree-node-slug {
  font-family: var(--mono);
  font-weight: 600;
}
.otree-node-title {
  fill: var(--text-dim);
}
.otree-node--clickable {
  cursor: pointer;
}
.otree-node--clickable:hover rect,
.otree-node--clickable:focus-visible rect {
  stroke-width: 2.5;
}
.otree-node--composite rect {
  stroke-width: 2.5;
}

.otree-node--undischarged rect { fill: var(--danger-bg); stroke: var(--danger); }
.otree-node--discharged rect { fill: var(--ok-bg); stroke: var(--ok-text); }
.otree-node--ambiguous-partial rect { fill: var(--warn-bg); stroke: var(--warn-text); }
.otree-node--superseded rect { fill: var(--open-bg); stroke: var(--border); stroke-dasharray: 4 2; }

.otree-hover-card {
  position: fixed;
  z-index: 50;
  min-width: 14rem;
  max-width: 300px;
  padding: 0.45rem 0.6rem;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
  font-size: 0.78rem;
  pointer-events: none;
}
.otree-hover-head {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.25rem;
}
.otree-hover-body {
  color: var(--text);
  margin-bottom: 0.2rem;
}
.otree-hover-meta {
  color: var(--text-dim);
  font-size: 0.72rem;
}
.otree-badge--undischarged { background: var(--danger); color: #fff; }
.otree-badge--discharged { background: var(--ok-bg); color: var(--ok-text); }
.otree-badge--ambiguous-partial { background: var(--warn-bg); color: var(--warn-text); }
.otree-badge--superseded { background: var(--open-bg); color: var(--text-dim); }
</style>
