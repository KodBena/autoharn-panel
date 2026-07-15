# omega/frontend speed reap — don't-do's and nice patterns

Scout pass over the maintainer's private omega checkout's `frontend/` (`<redacted: local absolute path>`, Vue 3 SPA, ~gogui) plus its RCAs,
postmortems, ADRs. Purpose: feed the Vue rebuild of autoharn's panel SPA
(Postgres-backed append-only ledger — typed row lists, a commission-
decomposition view, a planned obligation AND-tree graph, SSE polling ~2s).
Every entry below is either **VERIFIED** (I read the actual RCA/postmortem/
commit worklog text cited) or **INFERRED** (reasonable extrapolation, no
direct textual confirmation). No entry here is unverified-and-unmarked.

Stack note for context: omega/frontend is Vue 3.5 + Vite 8 + Vitest, plain
`reactive()`/`computed()` module-scope store (no Pinia/Vuex, no router
dependency in package.json), ECharts for charts, no CSS framework. That
shape is close to what a ledger-viewer needs.

---

## Don't do these

### 1. A `v-memo` key that includes a value that churns across the whole list on one mutation
**VERIFIED** — `docs/notes/postmortem/postmortem-close-at-scale-tab-strip-2026-06.md`.
`SidebarWidget.vue`'s tab `v-for` keyed its per-item `v-memo` on
`[board, index, ...]`. Closing one board reindexes every later board, so
`index` changes for the whole remainder of the list, every memo busts at
once, and the full list re-renders synchronously. At 230 open boards this
was measured at 26,797 `BoardTab` renders across 230 closes (∑231…2).
**Cost:** initially misattributed as ~78% of close-phase CPU by count; a
later CPU profile corrected this (see #8) but the storm was still real and
worth killing. **Fix:** don't let a per-item memo key carry anything that
changes for items *other than the one that changed* — if a "position" label
is needed, source it from something reference-stable (a rank computed
outside the memoized key), not from the loop index.
**Transfers to our ledger:** any typed-row list keyed by a stable row id
(not array position) should never let a memo/key depend on position if rows
can be inserted/removed from the middle (ours is append-only, so this is
lower risk — but any future "recently updated" reordering would reintroduce it).

### 2. Per-item inline closures as event-handler props in a long `v-for`
**VERIFIED** — same postmortem, its "Correction" section (dated 2026-06-22,
supersedes the original diagnosis above). The *actual* dominant driver of
the close-storm was `@click="activate(board)"`-style handlers: each closes
over the loop item, so it is a **fresh function reference on every parent
render**, which makes Vue's `shouldUpdateComponent` see changed props and
re-render every item regardless of any memo. Measured fix: BoardTab emits
its own id and the parent binds **stable, module-scope handlers** →
26,797 renders collapsed to 463 (~1 per close).
**Cost:** this, not the `v-memo` key, was the load-bearing defect; the team's
own first diagnosis was wrong and had to be corrected by measurement.
**Transfers directly:** any row component in our list view must not receive
`@click="fn(row)"` inline — bind a stable handler and pass the id as a prop,
or use event delegation on the list container.

### 3. Ranking or attributing perf cost without a CPU profile — structural/count-based inference is unreliable
**VERIFIED** — same postmortem: three wrong rankings in a row on the same
investigation (78%-from-render-count, then "the deep watch is #1", both
falsified by a real V8 CPU profile which found the true cost was a
`boardsById`-driven O(N²) reactive-get storm in a *different* function).
Quote: *"category-level attribution (Scripting vs Layout) was too coarse...
measure it, do not reason it."*
**Transfers:** if we ever chase a perf regression in the ledger view, get a
real CPU/flame profile before naming a root cause — a plausible story from
render counts or watcher topology can be confidently wrong.

### 4. Reading a high-frequency reactive value inside a composition/orchestration component's render
**VERIFIED** — `docs/notes/postmortem/postmortem-render-coupling-at-composition-nodes-2026-05-29.md`
and ADR-0010 Rule 2. `App.vue` (composition root) read per-navigation cursor
fields and per-tick engine metrics directly, so *any* update to those
re-rendered the entire app subtree. Recurred a second time (`TreeWidget`)
days after being named, because the fix used `v-memo` / pulled an element
out of a `v-for` — which fixes the **patch**, not the **render**: Vue
re-runs a component's whole render function on any reactive read that
component made, wherever in the template it sits. Measured: `TreeWidget`
render was 762ms/24% self-time in one profile with `patch` at only 60ms —
the "render ≫ patch" ratio is literally the diagnostic signature of this bug.
**Fix that actually worked:** stop the composition node's render from reading
the value at all — either an accessor (`() => T`) passed to leaf components
so the subscription is established only where it's *invoked*, or an
imperative escape (a plain `ref`, updated in a `watch`, never read in the
template).
**Transfers directly:** our AND-tree graph view and the commission-
decomposition view are exactly the shape at risk — an orchestrating
container component must not read the live/streaming obligation state
itself; only the leaf nodes that display it should.

### 5. Rendering data-dense fixed-size visuals as one DOM/SVG node per data point
**VERIFIED** — ADR-0010 Rule 1, `docs/worklog/2026-05-31-perf-boardtab-rugplot-canvas.md`,
`...-timeline-rugplot-canvas.md`. A ~340-move rugplot shipped as one
`<div>` per move (plus a per-slice i18n tooltip string built every render);
measured at 782ms/render, the single most expensive component in a
combined-stress profile. Each slice rendered at sub-pixel width — the
per-element DOM granularity bought nothing perceptible.
**Fix:** draw on `<canvas>` imperatively in a `watch`, off the render path.
**Transfers:** if the ledger view ever gets a dense visual summary (a
sparkline of ledger activity, a heat-strip of obligation states over time),
default to canvas once element count crosses roughly "more elements than
visible pixels," not DOM/SVG per row.

### 6. An unvirtualized list that renders every item regardless of what's on screen
**VERIFIED** — same postmortem, Findings 2 and the correction's item 4. At
230 open board tabs, all ~800 DOM nodes/tab were live simultaneously (~185k
nodes peak) even before any close; this is what made the close-storm's
per-close cost scale with total open count rather than visible count, and
what made GC-lag masquerade as a "leak" (large DOM/listener counts that
took a while to reclaim under a tight synchronous loop, confirmed non-leak
by a forced-GC heap test with flat tail-slope). **Fix:** virtualize the tab
strip so only the visible slice renders; measured drop in that close
long-task from 17.1s → 8.3s at 230 boards.
**Transfers directly:** our ledger is an append-only list that can grow
unboundedly over a session — list virtualization (windowed rendering) is
close to load-bearing for this exact shape, not an optional nicety.

### 7. Flex-child scroll containers without `min-height: 0`, and scroll-anchoring left on for a virtualized window
**VERIFIED** — same postmortem's correction item 4, confirmed present in
`frontend/src/components/chrome/SidebarWidget.vue` (`min-height: 0` comment
at line ~240, `overflow-anchor: none` at ~251). A flex item defaults to
`min-height: auto`, which lets it size to fit *all* content — defeating a
virtualized window's whole point (the container silently grows to hold every
item's height instead of clipping to the visible slice) — no error, layout
just doesn't clip. Separately, browser scroll-anchoring interacted badly with
a virtualized window's height changes and pinned a renderer at 99% CPU in a
feedback loop.
**Fix:** `min-height: 0` on the flex scroll container; `overflow-anchor: none`
on the virtualized viewport.
**Transfers directly:** if the ledger row list uses `flex: 1` inside a flex
column layout (a common panel-SPA shape) and gets virtualized, this is the
exact footgun to check for on day one, not after a profiler catches it.

### 8. A hand-maintained lookup cache (dictionary) kept in sync at every mutation site
**VERIFIED (as considered-and-rejected)** — `docs/worklog/2026-05-27-perf-fix2-boards-by-id-lookup.md`.
The O(N²) `store.boards.find(b => b.id === boardId)` per-consumer lookup was
fixed not by hand-maintaining a `Record<id, Board>` synced at every mutation
site (add/remove/replace — 5-6 call sites that would each need to remember
to update it), but by a **derived `computed()`** that rebuilds from the
source array whenever it's read after invalidation. The derived form has no
staleness-discipline to police; the hand-synced form does, silently, forever.
**Transfers directly:** if we build an id→row lookup for the ledger, prefer
a derived computed over a hand-maintained map, unless profiling shows the
O(N) rebuild-per-mutation itself is the bottleneck (it wasn't here).

### 9. Sub-15-second scale in the perf test battery, when the real regime is "hundreds of rows over a session"
**VERIFIED** — same close-at-scale postmortem, §5.2: the standing perf
battery topped out at 16 boards, explicitly validated "no regression" there,
and every net in the codebase (the render-count harness, ADR-0009's render÷
patch signature, the jank-extended study) was blind to an O(N²) cost that is
negligible at N=16 and a 37.8s wall-clock cost at N=230. Nothing was
dishonest — the battery just never varied N, only frequency at fixed small N.
**Transfers directly:** our ledger is unbounded over a session's life — any
perf harness we build must vary "how many rows exist," not just "how fast
do SSE updates arrive," or we'll ship the omega team's exact blind spot.

---

## Nice patterns

### 1. rAF-coalesce high-frequency input: "cancel the pending frame, keep only the latest"
**VERIFIED** — `docs/worklog/2026-05-27-perf-fix1-raf-coalesce-keydown.md`,
mirroring an existing wheel-handler pattern in `useScopedScroll.ts`. Each new
event of a coalesced class replaces a pending value and reschedules a single
`requestAnimationFrame`; a synchronous subset (things that must have a
determinate one-press-one-effect, like toggles, or things needing
`preventDefault` before the frame) stays outside the coalesce. Paired with an
`onUnmounted` cancel of any in-flight `rafId`.
**Vue-ledger shape:** if SSE delivers many small deltas in a burst, apply
this to the *repaint*, not the data ingestion — ingest every delta into the
store immediately (cheap), but coalesce the *reactive-read-triggering*
re-render trigger to one rAF tick. Keeps back-pressure without dropping data.

### 2. Derived `computed()` lookup maps instead of hand-synced caches
**VERIFIED** — `docs/worklog/2026-05-27-perf-fix2-boards-by-id-lookup.md`
(see Don't-do #8's flip side). `boardsById` is a `computed` sibling export
next to the store's other derived values; consumers get O(1) lookup, the
store never has to remember to keep a cache in sync.
**Vue-ledger shape:** an `obligationById` / `rowById` computed map alongside
the raw append-only array is the natural analog — cheap to add, no
mutation-site discipline required.

### 3. The imperative-escape idiom for anything read at high frequency: static ref + `watch()` writes the DOM/canvas directly, never read in the template
**VERIFIED** — ADR-0010 Rule 2 + its corollary, worked in
`2026-05-31-perf-treewidget-render-decouple.md` (an active-node ring moved
from a template-bound `<circle v-if>` to a static `<circle ref>` whose
`cx`/`cy`/`display` are set inside `watch(activeRingPos, ...)`) and the
canvas rugplot worklogs. The rule of thumb stated verbatim in the ADR: *"a
component reads a high-frequency reactive value only if its own job is to
display it"* — composition/chrome nodes should not read it at all; leaves
self-source, either via an accessor function passed down or via this
imperative escape. Always paired with `onUnmounted` releasing any
`ResizeObserver`/listener the escape registered.
**Vue-ledger shape:** this is very directly the pattern for a live-updating
AND-tree graph — the graph-layout/orchestrating component should not read
per-node obligation state; a leaf node component (or an imperative
canvas/SVG-attribute writer) should own that read.

### 4. Incremental accumulator with an explicit equivalence test against the full rebuild
**VERIFIED** — `docs/worklog/2026-05-31-perf-incremental-enriched-projection.md`.
Replaced an O(N)-per-frame full re-derive with an O(1)-per-packet patch
accumulator (`rebuild()` full / `patchNode()` incremental), backed by a
Vitest suite asserting `patchNode`-sequence ≡ `rebuild()` across overlaps,
window shifts, purges, and interleaved streams (9 cases). The team explicitly
chose this over a throttle specifically because a throttle introduces a
`shown ≤ live` asymmetry guarded only by an unenforceable convention,
whereas the incremental accumulator keeps the projection *exactly* live at
the cost of one *local, testable* invariant.
**Vue-ledger shape:** the commission-decomposition view and any derived
roll-up (counts by status, obligation-tree aggregates) over an append-only
ledger is exactly this shape — an O(1)-per-new-row patch function with an
equivalence test against "recompute everything from scratch," rather than a
throttle on the recompute.

### 5. Fingerprint/dedup guard on a watcher before triggering expensive re-derivation
**VERIFIED** — `docs/worklog/2026-05-27-perf-fix3-pv-hover-watch-guard.md`.
A `watch()` on a frequently-arriving stream computed a cheap structural
fingerprint of the *meaningful* fields and short-circuited when unchanged,
avoiding an animation/render restart on every no-op packet arrival — without
changing the watched composable's own API.
**Vue-ledger shape:** if SSE re-delivers a row whose displayed fields are
unchanged (e.g. a heartbeat/keepalive style refresh), fingerprint-compare
before triggering any re-render-inducing state write.

### 6. Two-tier version signals: "set changed" vs. "content changed," so composables reconcile cheaply
**VERIFIED** — `docs/worklog/2026-05-27-perf-fix4-per-board-watchers.md`.
`boardsSetVersion` bumps only on add/remove/replace of the *collection*, kept
deliberately separate from per-item content mutation signals. Composables
subscribe to the set-version and diff their own per-item watcher maps against
it (teardown removed ids, set up new ones) — an O(N) reconcile on the rare
set-change event, and zero per-item-mutation cost otherwise.
**Vue-ledger shape:** directly applicable — a `rowSetVersion` (bumped only
when a row is appended, never on an in-place status update) lets any
per-row composable (auto-scroll-to-new, unread-count, etc.) reconcile
cheaply without re-scanning on every field update.

### 7. A named, closed vocabulary + explicit substantiation discipline for perf claims
**VERIFIED** — ADR-0009 in full. Every "this is faster" / "this regressed" /
"no change" claim either carries a captured before/after profile reference
(a path + timestamp + gzipped size, profiles kept out of the repo,
user-local) or an explicit "unsubstantiated" tag naming the speculative win
and the cost. Canonical metric vocabulary: per-handler p50/p90/p99, LongTask
count+duration, GC minor/major, and — the one most worth lifting verbatim —
**component `render`÷`patch` ratio, where render≫patch is the render-coupling
tell** (ranking by `render` alone hid the #1 cost in this codebase's own
history for most of one arc). A structural/O(N)→O(1) change that's provably
faster by inspection is explicitly exempted from needing a captured profile.
**Vue-ledger shape:** cheap to adopt wholesale as a project norm — it costs
one sentence per perf claim ("speculative, structurally sound, not measured"
vs. "measured, before/after attached") and prevents the exact
count-based-inference trap in Don't-do #3.

### 8. Vanilla `reactive()` + `computed()` module-scope store, no state-management library
**INFERRED as a positive** (package.json has no Pinia/Vuex/Redux; the store
worklogs above show a plain `reactive()` object with `computed` exports and
composables owning their own watcher lifecycles) — the codebase reads as
choosing to keep the dependency surface minimal at this scale rather than
adopting a framework store up front. No RCA argues for this explicitly, so
it's inference from the evidence, not a documented decision.
**Vue-ledger shape:** for a single-page, single-store panel app (our shape:
one ledger, no multi-page routing complexity), a plain reactive store
module is a reasonable starting point before reaching for Pinia — revisit
only if devtools time-travel/persistence plugins become genuinely wanted.

---

## The one honest sentence

The single most load-bearing explanation for the felt speed: omega's team
repeatedly measured (not guessed) exactly which reactive reads were coupling
a whole subtree's render to a high-frequency data stream, and replaced each
one with an imperative-escape or accessor so per-interaction JS work
approaches zero on the paths a user actually feels — everything else
(canvas for dense visuals, incremental accumulators, rAF coalescing) is the
same idea applied to a different symptom of the same disease.
