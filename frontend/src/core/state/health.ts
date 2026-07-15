// src/core/state/health.ts -- module-scope `reactive()` store (no Pinia/Vuex, per the omega
// speed reap sheet's "nice pattern" #8 and SPEC.md/omega-parity choice of state management). One
// fetch at boot; `App.vue` and the co-sign panel (verdict/independence vocab, read-only banner)
// are its only readers.
import { reactive } from 'vue'
import { api } from '../services/api-client'
import type { Health } from '../services/types'

interface HealthState {
  health: Health | null
  error: string | null
  loaded: boolean
}

export const healthState: HealthState = reactive({ health: null, error: null, loaded: false })

export async function loadHealth(): Promise<void> {
  try {
    const { data, error } = await api.GET('/api/health')
    if (error) throw error
    healthState.health = data as unknown as Health
    healthState.error = null
  } catch (e) {
    healthState.error = e instanceof Error ? e.message : String(e)
  } finally {
    healthState.loaded = true
  }
}
