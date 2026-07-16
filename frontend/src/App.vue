<!--
  src/App.vue -- composition root. Per the omega speed-reap sheet's Don't-do #4, this component
  must NOT read any high-frequency reactive value in its own render -- the only reactive reads
  here are `activeTab` (derived from the low-frequency route path, row:557) and
  `healthState.health` (loaded once at boot, not a streaming value). The live-updates `tick` ref
  is read only by each tab
  component itself (leaf-owns-its-read), never here.
-->
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { healthState, loadHealth } from './core/state/health'
import { useLiveUpdates } from './core/composables/useLiveUpdates'
import LedgerTab from './core/components/LedgerTab.vue'
import ProfilesPanel from './core/components/ProfilesPanel.vue'
import WorkItemsTab from './extensions/autoharn/components/WorkItemsTab.vue'
import ReviewGapTab from './extensions/autoharn/components/ReviewGapTab.vue'
import QuestionsTab from './extensions/autoharn/components/QuestionsTab.vue'
import WorkViolationsTab from './extensions/autoharn/components/WorkViolationsTab.vue'
import CommissionTab from './extensions/autoharn/components/CommissionTab.vue'
import { TAB_PATHS } from './router'

const { status } = useLiveUpdates()

// App.vue is the ONE always-mounted root component (main.ts's `createApp(App)`); rather than a
// separate root wrapper, this reads its own route (router.ts) to decide tab-UI vs the deep-
// linkable item view (SPEC.md sec 2.2) -- the six tabs below are otherwise byte-for-byte what
// they were before routing existed, gated by `isItemRoute` rather than replaced.
const route = useRoute()
const router = useRouter()
// cycle3-unknown-path-404: was `isItemRoute = path.startsWith('/item/')`, which meant any path
// NOT starting with '/item/' fell through to the tab UI -- including a bogus, unrecognized path,
// silently rendering the default 'ledger' tab (pathToTab.get(...) ?? 'ledger' below) with no cue
// the URL was wrong. Inverted to a positive check: only a recognized tab path renders the tab
// UI; everything else (both '/item/:id' and the new catch-all not-found route) goes through
// RouterView, which resolves each to its own distinct view.
const isTabRoute = computed(() => (Object.values(TAB_PATHS) as string[]).includes(route.path))

type TabId = 'ledger' | 'profiles' | 'work' | 'review-gap' | 'questions' | 'work-violations' | 'commission'

// row:557/cycle3-tab-url-routing: activeTab is now DERIVED from the URL (not its own ref) so
// that switching tabs, reloading, bookmarking, or navigating directly to a tab's URL all agree
// on which tab is showing -- the URL is the single source of truth, per the consult's finding 3.
const pathToTab = new Map<string, TabId>(
  (Object.entries(TAB_PATHS) as [TabId, string][]).map(([id, path]) => [path, id]),
)
const activeTab = computed<TabId>(() => pathToTab.get(route.path) ?? 'ledger')

function selectTab(id: TabId) {
  if (activeTab.value === id) return
  router.push(TAB_PATHS[id])
}

const autoharnEnabled = computed(
  () => healthState.health?.extensions_enabled?.includes('autoharn') ?? false,
)

// 'Profiles' is core (row:141's commission: profile configuration from within the SPA is not
// autoharn-specific), so it is always in coreTabs, unlike the four autoharn-gated tabs below.
const coreTabs: { id: TabId; label: string }[] = [
  { id: 'ledger', label: 'Recent ledger' },
  { id: 'profiles', label: 'Profiles' },
]
const autoharnTabs: { id: TabId; label: string }[] = [
  { id: 'commission', label: 'Commission decomposition' },
  { id: 'work', label: 'Work items' },
  { id: 'review-gap', label: 'Review gap' },
  { id: 'questions', label: 'Questions' },
  { id: 'work-violations', label: 'Violations' },
]

const visibleTabs = computed(() =>
  autoharnEnabled.value ? [...coreTabs, ...autoharnTabs] : coreTabs,
)

onMounted(loadHealth)
</script>

<template>
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
        v-for="t in visibleTabs"
        :key="t.id"
        class="tab-btn"
        :class="{ active: activeTab === t.id }"
        role="tab"
        :aria-selected="activeTab === t.id"
        @click="selectTab(t.id)"
      >
        {{ t.label }}
      </button>
    </nav>

    <LedgerTab v-if="activeTab === 'ledger'" />
    <ProfilesPanel v-if="activeTab === 'profiles'" />
    <template v-if="autoharnEnabled">
      <CommissionTab v-if="activeTab === 'commission'" />
      <WorkItemsTab v-if="activeTab === 'work'" />
      <ReviewGapTab v-if="activeTab === 'review-gap'" />
      <QuestionsTab v-if="activeTab === 'questions'" />
      <WorkViolationsTab v-if="activeTab === 'work-violations'" />
    </template>
  </template>
  <RouterView v-else />

  <footer class="foot">
    Ledger panel — Vue 3 port. Extension boundary: core (rows/kinds/refs/supersession) vs
    <code>extensions/autoharn</code> (obligation/commission/cosign semantics), per SPEC.md sec 4.
  </footer>
</template>
