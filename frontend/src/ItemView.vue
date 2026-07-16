<!--
  src/ItemView.vue -- the item view's (SPEC.md sec 2.2) app-layer composition root, routed to by
  `/item/:id` (src/router.ts). Deliberately NOT under src/core/: it composes a core-generic
  component (core/components/ItemDetail.vue) with an autoharn-extension component
  (extensions/autoharn/components/ItemObligationsPanel.vue), the same core+extension composition
  App.vue itself does for the tab UI (scripts/lint-boundaries.mjs RULE 2 forbids a file UNDER
  core/ from importing extensions/, not an app-layer file from importing both).

  `autoharnEnabled` mirrors App.vue's own computed exactly (same `healthState.health` source,
  populated once at boot by App.vue's `onMounted(loadHealth)` -- App.vue is the one
  always-mounted root component, per main.ts, so that fetch has already run/is running
  regardless of which route is active).
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { healthState } from './core/state/health'
import ItemDetail from './core/components/ItemDetail.vue'
import ItemObligationsPanel from './extensions/autoharn/components/ItemObligationsPanel.vue'

const route = useRoute()

const rowId = computed(() => {
  const raw = route.params.id
  const n = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isFinite(n) ? n : null
})

const autoharnEnabled = computed(
  () => healthState.health?.extensions_enabled?.includes('autoharn') ?? false,
)
</script>

<template>
  <div class="item-view">
    <p><router-link to="/">&larr; back to panel</router-link></p>
    <div v-if="rowId === null" class="error-banner">'{{ route.params.id }}' is not a valid row id.</div>
    <template v-else>
      <ItemDetail :row-id="rowId" />
      <ItemObligationsPanel v-if="autoharnEnabled" :row-id="rowId" />
    </template>
  </div>
</template>

<style scoped>
.item-view {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
</style>
