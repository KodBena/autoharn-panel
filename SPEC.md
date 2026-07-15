# Ledger-panel SPA — feature specification (Fable-authored)

Date: 2026-07-15. Author: the orchestrating Fable session, at the maintainer's explicit
request (ledger commission of the same date: "the feature set should be professional and
complete... I'll probably choose to implement just a subset"). Status: DESIGN INPUT for the
standalone SPA repo — not ratified law, not a build order. The maintainer subsets at will;
tiers below exist so subsetting cuts along seams instead of through them.

This document moves to the SPA's own repository at its birth and lives there; autoharn's
copy becomes a pointer. The PoC it succeeds is `panel/` (frozen refs grammar, derived
statuses, `./led`-conduit co-sign) — everything below assumes those foundations and the
three PoC verdicts the maintainer has already returned: load-bearing text must never be
elided; a single-commission decomposition is one view among many, not the application; the
SPA is not a pure autoharn concern (core = generic ledger viewer, autoharn = extension,
enabled by default).

## 0. Principles (inherited, restated for the standalone repo)

- **The ledger is the only truth.** The SPA stores nothing derivable, caches only with the
  watermark as invalidation key, and never renders a fact it cannot attribute to rows.
- **Writes are a conduit, never a bypass.** Every mutation goes through the deployment's
  own typed grammar (`./led` today, its API-equivalent if one is ever ratified). Kernel
  refusals are rendered verbatim as first-class outcomes — a refusal is information.
- **Derive, don't duplicate.** Vocabularies (kinds, verdicts, independence grades,
  resolution types) come from the backend/API at runtime; hand-copied enums in the
  frontend are the defect class the PoC's critique loop spent two rounds killing.
- **No elision of load-bearing text.** Statements, refusal texts, witness refs wrap or
  expand; `text-overflow: ellipsis` is permitted only on genuinely decorative columns and
  every truncation must be expandable in place. (Maintainer verdict on the PoC.)

## 1. Configuration (concern 1 of the commission)

Single config source, environment-first, file-fallback (`panel.toml` or equivalent),
precedence documented:

- `LEDGER_PG_URI` — full Postgres URI, **or** discrete `PGHOST/PGDATABASE/...` fields.
- `LEDGER_SCHEMA`, `LEDGER_KERNEL_SCHEMA` — the world pair.
- `LED_BIN` — path to the deployment's `led` verb (the write conduit). Absent ⇒ the SPA is
  read-only and says so in the header rather than hiding write controls.
- `PANEL_BIND`, `PANEL_PORT` — bind scope is the operator's only auth knob (loopback
  default; `0.0.0.0` is a choice, not a default).
- `PANEL_POLL_INTERVAL` — SSE watermark poll cadence.
- `PANEL_EXTENSIONS` — extension list; `autoharn` present and enabled by default.
- Startup is fail-loud: unresolvable DB/config prints the exact missing key and exits
  nonzero. No silent defaults to anybody's host (the 192.168.122.1 lesson, now a class).

## 2. Views

### 2.1 Board (browsing view) — P0
The landing surface. Faceted, virtualized lists over every row kind: work items,
commissions, questions, findings, decisions, reviews, snags. Facets: kind, actor/principal,
state (open/claimed/closed/superseded), independence grade, date range, free-text. Columns
never elide statements (§0). **Superseded rows hidden by default, one visible toggle**
(maintainer verdict). Counts on every facet are computed by the same query that fills the
list (one home per count — the PoC's round-4 lesson, kept).

### 2.2 Item view (structured relational view) — P0
One row, everything the ledger relates to it: full statement, typed columns, refs in/out
(each a hoverable link, §3), supersede chain rendered as a chain, disposition/witness
edges, review/co-sign history with actor + independence badges, the raw row behind a
disclosure. Co-sign panel lives here (and only here in v1 — other views link in). Every
item view is deep-linkable (`/item/<row-id>`), so ledger citations elsewhere (turn
reports, docs) can point straight at it.

### 2.3 Obligation-tree graph view — P0 (maintainer-demanded)
The AND-tree from the ratified close-semantics model, drawn as a graph: leaf obligations
resolve by recorded acts, interior nodes by conjunction — the view renders exactly that
derivation, never a stored verdict. Color coding: **red = undischarged, green =
discharged**, amber = ambiguous/partial (e.g. AMBIGUOUS duplicate-identity groups), gray =
superseded (hidden with the global toggle). Hover = synopsis card (statement excerpt,
actor, age, discharge evidence); click = item view (2.2). Live recolor on ledger-change
events. Layout: layered DAG (roots left or top), stable across refetches so the graph
doesn't dance under the operator's cursor. Scale target: 500 nodes interactive; beyond
that, collapse-by-subtree with per-subtree discharge fractions on the collapsed node.

### 2.4 Commission decomposition — P0 (generalized)
The PoC's one view, demoted to citizen: works for ANY commission row, lists all
commissions (2.1 facet), renders decomposition items by the frozen refs grammar with
derived statuses and per-item co-sign links. The 0714 page is a bookmark, not an axiom.

### 2.5 Tandem view — P1 (parked row banked 2026-07-15, now specced)
Hydrates from turn-completion events (Stop-hook family) rather than navigation: shows the
rows written during the latest turn, the claims they discharge, rich links with hover
synopses into 2.2. Soft protocol first (robust parsing of ledger citations in turn
output); the hard harness-enforced "context scope" stays a separate autoharn-side decision
— this view must degrade gracefully to "rows since watermark W" when no protocol data
exists.

### 2.6 Timeline / audit view — P1
The append-only chain as a timeline: watermark, s26 row-hash chain verification status as
a badge (verified locally by the backend, never asserted without checking), kind-colored
density strip for navigation, jump-to-row. This is where "what happened while I slept"
lives.

### 2.7 Review-gap and question queues — P1
Two worklists the maintainer actually services: undischarged review gaps (with the actor
who owes them) and open questions (with age). Both are filters over 2.1 data — same query
home — but pinned as first-class destinations because they are the maintainer-presence
loop the SPA exists to serve.

## 3. Cross-cutting behaviors

- **Hover synopsis everywhere** (P0): any row reference anywhere renders as a link with a
  hover card — id, kind, statement first line un-elided, status, actor. One component, one
  data source (2.2's endpoint).
- **Live updates** (P0): SSE with watermark fallback, exactly the PoC mechanism; every
  view subscribes, no view refetches more than its own visible data.
- **Search** (P1): server-side full-text over statements, results as 2.1 rows.
- **Keyboard** (P1): j/k row navigation, enter = item view, `/` = search, `g` = graph.
- **Exports** (P2): any filtered view as JSON/CSV; the graph as SVG/DOT.
- **Verified-signature stamps** (P2, standing-deferred): when the signing work unfreezes,
  rows carrying verified signatures get the GitHub-style badge here; the SPA is the
  ergonomic home the maintainer named (ledger row of 2026-07-15). Until then the UI shows
  nothing — no unverified-stamp theater.
- **Accessibility floor** (P1): color coding always paired with a shape/label channel
  (red/green alone fails the obvious reader); focus order follows visual order.
- **Performance budget** (P0): first meaningful paint < 1s on localhost, interaction
  < 100ms, lists virtualized above 200 rows. `docs/omega-observatory/2026-07-15-frontend-speed-reap.md`'s
  "Don't do these" list is a normative appendix to this section.

## 4. Architecture constraints for the standalone repo

- **Vue 3 + Vite** (maintainer's choice, omega parity), **light color scheme carried over
  exactly** from the PoC's `styles.css` — extract its palette to design tokens first, then
  restyle nothing.
- **OpenAPI-typed client**: the backend already speaks OpenAPI via FastAPI; generate the
  TS types (`docs/omega-observatory/2026-07-15-structural-reap.md` entry #1) so the
  vocabulary classes stay single-homed at compile time too. The generated client is
  build output, never hand-edited, regenerated in CI against the backend's live
  `openapi.json`.
- **Extension boundary** (concern 5): the core knows Postgres-ledger-generic concepts
  (rows, kinds, refs, supersession). Everything autoharn-semantic — obligation trees,
  independence grades, `led` grammar, kernel vocabularies — lives in an `extensions/autoharn`
  module loaded per config, **enabled by default**. The test that the boundary is real: the
  core builds and runs (read-only, reduced views) against a bare ledger schema with the
  extension disabled.
- **Repo layout**: own repo (`KodBena/<name>`), backend + frontend together (they version
  together; the API contract is the internal seam), submoduled into autoharn under
  `tools/` alongside makespan (concern 3); autoharn's own docs reference it as an optional
  component that `--recursive` brings in free.

## 5. Priority tiers, restated for subsetting

- **P0** (the SPA is not usable without): board, item view, obligation graph, generalized
  commissions, hover synopses, live updates, no-elision, superseded toggle, config
  surface, performance budget.
- **P1** (professional): tandem, timeline, queues, search, keyboard, a11y floor.
- **P2** (complete): exports, signature badges, and whatever the maintainer's active use
  files next — this spec expects amendment rows, not private forks of itself.

## 6. Non-goals

Direct SQL writes from the SPA (never); storing any derived status; auth ceremony beyond
bind scope; dark mode before the light scheme is settled; rendering unconfirmed writes
optimistically (the ledger confirms, then the view shows it).

<!-- doc-attest-exempt: dated Fable-authored design input awaiting maintainer subsetting;
frozen as of its date, amendments arrive as ledger rows + successor sections. -->
