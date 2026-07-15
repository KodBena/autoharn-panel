// src/core/services/profiles.ts -- the ONE place `GET`/`POST`/`DELETE /api/profiles` are
// called from (backend/core/routes.py + backend/core/profiles_write.py, row:142/row:143).
//
// NOT routed through the generated `api` client's typed GET/POST/DELETE, same reasoning as
// `extensions/autoharn/services/cosign.ts`'s header comment: `POST`/`DELETE /api/profiles` are
// mounted ONLY when the backend is writable (`not cfg.read_only`, backend/app.py), so a
// `schema.d.ts` regenerated against a read-only backend (the safe default for `npm run gen-api`
// against a shared/live ledger) never carries those two paths' types -- and in fact `schema.d.ts`
// as checked in does not carry ANY `/api/profiles` path yet (never regenerated since row:142
// landed). Plain, hand-typed `fetch` calls avoid coupling this endpoint's buildability to
// whichever mode the backend happened to be in at `gen-api` time; request/response shapes are
// still fully typed via `Profile` (./types).
import type { Profile } from './types'

export interface ProfileUpsertFields {
  host: string
  db: string
  schema: string
  kern: string
  role?: string | null
}

// Thrown for a non-2xx response. `notMounted` distinguishes the "write routes absent because
// this deployment is read-only-locked" case (backend/app.py mounts POST/DELETE only when
// `not cfg.read_only` -- a locked deployment 404s the route entirely; FastAPI itself would 405
// if the path existed under a different method) from an ordinary validation/not-found error, so
// callers can render a specific, non-alarming message instead of a generic failure.
export class ProfilesApiError extends Error {
  readonly status: number
  readonly notMounted: boolean

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.notMounted = status === 404 || status === 405
  }
}

async function parseErrorDetail(resp: Response): Promise<string> {
  try {
    const body: unknown = await resp.json()
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      return String((body as { detail?: unknown }).detail)
    }
  } catch {
    // non-JSON body -- fall through to statusText below
  }
  return resp.statusText || `HTTP ${resp.status}`
}

async function asProfiles(resp: Response, path: string): Promise<Profile[]> {
  if (!resp.ok) {
    // A 404 hitting `DELETE /api/profiles/{name}` can ALSO mean "route mounted, but no profile by
    // that name" (backend/core/routes.py's `api_profiles_delete` raises HTTPException(404) for a
    // missing-name KeyError, same status as "route not mounted at all"). Route-shaped 404s (this
    // whole module only ever calls the fixed `/api/profiles` collection or `/api/profiles/<name>`
    // path) are ambiguous between the two causes at the HTTP layer alone; ProfilesPanel.vue
    // disambiguates by first checking the always-mounted GET's own success/failure, so a caller
    // only reaches this branch already knowing whether the backend is read-only-locked.
    const detail = await parseErrorDetail(resp)
    throw new ProfilesApiError(resp.status, `${path}: HTTP ${resp.status} — ${detail}`)
  }
  return (await resp.json()) as Profile[]
}

export async function listProfiles(): Promise<Profile[]> {
  const resp = await fetch('/api/profiles')
  return asProfiles(resp, '/api/profiles')
}

export async function upsertProfile(name: string, fields: ProfileUpsertFields): Promise<Profile[]> {
  const resp = await fetch('/api/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, ...fields }),
  })
  return asProfiles(resp, '/api/profiles')
}

export async function deleteProfile(name: string): Promise<Profile[]> {
  const resp = await fetch(`/api/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' })
  return asProfiles(resp, `/api/profiles/${name}`)
}
