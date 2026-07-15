// src/core/services/api-client.ts -- the ONE typed HTTP client this app uses to talk to the
// backend (the "one alias file" the architecture-lint boundary allows alongside `services/`
// directories for wire-level access -- see scripts/lint-boundaries.mjs).
//
// `schema.d.ts` is GENERATED, build output (SPEC.md sec 4: "generated client is build output,
// never hand-edited, regenerated ... against the backend's live openapi.json"). Regenerate it
// with `npm run gen-api` (see package.json; points at http://127.0.0.1:8420/openapi.json by
// default -- override with PANEL_DEV_PROXY_TARGET's host, or run
// `npx openapi-typescript <url> -o src/core/services/schema.d.ts` directly for an ad-hoc target).
//
// Every route in this backend (see backend/core/routes.py, backend/extensions/autoharn/
// routes.py) returns `dict[str, Any]` / `list[dict[str, Any]]` rather than a Pydantic response
// model, so the GENERATED types for response bodies are themselves close to `unknown` -- that
// is a backend typing gap, not something this file can paper over honestly. `types.ts` (this
// directory) and `extensions/autoharn/services/types.ts` hand-declare the actual JSON shapes
// (as documented by the vanilla PoC's own "frozen wire shapes" comment and this repo's route
// source) so the rest of the app still gets real autocomplete/type-checking; explicitly marked
// as a hand-authored augmentation, not a duplicate source of truth for anything the backend
// enforces.
import createClient from 'openapi-fetch'
import type { paths } from './schema'

export const api = createClient<paths>({ baseUrl: '' })
