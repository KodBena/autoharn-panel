// src/core/composables/useLiveUpdates.ts -- ONE SSE connection (with watermark-poll fallback), fanned
// out to every mounted view via a single rAF-coalesced "tick" ref (SPEC.md sec 3: "every view
// subscribes ... no view refetches more than its own visible data" -- each tab component
// watches `tick` itself and decides what, if anything, it needs to re-fetch; this module knows
// nothing about what changed, only that the ledger did).
//
// The rAF-coalescing follows the omega speed-reap sheet's "nice pattern" #1 verbatim: a burst
// of SSE messages (or watermark-poll detections) in one frame collapses to a single `tick` bump,
// so N ledger-change events arriving between two paints trigger each subscriber's refetch once,
// not N times. This is coalescing the REPAINT/refetch trigger, not the ingestion -- there is no
// data to ingest client-side here (the SPA never caches ledger content across a refetch, per
// SPEC.md sec 0 "stores nothing derivable"), so there is only one signal to coalesce.
import { ref } from 'vue'
import { api } from '../services/api-client'
import type { Watermark } from '../services/types'

export type LiveStatus = 'connecting' | 'live' | 'polling' | 'down'

const POLL_INTERVAL_MS = 2000

class LiveConnection {
  status = ref<LiveStatus>('connecting')
  // Bumped at most once per animation frame, no matter how many ledger-change signals arrived
  // since the last paint -- the one thing every view watches.
  tick = ref(0)

  private pollTimer: ReturnType<typeof setInterval> | null = null
  private lastWatermark: Watermark | null = null
  private rafPending = false
  private started = false

  start(): void {
    if (this.started) return
    this.started = true
    this.startSSE()
  }

  private bumpTick(): void {
    if (this.rafPending) return
    this.rafPending = true
    requestAnimationFrame(() => {
      this.rafPending = false
      this.tick.value += 1
    })
  }

  private startSSE(): void {
    let src: EventSource
    try {
      src = new EventSource('/api/events')
    } catch {
      this.status.value = 'polling'
      this.startPolling()
      return
    }
    src.addEventListener('open', () => {
      this.status.value = 'live'
    })
    src.addEventListener('message', (ev) => {
      this.status.value = 'live'
      try {
        const payload = JSON.parse(ev.data)
        if (payload && payload.type === 'ledger-change') {
          this.bumpTick()
        }
      } catch {
        // a malformed SSE payload is not fatal to the view -- ignore and keep the connection.
      }
    })
    src.addEventListener('error', () => {
      this.status.value = 'polling'
      src.close()
      this.startPolling()
    })
  }

  private startPolling(): void {
    if (this.pollTimer) return
    this.pollTimer = setInterval(async () => {
      try {
        const { data, error } = await api.GET('/api/watermark')
        if (error) throw error
        const wm = data as unknown as Watermark
        const prior = this.lastWatermark
        if (!prior || wm.max_id !== prior.max_id || wm.count !== prior.count) {
          this.lastWatermark = wm
          this.bumpTick()
        }
      } catch {
        this.status.value = 'down'
      }
    }, POLL_INTERVAL_MS)
  }
}

// Module-scope singleton (the omega-reap "plain reactive()/computed() store, no Pinia" shape,
// SPEC.md/omega parity) -- every component importing this gets the SAME connection.
const connection = new LiveConnection()

export function useLiveUpdates() {
  connection.start()
  return { status: connection.status, tick: connection.tick }
}
