<!--
  src/NotFoundView.vue -- in-app "page not found" view for any path that matches none of
  router.ts's routes (the catch-all `/:pathMatch(.*)*`). Mirrors the existing, already-good
  "no such row" empty state in core/components/ItemDetail.vue (same panel/h2/muted shape, same
  understated tone) rather than a raw error dump, per cycle-3 consult finding 4 (SERIOUS): an
  unrecognized path used to fall through silently to the default ledger tab with a 200 and no
  visual cue the URL was bogus.
-->
<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <section class="panel">
    <h2>Page not found</h2>
    <p class="muted">'{{ route.fullPath }}' does not match any route in this app.</p>
    <p><router-link to="/ledger">&larr; back to the ledger</router-link></p>
  </section>
</template>
