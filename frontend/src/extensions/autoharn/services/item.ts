// src/extensions/autoharn/services/item.ts -- the ONE place `GET /api/item/{row_id}/obligations`
// is called from (ItemView.vue). A plain, hand-typed `fetch` rather than the generated `api`
// client for the same reason cosign.ts's sibling call is (see that file's header comment): this
// route is registered by the `autoharn` extension only, and `schema.d.ts` is regenerated build
// output that may or may not have been produced against a build with the extension enabled --
// coupling this call's buildability to that would be backwards. Request/response shapes are
// still fully typed via `ItemObligations` below.
import type { ItemObligations } from './types'

export async function fetchItemObligations(rowId: number): Promise<ItemObligations> {
  const resp = await fetch(`/api/item/${rowId}/obligations`)
  let body: unknown = null
  try {
    body = await resp.json()
  } catch {
    throw new Error(`/api/item/${rowId}/obligations: HTTP ${resp.status}, non-JSON response`)
  }
  if (!resp.ok) {
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? String((body as { detail?: unknown }).detail)
        : resp.statusText
    throw new Error(`/api/item/${rowId}/obligations: HTTP ${resp.status} — ${detail}`)
  }
  return body as ItemObligations
}
