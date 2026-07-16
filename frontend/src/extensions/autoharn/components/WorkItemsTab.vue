<!--
  src/extensions/autoharn/components/WorkItemsTab.vue -- autoharn-semantic (`work_item_current`,
  claimant/state/resolution vocabulary owned by the kernel, SPEC.md sec 4 extension boundary).
  Backed by `GET /api/work` (extensions.autoharn.routes) -- no superseded concept exposed by
  this view (work items are a derived "current" projection, not raw ledger rows), so no toggle
  here; virtualization + no-elision still apply via the shared DataTable.
-->
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '../../../core/services/api-client'
import type { Column } from '../../../core/components/DataTable.vue'
import DataTable from '../../../core/components/DataTable.vue'
import { useLiveUpdates } from '../../../core/composables/useLiveUpdates'

const rows = ref<Record<string, unknown>[]>([])
const error = ref<string | null>(null)
const { tick } = useLiveUpdates()

const columns: Column[] = [
  { key: 'slug', label: 'slug', mono: true, width: '14rem' },
  { key: 'state', label: 'state', width: '6rem' },
  { key: 'claimant_name', label: 'claimant', width: '8rem' },
  { key: 'resolution', label: 'resolution', width: '10rem', richText: true },
  { key: 'title', label: 'title', width: '3fr', richText: true },
]

async function load(): Promise<void> {
  try {
    const { data, error: err } = await api.GET('/api/work')
    if (err) throw err
    rows.value = (data ?? []) as Record<string, unknown>[]
    error.value = null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(load)
watch(tick, load)
defineExpose({ reload: load })
</script>

<template>
  <section class="panel">
    <h2>
      Work items
      <span class="refresh-row"><button @click="load">Refresh</button></span>
    </h2>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <DataTable :columns="columns" :rows="rows" :row-key="(r) => r.slug as string" empty-text="No work items." />
  </section>
</template>
