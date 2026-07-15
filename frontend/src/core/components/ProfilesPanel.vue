<!--
  src/core/components/ProfilesPanel.vue -- "Profiles" tab, CORE (not autoharn-extension: profile
  storage is a bare panel.toml concept, per SPEC.md sec 4's extension boundary), always visible
  regardless of `autoharn_enabled` (App.vue wires this tab unconditionally).

  Row:141's commission, verbatim: "You're supposed to be able to configure your profiles from
  within the SPA itself" -- this is that surface: list/add/delete against the real
  GET/POST/DELETE /api/profiles endpoints (row:142/row:143's backend), not a read-only display.

  Deliberately NOT a live-switch control: `PANEL_PROFILE` resolves exactly once, at backend
  startup (backend/config.py, no runtime re-validation path exists at all) -- an architectural
  fact, not a shortcut, per README.md's config section. This panel manages the catalog written to
  panel.toml's `[profiles.<name>]` tables; activating a different one for THIS running backend
  still requires an operator restart with `PANEL_PROFILE=<name>` set. The note below says so
  plainly rather than leaving a live-switch impression by omission.
-->
<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { healthState } from '../state/health'
import { deleteProfile, listProfiles, ProfilesApiError, upsertProfile } from '../services/profiles'
import type { Profile } from '../services/types'
import type { Column } from './DataTable.vue'
import DataTable from './DataTable.vue'

const profiles = ref<Profile[]>([])
const loadError = ref<string | null>(null)
const loading = ref(false)

// Set only once an actual POST/DELETE attempt comes back 404/405 -- distinct from
// `healthState.health?.read_only`, which is a proactive, same-information signal used to hide
// the form up front but is not treated as authoritative on its own (health may be stale or
// unloaded when this panel mounts): the two together make the "write route genuinely absent"
// message robust to either source alone being unavailable.
const writeRouteConfirmedAbsent = ref(false)

const readOnlyKnown = computed(() => healthState.health?.read_only === true)
const writeUnavailable = computed(() => readOnlyKnown.value || writeRouteConfirmedAbsent.value)
const readOnlyReasonText = computed(() => {
  const reason = healthState.health?.read_only_reason
  if (reason === 'locked') return 'this deployment is locked read-only (PANEL_READONLY).'
  if (reason === 'no-write-conduit') return 'this deployment has no write conduit configured (LED_BIN unset).'
  return 'this deployment is read-only.'
})

const columns: Column[] = [
  { key: 'name', label: 'name', width: '9rem' },
  { key: 'host', label: 'host', width: '9rem' },
  { key: 'db', label: 'db', width: '8rem' },
  { key: 'schema', label: 'schema', width: '8rem' },
  { key: 'kern', label: 'kern', width: '8rem' },
  { key: 'role', label: 'role', width: '7rem' },
]

// DataRow (the row renderer DataTable/`v-for`-mounts) only ever renders `cellText()` -- plain
// stringified values, no slot for interactive content -- so the per-row delete button lives in
// its own small list below the table instead of inside a DataTable cell; adding an interactive-
// cell slot would touch a shared component every other tab also uses, for a need only this
// panel has.
const displayRows = computed(() => profiles.value as unknown as Record<string, unknown>[])

async function load(): Promise<void> {
  loading.value = true
  try {
    profiles.value = await listProfiles()
    loadError.value = null
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}
load()

// -- add/edit form --
interface FormFields {
  name: string
  host: string
  db: string
  schema: string
  kern: string
  role: string
}

function blankForm(): FormFields {
  return { name: '', host: '', db: '', schema: '', kern: '', role: '' }
}

const formOpen = ref(false)
const form = reactive<FormFields>(blankForm())
const formErrors = ref<string[]>([])
const submitPending = ref(false)
const submitError = ref<string | null>(null)
const submitNotMounted = ref(false)

function openForm(): void {
  Object.assign(form, blankForm())
  formErrors.value = []
  submitError.value = null
  submitNotMounted.value = false
  formOpen.value = true
}

function cancelForm(): void {
  formOpen.value = false
}

function validate(): string[] {
  const errors: string[] = []
  if (!form.name.trim()) errors.push('name is required')
  if (!form.host.trim()) errors.push('host is required')
  if (!form.db.trim()) errors.push('db is required')
  if (!form.schema.trim()) errors.push('schema is required')
  if (!form.kern.trim()) errors.push('kern is required')
  // role is optional -- backend/core/routes.py's ProfileUpsertRequest.role defaults to None.
  return errors
}

async function submitForm(): Promise<void> {
  const errors = validate()
  formErrors.value = errors
  if (errors.length > 0) return

  submitPending.value = true
  submitError.value = null
  submitNotMounted.value = false
  try {
    profiles.value = await upsertProfile(form.name.trim(), {
      host: form.host.trim(),
      db: form.db.trim(),
      schema: form.schema.trim(),
      kern: form.kern.trim(),
      role: form.role.trim() || null,
    })
    formOpen.value = false
  } catch (e) {
    if (e instanceof ProfilesApiError && e.notMounted) {
      writeRouteConfirmedAbsent.value = true
      submitNotMounted.value = true
    }
    submitError.value = e instanceof Error ? e.message : String(e)
  } finally {
    submitPending.value = false
  }
}

// -- delete --
const deletePending = ref<string | null>(null)
const deleteError = ref<string | null>(null)
const deleteNotMounted = ref(false)

async function onDelete(name: string): Promise<void> {
  if (!window.confirm(`Delete profile ${JSON.stringify(name)}? This edits panel.toml and cannot be undone from here.`)) {
    return
  }
  deletePending.value = name
  deleteError.value = null
  deleteNotMounted.value = false
  try {
    profiles.value = await deleteProfile(name)
  } catch (e) {
    if (e instanceof ProfilesApiError && e.notMounted) {
      writeRouteConfirmedAbsent.value = true
      deleteNotMounted.value = true
    }
    deleteError.value = e instanceof Error ? e.message : String(e)
  } finally {
    deletePending.value = null
  }
}
</script>

<template>
  <section class="panel">
    <h2>
      Profiles
      <span class="refresh-row">
        <button @click="load" :disabled="loading">Refresh</button>
        <button v-if="!writeUnavailable" class="primary" @click="openForm" :disabled="formOpen">
          Add profile
        </button>
      </span>
    </h2>

    <p class="profiles-note">
      This catalog is <strong>panel.toml</strong>'s <code>[profiles.&lt;name&gt;]</code> table --
      adding, editing, or deleting a profile here changes what is available, but it does
      <strong>not</strong> change which profile this running backend is connected to. This app's
      config is resolved once, at startup (<code>PANEL_PROFILE</code>): to make a different
      profile the live connection, restart the backend process with
      <code>PANEL_PROFILE=&lt;name&gt;</code> set. There is no live-switch control here or
      anywhere else in this app, by design.
    </p>

    <div v-if="writeUnavailable" class="error-banner">
      Read-only: {{ readOnlyReasonText }} Adding, editing, and deleting profiles is disabled;
      the list below is still live.
    </div>

    <div v-if="loadError" class="error-banner">{{ loadError }}</div>

    <div v-if="formOpen" class="cosign-form profiles-form">
      <label>name: <input v-model="form.name" type="text" placeholder="profile name" /></label>
      <label>host: <input v-model="form.host" type="text" /></label>
      <label>db: <input v-model="form.db" type="text" /></label>
      <label>schema: <input v-model="form.schema" type="text" /></label>
      <label>kern: <input v-model="form.kern" type="text" /></label>
      <label>role (optional): <input v-model="form.role" type="text" /></label>
      <div class="profiles-form-actions">
        <button class="primary" :disabled="submitPending" @click="submitForm">Save</button>
        <button :disabled="submitPending" @click="cancelForm">Cancel</button>
      </div>
      <ul v-if="formErrors.length" class="cosign-result refused profiles-errors">
        <li v-for="e in formErrors" :key="e">{{ e }}</li>
      </ul>
      <div v-if="submitError && !submitNotMounted" class="cosign-result refused">{{ submitError }}</div>
      <div v-if="submitNotMounted" class="cosign-result refused">
        Write route not available -- {{ readOnlyReasonText }} {{ submitError }}
      </div>
    </div>

    <div v-if="deleteError" class="error-banner">
      {{ deleteNotMounted ? `Write route not available -- ${readOnlyReasonText} ` : '' }}{{ deleteError }}
    </div>

    <DataTable
      :columns="columns"
      :rows="displayRows"
      :row-key="(r) => r.name as string"
      empty-text="No profiles configured."
    >
    </DataTable>
    <ul v-if="!writeUnavailable && profiles.length" class="profiles-delete-list">
      <li v-for="p in profiles" :key="p.name">
        <button :disabled="deletePending === p.name" @click="onDelete(p.name)">
          {{ deletePending === p.name ? 'Deleting…' : `Delete ${p.name}` }}
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.profiles-note {
  font-size: 0.82rem;
  color: var(--text-dim);
  margin: 0 0 0.75rem;
  padding: 0.6rem 0.75rem;
  background: var(--open-bg);
  border-radius: 6px;
  border: 1px solid var(--border);
}
.profiles-form {
  flex-direction: column;
  align-items: stretch;
}
.profiles-form label {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  font-size: 0.78rem;
  color: var(--text-dim);
}
.profiles-form-actions {
  display: flex;
  gap: 0.4rem;
}
.profiles-errors {
  margin: 0;
  padding-left: 1.1rem;
}
.profiles-delete-list {
  list-style: none;
  margin: 0.6rem 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
</style>
