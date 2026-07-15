# Frontend architecture reap: omega/frontend → ledger-panel SPA

Scout: read-only survey of the maintainer's private omega checkout's `frontend/` (`<redacted: local absolute path>`) current state
(no git archaeology; a sibling scout covers history). Commission
(maintainer, 2026-07-15, near-verbatim): omega/frontend has "somewhat
rigorous architectural discipline (or at least, as of late — after
refactoring)... which also might be worth doing for [the new SPA]... I
like the general shape of what we have there." Feeds the ledger-panel
SPA (`autoharn-panel`: Vue 3 + Vite + TS, plain `reactive()`/`computed()`
store, OpenAPI-generated client, generic-core-vs-autoharn-extension
boundary).

Documents read in full (VERIFIED, end-to-end): `frontend/CLAUDE.md`,
`frontend/tests/CLAUDE.md`, `docs/adr/0001-state-mutation-and-readonly.md`,
`docs/adr/0003-frontend-portability-and-domain-boundaries.md`,
`docs/adr/0011-mechanization-discipline.md`. Read for structure/key
sections only (headings + targeted excerpts, not end-to-end — flagged
per rule below rather than bluffed): `docs/adr/0002-fail-loudly.md`
(full "Concrete rules" section read in full, rest skimmed by heading),
`docs/adr/0006-source-file-headers.md`, `docs/adr/0007-file-size-and-information-density.md`
(skimmed by heading + thresholds excerpt), `eslint.config.js` (header
rationale block + rule list read; full 73KB file not read start to end),
`.github/workflows/frontend-ci.yml` (partial). `docs/adr/0004`, `0005`,
`0008`, `0009`, `0010` were not opened this pass — cited only where
`frontend/CLAUDE.md` or another read document quotes them; treat any
0004/0005/0008/0009/0010-specific claim below as INFERRED-from-citation,
not VERIFIED, unless marked otherwise. omega's own house rule ("the
single gravest sin... is to fail to read a piece of documentation from
beginning to end... and then make any statement that references any
part within it") is noted, not fully honored, for the docs skimmed —
disclosed rather than bluffed, per that same rule's own instruction on
budget-deferral.

---

## The structural rules

### 1. Four-layer architecture: Components / Composables / Services / State(+Store)

**The rule.** Components (`src/components/*`, `App.vue`) are thin
renderers — no business logic, no direct service calls. Composables
(`src/composables/*`) hold the real logic as "pure-ish functions over
reactive refs." Services (`src/services/*`) are effectful singletons
(API calls, WebSocket clients, debounced persistence) — the sole ACL
(`src/services/backend-service.ts`) is where wire shapes (snake_case)
become domain types (camelCase, branded). State (`src/state/*`) holds
reactive-state modules that are not effectful singletons and that a
display *leaf* may read directly. A single reactive `GlobalStore`
(`src/store/index.ts`) is the store — no Pinia (ADR-0001).

**Where stated/enforced.** `frontend/CLAUDE.md` "Architectural shape."
Enforced at **build/CI gate**: `eslint.config.js`'s `no-restricted-imports`
denies components importing `src/services/**` (deny-by-default, see
rule 3 below); it does NOT itself police `src/state/**` — that's
deliberate (see rule 1a). Nothing mechanically forces composables to
avoid direct backend calls beyond the wire-type import gate (rule 2).

**Defect class foreclosed.** Logic scattered into components (untestable
without mounting; the project's own stated reason — three-tier tests
drive a composable against fakes with no Vue mount at all); effects
leaking into places their cleanup discipline doesn't reach.

**Verdict: ADOPT, with a naming adjustment.** The Components/Composables/
Services split maps directly onto Vue 3 + Vite + TS and is exactly the
shape a "plain reactive()/computed() store" project needs to keep
disciplined without Pinia's typed-actions crutch. For the ledger-panel
SPA, the extension boundary (generic core vs. autoharn extension) is an
orthogonal axis that should compose with this one, not replace it —
i.e. both the core and the extension get their own
components/composables/services/state, or the boundary is expressed as
an ADR-0003-style band tag layered on top (see rule 6). VERIFIED from
`frontend/CLAUDE.md`.

### 1a. The State-vs-Services seam is directory-structural, not a name/enum

**The rule.** Reactive-state modules that a display leaf reads directly
(under ADR-0010 read-locality) live in `src/state/`; effectful
singletons live in `src/services/`. The distinction used to be an
enumerated exemption list (`REACTIVE_STATE_EXEMPTIONS`) inside the
services-import lint; it was **relocated to a directory** (2026-06-11)
specifically so the lint boundary becomes purely structural — deny
`src/services/**` from components, and `src/state/**` is simply outside
the deny rule because of where it lives, not because of a maintained
list.

**Where stated/enforced.** `frontend/CLAUDE.md` "Tension with ADR-0010
read-locality" + `eslint.config.js` header (rationale block, "Shape
history" paragraph). Enforced at **build/CI gate** — directory location
IS the enforcement, checked by the existing import-boundary lint with
zero extra machinery.

**Defect class foreclosed.** ADR-0011 Rule 4 by name: "enumerations of
instances fail open at the next instance" — a new reactive-state module
added to the enum-exemption list only if someone remembered; a new one
added to `src/state/` is automatically correctly classified.

**Verdict: ADOPT as a pattern, not necessarily the literal directory
name.** This is the single cleanest idea in the corpus: when a boundary
would otherwise require an enumerated exception list, look for a way to
make the boundary a directory (or another structural fact a linter can
check without a maintained list) instead. For the ledger-panel SPA:
if the reactive store is plain `reactive()`/`computed()` (not
per-composable state modules), this seam may not even arise the same
way — worth deciding explicitly at design time whether "read-locality
leaves" is a real category in the new SPA, and if so, giving it a
directory rather than a convention from day one.

### 2. The ACL is the only place wire shapes appear

**The rule.** OpenAPI-generated wire types (`src/types/backend.ts`,
snake_case) may be imported ONLY within the services layer and
`src/types.ts` (the type-level alias boundary). No other module sees
snake_case; the ACL translates, and **validates rather than coerces**
(missing required fields produce warnings/errors, not silently-filled
defaults — ADR-0002 concrete rule 4).

**Where stated/enforced.** `frontend/CLAUDE.md` "Type-driven design" +
"Reading documentation" section's "OpenAPI codegen... is the source of
truth... never hand-edit the generated file." Enforced at **compile-time
+ build/CI gate**: `eslint.config.js`'s `no-restricted-imports` +
`@typescript-eslint/no-restricted-imports` superset, "Zero violations at
adoption — this codified an invariant that already held" (i.e. measured
before gating at error, per ADR-0011 Rule 3).

**Defect class foreclosed.** snake_case (or any wire-shape idiosyncrasy)
leaking past the boundary into domain code, which then couples every
consumer to the backend's literal JSON shape instead of a stable domain
type.

**Verdict: ADOPT directly — this is exactly autoharn-panel's own stated
design already** (OpenAPI-generated client + presumably an ACL). The
one addition worth taking: a **mechanical lint**, not just a naming
convention, forbidding import of the generated types outside the
services layer. Cheap to write (one `no-restricted-imports` pattern),
forecloses an entire defect class autoharn-panel's own CLAUDE.md
philosophy (gate culture) already wants foreclosed mechanically rather
than left to review.

### 3. Deny-by-default import boundary, not an enumerated blocklist

**The rule.** Components (and `App.vue`) may not import from
`src/services/**` — **deny-by-default**, not an enumerated list of
"the four effectful singletons we remembered to name."

**Where stated/enforced.** `eslint.config.js` header, "Shape history"
paragraph: the rule began 2026-05-31 as a 4-item blocklist that was
"incomplete from day one" (four other pre-existing services were never
on it) and "fail-open" (a new service was importable from components
until someone remembered to enumerate it); inverted to deny-by-default
2026-06-10. Enforced at **build/CI gate**.

**Defect class foreclosed.** The exact ADR-0011 Rule 4 failure class:
an enumerated allow/deny list that a new instance silently escapes.
This is stated as a **paid-for lesson** (the rule existed, was
incomplete, and shipped that way for over a week before being fixed) —
not a hypothetical.

**Verdict: ADOPT.** Directly transferable and cheap: write the
import-boundary lint as deny-by-default from day one in the new
repo, rather than reproducing omega's discovery-through-incompleteness
path. This is the single most mechanically reusable lesson in the
corpus for a fresh project.

### 4. Type-driven design: branded IDs, discriminated unions, justified casts

**The rule.** Branded types for identifiers that shouldn't be confused
(construction only through the ACL or a dedicated factory — no raw
`string`/`number` flows through domain code). Discriminated unions for
multi-mode state, verified by exhaustiveness (`never`-typed default
branch). `readonly` on true value objects, dropped on reactive
containers the runtime actually mutates (ADR-0001 — see rule 5).
`Optional<T>` / discriminated unions over nullable fields. Keyed caches
mint a **branded key at construction** whose brand names every input
the cached value's content depends on (worked failure: an under-keyed
cache stranding stale entries after a "palette swap," 2026-06-08). Every
`as` cast needs a comment justifying why it's safe — enforced as a
concrete ADR-0002 rule, and there's a dedicated lint
(`local/justification-adjacency`) checking the justification sits next
to the cast.

**Where stated/enforced.** `frontend/CLAUDE.md` "Type-driven design";
`docs/adr/0001` (readonly policy in detail); `docs/adr/0002` concrete
rule 2 (cast justification); `eslint-rules/justification-adjacency.js`.
Enforcement is **mixed**: branding/discriminated-unions/exhaustiveness
are compile-time; cast-justification is build/CI-gated by the custom
lint but its *content* (is the justification actually true) is
review-only — ADR-0011's own Context cites a measured "~50% conformance
in a 32-of-224 `.ts` sample" for the cast-justification rule, an
honestly-disclosed enforcement gap, not a claimed 100%.

**Defect class foreclosed.** ID confusion (passing a `CardId` where a
`UserId` is expected); non-exhaustive state handling silently falling
through; unjustified unsafe casts hiding real type errors; a cache
keyed on fewer dependencies than the value it stores actually depends
on (stranded-bucket bugs).

**Verdict: ADOPT the branding + discriminated-union + exhaustiveness
discipline wholesale** — these are TypeScript idioms with zero
Vue-specific coupling, directly reusable in autoharn-panel, and cheap.
**ADOPT the cast-justification lint** (mechanical, cheap, and
ADR-0011's own honest 50%-conformance number is a useful calibration:
expect the lint to need a baseline-measure-then-gate rollout, not a
same-day 100%). **ADAPT the keyed-cache-brand rule**: relevant only if
autoharn-panel grows a content-addressed cache; worth stating as a
standing rule in the new project's CLAUDE.md now, cheaply, before the
first cache is written, rather than after a stranding bug.

### 5. `readonly` reflects actual write behavior; mutation goes through named mutator functions by convention, not by the type system

**The rule (ADR-0001, VERIFIED full read).** State containers
(`BoardState`, `GlobalStore`, etc.) are NOT `readonly` — the type
honestly admits they're mutated. Value objects (`Move`, `Point`,
branded IDs) ARE `readonly`. The "route writes through named mutators"
convention survives, but as a **code-review-enforced** convention, not
a compiler-enforced one — TypeScript's `readonly` is compile-time-only
and was never actually stopping runtime mutation (mutators used
internal `as any` casts to defeat it). Direct template writes to UI-only
state (`store.session.ui.*`) are an explicit sanctioned exception.

**Where stated/enforced.** `docs/adr/0001` in full. Originally
**review-only** ("grep for direct `.boards[` writes during review");
**mechanized** 2026-06-10 into `local/store-write-needs-owner`, an
ESLint rule enumerating each store subtree's legitimate writer files
(build/CI gate) — itself later strengthened (2026-06-11) with real
scope analysis (resolves renamed imports and one-hop aliases), with an
explicitly disclosed residual gap (two-hop aliasing, reassigned root
bindings) still review-only.

**Defect class foreclosed.** A compile-time-only annotation
(`readonly`) that lies about actual runtime behavior — the general
principle "type declarations should match actual behavior, no
aspirational annotations" (explicitly named as the same philosophy that
governs ADR-0003's Port-extraction stance too). Also: an untracked
direct write bypassing the version-counter bump a mutator is responsible
for, causing a stale reactive read downstream.

**Verdict: ADOPT the philosophy (types must not lie about mutability);
ADAPT the mechanism to the new project's actual store shape.**
autoharn-panel's store is "plain `reactive()`/`computed()`," which is
architecturally close to omega's (no Pinia there either, same reasoning
against it — see ADR-0001 Alternative C, briefly: Pinia is a migration
orthogonal to the readonly question, large blast radius, incremental
payoff). Concretely: don't mark reactive state `readonly` aspirationally;
if a mutator-function convention is adopted for a given state slice, name
its legitimate writers early and consider a cheap
name/directory-quantified lint over "who writes to this slot" rather than
leaving it purely to review from the start — the omega history shows the
review-only version decayed measurably (0/20/10 stray-writer counts
found at audit) before being mechanized.

### 6. Domain-boundary bands (ADR-0003) — evaluate new modules against "what would change for a port?"

**The rule (VERIFIED full read).** Three bands: Band 1 (truly
domain-agnostic — would survive a port to ANY other domain), Band 2
(agnostic within a problem class — e.g. any turn-based game with a
tree — but not outside it), Band 3 (essentially domain-bound; porting
is replacement, not refactor). The authoring-time question: "what
would change for a [Chess] port?" — if "everything," isolate behind a
clear interface; if "nothing," name it for the problem class not the
instance; if "some," that's a seam — design it deliberately without
necessarily extracting an abstraction. Explicitly **not** a mandate to
preemptively extract Port interfaces (cites Sandi Metz: "duplication is
cheaper than the wrong abstraction" — extraction waits for a second
concrete use case). The per-file band tags live in `frontend/FILES.md`
(a lookup doc, explicitly exempted from the "read end-to-end" rule);
the definitions/seam-analysis live in the ADR.

**Where stated/enforced.** `docs/adr/0003` in full;
`frontend/CLAUDE.md` "File map" section names `FILES.md`'s band tags.
Enforcement is **split**: the *content* judgment ("is this the right
band?") is explicitly **review-only, policy** (ADR-0003's own Negative
consequence, unresolved even after mechanization — see next). The
*structural* half — "does file X actually import only from files whose
band is ≥ its own" — was mechanized 2026-06-11 as a **build/CI gate**:
`tools/band-conformance/check.mjs` parses `FILES.md`'s band tags against
the real `src` import graph and fails on drift (a FILES.md row that
resolves to no file, a src file missing a row, a broken import), with
band-*ordering* violations reported advisory-first and ratcheted (fails
only on a *new* leak beyond a measured baseline) — an explicit instance
of ADR-0011 Rule 5 (gate the crisp mechanical predicate; advise on the
judgment-shaped one).

**Defect class foreclosed.** Silent domain-coupling creep: a
"generic" module quietly importing something instance-specific, so a
later port/fork discovers the coupling only when it breaks. Also
guards against premature, wrong-shaped abstraction (the Metz argument)
— the ADR explicitly documents this cutting the *other* direction too
(NOT extracting a Port before a second real adopter exists).

**Verdict: ADAPT, don't lift the specific bands.** autoharn-panel's
generic-ledger-core-vs-autoharn-extension boundary is structurally the
*same problem* ADR-0003 solves for omega (Go client vs. hypothetical
Chess/flashcard fork) — the "what would change for a [use case outside
the extension]?" question is directly transferable as the extension
boundary's authoring-time discipline. What to adapt rather than adopt
verbatim: omega's band count (3) and axis (game-class) are Go-specific;
autoharn-panel likely wants exactly 2 bands (generic-core vs.
extension-bound) since it's designing FOR the fork from day one rather
than discovering the boundary after the fact — which actually makes
autoharn-panel's case for the ADR-0003 mechanization (band-conformance
CI check) *stronger*, not weaker: the boundary is a known, load-bearing
design constraint at day one rather than a retrofit, so a
band(file) >= band(import) style CI gate over "core" vs. "extension"
imports could be adopted from the start rather than retrofitted after
drift is already measured. This is arguably the single most relevant
transferable idea for the specific "generic core vs. extension"
framing in the commission.

### 7. File-size and information-density targets (ADR-0007) with a rolling-archive escape valve for append-only growth

**The rule (INFERRED from `frontend/CLAUDE.md` quotes + ADR-0007
headings, not full ADR-0007 read).** Soft-threshold targets: TS/JS
files ≤200 lines (≤300 acceptable), Vue SFCs ≤250 lines with no
individual template/script/style section >~150. Explicitly a **soft
threshold that flags, not a hard ceiling** ("Not a hard line-count
limit"). When a file grows past it: extract a composable, extract a
child component, or move CSS out — "never compress logic to fit." A
worked pattern for append-only-growth files that would otherwise
violate the threshold: `src/store/migrations.ts` keeps exactly the
latest **two** migrations as "style anchors," archiving older ones into
`archived-migrations.ts` on every PR that adds a new migration (same-PR
cadence, frozen bodies, cut-and-paste never edit-during-move).

**Where stated/enforced.** `frontend/CLAUDE.md` "Vue Single-File
Components" + "Rolling-archive discipline for `src/store/migrations.ts`";
`docs/adr/0007` (headings only, not fully read this pass — flagged).
Enforcement: **review-only / checklist**, no mechanical line-count gate
found in `eslint.config.js` or CI in this pass (ADR-0007's own
"Revisit when" heading mentions thresholds "can become enforced
limits," implying not yet).

**Defect class foreclosed.** Files that grow monotonically and never
get refactored because there's no explicit trigger — the migrations
rolling-archive is a direct, cheap answer to "this file structurally
only grows" (schema migrations, changelogs, any append-only ledger).

**Verdict: ADOPT the size-target discipline as a stated soft
convention (cheap, zero mechanism cost); ADOPT the rolling-archive
pattern specifically if/when autoharn-panel's own store or ledger-panel
code accrues an append-only file** (schema migrations are a very likely
candidate given "ledger" framing) — this is a small, concrete,
proven-cheap idea worth pre-committing to rather than discovering after
a migrations file hits 1100 lines (which is what happened here before
the fix, per `frontend/CLAUDE.md`'s dated note).

### 8. Three-tier test architecture mirroring the layering

**The rule (VERIFIED full read of `tests/CLAUDE.md`).** Tier 1
(`tests/unit/`): pure TS, no DOM/Vue/fakes — functions of plain inputs
to plain outputs. Tier 2 (`tests/fakes/`): spy-bearing fake objects
substituting effectful service singletons, exposing only the subset of
the real surface actually exercised, with a `reset…()` per fake called
in `beforeEach`. Tier 3 (`tests/integration/`): composables driven
against the real store/navigator/rules-engine/i18n and against the
fakes at the proxy/backend/persistence boundary only — this is where
"the highest-value behaviour assertions live" (resource-ownership
cleanups, async/timeout state machines). Component-level/template tests
and E2E are explicitly **out of scope** ("low ROI for the current
shape... defer until the gap shows up empirically"), with one **named
exception**: render-count regression guards
(`tests/integration/render-count/`) that mount a component but assert
only render *frequency*, not output — a CI-catchable proxy for the
ADR-0010 render-locality invariant, which is otherwise only visible
under a profiler. Non-hermetic-test gotchas are documented explicitly:
register teardown at creation (`onTestFinished`), not end-of-body, so a
mid-test throw doesn't leak state into the next test; `withSetup()` is
needed to give a bare `useComposable()` call a component instance so
its `onUnmounted`/`watch` actually get cleaned up.

**Where stated/enforced.** `frontend/tests/CLAUDE.md` in full. Enforced
at **build/CI gate**: `.github/workflows/frontend-ci.yml` runs build +
`eslint .` + `npm run test:run` on every PR (landed 2026-06-01), so a
failing test or a render-count regression blocks merge.

**Defect class foreclosed.** Effect-orchestration bugs (abort/resume
choreography, timeout paths) that are expensive to test if only
reachable by mounting full components; non-hermetic test suites where
one failure cascades into unrelated false failures (explicitly named
as "its own bug," not a side effect); render-coupling regressions that
otherwise only show up in a profiler after the fact.

**Verdict: ADOPT the tier structure and the "component tests are
low-ROI, defer" call** — this is directly reusable guidance for a
Vue+Vite+TS SPA of similar scale, and the reasoning (test the
composable's wiring, not the DOM) transfers cleanly to autoharn-panel's
plain-reactive-store shape. ADOPT the fake-pattern conventions
(minimal-surface fakes + `reset…()` + `vi.mock` hoisting note +
`vi.importActual` for `instanceof` checks) verbatim — these are
Vitest/Vue mechanics, not omega-specific. SKIP the render-count harness
unless/until ledger-panel grows a canvas-scale or high-frequency-render
component — it is a real, working pattern, but its trigger condition
(data-dense visuals, ADR-0010) may not exist in a ledger panel; note it
so it's picked up if that changes rather than reinvented.

### 9. Mechanization Discipline (ADR-0011) — every rule declares its enforcement register; recurrence converts prose to mechanism

**The rule (VERIFIED full read).** Five rules, most load-bearing here:
(1) every discipline-stating rule must name its enforcement level from
a closed vocabulary — compile-time / build-CI-gate / write-time-DB-
constraint / query-time-gate / advisory-surface /
checklist-at-a-named-moment / review-only — and "review-only" is
"legitimate but presumptively decaying," its declaration making that a
visible, challengeable choice rather than a silent one; (2) when a
failure shape *recurs* after being described in prose, the corrective
must convert to mechanism at the strongest feasible/proportionate
level, or carry an explicit "policy-only, here's why, here's the
trigger" admission — not just more prose; (3) mechanisms adopt
measure-first (assess stock rules before writing custom ones; measure
the tree via a scratch config before picking severity; gate at `error`
only on a zero-or-fully-triaged baseline); (4) nets must quantify over
the *class* (an ownership slot, a name/shape predicate, deny-by-default)
not enumerate *instances* — four named paid-for failures of the
enumeration shape, one being the exact services-import-boundary history
in rule 3 above; (5) don't gate judgment-shaped output with a mandatory
tollgate — that produces "bungled compliance, strictly worse than
missing compliance"; use checklists/advisory surfaces for those instead.

**Where stated/enforced.** `docs/adr/0011` in full. Self-applies at
**checklist-at-a-named-moment + audit-sweep**: a line in
`docs/pre-merge-checklist.md`, and a periodic audit sweep checks for
absent enforcement-declarations and un-measured mechanism adoptions.

**Defect class foreclosed.** The project's own named "characteristic
failure mode": "the invisible-at-authoring, visible-only-in-aggregate
defect, against which policy enforced by one person's attention and
memory is structurally weak." Also directly forecloses vague
enforcement claims — an unstated "this is enforced" that turns out to
mean "someone should remember to check."

**Verdict: this is the single most load-bearing, most directly portable
idea in the whole corpus, and it is exactly autoharn's own stated
culture already** (CLAUDE.md's "gate culture," `gates/no_lazy_imports.py`,
the WITNESSED/REFUSED-AS-EXPECTED/UNEXERCISED discipline). **ADOPT
outright, near-verbatim, as a standing rule for autoharn-panel and/or
its CLAUDE.md**: every architectural rule written for the new SPA
should state its enforcement register at authoring time, using
omega's exact vocabulary (it's a good, complete vocabulary and there's
no reason to reinvent one) — and Rule 4 (quantify over the class, not
the instance) should be applied prospectively to every lint/gate
authoutoharn-panel writes, given omega's four independent paid-for
failures of the enumeration shape. This closes precisely the gap the
commission implicitly flags: a fresh project has zero rules yet, so
"declare the enforcement register when the rule is written" is far
cheaper to do now than to retrofit later, which is exactly what omega
had to do repeatedly (services boundary, store-write-needs-owner,
band-conformance all started as review-only/enumerated and were
converted after a measured failure).

### 10. Fail-loudly's concrete rules (ADR-0002) — no silent retry, no coercion at the ACL, no swallowed errors, sentinel-returns are a red flag

**The rule (VERIFIED — "Concrete rules" section read in full, rest of
ADR-0002 skimmed by heading).** Seven numbered concrete rules: no
automatic retry masking a genuine failure; type assertions must be
justified (see rule 4 above); sentinel-return-instead-of-throw is a red
flag requiring justification (prefer throw / `undefined` / a
discriminated `{ok:true,value}|{ok:false,reason}` result); the ACL
validates rather than coerces (missing fields error/warn, never get
silently defaulted); empty `catch (e) {}` is never acceptable; two later
rules on design-time-drift and closest-match-selection (choosing from a
closed vocabulary when no true match exists is a silent failure —
provisionally housed here, formally homed in ADR-0008 classification
discipline).

**Where stated/enforced.** `docs/adr/0002`. Mixed: type assertions and
`catch{}` patterns are lintable in principle (justification-adjacency
lint covers casts; no explicit `catch{}` lint confirmed this pass);
ACL-validates-not-coerces and no-silent-retry are largely **review-only**
architectural conventions, not currently gated per this pass's reading.

**Defect class foreclosed.** Errors that vanish instead of surfacing —
the project's umbrella tenet, applied specifically to error-handling
idiom (as opposed to Rule 1's application to documentation-reading).

**Verdict: ADOPT the concrete-rules list verbatim as SPA-authoring
guidance** — these are generic TypeScript/error-handling hygiene, no
Vue or Go coupling, and align directly with autoharn's own fail-loudly
posture (ADR-0002 in autoharn's own law is presumably a cognate — worth
checking whether autoharn already has an equivalent and cross-linking
rather than duplicating). Where mechanizable cheaply (cast
justification, maybe a `no-empty` / custom "swallowed catch" lint),
ADOPT the lint too, per rule 9's own logic (declare it, don't leave it
implicit).

---

## The load-bearing honesty note

Several of the rules above are candid about their own limits in a way
worth calling out as a pattern rather than a rule: ADR-0003 records its
own band tags **disagreeing with the ADR's prose** in three places and
leaves the disagreement recorded, not silently resolved. ADR-0001
records a mechanization's own **narrowing** (a dropped READ-argument
firing) as a disclosed regression, not a quiet one. ADR-0011 cites a
measured 50% conformance rate for its own cast-justification rule as
the reason a "review-only" declaration is honest rather than
aspirational. This is a cultural trait (documented gaps stay documented
rather than getting papered over at the next edit), not a single rule
to adopt/adapt/skip — but it is the trait that makes the rest of this
sheet trustworthy, and it's worth carrying into autoharn-panel's own
documentation habits explicitly.

---

## Single most load-bearing rule for the ledger-panel rebuild

**ADR-0011, Mechanization Discipline** (rule 9 above) — specifically
its Rule 1 (every discipline-stating rule names its enforcement
register from a closed vocabulary at the moment it's written) and Rule
4 (nets quantify over the class, not the instance). A brand-new
project gets to adopt this for free, at zero retrofit cost, on day one
— which is exactly the advantage omega's own history shows was
*not* available to it: every mechanized rule in this sheet (services
boundary, store-write ownership, band-conformance) started life as an
enumerated list or a review-only convention and was converted only
after a measured, paid-for failure. autoharn-panel doesn't have to pay
that tuition if the discipline is stated and gated from the start
rather than discovered. Given autoharn's own CLAUDE.md already treats
gate culture as central (the lazy-imports gate, the WITNESSED/
UNEXERCISED claim discipline), ADR-0011 is less "new idea to import"
and more "the missing explicit vocabulary that makes autoharn's
existing instincts legible and checkable" — worth lifting close to
verbatim.
