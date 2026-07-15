# omega structural reap — 2026-07-15

Scout pass over the maintainer's private omega checkout (`<redacted: local absolute path>`), read-only, commissioned to find structural/architectural
flair autoharn/panel could learn from. Ten entries, capped deliberately — omega is a
large, mature codebase (backend + Vue frontend + KataGo proxy submodule) and most of
what's there is domain-specific (Ebisu scheduling, SGF trees, qEUBO) and not relevant
to panel's much smaller surface. What follows is what actually transfers.

Everything below marked "verified" was read directly out of the cited file. Nothing
here is secondhand.

---

## 1. OpenAPI types generated, hand-rolled typed client consumes them
**Reap**

What it is: `frontend/package.json`'s `gen:api` script runs
`openapi-typescript ${GENAPI_BASE_URL:-http://127.0.0.1:8764}/openapi.json -o src/types/backend.ts`
against the live `fastapi dev` server. `frontend/src/services/api-client.ts` then imports
`components` from that generated file (`type AuthMeResponse = components['schemas']['AuthMeResponse']`)
and uses it to type a hand-written `fetch` wrapper — no generated client, just generated
*types* feeding a client the team still owns and can put its own auth/retry/error
policy into (verified: the 401 silent-retry logic, `ApiError` class, and system-message
sink integration in `api-client.ts` are all bespoke, sitting on top of the generated types).

Why it's worth not forgetting: it gets schema-first typing without the two usual costs —
no committed OpenAPI YAML to keep in sync by hand (FastAPI derives it from the Pydantic
models that already exist), and no heavyweight generated client whose shape fights how
you actually want to call it. The type-check is a lint-time gate for free.

What adopting it in panel would look like: `panel/frontend/app.js` is currently 486 lines
of vanilla JS with no static types at all talking to a FastAPI backend that already emits
`/openapi.json` for free. Panel doesn't use TypeScript today, so the direct win needs one
of: (a) a light TS build step just for `api-client`-equivalent code, or (b) generating
JSDoc `@typedef`s instead of `.ts` (openapi-typescript can target that too) so plain JS gets
IDE-level type hints on ledger-row shapes without a build step at all. Either is a small,
self-contained addition — doesn't require converting the whole SPA to TypeScript.

---

## 2. Ports as `typing.Protocol` + import-inspectable Dependency Rule
**Reap**

What it is: `backend/repositories/ports.py` declares six repository Protocols
(`CardRepositoryPort`, `LineageRepositoryPort`, etc.) that the service layer and route
layer depend on structurally — "any class matching the method signatures satisfies the
Port" (verified, module docstring). The file's own docstring states the enforcement
mechanism: "The Dependency Rule is enforceable by inspecting this file's imports —
everything comes from `typing`, `domain.*`, or `schemas.*`. Nothing from `sqlalchemy.*`,
nothing from `db.schema`." Adapters (`backend/repositories/card_repository.py`'s
`CardRepository(CardRepositoryPort, CardWriteRepositoryPort)`, verified) inherit
explicitly so mypy/pyright catch signature drift; consumers just take the Protocol type
and don't know which adapter they got.

Why it's worth not forgetting: it's hexagonal architecture without a DI-container tax —
the boundary is asserted by an import-grep-able file, not a framework. Cheap to verify,
cheap to teach a new contributor by reading one file.

What adopting it in panel would look like: `panel/backend/ledger_read.py` and
`cosign.py` currently talk to Postgres directly from what looks like the request-handling
layer (not yet verified in depth — flagging as inferred from file count, not read
line-by-line this pass). If panel's backend grows past its current ~260-line `app.py`,
carving a `ports.py` Protocol for "the ledger reads panel needs" before the SQL spreads
across handlers would buy the same cheap-to-audit boundary, sized for panel's much
smaller surface (probably 2-3 Protocols, not six).

---

## 3. In-memory fakes implement the same Protocol as production adapters
**Reap**

What it is: `backend/tests/fakes/card_repository.py` and siblings are plain-Python
classes that structurally satisfy the same Port Protocols from entry #2 — e.g.
`FakeAnalysisBundleRepository` reproduces the production adapter's per-user byte-quota
behavior, tenancy filtering, and error types (verified: docstring enumerates each
contract point the fake mirrors: quota enforcement, cross-tenant `None` returns,
idempotent delete). Because it's the same Protocol, not a mock library's `Mock()`, a
signature change in the Port breaks the fake at type-check time instead of silently
returning `MagicMock()` from every call.

Why it's worth not forgetting: it's the natural payoff of #2 — you don't get fakes this
cheap without the Protocol boundary existing first. Service-layer tests read like tests
of real behavior (quota exceeded, cross-tenant isolation) rather than "assert mock was
called with these args."

What adopting it in panel would look like: contingent on #2 existing first. Once panel
has a Port for ledger reads, a `FakeLedgerReader` implementing it in-memory would let
disposition/cosign logic be tested without a live Postgres — currently (inferred, not
verified this pass) panel's tests likely need the real DB, which is heavier to spin up
per test run.

---

## 4. Routes always registered; disabled optional feature is a 503, not a missing route
**Reap**

What it is: `backend/main.py`'s `lifespan` imports `qeubo`'s heavy dependencies
(torch/botorch/gpytorch) only inside `if config.QEUBO_ENABLED:` (verified), but
`api/routes/qeubo.py`'s routes are registered unconditionally in `main.py`'s router
list. The dependency function backing those routes returns 503 when
`app.state.qeubo_service` was never set. `core/config.py`'s docstring states the intent
plainly: "everyone else gets a backend with /qeubo/* routes returning 503 (the
dispatch's documented disabled-state contract)."

Why it's worth not forgetting: the OpenAPI schema is identical regardless of which
features are enabled at a given deployment — no conditional-registration branching to
reason about, no "does this install even have that route" question for a client to
answer. The heavy-import cost is still avoided (verified: the torch/botorch import is
textually inside the `if`, so a default install never pays it).

What adopting it in panel would look like: panel doesn't have optional heavy features
today as far as this pass found, so this is a pattern to bank for when one shows up
(e.g. if a future panel capability needs an optional heavy dependency) rather than
something to retrofit now.

---

## 5. `work_status_violations`: a CI-gate view for invariants a CHECK constraint can't express
**Reap**

What it is: `tools/work-status/schema.sql` enforces per-row shape with ordinary
`CHECK`/`FOREIGN KEY` constraints, then adds one view,
`work_status_violations`, for the cross-row invariants that are structurally
unreachable from a row-local constraint: dependency cycles and parent cycles, computed
via `WITH RECURSIVE ... CYCLE ... SET is_cycle`, plus a "shipped item has no ship
reference" check (verified, full view body read). The file's comment states the
contract: "a validator/CI gate fails the build if any row comes back."

Why it's worth not forgetting: it's a clean division of labor — structural invariants
stay in `CHECK`/FK (fail on write, cheapest possible enforcement), invariants that need
a whole-table graph walk go in a view a gate polls (fail on read, but exhaustive and
declarative — no hand-rolled cycle-detection code to maintain).

What adopting it in panel would look like: if the ledger schema autoharn already runs
has any cross-row invariant that isn't already a FK/CHECK (e.g. "every co-signed row has
a corresponding decision row," "no disposition references a quarantined session") a
parallel view + a gate step that fails on non-empty would be a small, idiomatic addition
that fits how `judge`'s verdicts already work by parallel construction to omega's here.
Not proposing a specific instance since this pass didn't audit the panel/ledger schema
for candidate invariants.

---

## 6. Generic, table-agnostic audit-log trigger + `table_asof()` time-travel
**Consider**

What it is: `tools/work-status/schema.sql`'s audit section (verified) installs one
`record_audit()` trigger function, attached identically to five different tables via
`AFTER INSERT OR UPDATE OR DELETE ... FOR EACH ROW`, writing `old_row`/`new_row` as
`jsonb` plus `actor` (from `application_name`) and an optional `commit_sha` (from a
transaction-local GUC, `audit.commit`, only set when a write corresponds to a git
commit — "absence is honest, not missing data," per the file's own comment). A single
SQL function, `table_asof(tbl, timestamptz)`, reconstructs any audited table's state at
any past instant by picking the latest `new_row` per key at or before that time.
`tools/work-status/asof.sh` wraps it for git-sha lookups.

Why it's worth not forgetting: it's a generic mechanism, not five bespoke history
tables — one trigger function, one reconstruction function, reused verbatim per table.
Attribution (actor + optional commit) is structural, not a convention someone has to
remember to follow.

Why "consider" not "reap": autoharn's ledger already has its own append-only,
attributed-history discipline via `./led` and the ledger schema, and ADR-0013
(execution-integrity) likely already covers the shape of guarantee this buys — I did not
cross-check the live ledger schema this pass to confirm overlap vs. gap, so I can't
call this a clean reap. Flagging it because the *generic-trigger-over-bespoke-tables*
technique is reusable independent of whether the history-tracking need itself is
already met: if panel or another autoharn component ever needs audit history on a table
that ISN'T already inside the ledger's own append-only discipline, this is the shape to
copy rather than hand-rolling a new history table per case.

---

## 7. `cochange-advisory.mjs`: per-PR-diff derived-doc drift detector, ack lives in a commit message
**Reap**

What it is: `tools/doc-graph/cochange-advisory.mjs` (verified, full header read) flags
when a PR's diff touches a doc marked `<!-- derived-from: <glob> -->` as a source, but
doesn't touch the derived doc itself. Two design choices stand out: (a) it's
**per-PR-diff, not state-based** — it only fires on the PR whose diff actually changes
the pairing, computed from `<base>...HEAD`, so once merged it can never re-fire on that
pairing again (the alternative, "derived is older than source," would nag on every
subsequent PR forever); (b) the silence valve is a `cochange-ack: <doc> — <reason>` line
in any commit message of the firing PR, scanned and matched against that specific pair —
no accreting ack-file to maintain, and the rationale is durably attached to the commit
that made the call. It's advisory (exit 0), not a gate, by explicit design (cited:
"too soft to gate").

Why it's worth not forgetting: it solves a real problem — content-snapshot docs going
stale while their cross-reference stays valid — with a mechanism that can't accumulate
either false-positive fatigue (transience is structural) or ack-file cruft (the ack lives
where the decision was made).

What adopting it in panel/autoharn would look like: autoharn has exactly this shape of
risk — `GLOSSARY.md`, `ORCH-CAPABILITIES.md`, and the `law/adr/` synopsis are all docs
that summarize/project from other sources, and the project already has PR-based CI
elsewhere. A `<!-- derived-from: law/adr/*.md -->` marker on the relevant doc(s) plus a
port of this script (it's zero-dep Node, self-contained, ~modest size) would catch the
same drift class autoharn's own `law/adr/history/README.md` "Extraction Pointer"
convention exists to prevent by hand today.

---

## 8. Teardown-registry: dependency-inversion to break an import cycle, with an explicit ordering band
**Consider**

What it is: `frontend/src/store/teardown-registry.ts` (verified, full header read) is a
leaf module (imports nothing but types) that owners register cleanup handlers into at
module-init time, instead of the store importing each owner directly to call its
cleanup. This inverts the store→owner edge that was forming an import cycle
(`store ↔ services ↔ api-client`), which the header states was "the structural
precondition of the vite-8.x vitest-teardown deadlock" fixed in PR #444. Handlers carry
an explicit numeric `order` because one ordering constraint (engine-stop-before-ledger-
purge) is a correctness requirement, not mere hygiene, and can't be left to import-graph-
determined registration order. `tools/cycle-check/check.mjs` is the companion CI
ratchet: Tarjan's-SCC-based, gates on cycle count/cyclic-node count EXCEEDING a measured
non-zero baseline (never on zero, since the current baseline isn't yet zero) — the same
"NO-NEW-X ratchet" shape used elsewhere in omega's tooling.

Why it's worth not forgetting: registries-instead-of-mutual-imports is a generically
useful pattern anywhere two modules both want to react to the same lifecycle event but
neither should import the other; the ratchet-not-absolute-gate move is a reusable way to
introduce a structural CI check on a codebase that already has some of the smell without
that check being unshippable on day one.

Why "consider" not "reap": panel's frontend is 486 lines of vanilla JS in one file today
— there's no import graph yet for a cycle to form in. Worth keeping in the back pocket
for if/when panel's frontend is split into multiple modules with a shared store; not
worth introducing machinery for a problem that doesn't exist yet.

---

## 9. Frozen migration bodies + an independent runtime-shape witness (append-only store schema evolution)
**Admire-but-skip** (the append-only discipline itself autoschema's LAW already holds;
the specific witness mechanism is the part worth naming)

What it is: `frontend/src/store/migration-witness.ts` (verified) provides a
`witnessedContainer` helper, used by both `migrations.ts` (active bodies) and
`archived-migrations.ts` (bodies aged out under a "rolling-archive cadence"). Each
migration body is documented as FROZEN ONCE SHIPPED — "a behavioural change would
silently retro-edit shipped migrations in the wild." The witness is built from the
*live* `defaults` module rather than a frozen inline snapshot, so it asserts a
migration's target container exists in the CURRENT runtime shape (an assertion that
must stay honest as the runtime evolves) while the migration body's own transform logic
is separately frozen (an output that must NOT evolve). The split — frozen transform,
live-checked precondition — is the load-bearing idea.

Why noting it at all given the skip verdict: autoharn's own posture (frozen kernel
lineage, "runs are strictly linear," append-only ledger) is the same shape of
discipline, already covered by standing rulings — nothing to import wholesale. The
piece that's specifically interesting and not obviously already present: separating
"the thing that must never change" (the migration body) from "the thing that checks it
against current reality" (the witness) into two different freeze postures in the same
file family, rather than freezing the whole migration+check unit together. If autoharn
ever needs a client-side (panel frontend) persisted-state schema that evolves over
multiple panel releases, this split is worth re-reading before designing that migration
path from scratch.

---

## 10. `fastapi dev` + always-registered-routes dev loop, `openapi.json` served locally by default
**Admire-but-skip** (autoharn already runs an equivalent workflow)

What it is: `backend/run.sh` is one line — `fastapi dev main.py --host 127.0.0.1 --port
8765` (verified) — no separate uvicorn invocation, no separate reload-flag wiring;
`fastapi dev` gives autoreload and the interactive OpenAPI docs UI for free at
`/docs`, which is also what feeds entry #1's `gen:api` step locally
(`GENAPI_BASE_URL` defaults to `http://127.0.0.1:8764/openapi.json` in `package.json`,
matching this exact dev-server convention).

Why "admire-but-skip": panel's `README.md` (not re-read line-by-line this pass, but
panel was already confirmed to be a FastAPI app with `app.state`-based lifespan) is
presumably already run the same simple way — this is the ordinary, unremarkable way to
run a FastAPI dev server, not a structural insight unique to omega. Noted only because
it's the plumbing that makes entry #1 (`gen:api`) a one-command loop rather than a
multi-step chore, which IS worth remembering if #1 gets adopted.

---

## What autoharn does better (not padding — genuinely asymmetric findings)

- **Ledger-centric write discipline.** omega's `todo` Postgres store (tools/work-status)
  is a close cousin of autoharn's ledger idea but is a side-store for one bounded
  concern (work-status tracking); autoharn's `./led` ledger is the spine of the whole
  system's provenance model, with a `judge` verdict layer and co-sign flow that omega
  has no equivalent of anywhere this pass looked.
- **Explicit escalation/delegation contract.** omega's CLAUDE.md (23KB, skimmed but not
  read in full this pass) did not surface an equivalent to autoharn's typed-event
  escalation rule or the Sonnet-first delegation policy in the portions read — omega
  reads as a single-maintainer project without the same orchestration-of-AI-agents
  layer autoharn has built out.
- **LAW as living, ratified corpus with succession rules.** omega has ADRs (its own
  ADR corpus, the one that seeded autoharn's) but this pass found no equivalent to
  autoharn's succession-rule ceremony (commission/conformance instrument, adversarial
  fresh-context review) for when the primary authoring model is unavailable.

## Explicitly foreclosed by autoharn's LAW (noted, not recommended)

- The generic audit-log trigger (#6) technique is fine as a technique, but any
  proposal to derive/store a value autoharn can compute at read-time instead runs into
  ADR-0000's spirit against stored derivables — flagging this so nobody reads #6 as "go
  store computed history" rather than "here's a pattern for capturing raw write facts,
  which is different."
- Nothing else in this pass ran into lazy imports as a pattern worth citing either way —
  omega's own modules (verified in `main.py`, `ports.py`) import eagerly at module top,
  consistent with autoharn's ban rather than in tension with it.

## Omega's apparent state (worth telling the maintainer directly)

Nothing suggests omega is mid-refactor or broken. The codebase reads as mature and
actively maintained: recent commit timestamps (`api/routes/*.py` and `backend/qeubo/`
touched as recently as Jul 12), a green-looking CI surface (four workflows: frontend-ci,
source-headers-ci, doc-graph-ci, cochange-advisory-ci), and docstrings throughout that
reference specific PR numbers and dated incidents (PR #339, PR #444, 2026-06-10 audit)
in a way that reads as a team that documents its own history carefully rather than one
patching over instability. One thing worth a note: `backend/cards.db` and
`backend/cards_old.db` both sit at the repo root next to source (not verified as
gitignored or not this pass) — not a structural finding, just an artifact I noticed in
passing and didn't chase further since it's out of this commission's scope.
