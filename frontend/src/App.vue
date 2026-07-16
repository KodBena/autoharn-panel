<!--
  src/App.vue -- composition root. Per the omega speed-reap sheet's Don't-do #4, this component
  must NOT read any high-frequency reactive value in its own render -- the only reactive reads
  here are `activeTab` (derived from the low-frequency route path, row:557) and
  `healthState.health` (loaded once at boot, not a streaming value). The live-updates `tick` ref
  is read only by each tab
  component itself (leaf-owns-its-read), never here.
-->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { healthState, loadHealth } from './core/state/health'
import { useLiveUpdates } from './core/composables/useLiveUpdates'
import { TAB_DEFS, type TabId } from './tabs'

const { status } = useLiveUpdates()

// App.vue is the ONE always-mounted root component (main.ts's `createApp(App)`); rather than a
// separate root wrapper, this reads its own route (router.ts) to decide tab-UI vs the deep-
// linkable item view (SPEC.md sec 2.2). All tab wiring (which tabs exist, their labels,
// components, and route paths) is data-driven from `./tabs`'s TAB_DEFS array (work item
// tab-architecture-consolidation, row:748) -- previously 3 hand-maintained parallel spots here
// (a `TabId` union, separate `coreTabs`/`autoharnTabs` arrays, and a template `v-if` chain per
// tab), each touched by every tab-adding commit. That also removes this file's own stale tab-
// count comment this paragraph used to carry ("the six tabs below") -- TAB_DEFS is now the one
// place a tab count could be read from, so there is nothing left here to hand-narrate or drift.
const route = useRoute()
const router = useRouter()
// cycle3-unknown-path-404: was `isItemRoute = path.startsWith('/item/')`, which meant any path
// NOT starting with '/item/' fell through to the tab UI -- including a bogus, unrecognized path,
// silently rendering the default 'ledger' tab (pathToTab.get(...) ?? 'ledger' below) with no cue
// the URL was wrong. Inverted to a positive check: only a recognized tab path renders the tab
// UI; everything else (both '/item/:id' and the new catch-all not-found route) goes through
// RouterView, which resolves each to its own distinct view.
const isTabRoute = computed(() => TAB_DEFS.some((t) => t.path === route.path))

// row:557/cycle3-tab-url-routing: activeTab is now DERIVED from the URL (not its own ref) so
// that switching tabs, reloading, bookmarking, or navigating directly to a tab's URL all agree
// on which tab is showing -- the URL is the single source of truth, per the consult's finding 3.
const pathToTab = new Map<string, TabId>(TAB_DEFS.map((t) => [t.path, t.id as TabId]))
const activeTab = computed<TabId>(() => pathToTab.get(route.path) ?? 'ledger')

function selectTab(id: TabId) {
  if (activeTab.value === id) return
  const def = TAB_DEFS.find((t) => t.id === id)
  if (def) router.push(def.path)
}

const autoharnEnabled = computed(
  () => healthState.health?.extensions_enabled?.includes('autoharn') ?? false,
)

// 'Profiles' is core (row:141's commission: profile configuration from within the SPA is not
// autoharn-specific), unlike the 7 autoharn-gated tabs -- TAB_DEFS' own `core` field carries this
// now, filtered here instead of two separately-declared arrays.
const visibleTabs = computed(() => TAB_DEFS.filter((t) => t.core || autoharnEnabled.value))

// The single mounted tab component, replacing the old per-tab `v-if="activeTab === '...'"` chain
// (itself nested inside a `v-if="autoharnEnabled"` template for the 7 gated tabs). Derived from
// `visibleTabs`, NOT the full TAB_DEFS, so navigating straight to a gated tab's URL while
// autoharn is disabled renders nothing for it (same graceful-degrade as before: the tab bar
// shows only core tabs, and no component mounts for a route whose tab isn't currently visible).
// Exactly one tab component is ever mounted at a time (never all 9 with some hidden), matching
// every tab's own onMounted-fetch-on-mount contract (see e.g. LedgerTab.vue's own header
// comment: "no other tab does extra work because this one is open").
const activeTabDef = computed(() => visibleTabs.value.find((t) => t.id === activeTab.value))

onMounted(loadHealth)

// cycle5-tab-bar-accessibility (findings 5+6, docs/consults/2026-07-16-spa-audit-5): the tablist
// had role="tab"/aria-selected but no roving tabindex and no ArrowRight/ArrowLeft handling -- per
// the WAI-ARIA APG Tabs pattern, only the active tab sits in the normal tab order (tabindex 0),
// every other tab is -1, and arrow keys move BOTH focus and selection between them (wrapping at
// the ends). tabButtonRefs is keyed by index into `visibleTabs`, same array the template v-for
// walks, so the ref at `nextIndex` is always the button for `visibleTabs.value[nextIndex]`.
const tabButtonRefs = ref<(HTMLButtonElement | null)[]>([])
function setTabButtonRef(el: Element | { $el?: Element } | null, index: number) {
  tabButtonRefs.value[index] = (el as HTMLButtonElement | null) ?? null
}
function onTabKeydown(event: KeyboardEvent, index: number) {
  if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
  event.preventDefault()
  const tabs = visibleTabs.value
  if (tabs.length === 0) return
  const delta = event.key === 'ArrowRight' ? 1 : -1
  const nextIndex = (index + delta + tabs.length) % tabs.length
  selectTab(tabs[nextIndex].id)
  nextTick(() => tabButtonRefs.value[nextIndex]?.focus())
}
</script>

<template>
  <a href="#main-content" class="skip-link">Skip to content</a>

  <header class="top">
    <div class="title-block">
      <h1>Ledger panel</h1>
      <span
        v-if="healthState.health?.read_only"
        class="badge"
        :class="healthState.health?.read_only_reason === 'locked' ? 'badge-locked' : 'badge-OPEN'"
        :title="healthState.health?.read_only_reason === 'locked'
          ? 'An operator deliberately disabled writes at startup (PANEL_READONLY), independent of whether a write conduit is configured.'
          : undefined"
      >{{ healthState.health?.read_only_reason === 'locked' ? 'read-only (locked)' : 'read-only' }}</span>
    </div>
    <div class="health-strip">
      <span v-if="healthState.health">
        {{ healthState.health.schema }}@{{ healthState.health.kern_schema }}<template v-if="healthState.health.active_profile"> (profile: {{ healthState.health.active_profile }})</template>
      </span>
      <span v-if="healthState.error" class="error-banner">{{ healthState.error }}</span>
      <span>
        <span class="dot" :class="status"></span>
        <span
          :title="status === 'live'
            ? 'Ledger updates are streamed live over Server-Sent Events; no polling delay.'
            : status === 'polling'
            ? 'SSE is unavailable; falling back to polling the ledger every ~2 seconds.'
            : status === 'down'
            ? 'Live-update connection is down; ledger data may be stale until it reconnects.'
            : 'Establishing the live-update connection.'"
        >{{ status === 'live' ? 'live (SSE)' : status === 'polling' ? 'polling (~2s)' : status === 'down' ? 'disconnected' : 'connecting' }}</span>
      </span>
    </div>
  </header>

  <template v-if="isTabRoute">
    <nav class="tabs" role="tablist">
      <button
        v-for="(t, index) in visibleTabs"
        :key="t.id"
        :ref="(el) => setTabButtonRef(el as Element | null, index)"
        :id="`tab-${t.id}`"
        class="tab-btn"
        :class="{ active: activeTab === t.id }"
        role="tab"
        :aria-selected="activeTab === t.id"
        :aria-controls="`tabpanel-${t.id}`"
        :tabindex="activeTab === t.id ? 0 : -1"
        @click="selectTab(t.id)"
        @keydown="onTabKeydown($event, index)"
      >
        {{ t.label }}
      </button>
    </nav>
  </template>

  <main id="main-content" tabindex="-1">
    <template v-if="isTabRoute">
      <div
        v-if="activeTabDef"
        :id="`tabpanel-${activeTab}`"
        role="tabpanel"
        :aria-labelledby="`tab-${activeTab}`"
        tabindex="0"
      >
        <component :is="activeTabDef.component" :key="activeTab" />
      </div>
    </template>
    <RouterView v-else />
  </main>

  <footer class="foot">
    Ledger panel — Vue 3 port. Extension boundary: core (rows/kinds/refs/supersession) vs
    <code>extensions/autoharn</code> (obligation/commission/cosign semantics), per SPEC.md sec 4.
  </footer>
</template>
