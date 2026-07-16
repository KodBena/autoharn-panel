# Consult: SPA professionalism audit vs. SAP/Oracle-class enterprise software — cycle 3

This document records a third, independent, single-agent review of this repo's own web panel, run
after cycle 2's 5 work items (fixing the deficiencies
[the cycle-2 consult](../2026-07-16-spa-professionalism-audit-cycle2/2026-07-16-spa-professionalism-audit-cycle2.md)
identified) had all shipped, per [CLAUDE.md](../../CLAUDE.md)'s ADR-0005 instance-bindings rule
("Consult / decision records ... live under `docs/consults/`").

- **Date:** 2026-07-16
- **Commissioned via:** ledger row 514 (`./led show 514`), the maintainer's instruction to continue
  the fix-point iteration and start a cycle-3 scout while a separate ledger-hygiene question was
  being resolved.
- **Method:** one deliberately unbiased general-purpose subagent, Playwright (headless Chromium)
  against the live deployment, running in `PANEL_READONLY` (locked) mode, after all 5 cycle-2 work
  items had shipped. The agent was explicitly told not to read this project's ledger, git log, or
  `docs/consults/` directory before or during its audit, so as to draw conclusions fresh rather than
  from a briefed findings list.
- **Recorded finding:** ledger row 529 (`./led show 529`) — a paraphrase pointing at this file as the
  durable record.
- **Work item:** `spa-professionalism-cycle-3-scout` (row 518), closed shipped (row:530). Note: the
  close's own `work_witness` field literally reads `row:525`, a mis-citation guessed before row 529
  existed — disclosed in ledger row 531/532 rather than corrected in place (a closed `work_closed`
  row cannot be edited, and superseding it to fix a citation would needlessly re-open review debt).
  The correct witness is row:529.
- **Raw evidence:** the agent's own screenshots/scripts were produced in its own sandboxed
  environment and were not retrieved into this repo; this file reproduces its full final report
  verbatim, per the same convention cycle 2's consult file used.

This is the agent's own final report, reproduced **verbatim** ([ADR-0005 Rule 9](../../law/adr/0005-documentation-discipline.md)
— a commissioned review's report is recorded verbatim, never paraphrased into a lossier summary).
No wording below has been altered from what the dispatched agent actually returned; only this
surrounding provenance section is the orchestrating session's own words.

---

# Professionalism / UX Audit — autoharn-panel Ledger SPA

**Auditor**: independent, fresh-context review (no prior audit history consulted)
**Target**: `http://127.0.0.1:8420/` (bound `0.0.0.0:8420`), confirmed live via `GET /api/health` → `PANEL_READONLY=locked`, schema `experience/experience_kernel`, ~524 ledger rows at time of audit
**Method**: Headless Chromium via Playwright (`/tmp/panel-verify` node_modules, reused for this session), scripted exploration of all 6 tabs (Recent ledger, Profiles, Commission decomposition, Work items, Review gap, Questions), the `/item/:id` deep-link view, filter/search/sort controls, direct API calls, a 600px-viewport responsive pass, and console/network monitoring throughout.

---

## Ranked Findings

### CRITICAL

**1. The virtualized row list renders as completely unreadable, overlapping garbage above 200 rows — a hard, sharply reproducible layout break.**

- **Repro**: On the "Recent ledger" tab, set the `limit:` field to any value **≥ 201** (e.g., 201, 250, 300, 999999). At `limit=200` the table renders cleanly (verified, screenshot `thresh-limit-200.png`). At `limit=201` the exact same UI instantly renders every row's text overlapping the row above/below it — timestamps, statements, and "click to expand" affordances all interleave into illegible text soup (screenshots `thresh-limit-201.png`, `edge-limit-300.png`, `edge-limit-999999.png`). The underlying API call (`GET /api/rows?...limit=999999...`) returns a perfectly good `200` with correct row data — this is a pure front-end rendering defect in whatever virtualization kicks in above the row-count threshold, not a data problem.
- **Why it matters**: This isn't an edge case a user has to go looking for — it's one text-field edit away from the default view (raise "limit" from 200 to 201) on the single most-used tab in the app. For a ledger panel whose entire purpose is "render an append-only ledger you can scan," a broken virtualized-scroll mode above 200 rows is disqualifying at an SAP/Oracle bar: those platforms handle grids with tens of thousands of rows without visual corruption. No console error or exception accompanies it (confirmed via `pageerror`/`console` listeners), meaning this will not even surface in error monitoring — it will simply look broken to whoever hits it.
- **Where to look**: whatever virtualization mechanism gates on row count in the Recent-ledger table component (per the repo's own stated design goal of "virtualization above 200 rows") is either not measuring/positioning rows correctly, or a fixed-height/absolute-position assumption is wrong for this dataset's variable statement lengths.

**2. A negative `limit` value crashes the API with an unhandled `500 Internal Server Error` instead of a validated `400`.**

- **Repro**: On "Recent ledger," type `-5` into the `limit:` field (the number input carries `min="1"` in markup, but nothing in the live-query path calls `checkValidity()` before firing the fetch, so a keyboard-typed negative value still reaches the backend unvalidated). Network capture: `GET /api/rows?...limit=-5&offset=0` → `500`, body literally `Internal Server Error` (no JSON, no detail). The front end degrades reasonably here — it shows a banner and keeps the last-good rows visible underneath rather than crashing (screenshot `edge-limit-neg5.png`) — but the backend itself has no input validation on `limit`, so a negative value evidently reaches the SQL layer unguarded and throws.
- **Why it matters**: An enterprise-grade API never lets user-controllable numeric input reach the query layer unvalidated; a raw, unstructured `500` (as opposed to a typed `400` with a field-level message) is the textbook definition of an unhandled fault. `min="1"` in markup gives a false sense of protection — it doesn't gate the actual AJAX trigger.

### SERIOUS

**3. No tab has a URL — only the item-detail view is a real deep link. Reloading the page (or sharing a link) always discards whatever tab you were on and drops you back to "Recent ledger."**

- **Repro**: Click "Work items," confirm the tab is now active and its content (slug/state/claimant table) is showing. Call `page.reload()` (equivalent to hitting the browser refresh button). Result: the app reloads to the "Recent ledger" tab every time (screenshot `dl-01-after-reload.png` — table columns are ID/KIND/ACTOR/STATEMENT, i.e., Recent Ledger, not Work Items), with the address bar unchanged (`http://127.0.0.1:8420/`). Confirmed via source inspection (`frontend/src/router.ts`): the *only* registered vue-router route besides `/` is `/item/:id`; the five other tabs are pure in-memory component state, never reflected in the URL. In-app navigation (clicking a `row:NNN` citation, then browser Back) does preserve tab state because it never leaves the mounted SPA instance — but any real page load (refresh, bookmark, shared link, address-bar retype) always lands on "Recent ledger," silently, with no indication anything was lost.
- **Why it matters**: this is precisely the scenario the task was asked to test ("deep links via direct navigation/reload, not just in-app clicks"), and it fails for 5 of the app's 6 views. Enterprise ledger/audit tools are used by people who bookmark a specific queue ("Review gap," "Work items filtered to open") and send that link to a colleague, or refresh mid-session without losing place. None of that works here outside the one `/item/:id` view.

**4. Any unrecognized path silently renders the full normal app shell with a `200` — there is no reachable "this address doesn't exist" state for arbitrary bad URLs, and the wrong address bar persists.**

- **Repro**: Navigate directly to `http://127.0.0.1:8420/some/bogus/deep/path`. Server responds `200` (SPA history-fallback, expected), but the client also just renders the default tab UI with no error, no redirect to `/`, and no visual cue the URL is bogus (screenshot `dl-02-bogus-path.png`). Source confirms why: `App.vue`'s only route branch is `isItemRoute = route.path.startsWith('/item/')` — literally everything else, valid or not, falls through to the same normal tab UI. This is different from, and weaker than, `/item/999999999` (a numeric but nonexistent row id), which *does* show a proper, well-designed "no such row" empty state (screenshot `item-02-invalid-id.png`) — so the app clearly has the *pattern* for a good not-found state, it's just not applied to the path level.
- **Why it matters**: a stale bookmark, a typo'd URL, or a link copied with a trailing path segment all look identical to the working app — no signal to the user or to monitoring that they're on a dead URL. This is a lesser variant of finding 3 (both stem from having only one real route), but distinct enough to call out separately since it's about wrong URLs rather than losing state on a right one.

### MODERATE

**5. Tab buttons carry no ARIA tab semantics — no `role="tab"`/`role="tablist"`, no `aria-selected`.**

- **Repro**: Evaluated all 6 tab-bar buttons via `document.querySelectorAll('button')` — every one returns `role: null`, `ariaSelected: null`. They are plain `<button>` elements distinguished only by CSS (visually: white background + bold text for the active tab). Keyboard tab order (`tabIndex: 0`) works, so keyboard users can reach and activate them, but a screen reader gets no signal about which of the six is currently selected, nor that they form a tab group at all.
- **Why it matters**: WCAG/ARIA Authoring Practices expect `tablist`/`tab`/`tabpanel` roles with `aria-selected` for exactly this pattern; an SAP/Oracle-class product audited for accessibility compliance would flag this immediately. Low effort to fix (a few ARIA attributes), meaningfully impacts screen-reader users.

**6. `limit=0` silently returns zero rows with a generic empty-state message, indistinguishable in tone from a genuine "no matches" filter result.**

- **Repro**: Set `limit:` to `0` → API returns `200` with `[]`, UI shows "No ledger rows match..." (same wording family as a real empty-filter result). Technically correct REST semantics (`limit=0` → 0 rows), but nothing in the UI hints that the *reason* is the limit field itself rather than the kind/actor/date filters — a user who fat-fingers the limit field into `0` has no clue why their normally-populated ledger view suddenly looks empty.
- **Why it matters**: minor confusion multiplier, but worth a friendlier micro-copy ("limit is set to 0 — increase it to see rows") given how easy this is to trigger by accident (the same input field the negative-value and 201-row bugs live in).

### MINOR

**7. Commission-decomposition default selection (commission #1) shows "0 item(s)" and an empty decomposition list, with no visual cue pointing the user toward the two commissions (of 15) that actually have items (#434, #514).**

- Not a defect in rendering — this reflects a genuinely sparse dataset (13 of 15 commissions have zero decomposed items) — but the dropdown's own label format (`#1 — 0 item(s) — ...`) is the only signal; there's no "jump to a commission that has items" affordability, and a first-time user landing on an empty default screen could reasonably conclude the feature is broken rather than the data being sparse. Consider defaulting the selector to the most-recently-active or highest-item-count commission instead of the numerically-first one.

---

## What already meets a professional bar (do not regress)

- **Read-only lock discipline**: the "read-only (locked)" badge with a hover tooltip explaining *why* (`PANEL_READONLY` vs no-write-conduit) is exactly the kind of honest, precise status communication enterprise tools often get wrong. Every write affordance (co-sign buttons) is genuinely disabled with an inline explanation, not just cosmetically hidden.
- **Empty states are well-designed where they exist**: Profiles ("No profiles configured"), Review gaps ("No review gaps — every countersign obligation is currently discharged"), Work items filtered-to-nothing ("No work items match this filter"), and the `/item/<nonexistent-id>` view (full obligation/co-sign panel structure preserved, just correctly disabled/empty) are all clear, calm, on-brand, and structurally consistent — no raw JSON dumps, no blank white screens.
- **Input validation messaging on the item route**: `/item/abc-not-a-number` returns a clean `'abc-not-a-number' is not a valid row id.` message rather than a stack trace or blank page.
- **Search/filter correctness**: Work items search-by-slug-or-title, state filter, and Recent-ledger kind filter all behave correctly under normal and bogus-term inputs (verified empty and populated cases), with results updating without page reload and no console errors.
- **Truncation UX**: long ledger statements truncate by default with an explicit, discoverable "click a row to expand or collapse" affordability and character counts — a genuinely good design decision for a dense append-only ledger.
- **Responsive layout (600px)**: every tab reflows cleanly into a stacked-card layout at a narrow viewport with zero horizontal scroll (`document.documentElement.scrollWidth` checked programmatically across all 5 tabs) — this is done properly already, unlike the desktop virtualization bug.
- **Citations as real links**: `row:NNN` references inside statements render as working `<a href="/item/NNN">` anchors (not plain text), and clicking one navigates correctly and doesn't double-fire the row's own expand/collapse toggle.
- **SSE stability**: monitored 12 seconds idle post-load — one clean `200` on `/api/events`, zero console noise, no reconnect storm.
- **Console cleanliness under normal use**: zero console errors/warnings/pageerrors across the entire ordinary click-through of all six tabs, filters, and citations — errors only appeared when I deliberately hit nonexistent API paths or malformed input, which is the correct behavior.
- **Labeled form controls**: every filter input on Recent Ledger has a properly associated `<label for=...>` (kind, actor, since, until, limit) — accessible by label-click and screen reader, a detail many internal tools skip.

---

## Self-reported tool-use summary

*(self-reported by the subagent; no independent harness verification of these counts)*

- Bash tool calls: ~20 (environment discovery, Playwright scripting/execution, curl checks)
- Read tool calls: ~14 (screenshots + `router.ts`/`App.vue` source snippets)
- Edit tool calls: 1 (fixing `waitUntil: networkidle` → `load` after the SSE-induced timeout)
- Write tool calls: 2 (audit scripts)
- No Agent/Task delegation was used — this audit was performed directly in-session via scripted Playwright driven through Bash, since no Playwright MCP tool was available in this environment.
- Approximate total tool invocations this session: ~40.
- Total subagent tokens (self-reported): 99,071. Tool uses: 50. Duration: ~695s.
