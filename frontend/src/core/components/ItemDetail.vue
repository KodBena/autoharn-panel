<!--
  src/core/components/ItemDetail.vue -- the CORE-GENERIC half of the item view (SPEC.md sec
  2.2): one row, everything core's own `GET /api/rows/{id}` already relates to it -- full
  statement (no-elision, SPEC.md sec 0), typed columns, refs in/out, supersede chain, the raw
  row behind a disclosure. Nothing autoharn-specific (obligation/cosign/review) lives here --
  that is `extensions/autoharn/components/ItemObligationsPanel.vue`'s job, composed alongside
  this component by the app-layer `src/ItemView.vue`, never imported from here (scripts/lint-
  boundaries.mjs RULE 2: core may not import extensions).
-->
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '../services/api-client'
import type { LedgerRow } from '../services/types'
import { fmtTs } from '../../utils/format'
import CitationText from './CitationText.vue'

const props = defineProps<{ rowId: number }>()

const row = ref<LedgerRow | null>(null)
const error = ref<string | null>(null)
// True once a 404 from GET /api/rows/{id} confirms "route resolved, id doesn't exist" -- kept
// distinct from `error` (a generic network/server failure) so the template can render the
// graceful in-app "no such row" message instead of the error banner for this one, expected case.
const notFound = ref(false)
const loading = ref(false)
const showRaw = ref(false)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  notFound.value = false
  try {
    const { data, error: err, response } = await api.GET('/api/rows/{row_id}', {
      params: { path: { row_id: props.rowId } },
    })
    if (err) {
      if (response.status === 404) {
        notFound.value = true
        row.value = null
        return
      }
      throw err
    }
    row.value = (data ?? null) as unknown as LedgerRow | null
  } catch (e) {
    row.value = null
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.rowId, load)

defineExpose({ reload: load })
</script>

<template>
  <section class="panel">
    <h2>Item — row {{ rowId }}</h2>
    <div v-if="loading" class="muted">loading…</div>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <template v-if="row">
      <dl class="item-fields">
        <dt>kind</dt>
        <dd>{{ row.kind }}</dd>
        <dt>actor</dt>
        <dd>{{ row.actor_name ?? '(none)' }}</dd>
        <dt>ts</dt>
        <dd class="mono">{{ fmtTs(row.ts) }}</dd>
        <dt>statement</dt>
        <!-- no-elision (SPEC.md sec 0): full text, wraps, never clipped -->
        <dd class="statement-text"><CitationText :text="row.statement" /></dd>
        <dt>refs (raw)</dt>
        <dd class="statement-text mono">{{ row.refs || '(none)' }}</dd>
        <dt>refs → rows</dt>
        <dd>
          <span v-if="!row.ref_row_ids || row.ref_row_ids.length === 0" class="muted">(none)</span>
          <span v-else class="mono">{{ row.ref_row_ids.join(', ') }}</span>
        </dd>
        <dt>supersede chain</dt>
        <dd>
          <span class="mono">
            predecessors: {{ row.predecessors && row.predecessors.length ? row.predecessors.join(', ') : '(none)' }}
            · successor: {{ row.successor ?? '(none)' }}
          </span>
        </dd>
      </dl>
      <button @click="showRaw = !showRaw">{{ showRaw ? 'hide' : 'show' }} raw row</button>
      <pre v-if="showRaw" class="raw-disclosure">{{ JSON.stringify(row, null, 2) }}</pre>
    </template>
    <div v-else-if="notFound" class="muted">no such row — item {{ rowId }} does not exist.</div>
    <div v-else-if="!loading && !error" class="muted">no such row.</div>
  </section>
</template>

<style scoped>
.item-fields {
  display: grid;
  grid-template-columns: 8rem 1fr;
  gap: 0.35rem 0.75rem;
}
.item-fields dt {
  font-weight: 600;
  color: var(--text-dim);
}
.item-fields dd {
  margin: 0;
}
.statement-text {
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.raw-disclosure {
  overflow-x: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  padding: 0.5rem;
  border-radius: 4px;
}
</style>
