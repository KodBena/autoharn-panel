<!--
  src/App.vue -- composition root. Per the omega speed-reap sheet's Don't-do #4, this component
  must NOT read any high-frequency reactive value in its own render -- the only reactive reads
  here are `activeTab` (a user-driven, low-frequency ref) and `healthState.health` (loaded once
  at boot, not a streaming value). The live-updates `tick` ref is read only by each tab
  component itself (leaf-owns-its-read), never here.
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { healthState, loadHealth } from './core/state/health'
import { useLiveUpdates } from './core/composables/useLiveUpdates'
import LedgerTab from './core/components/LedgerTab.vue'
import ProfilesPanel from './core/components/ProfilesPanel.vue'
import WorkItemsTab from './extensions/autoharn/components/WorkItemsTab.vue'
import ReviewGapTab from './extensions/autoharn/components/ReviewGapTab.vue'
import QuestionsTab from './extensions/autoharn/components/QuestionsTab.vue'
import CommissionTab from './extensions/autoharn/components/CommissionTab.vue'

const { status } = useLiveUpdates()

// App.vue is the ONE always-mounted root component (main.ts's `createApp(App)`); rather than a
// separate root wrapper, this reads its own route (router.ts) to decide tab-UI vs the deep-
// linkable item view (SPEC.md sec 2.2) -- the six tabs below are otherwise byte-for-byte what
// they were before routing existed, gated by `isItemRoute` rather than replaced.
const route = useRoute()
const isItemRoute = computed(() => route.path.startsWith('/item/'))

type TabId = 'ledger' | 'profiles' | 'work' | 'review-gap' | 'questions' | 'commission'
const activeTab = ref<TabId>('ledger')

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
        <span>{{ status === 'live' ? 'live (SSE)' : status === 'polling' ? 'polling (~2s)' : status === 'down' ? 'disconnected' : 'connecting' }}</span>
      </span>
    </div>
  </header>

  <template v-if="!isItemRoute">
    <nav class="tabs">
      <button
        v-for="t in visibleTabs"
        :key="t.id"
        class="tab-btn"
        :class="{ active: activeTab === t.id }"
        @click="activeTab = t.id"
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
    </template>
  </template>
  <RouterView v-else />

  <footer class="foot">
    Ledger panel — Vue 3 port. Extension boundary: core (rows/kinds/refs/supersession) vs
    <code>extensions/autoharn</code> (obligation/commission/cosign semantics), per SPEC.md sec 4.
  </footer>
</template>
