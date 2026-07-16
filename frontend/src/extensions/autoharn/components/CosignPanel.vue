<!--
  src/extensions/autoharn/components/CosignPanel.vue -- the co-sign control (SPEC.md sec 2.2:
  "co-sign panel lives here"; this port keeps it inline on each co-signable target -- item fast
  path, witness, or ambiguous candidate row -- as the vanilla PoC did, since the full item-view
  route (2.2) is out of this port's scope).

  Verbatim-refusal rendering (SPEC.md sec 0 "a refusal is information"): whatever the backend
  returns for exit_code/stdout/stderr is shown as-is, un-elided, un-summarized -- this component
  does not decide a refusal was "probably fine" and hide it.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { healthState } from '../../../core/state/health'
import { submitCosign } from '../services/cosign'
import type { CosignInfo, CosignResponse } from '../services/types'

const props = defineProps<{
  rowId: number
  cosign: CosignInfo | null
  label: string
}>()

const emit = defineEmits<{ (e: 'cosigned'): void }>()

const open = ref(false)
const pending = ref(false)
const result = ref<CosignResponse | null>(null)
const errorText = ref<string | null>(null)

const verdicts = computed(() => healthState.health?.autoharn?.verdicts ?? ['self-review', 'attest'])
const independenceValues = computed(
  () => healthState.health?.autoharn?.independence_values ?? ['self-review'],
)
const stampArmed = computed(() => healthState.health?.autoharn?.stamp_secret_armed ?? false)

// In read-only/locked mode, POST /api/cosign is never mounted server-side (backend/app.py gates
// the write router on `not cfg.read_only`) -- there is no live kernel refusal to relay, just a
// route that doesn't exist. Gate the button here on healthState.health.read_only so a click never
// reaches that missing route and surfaces a raw HTTP 405; the note below is this app's own honest
// copy, not a fabricated stand-in for a kernel message (see row:459).
const readOnlyKnown = computed(() => healthState.health?.read_only === true)
const readOnlyReasonText = computed(() => {
  const reason = healthState.health?.read_only_reason
  if (reason === 'locked') return 'this deployment is locked read-only (PANEL_READONLY).'
  if (reason === 'no-write-conduit') return 'this deployment has no write conduit configured (LED_BIN unset).'
  return 'this deployment is read-only.'
})

const verdict = ref(verdicts.value[0] ?? '')
const independence = ref(independenceValues.value.includes('self-review') ? 'self-review' : (independenceValues.value[0] ?? ''))
const basis = ref('')

function openForm(): void {
  open.value = true
  result.value = null
  errorText.value = null
}

function cancel(): void {
  open.value = false
}

async function submit(): Promise<void> {
  pending.value = true
  result.value = null
  errorText.value = null
  try {
    result.value = await submitCosign({
      row_id: props.rowId,
      verdict: verdict.value,
      independence: independence.value,
      basis: basis.value || '(no basis text entered)',
    })
    if (result.value.ok) emit('cosigned')
  } catch (e) {
    errorText.value = e instanceof Error ? e.message : String(e)
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="cosign-inline" v-if="cosign && cosign.cosigned">
    <span class="badge badge-COSIGNED">co-signed</span>
    <span class="muted mono">by {{ cosign.by || '?' }} · review {{ cosign.review_id }} · {{ cosign.verdict }}</span>
  </div>
  <div class="cosign-inline" v-else-if="readOnlyKnown">
    <button disabled title="writes disabled in this deployment">{{ label }} (disabled)</button>
    <span class="muted cosign-readonly-note">read-only deployment -- writes disabled: {{ readOnlyReasonText }}</span>
  </div>
  <div class="cosign-inline" v-else>
    <button v-if="!open" @click="openForm">{{ label }}</button>
    <div v-else class="cosign-form">
      <label>verdict:</label>
      <select v-model="verdict">
        <option v-for="v in verdicts" :key="v" :value="v">{{ v }}</option>
      </select>
      <label>independence:</label>
      <select v-model="independence">
        <option v-for="v in independenceValues" :key="v" :value="v">{{ v }}</option>
      </select>
      <input v-model="basis" type="text" placeholder="basis statement (why you are co-signing)" />
      <button class="primary" :disabled="pending" @click="submit">submit</button>
      <button :disabled="pending" @click="cancel">cancel</button>
      <div class="cosign-note">
        technical/managerial/financial require a verified interception stamp; this deployment's
        stamp secret is {{ stampArmed ? 'armed' : 'NOT armed' }}. Your independence as maintainer
        is carried by the actor field (maintainer ≠ author), which is also what discharges the
        review obligation. A stamp-unprovable independence claim will be refused by the kernel —
        you will see the refusal verbatim below, not a paved-over success.
      </div>
      <!-- no-elision (SPEC.md sec 0): the FULL stdout/stderr text, never truncated -->
      <div v-if="result" class="cosign-result" :class="result.ok ? 'ok' : 'refused'">exit_code={{ result.exit_code }}
<template v-if="result.stdout">
stdout:
{{ result.stdout }}
</template><template v-if="result.stderr">
stderr:
{{ result.stderr }}
</template><template v-if="result.review_id">
review_id={{ result.review_id }}
</template></div>
      <div v-if="errorText" class="cosign-result refused">{{ errorText }}</div>
    </div>
  </div>
</template>
