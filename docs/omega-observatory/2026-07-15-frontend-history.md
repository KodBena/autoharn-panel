# omega/frontend: how the structure got here

Historian pass, 2026-07-15. Read-only against the maintainer's private omega checkout (`<redacted: local absolute path>`). Sibling
scout covers the current architecture; this covers the sequence that produced
it — commit history, ADR dates, postmortems, retrospectives, worklogs. VERIFIED
means the artifact was read; INFERRED means reconstructed from commit shapes,
dates, or cross-references without reading the underlying source directly.

One framing note up front, because the commission asked for it plainly: the
project's own record is candid that discipline mostly arrived *after* pain,
and says so about itself repeatedly (see §6). There is no arc-narrative to
tell here beyond the one the project already told on itself.

## 0. What "frontend" is, and a caveat about the git history's shape

VERIFIED (`docs/archive/handoff-2026-04-frontend-pre-umbrella.md`): the
product ("gogui", a Go/Weiqi study app — SR flashcards graded by KataGo) is
three peer sub-projects — `frontend/` (Vue 3 + TypeScript SPA), `backend/`
(FastAPI), `proxy/` (KataProxy, engine multiplexer) — that were merged into
one monorepo on 2026-04-26.

VERIFIED (`git log`): the visible git history is 1,388 commits, and it
**starts** at commit `e5c857bc` ("initial") on 2026-04-26, immediately
followed by `bc6d6e99` ("meta monorepo") the same day. There is no earlier
git record — the pre-monorepo history was not carried forward. The frontend
handoff note (also 2026-04-25, one day before "initial") says the reactive
store + composable architecture was the product of "twelve months of feature
accretion" by a single author, so the visible repository is a snapshot at the
*end* of a much longer pre-history that isn't recoverable from `git log`
here. Everything below is therefore the history of the frontend **as an
umbrella-monorepo member**, not the whole lifetime of the codebase.

## 1. Before the discipline: what the handoff describes at the seam (2026-04-25/26)

VERIFIED (`docs/archive/handoff-2026-04-frontend-pre-umbrella.md`,
2026-04-25, "outgoing frontend collaborator"): at the close of what the
document calls the "pre-release infrastructure sweep," the frontend had:

- A working reactive store + composable layer, already described as "solid"
  after a year of accretion — this was NOT something the ADR era built; it
  predates the ADRs and the ADRs mostly formalize discipline around it.
- **No test suite at all.** Quoted verbatim: *"There is no test suite. This
  is an honest gap. The codebase has been developed by single-author
  iteration with careful manual review; the absence of tests is a debt that
  should be paid down..."* This is the project naming its own gap candidly,
  before any pain forced the admission — a case of the record being honest
  proactively, not reactively.
- `readonly` annotated on "essentially every field of every interface" in
  `src/types.ts` — an aspirational annotation that didn't match runtime
  behavior (state was mutated pervasively through templates, service layers,
  and mutator functions with internal `as any` casts to shed the shell).

VERIFIED (ADR-0001, dated 2026-04-24): the trigger for the whole ADR corpus
was mechanical, not aspirational-first: running `vue-tsc --strict` (which
"had not been run in a long time") surfaced **~70 `readonly` violations out
of ~124 total build errors**. ADR-0001 (state mutation / readonly policy)
resolved this by admitting the codebase was mutable-by-design and removing
the lying annotation rather than retrofitting real immutability. This is the
founding pattern for nearly everything that follows: a mechanical tool
surfaces a gap between claimed and actual behavior, and the ADR aligns the
claim with reality rather than manufacturing the aspiration.

ADR-0002 through ADR-0007 (Fail Loudly, Frontend Portability/Domain
Boundaries, Minimal-Touch Edits, Documentation Discipline, Source File
Headers, File Size/Information Density) are **all dated the same two days**,
2026-04-24 to 2026-04-26 — authored as a batch during this one "strict-mode
build sweep," not accreted organically over the project's life. ADR-0004
(minimal-touch edits) names its own trigger directly: a prop-contract
regression during the sweep itself, where a "one-line fix" silently turned
local helper functions into required props with no compiler complaint
(both old and new prop interfaces were valid TypeScript) — a runtime
break the type system had no way to flag.

**One clear counter-example, honestly noted per the commission's ask:**
ADR-0003 (frontend portability / domain boundaries) is dated 2026-04-24,
*speculative and forward-looking* — written when "no concrete adopter was on
the horizon" for a non-Go domain. This is discipline arriving *before* pain,
not after. It held up: a real second adopter (a "generic knowledge flash-card
fork") materialized 2026-06-09/10, about six weeks later (VERIFIED, ADR-0003
2026-06-10 amendment), and a second candidate (`chess-clone`) was filed
around the same time. So the proactive bet paid off here — the exception the
commission asked to flag if found.

Similarly ADR-0007 (file size / density) was *proposed* 2026-04-26 but not
formally *accepted* until 2026-06-11, on the strength of six weeks of
practice actually using it (the C2 arc splitting `App.vue` 593→500 lines the
day after authoring, a `types.ts` split later approved as a named deviation).
Its numeric density thresholds (60%/40%) were "never measured in practice" —
proposed as if mechanical, used as qualitative judgment.

## 2. The v1.0.0 freeze and the first release cycle (2026-04-26 → 2026-04-30)

VERIFIED (`docs/archive/README.md`, `docs/archive/release-scope-2026-04.md`):
a scope freeze authored 2026-04-28 named seven items gating v1.0.0; all seven
closed by 2026-04-30 (git: `0eec867` "docs: close v1.0.0" on 2026-04-30). This
cycle also carried the de-branding pass (first commits 2026-04-27, renaming
away from the project's prior name/theme — the codebase now known as "omega"
was "gogui" at this point) and the auth-lifecycle / store-schema-versioning /
C2 composable-extraction arcs referenced in ADR-0007's acceptance note.

This was a refactor-by-plan cycle: scoped in advance, closed on schedule, not
a reaction to an incident.

## 3. Post-v1.0 → v1.1 cycle (2026-05-02 → 2026-05-08): audits, not incidents

VERIFIED (`docs/archive/README.md`): this cycle shipped the color-theming
substrate, a magic-literals audit (closed 2026-05-03 across nine PRs), a
resource-ownership audit (closed 2026-05-04), the cards-tab merge (PRs
#140-142), the forest-directory-hierarchy redesign (PRs #149-154), i18n PR1,
the cross-team analysis-persistence arc, and "the two testing arcs (backend,
frontend)" — the first tests landing, months after the 2026-04-25 handoff
had named their absence as an honest gap.

These were largely planned audits (design notes exist for each: cards-tab
merge plan, forest-directory redesign, magic-literals audit plan,
resource-ownership audit plan) — discipline arriving as *scheduled cleanup*,
not incident response, though motivated by debt the handoff had already
flagged.

## 4. ADR-0008, Classification Discipline (2026-05-17) — born from three postmortems

VERIFIED (ADR-0008 Context): this tenet was explicitly *reactive*. Three
named incidents fed it:
- `postmortem-knob-registry-qeubo-domain-2026-05.md` — a `KnobDomain` enum
  value `'qeubo'` that actually named a consumer, not a domain; the mislabel
  "propagated through six commits before surfacing."
- `postmortem-knob-toolbar-popover-2026-05.md` — a popover mounted into the
  wrong chrome neighborhood by closest-match.
- `docs/worklog/2026-05-14-popover-hover-finickiness.md` — a hover pattern
  copied from a tooltip component without verifying it fit a popover's
  different interaction shape (users reach *into* a popover; they only
  glance at a tooltip).

The principle itself had already been half-named on 2026-05-15 as ADR-0002
Rule 7, explicitly filed with a "provisional home" flag — the author naming,
in the record, that the rule was broader than fail-loudly proper and would
need its own home. Two days later it got one (ADR-0008).

## 5. The performance arc (2026-05-27 → 2026-05-31): pain, then a name, then pain again, then a name that stuck

This is the most instructive sequence in the whole corpus, and closely
matches the commission's "arrived after pain" hypothesis, with a documented
partial failure inside it.

**2026-05-27 — first perf arc.** VERIFIED (ADR-0009 Context): four
structural perf fixes shipped with real profiling behind them, but a Phase 2
dispatcher refactor shipped *without* any attached profile. Within hours a
user-perceived jitter triggered an ad-hoc investigation using `jq` against a
raw Firefox profile dump, no shared vocabulary, no baseline capture. The
project author is quoted directly naming the trigger for codifying a
discipline: *"I really don't like ad-hoc anything."* ADR-0009 (Performance
Investigation Discipline) followed the same day, naming canonical tools
(`profiler-cli`, later a Chrome/CDP capture path added 2026-06-01) and a
metric vocabulary.

**2026-05-29 — the render-coupling postmortem, written but not adopted.**
VERIFIED (ADR-0010 Context, citing
`postmortem-render-coupling-at-composition-nodes-2026-05-29.md`): a ~300-line
postmortem named the render-coupling anti-pattern (an orchestration
component reading a high-frequency reactive value, coupling a whole subtree's
re-render to it), found four instances, and *proposed* a tenet — but the
proposal was explicitly deferred pending maintainer sign-off. It sat
un-adopted.

**2026-05-31 — the same pattern recurs, in a component that had already been
partially hardened against it.** VERIFIED (ADR-0010 Context): `TreeWidget`
had already had its active-node ring pulled out of a `v-for` and given
`v-memo` — someone had internalized "decouple the high-frequency element."
But the ring was still bound reactively in the template, so every navigation
re-ran the component's *entire render function* (762 ms, the single biggest
JS cost in the capture) even though the *patch* was cheap (59.8 ms). ADR-0010
records the lesson verbatim: *"`v-memo` and 'pull the element out of the
loop' fix the patch, not the render; a reactive read anywhere in a template
re-runs the whole render function; render ≫ patch is the tell."* ADR-0010
(Render Locality and Canvas for Data-Dense Visuals) shipped that day, and its
own Context states the point directly: *"a doc that describes a pattern does
not stop it recurring one component over. The name has to be a tenet the
author reaches for and the reviewer checks against."*

The 2026-05-31 "green" perf arc retrospective (VERIFIED,
`docs/notes/green-perf-arc-retrospective-2026-05-31.md`) records the payoff:
`BoardTab` 782ms→0 renders, `TreeWidget`'s tree-nav render eliminated, and an
honest admission that the fix *revealed* a new hotspot (`MiniBoard`, now the
top component render) rather than pretending the problem was fully solved —
consistent with the project's fail-loudly posture applied to its own
retrospectives.

## 6. The 2026-06-01 RCA and the corpus's own diagnosis of itself

VERIFIED (`docs/notes/postmortem/rca-discipline-lapses-2026-06-01.md`): a
maintainer-requested RCA into two lapses (stringly-typed errors reparsed at
six call sites; docs shipped-but-open). The framing the maintainer insisted
on, quoted verbatim: *"This is a single-maintainer project with no second
reviewer. The discipline's only guard is one person's attention and memory.
That is the lapse-surface to examine — not to treat as exculpatory. 'Review
would have caught it' is unavailable as a corrective; the question is what
mechanism could have, since the human guard demonstrably did not."*

The RCA's timeline finding is the sharpest single data point in the corpus:
the unstructured `API Error <status>: <body>` throw format was in the
**very first commit** of the repository (`e5c857b`, 2026-04-26) — it
predates every ADR. The *first* consumer to reparse it (`useAuth.ts`, same
day) carried an inline comment, *"Brittle in principle,"* written by the
author who introduced it. Five more reparse sites accreted over the next
four weeks, each individually well-typed and locally reasonable. The
comment flagged the hazard correctly at instance #1 and did nothing to stop
instances #2–6, because nothing aggregated per-file comments into a
recognized recurring pattern — a comment is not a mechanism. This RCA is the
direct ancestor of ADR-0011.

## 7. The 2026-06-10 corpus audit: the project measures its own thesis

VERIFIED (`docs/notes/audit/audit-spa-history-lessons-2026-06-10.md`, an
audit run at 1,129 commits): its lesson **L1** states the thesis this whole
history keeps proving in different clothes:

> *"Prose disciplines decay; mechanisms stick."* — the cast-justification
> rule held at only ~50% conformance in a 32-site sample; the render-coupling
> anti-pattern recurred *after* a full postmortem described it; a
> hand-maintained cleanup census said "Four cleanups" when there were
> eleven. Conversely: every RCA-minted lint has held since its adoption
> date, and the render-count harness paired with ADR-0010 shows no
> recurrence in the following nine days.

Other lessons from the same audit worth citing: **L2** (multi-writer state
slots want a named owner module, not a per-writer lint — the card-tree slot
was "re-fixed within ~3.5 hours" once, then held once an owner module
existed); **L3** (a deferral only survives if it's filed as a ledger/DB item
at authoring time — deferrals recorded only in worklog prose "reliably
evaporated"); **L6** (even the ADRs' own "Revisit when" triggers rotted
silently in two cases before this audit caught it).

## 8. ADR-0011, Mechanization Discipline (2026-06-11) — the capstone

VERIFIED (ADR-0011): explicitly named as answering the 2026-06-01 RCA's open
question and generalizing the 2026-06-10 audit's L1. Its core rule: **every
discipline-stating rule must declare its own enforcement surface**
(compile-time / CI gate / DB constraint / query-time gate / advisory /
checklist-at-a-named-moment / review-only), and "review-only" is
"legitimate but presumptively decaying" — a status that must be *declared*,
not silently assumed. Rule 2: a *recurring* failure converts to a mechanism,
not more prose, on pain of repeating exactly the render-coupling story
above. Rule 5, notably, is the discipline's own self-check against
overreach: a mandatory gate on judgment-shaped output produces "bungled
compliance, strictly worse than missing compliance" — citing a gate that
was tried and retracted elsewhere in the project. The tenet does not claim
mechanization is free or universally correct; it explicitly warns against
cargo-culting gates onto judgment calls.

By this point the pattern is fully mechanized in practice, not just
declared: `frontend/eslint.config.js` carries rules tied to specific ADRs
(no-floating-promises, switch-exhaustiveness-check, a message-reparse ban
named directly after the RCA, an `only-throw-error` ban, local ownership
rules for `store.boards`/`store.engine`/`store.profile`), a
`band-conformance` CI check enforces ADR-0003's domain-band ordering against
`FILES.md`, and a doc-graph freshness gate + co-change advisory catch stale
cross-references. Each of these is cited in the relevant ADR's own amendment
trail as the moment a "Revisit when" trigger fired.

## 9. Order of arrival, compact

- **2026-04-24/25/26** — `vue-tsc --strict` surfaces ~124 build errors after
  a long gap; ADR-0001 (readonly) and the founding ADR batch (0002, 0004,
  0005, 0006, 0007) authored in two days, mostly reactive to the sweep;
  ADR-0003 (portability) is the one written proactively, with no adopter yet.
  No test suite exists at this point (named candidly in the handoff).
- **2026-04-26** — monorepo formed; git history begins here (pre-history not
  recoverable via `git log`).
- **2026-04-27** — de-branding pass begins.
- **2026-04-28→30** — v1.0.0 scope frozen and shipped on schedule (planned,
  not reactive).
- **2026-05-02→08** — v1.0→v1.1 cycle: theming substrate, magic-literals
  audit, resource-ownership audit, cards-tab merge, forest-directory
  redesign, first test suites land.
- **2026-05-14/15** — popover pattern-imitation bug; ADR-0002 Rule 7
  half-names the classification principle, flags itself as provisional.
- **2026-05-17** — ADR-0008 (classification discipline), reactive to three
  named postmortems.
- **2026-05-27** — ad-hoc perf firefighting on a shipped-without-profile
  refactor; ADR-0009 (perf investigation discipline) same day.
- **2026-05-29** — render-coupling postmortem written; tenet *proposed but
  not adopted*.
- **2026-05-31** — the same pattern recurs in a partially-hardened component;
  ADR-0010 (render locality) adopted same day, with the recurrence itself
  cited as the proof a description alone doesn't work.
- **2026-06-01** — RCA into a stringly-typed-error anti-pattern that shipped
  in the very first commit and was flagged ("Brittle in principle") at its
  first reparse site four weeks earlier without the flag stopping five more
  instances.
- **2026-06-10** — corpus-wide audit at 1,129 commits states the project's
  own thesis (L1: prose decays, mechanisms stick) as an empirically measured
  finding, not a slogan.
- **2026-06-11** — ADR-0011 (mechanization discipline): every discipline must
  declare its enforcement surface; recurrence converts to mechanism, with an
  explicit counter-rule (Rule 5) against gating judgment calls.

## 10. What this suggests for a fresh SPA starting today

The autoharn ledger-panel is a green-field SPA; omega's history is a paid
tuition bill, and it's worth reading which parts of that bill were
avoidable and which weren't.

**Worth having from day one (omega paid real cost to learn these; a fresh
project can skip the tuition):**

1. **Don't let type annotations aspirationally lie.** `readonly` marking
   fields that are actually mutated cost a ~124-error strict-mode reckoning
   months into the project. If a container is genuinely mutable, say so from
   the first commit; reserve immutability annotations for true value objects.
2. **Structure errors as data from the first throw site, not the sixth.**
   The stringly-typed-error anti-pattern in omega traces to the *very first
   commit*. A typed error class (`status`, `body` as real fields, not
   embedded in a message string) costs nothing extra to write the first
   time and is exactly the kind of decision that's cheap early and expensive
   to retrofit across N call sites later.
3. **Fail loudly by default, silent-by-exception (not the reverse).**
   Cheap to establish as a habit from the first API client and the first
   catch block; expensive to retrofit once six call sites have grown used to
   swallowing errors.
4. **Keep files small and single-purpose early.** Not because the numeric
   thresholds matter (omega's own postmortem admits its 60%/40% density
   numbers were never measured), but because the *practice* of splitting on
   sight avoids the specific hazard ADR-0004 exists to police — full-file
   rewrites under partial visibility silently breaking a prop contract the
   type-checker can't see. That hazard is present in any Vue/React/TS app
   from line one; there's no "too early" for it.
5. **If a second domain or a different consumer is even plausible, write
   the boundary down early — it's cheap insurance.** ADR-0003 is the one
   ADR omega got right *before* pain, and it paid off (a real fork showed up
   ~6 weeks later and the boundary held). This is the one case worth
   copying prophylactically rather than waiting for the RCA.

**Genuinely earned only after scale (omega's own record shows these firing
only once real recurrence or real profiling data existed — a fresh SPA
should NOT front-load them):**

1. **Classification discipline (ADR-0008)-style tenets, and mechanized
   enforcement of them.** These emerged from *specific, named, repeated*
   incidents (three postmortems, a measured 50% cast-justification
   conformance rate). Writing an abstract "verify vocabulary fit" rule
   before any vocabulary has actually drifted is exactly the kind of
   synthetic, fabricated-ahead-of-need process ADR-0008 itself would flag as
   a category error — there's no real vocabulary yet to misfit.
2. **A performance-investigation tenet with a canonical tool surface and
   metric vocabulary (ADR-0009).** This requires having already burned an
   ad-hoc investigation to know what a canonical one should look like
   (omega's own comparison report measured the ad-hoc method against the
   tooled one — that comparison couldn't exist before the ad-hoc pain
   happened). A green-field app has no hot paths yet worth a profiling
   discipline; premature profiling infrastructure is cargo cult.
3. **Render-locality rules for canvas-vs-DOM tradeoffs (ADR-0010).** This is
   scale-dependent by construction — the rule exists because a *specific*
   component crossed from "a few DOM nodes" to "hundreds of data points per
   render." Building the rule before any component approaches that scale is
   solving a problem that doesn't exist yet.
4. **Mechanization Discipline itself (ADR-0011) as a standalone up-front
   rule.** Its own Rule 5 warns against exactly this: gating judgment-shaped
   work prematurely produces "bungled compliance, strictly worse than
   missing compliance." The instinct "mechanize everything early" is the
   overcorrection ADR-0011 explicitly refuses to make. What *is* worth
   taking early is the weaker, cheaper precursor: when you write a
   discipline down, note in one line how (if at all) it's enforced, so the
   gap is visible from day one rather than discovered at the tenth
   violation.

The throughline, if there is one: omega's cheap lessons are almost all
"align a static claim (a type, a throw shape, an error boundary) with
reality from the start," which costs nothing extra when done first and a
lot when retrofitted. Its expensive lessons are almost all "build a
named, mechanized discipline in response to a *specific, measured*
recurrence" — and building those before the recurrence exists is not
foresight, it's the same closest-match/fabricated-category failure
ADR-0008 spent a whole tenet warning against.
