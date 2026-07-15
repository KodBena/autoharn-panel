// src/extensions/autoharn/services/cosign.ts -- the ONE place `POST /api/cosign` is called
// from. Kept a thin wrapper (not a class/store) because there is no state to hold here: the
// caller (CosignPanel.vue) owns its own open/pending/result UI state and decides what to do
// with the response (SPEC.md sec 0: "a refusal is information" -- the caller renders
// `stdout`/`stderr`/`exit_code` verbatim, this module does not interpret or discard them).
//
// NOT routed through the generated `api` client's typed POST: `POST /api/cosign` is registered
// by `backend.extensions.autoharn.routes.build_write_router()` ONLY when the backend's `LED_BIN`
// is set (a read-only deployment never exposes it at all, per that module's own docstring) --
// so a `schema.d.ts` regenerated against a read-only backend (the only mode safe to point at a
// shared/live ledger for `npm run gen-api`, since write mode also runs a startup principal-
// registration side effect) never carries this path's type, and `openapi-fetch`'s `paths` type
// would make `api.POST('/api/cosign', ...)` a compile error until someone regenerates against a
// write-enabled backend. A plain, hand-typed `fetch` call avoids coupling this one endpoint's
// buildability to which mode the backend happened to be in at `gen-api` time -- the request/
// response shapes are still fully typed by `CosignRequest`/`CosignResponse` below.
import type { CosignRequest, CosignResponse } from './types'

export async function submitCosign(req: CosignRequest): Promise<CosignResponse> {
  const resp = await fetch('/api/cosign', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  let body: unknown = null
  try {
    body = await resp.json()
  } catch {
    throw new Error(`/api/cosign: HTTP ${resp.status}, non-JSON response`)
  }
  if (!resp.ok) {
    // The backend returns HTTPException(400) for a CosignValidationError with a plain `detail`
    // string (see backend/extensions/autoharn/routes.py) -- surface it as a thrown Error so the
    // caller's existing catch/display path handles it the same as a network failure. A kernel
    // REFUSAL (row_id resolved, `led cosign` ran, kernel said no) is NOT this path -- that comes
    // back as a normal 200 with ok:false, exit_code!=0, stderr populated, and is not an error here.
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? String((body as { detail?: unknown }).detail)
        : resp.statusText
    throw new Error(`/api/cosign: HTTP ${resp.status} — ${detail}`)
  }
  return body as CosignResponse
}
