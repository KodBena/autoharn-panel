# Ledger panel — a standalone SPA for a Postgres-backed append-only decision ledger

This repo is the standalone home for the ledger-panel SPA (see `SPEC.md` for the full design
input this build works from). It is a small, self-contained web page plus a local API server:
it reads an append-only decision ledger and renders it as something you can scan and act on. The
core is generic — it knows rows, kinds, refs, and supersession, nothing project-specific. An
`autoharn` extension (enabled by default) adds the autoharn-semantic layer: commission
decomposition items, obligation/witness derivation, and the one write path this panel has
(co-signing, via the deployment's own `led`-grammar binary) — see SPEC.md sec 4 for the
extension boundary this repo is built around.

This repo was carried over from a proof-of-concept that lived inside the `autoharn` checkout at
`panel/`; that PoC's frozen refs grammar, derived statuses, and co-sign-via-conduit design are
this build's foundation (`extensions/autoharn/` is a close port of that PoC's backend).

## 1. Configuration (SPEC.md sec 1)

Everything the backend needs is resolved once at startup by `backend/config.py`, environment-
first, `panel.toml`-fallback, fail-loud (an unresolvable config prints the exact missing key and
exits nonzero — never a silent default to any host):

| Setting | Env var | Notes |
|---|---|---|
| Full connection URI | `LEDGER_PG_URI` | wins outright over discrete fields |
| Discrete connection | `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD` | standard libpq names |
| Ledger schema | `LEDGER_SCHEMA` | required (from one of the three sources below) |
| Kernel/principal schema | `LEDGER_KERNEL_SCHEMA` | required |
| Subject role | `LEDGER_ROLE` | optional — omit for a bare/self-owned schema (no `SET ROLE`) |
| Write conduit | `LED_BIN` | absent ⇒ **read-only mode**, surfaced in `/api/health` and the UI header |
| Bind host/port | `PANEL_BIND` / `PANEL_PORT` | default `127.0.0.1:8420` — loopback by default, `0.0.0.0` is a choice, not a default |
| SSE poll cadence | `PANEL_POLL_INTERVAL` | default 2s |
| Extensions | `PANEL_EXTENSIONS` | comma-separated; default `autoharn` |

A fourth, autoharn-specific source: if neither `LEDGER_PG_URI` nor any discrete `PG*` field is
set at all, `config.py` looks for an autoharn `deployment.json` (`LEDGER_DEPLOYMENT` env, else
`<repo_root>/deployment.json`, else `<repo_root>/../deployment.json` — the latter finds an
autoharn checkout's own record when this repo is nested under it, e.g. at `tools/panel/`) and
reads its `db`/`host`/`schema`/`kern`/`role` as one unit. This repo does **not** import any code
from an autoharn checkout to do this — it re-parses that JSON shape itself, so a bare checkout of
this repo (no autoharn beside it) still has two fully working config sources (URI, discrete).

**What you need installed once, before the first run** (or use the repo's own `.venv` — see
below):

```
python3 -m pip install --user -r backend/requirements.txt
```

## 2. Start the backend

From the repository root:

```
cd backend
LEDGER_PG_URI="host=<host> dbname=<db>" LEDGER_SCHEMA=<schema> LEDGER_KERNEL_SCHEMA=<kern> \
  LED_BIN=/path/to/your/led \
  python3 -m uvicorn app:app --host 127.0.0.1 --port 8420
```

(Omit `LED_BIN` for read-only mode; omit `LEDGER_ROLE` for a schema with no distinct subject
role — see §1's table.) What you should see:

```
INFO:     Started server process [NNNNN]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8420 (Press CTRL+C to quit)
```

If the `autoharn` extension is enabled (default) and `LED_BIN` is set, startup also registers
the configured maintainer principal (`PANEL_MAINTAINER_PRINCIPAL`, default `maintainer`)
idempotently, the same `ON CONFLICT DO NOTHING` a hand-run `register-principal` would do. You
will not see this fail unless the conduit itself is broken; if it does, the server refuses to
finish starting and names the exit code and the conduit's own stderr.

A quick sanity check, in a second terminal, while the server above keeps running:

```
curl -s http://127.0.0.1:8420/api/health
```

WITNESSED (live, against a real autoharn deployment, extension enabled, `LED_BIN` set):

```json
{"ok":true,"config_source":"connection=autoharn-deployment.json, schema=autoharn1/autoharn1_kernel, led_bin=/path/to/led",
 "schema":"autoharn1","kern_schema":"autoharn1_kernel","read_only":false,
 "extensions_enabled":["autoharn"],
 "autoharn":{"stamp_secret_armed":false,
   "verdicts":["attest","attest_with_reservations","refuse"],
   "independence_values":["self-review","technical","managerial","financial"]},
 "maintainer_principal":"maintainer"}
```

`stamp_secret_armed: false` means this deployment has not armed the interception-stamp
mechanism, so only `self-review` co-signs will succeed — an honest statement about what this
deployment can currently prove, not an error.

## 3. Open the SPA

With the backend running, open **`http://127.0.0.1:8420/`** — `backend/app.py` mounts
`frontend/` as static files at `/`, registered *after* every `/api/*` route so those routes keep
precedence (`GET /api/nonexistent` still 404s as JSON; it never falls through to `index.html`).
Do not open `frontend/index.html` directly via a `file://` URL — a root-relative `fetch()` call
resolves against the document's own origin, and a `file://` document has no origin the backend
can answer; this is why the fix is a same-origin static mount, not a frontend change, and it
will not change.

## 4. Pick a commission and read it item by item (autoharn extension)

The landing view lists every commission on the ledger (`GET /api/commissions` — any
`kind='commission'` row, not a single hardcoded one: the panel is not a single-commission
product). What you get is the commission's own verbatim text followed by one row per
decomposition item: a short label an agent wrote, a status, and the witnesses that back the
label up.

**The five states, and what each asks you to do:**

- **`OPEN`** — the item exists but has no witness that resolves at all, or every witness is not
  yet substantive. Nothing to co-sign yet.
- **`WITNESSED`** — at least one witness resolves and is substantive, but nobody has co-signed
  anything yet. Read the witness(es); if satisfied, co-sign (§5).
- **`PARTIAL`** — you've co-signed some but not all witnesses. Co-sign the rest if satisfied.
- **`COSIGNED`** — either the item row itself is co-signed (the fast path), or every witness is.
  Discharged.
- **`AMBIGUOUS`** (a hazard banner, not a normal state) — two or more independent, non-
  superseding ledger rows claim the same decomposition item identity. The panel refuses to
  guess which is right: read both (or all) colliding rows and supersede the wrong one. Either
  candidate is still individually co-signable in the meantime.

## 5. Co-sign an item or a witness

Click co-sign on either the item row itself, or on any individual witness that has its own
`cosign_target_row`. You pick a **verdict** (`attest`, `attest_with_reservations`, `refuse`) and
an **independence** value (`self-review`, `technical`, `managerial`, `financial`) — both lists
are read live from `GET /api/health`'s `autoharn.verdicts`/`autoharn.independence_values`, never
hand-typed into the page, so they can never drift from what the conduit actually accepts. You
write a short basis statement.

Behind the click, the panel runs exactly `LED_ACTOR=<maintainer principal> <LED_BIN> review
<row_id> <verdict> <independence> <basis>` — the same command you would type by hand. Whatever
comes back is shown to you verbatim (stdout, stderr, exit code) — never paraphrased, never
silently retried, never turned into a fake success. This path only exists when `LED_BIN` is
configured; a read-only deployment gets every read route but no write route at all (a `POST
/api/cosign` on a read-only deployment gets a plain HTTP failure, never a route that would
silently 500).

## 6. The independence note, read honestly

`self-review` is the only independence value that will succeed against a deployment whose
`stamp_secret` mechanism is unarmed (`GET /api/health`'s `autoharn.stamp_secret_armed` tells you
this up front). That is not a defect in the panel — it is an honest statement about what the
deployment can currently prove. What still makes a self-review co-sign meaningful is that the
co-signing principal is a different, registered ledger principal from the agent whose row is
being signed — the segregation-of-duties check the conduit enforces on every review.

## 7. Keeping the view live

There is no database trigger pushing a ledger change to this page the instant it happens —
instead, the backend polls the ledger's watermark on a short interval (`PANEL_POLL_INTERVAL`,
default 2 seconds) and pushes a "something changed" event over Server-Sent Events
(`GET /api/events`) to every open tab the moment the watermark moves. If your browser tab's SSE
connection drops, the page falls back to polling `/api/watermark` itself. A manual reload always
shows the true, current ledger state — the polling is a convenience, never the source of truth.

## 8. The extension boundary (SPEC.md sec 4)

`backend/core/` knows only generic ledger concepts: rows, kinds, refs (`row:<id>` tokens),
supersession. It never queries a view or table that any extension owns. `backend/extensions/
autoharn/` adds everything autoharn-semantic: the `panel-item:` decomposition grammar,
obligation/witness derivation, the co-sign write path, and the kernel's own closed verdict/
independence vocabularies — loaded only when `"autoharn"` appears in `PANEL_EXTENSIONS`
(default: it does). `tests/test_core_boundary.py` is the proof: it stands up a schema with
*only* a `ledger` table and a `principal` table (no kernel views, no `commission`/`work_item`
kind, no `stamp_secret`), runs the API with the extension disabled, and exercises the core
routes end to end against it.

## 9. Repository layout

```
backend/
  config.py            -- the one config-resolution home (SPEC.md sec 1)
  db.py                 -- the one connection home (schema-generic: SET ROLE only if configured)
  app.py                -- FastAPI app factory; mounts core, conditionally mounts extensions
  core/                  -- ledger-generic reads + routes
  extensions/autoharn/   -- autoharn-semantic reads, cosign write path, routes
frontend/               -- the SPA (ported PoC frontend; a Vue rebuild is a later phase)
seed/                   -- one-time, idempotent ledger-authoring seed scripts (not runtime code)
tests/                  -- pytest suite: pure disposition tests, live cosign fixture, core-boundary witness
SPEC.md                 -- the ratified-for-this-build design input (moved here from autoharn's design/)
```

## 10. Filed residuals (carried over from the PoC, still open)

- `panel-cosign-independence-grade` — the independence vocabulary cannot yet express "a genuine
  executive endorsement whose independence is not stamp-provable" as anything other than
  `self-review`-labeled-honestly.
- `panel-item-span-anchor` — a future live character-span locator from an item's label into the
  commission's own text is not built.
- A Vue rebuild of `frontend/` (SPEC.md sec 4's Vue 3 + Vite architecture constraint, and the
  rest of SPEC.md's P0/P1 view list) has not happened yet — the frontend shipped here is the
  ported PoC page, kept working, not yet restyled or rebuilt.
