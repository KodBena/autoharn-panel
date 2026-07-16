<!--
  src/extensions/autoharn/components/CommissionTab.vue -- commission decomposition, generalized
  to ANY commission row (SPEC.md sec 2.4: "the PoC's one view, demoted to citizen" -- a picker
  over `GET /api/commissions` plus the same per-item/witness/ambiguous rendering the vanilla PoC
  had, ported to Vue rather than re-designed).
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../../../core/services/api-client'
import { useLiveUpdates } from '../../../core/composables/useLiveUpdates'
import { fmtTs, truncate } from '../../../utils/format'
import CosignPanel from './CosignPanel.vue'
import CitationText from '../../../core/components/CitationText.vue'
import type { Commission, CommissionDetail, DecompositionItem } from '../services/types'

const commissions = ref<Commission[]>([])
const selectedRow = ref<number | null>(null)
const detail = ref<CommissionDetail | null>(null)
const error = ref<string | null>(null)
const { tick } = useLiveUpdates()

const pickerNote = computed(() =>
  commissions.value.length ? `${commissions.value.length} commission row(s)` : '',
)

async function loadCommissions(): Promise<void> {
  const { data, error: err } = await api.GET('/api/commissions')
  if (err) throw err
  commissions.value = (data ?? []) as unknown as Commission[]
  if (commissions.value.length === 0) return
  const stillPresent = commissions.value.some((c) => c.row_id === selectedRow.value)
  if (!stillPresent) {
    // Default to the most recent commission that actually has decomposed items -- landing on
    // the numerically-first commission (which may well be item-count 0) leaves a first-time
    // user staring at an empty screen with no cue that most commissions are simply sparse.
    // Falls back to the numerically-first commission (commissions[0]) only when NONE have
    // items yet, so the picker never has no selection.
    const withItems = commissions.value.filter((c) => c.item_count > 0)
    const preferred = withItems.length
      ? withItems.reduce((latest, c) => (c.ts > latest.ts ? c : latest))
      : commissions.value[0]
    selectedRow.value = preferred.row_id
  }
}

async function loadDetail(): Promise<void> {
  if (selectedRow.value === null) {
    detail.value = null
    return
  }
  const { data, error: err } = await api.GET('/api/commission/{commission_row}', {
    params: { path: { commission_row: selectedRow.value } },
  })
  if (err) throw err
  detail.value = data as unknown as CommissionDetail
}

async function loadAll(): Promise<void> {
  try {
    await loadCommissions()
    await loadDetail()
    error.value = null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

function isAmbiguous(item: DecompositionItem): boolean {
  return item.status === 'AMBIGUOUS'
}

onMounted(loadAll)
watch(selectedRow, loadDetail)
watch(tick, loadAll)
defineExpose({ reload: loadAll })
</script>

<template>
  <section class="panel">
    <h2>
      Commission decomposition
      <span class="refresh-row"><button @click="loadAll">Refresh</button></span>
    </h2>
    <div class="commission-picker">
      <label for="commission-select">commission:</label>
      <select id="commission-select" v-model.number="selectedRow">
        <option v-if="commissions.length === 0" disabled>(no commissions found)</option>
        <option v-for="c in commissions" :key="c.row_id" :value="c.row_id">
          #{{ c.row_id }} — {{ c.item_count }} item(s) — {{ truncate(c.statement, 70) }}
        </option>
      </select>
      <span class="muted" style="font-size: 0.78rem">{{ pickerNote }}</span>
    </div>

    <div v-if="error" class="error-banner">{{ error }}</div>

    <template v-if="detail">
      <template v-if="!detail.commission">
        <p class="empty-note">Commission row {{ detail.commission_row }} not found.</p>
      </template>
      <template v-else>
        <div class="item-meta">
          row {{ detail.commission.id }} · {{ detail.commission.actor_name || '(unknown actor)' }} ·
          {{ fmtTs(detail.commission.ts) }}
        </div>
        <!-- no-elision (SPEC.md sec 0): full commission statement, never clamped -->
        <div class="commission-text"><CitationText :text="detail.commission.statement" /></div>

        <div class="item-list">
          <p v-if="detail.items.length === 0" class="empty-note">
            No decomposition items authored for this commission yet.
          </p>

          <template v-for="item in detail.items" :key="item.item_id">
            <!-- ambiguous identity-collision item -->
            <div v-if="isAmbiguous(item)" class="item-row ambiguous">
              <div class="item-head">
                <span class="item-id">{{ item.item_id }}</span>
                <span class="badge badge-AMBIGUOUS">AMBIGUOUS</span>
                <span class="item-label">
                  identity collision — two or more non-superseding rows claim this item id
                </span>
              </div>
              <p class="muted">
                The panel does not pick a winner. Each candidate row below is independently
                co-signable; resolve the collision itself with a ledger --supersedes outside the
                panel.
              </p>
              <div class="witness-list">
                <div v-for="rid in item.ambiguous_row_ids ?? []" :key="rid" class="witness-row">
                  <div class="witness-facts">
                    <span class="tag">row:{{ rid }}</span>
                  </div>
                  <CosignPanel
                    :row-id="rid"
                    :cosign="{ cosigned: false, by: null, review_id: null, verdict: null }"
                    label="co-sign this candidate row"
                    @cosigned="loadAll"
                  />
                </div>
              </div>
            </div>

            <!-- ordinary resolved item -->
            <div v-else class="item-row">
              <div class="item-head">
                <span class="item-id">{{ item.item_id }}</span>
                <span class="badge" :class="`badge-${item.status}`">{{ item.status }}</span>
                <span class="item-label">{{ item.label || '' }}</span>
                <span class="item-meta">row {{ item.row_id }}</span>
              </div>
              <CosignPanel
                v-if="item.row_id !== null"
                :row-id="item.row_id"
                :cosign="item.cosign"
                label="co-sign this item (fast path)"
                @cosigned="loadAll"
              />
              <div v-if="item.witnesses.length" class="witness-list">
                <div v-for="(w, wi) in item.witnesses" :key="wi" class="witness-row">
                  <div class="witness-facts">
                    <span class="tag">{{ w.ref_kind }}:{{ w.ref }}</span>
                    <span>{{ w.resolved ? 'resolves' : 'does not resolve' }}</span>
                    <span>{{ w.substantive ? 'substantive' : 'not substantive' }}</span>
                  </div>
                  <CosignPanel
                    v-if="w.cosign_target_row !== null"
                    :row-id="w.cosign_target_row"
                    :cosign="w.cosign"
                    label="co-sign this witness"
                    @cosigned="loadAll"
                  />
                  <span v-else class="muted">
                    (no target row yet — witness not resolved to a co-signable row)
                  </span>
                </div>
              </div>
            </div>
          </template>
        </div>
      </template>
    </template>
  </section>
</template>
