<!--
  src/extensions/autoharn/components/ItemObligationsPanel.vue -- the AUTOHARN-SEMANTIC half of
  the item view (SPEC.md sec 2.2: "disposition/witness edges, review/co-sign history with actor
  + independence badges. Co-sign panel lives here"). Composed alongside the core-generic
  `core/components/ItemDetail.vue` by the app-layer `src/ItemView.vue` -- never imported FROM
  core (scripts/lint-boundaries.mjs RULE 2), though this file may freely import core (the
  boundary is one-directional).

  Data comes from `GET /api/item/{row_id}/obligations` (backend/extensions/autoharn/routes.py),
  a NEW route added alongside (not folded into) core's `GET /api/rows/{id}` -- core stays
  ignorant of obligations/cosign/review entirely.
-->
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import CosignPanel from './CosignPanel.vue'
import ResourceFieldsCard from './ResourceFieldsCard.vue'
import { fetchItemObligations } from '../services/item'
import type { DischargeGrade, ItemObligations } from '../services/types'
import { fmtTs } from '../../../utils/format'

const props = defineProps<{ rowId: number }>()

// Cycle-5 audit finding 2 (CRITICAL): `independence` (verdict + label above) is whatever the
// reviewing writer typed -- self-asserted, unverified. `discharge_grade` is the kernel's own
// trigger-computed read of the SAME review's stamp facts (never writer-supplied, never
// overridable -- backend extensions.autoharn.ledger_read.reviews_for_row's docstring). Label/
// tooltip/badge-class ladder mirrors CommissionTab.vue's commission-trust-badge convention
// (same shape of problem: a closed, weak-to-strong vocabulary that needs an at-a-glance visual
// distinction, not just more unstyled text) -- kept local to this component rather than shared,
// same precedent that file already set for its own trust ladder.
const GRADE_LABELS: Record<DischargeGrade, string> = {
  'same-principal': 'SAME PRINCIPAL',
  'same-session': 'SAME SESSION',
  'distinct-session': 'DISTINCT SESSION',
  'distinct-deployment': 'DISTINCT DEPLOYMENT',
}
const GRADE_TOOLTIPS: Record<DischargeGrade, string> = {
  'same-principal':
    'SAME PRINCIPAL -- the kernel found this review and the row it regards share the same (session, agent) pair, or one side has no stamp at all. The weakest grade: this is a self-attestation, whatever independence value it claims.',
  'same-session':
    'SAME SESSION -- a different agent wrote this review than wrote the row it regards, but within the SAME session. Second-weakest grade: not the identical actor, but not an arms-length review either.',
  'distinct-session':
    'DISTINCT SESSION -- a genuinely different session wrote this review than wrote the row it regards. A real independence signal.',
  'distinct-deployment':
    'DISTINCT DEPLOYMENT -- reviewed from an entirely separate deployment. The strongest grade the kernel can compute.',
}

function gradeLabel(grade: DischargeGrade | null): string {
  if (grade === null) return 'UNKNOWN'
  return GRADE_LABELS[grade] ?? grade.toUpperCase()
}
function gradeTooltip(grade: DischargeGrade | null): string {
  if (grade === null) return 'UNKNOWN -- this review row carries no kernel-computed discharge grade (a pre-s29-vintage row, never seen live in this deployment).'
  return GRADE_TOOLTIPS[grade] ?? grade
}
function gradeBadgeClass(grade: DischargeGrade | null): string {
  return `badge-discharge-${grade ?? 'unknown'}`
}

const data = ref<ItemObligations | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    data.value = await fetchItemObligations(props.rowId)
  } catch (e) {
    data.value = null
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
    <h2>Obligations & co-sign</h2>
    <div v-if="loading" class="muted">loading…</div>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <template v-if="data">
      <ResourceFieldsCard v-if="data.resource_fields" :fields="data.resource_fields" />

      <h3>Co-sign (this row)</h3>
      <CosignPanel :row-id="rowId" :cosign="data.cosign" label="co-sign this row" @cosigned="load" />

      <h3>Review / co-sign history</h3>
      <div v-if="data.reviews.length === 0" class="muted">no reviews regard this row.</div>
      <table v-else>
        <thead>
          <tr>
            <th>review id</th>
            <th>actor</th>
            <th>verdict</th>
            <th>independence (self-declared)</th>
            <th>discharge grade (kernel-computed)</th>
            <th>ts</th>
            <th>basis</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in data.reviews" :key="r.review_id">
            <td class="mono">{{ r.review_id }}</td>
            <td>{{ r.actor_name ?? '(none)' }}</td>
            <td><span class="badge" :class="r.verdict === 'attest' ? 'badge-COSIGNED' : 'badge-WITNESSED'">{{ r.verdict }}</span></td>
            <td>{{ r.independence }}</td>
            <td>
              <span
                class="badge"
                :class="gradeBadgeClass(r.discharge_grade)"
                :title="gradeTooltip(r.discharge_grade)"
              >{{ gradeLabel(r.discharge_grade) }}</span>
            </td>
            <td class="mono">{{ fmtTs(r.ts) }}</td>
            <td class="statement-text">{{ r.basis }}</td>
          </tr>
        </tbody>
      </table>

      <h3>Witness edges (this row's own refs)</h3>
      <div v-if="data.witnesses.length === 0" class="muted">no row:/work: witness tokens in this row's refs.</div>
      <ul v-else class="witness-list">
        <li v-for="w in data.witnesses" :key="`${w.ref_kind}:${w.ref}`">
          <span class="mono">{{ w.ref_kind }}:{{ w.ref }}</span>
          <span class="muted"> — {{ w.resolved ? 'resolved' : 'dangling' }}, {{ w.substantive ? 'substantive' : 'not yet substantive' }}</span>
          <span v-if="w.cosign?.cosigned" class="badge badge-COSIGNED">co-signed by {{ w.cosign.by }}</span>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.statement-text {
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.witness-list {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
</style>
