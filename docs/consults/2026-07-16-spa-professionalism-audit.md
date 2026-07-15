# Consult: SPA professionalism audit vs. SAP/Oracle-class enterprise software

This document records an independent, single-agent review of this repo's own web panel (the
Vue SPA served by `backend/`), judged against the bar of professional enterprise management
software (Oracle Enterprise Manager / SAP / Datadog class) rather than "does it technically
work." It is read by anyone deciding whether the panel is ready to show to a stakeholder, or
picking the next UI defect to fix. The following records this consult's own provenance and
method:

- **Date:** 2026-07-16
- **Commissioned via:** ledger row 183 (a `commission`-kind row on this deployment's own
  Postgres decision ledger, read via `./led show 183`)
- **Method:** one deliberately un-led Sonnet subagent, Playwright (headless Chromium) against
  the live deployment at `http://192.168.122.68:8420/`, running in `PANEL_READONLY` mode (a
  startup-only safety override that forces the deployment read-only regardless of whether a
  write conduit is configured — see [README.md](../../README.md)'s config table)
- **Recorded finding:** ledger row 189
- **Work item:** `spa-professionalism-audit` (closed shipped, witness row 189, review row 192,
  independence `technical` — one of this project's countersign-independence grades, see
  [CLAUDE.md](../../CLAUDE.md) point 3)
- **Brief given to the agent:** judge the app against a professional/enterprise management-
  console bar (Oracle Enterprise Manager / SAP / Datadog class), not "does it work." Two
  optional, explicitly disregardable pieces of context were given (the commissioner's — this
  project's maintainer, in his commissioning role, see [CLAUDE.md](../../CLAUDE.md) point 11 —
  own complaints about "Recent ledger" length and unresolved internal vocabulary) — the agent
  was told to reach its own conclusions, not treat them as a checklist.

This is the agent's report, reproduced verbatim
([ADR-0005 Rule 9](../../law/adr/0005-documentation-discipline.md) — a commissioned review's
report is recorded verbatim, never paraphrased into a lossier summary). Only link markup and
path corrections below have been added on top of the agent's original wording, per an A:B:C
fresh-context legibility pass ([law/adr/0017-the-zero-context-reader.md](../../law/adr/0017-the-zero-context-reader.md));
none of the agent's own claims were altered.

---

## Assessment: autoharn-panel SPA vs. professional/enterprise bar

**Method**: I drove all six tabs (Recent ledger, Profiles, Commission decomposition, Work items, Review gap, Questions) using Playwright (headless Chromium) against the live read-only deployment at `http://192.168.122.68:8420/`, and I exercised the API directly (`/api/health`, `/api/rows`, `/api/commissions`, `/api/ledger/recent`, `/api/rows/facet-counts`), filter/toggle/limit controls, a deep-link probe (`/item/1`), and three viewport widths (1440/768/390px). Screenshots saved under the scratchpad `shots/` directory (an ephemeral, session-local path, not part of this repo). I grounded this assessment in the sibling autoharn checkout's own `` `README.md` `` and `` `design/Autoharn.idr` `` (both live outside this repository, at `/home/bork/w/vdc/1/experience/autoharn/`, not as in-repo links), and in this repo's own [`README.md`](../../README.md)/[`SPEC.md`](../../SPEC.md), before judging.

### 1. The flagship view is silently non-functional against this deployment's real data (most serious finding)

"Commission decomposition" is the one view the sibling autoharn checkout's own README (not this repo's) calls out by name ("a commission-decomposition view"), and [`SPEC.md`](../../SPEC.md) calls it P0. I selected all 7 commissions in the dropdown (`#1, #14, #48, #130, #141, #177, #183`) — **every single one reports "0 item(s)"** and "No decomposition items authored for this commission yet," even for commission `#48`, which the Work Items tab shows has 13 real, shipped work items referencing it (`--refs row:48`): `panel-profile-storage`, `panel-readonly-lock`, `panel-profiles-management-ui`, etc.

Root cause, confirmed by reading [`backend/extensions/autoharn/ledger_read.py`](../../backend/extensions/autoharn/ledger_read.py): this view only recognizes a specific `panel-item:<commission_row>:<item_id>` token grammar (`_PANEL_ITEM_TOKEN_RE`), a PoC-era convention. But this deployment's actual, documented operating discipline (this repo's own [`CLAUDE.md`](../../CLAUDE.md) point 1: `./led work open <slug> <title> --refs row:<commission-id>`) never emits that token — it uses plain `work_opened`/`work_claimed`/`work_closed` rows with a bare `--refs row:N`. The result: the headline view and the deployment's real workflow have silently diverged, and the UI gives no warning that it's looking for the wrong shape of data — it just reports zero progress on commissions that in fact have extensive, shipped work against them. An executive glancing at this view would conclude nothing has happened on a commission that is substantially complete. This is exactly the kind of silent-wrong-answer a management console must never produce (contrast: Oracle Enterprise Manager or Datadog would either find the data under the convention actually in use, or loudly flag "no items match the expected schema" rather than a clean, plausible-looking empty state).

### 2. "Recent ledger" is the commissioner's complaint, and it's worse than it sounds

At only 185 total ledger rows (`/api/watermark` → `count: 185`), the default view (limit 200, no superseded) renders **173 `<tr>` rows in one flat, unpaginated table**, and the full page is **48,198 pixels tall** (measured via full-page screenshot). Each row's `STATEMENT` cell has no truncation (by design — [`SPEC.md`](../../SPEC.md)'s no-elision rule is honestly followed: `overflow: visible`, `text-overflow: clip`, full word-wrap) but that means a single decision row like id `187` wraps to ~14 lines by itself. At 1440px wide, the four metadata columns (ID/KIND/ACTOR/TS) together occupy roughly 15% of the row width, so most of a very tall page is one column of prose.

There is virtualization code (`@tanstack/vue-virtual`, threshold `VIRTUALIZE_ABOVE = 200`) sitting ready in [`frontend/src/core/components/DataTable.vue`](../../frontend/src/core/components/DataTable.vue), but the ledger hasn't crossed 200 rows yet, so it's currently dormant — and virtualization only fixes render cost, not navigability. There is no pagination, no "jump to row/date," no sort-by-column (headers are static `<th>` text, unclickable), no date-range or actor facet ([`SPEC.md`](../../SPEC.md) §2.1 promises kind/actor/state/independence/date-range/free-text facets; only a kind filter and a superseded-rows toggle exist today). An operator wanting "what happened last Tuesday" or "everything actor X wrote" has no tool but scrolling and Ctrl-F. This confirms the "extremely long, hard-to-navigate list" complaint concretely, and shows it will only get worse as the ledger crosses the 200-row virtualization threshold with no compensating navigation aids.

### 3. Internal vocabulary leaks into the UI with zero resolution mechanism, everywhere

I grepped the rendered page text and found `s28, s29, s30, s31, s32, s33, s34, s35` (kernel-generation identifiers), `ADR-`, `discharge_grade`, `blocks-close`, and similar internal shorthand appearing verbatim in statement text with no glossary, tooltip, or link-out. I then grepped the entire frontend source for `glossary`/`tooltip`/`title="` — **there is no such mechanism anywhere in the codebase.** Every internal term a ledger author happens to type (a work-item slug, a kernel generation, an ADR number) is presented to whoever opens this panel exactly as raw as it was written, with no resolution path short of asking the author. This is exactly the commissioner's second complaint, and it's structural, not incidental — nothing in the architecture even attempts to bridge it.

Compounding this: the "kind:" filter on Recent ledger is a **blind free-text input**, not a dropdown or autocomplete drawing from the live kind vocabulary the backend already knows (`/api/rows/facet-counts` returns the exact list: `work_closed, commission, finding, work_claimed, note, decision, assumption, review, snag, work_depends_on, verification, work_opened`). Typing an unrecognized string (I tried `not_a_real_kind`) silently returns "No ledger rows match this filter" — correct behavior, but it means an operator has to already know the internal enum spelling to use the one facet control that exists. A dropdown populated from the live vocabulary (which the backend already serves) would cost little and directly close this gap.

### 4. Promised cross-cutting features are not built: no hover synopsis, no item view, no ref links

[`SPEC.md`](../../SPEC.md) lists "hover synopsis everywhere" and "every row reference anywhere renders as a link with a hover card" as P0. I checked: statements containing `--refs row:14`, `row:143`, `row:183` etc. render as **plain text inside `<td>`**, not `<a>` elements — zero clickable ref links found anywhere (`document.querySelectorAll('a')` matching `row:` returned none). I also probed the deep-link the spec promises (`/item/<row-id>`) directly: `GET /item/1` returns **HTTP 404** — there is no item view at all yet. This matches this repo's own [`README.md`](../../README.md) ("the item view (sec 2.2), obligation-tree graph (sec 2.3)... remain unbuilt"), so it's an honestly-disclosed gap rather than a bug, but it means the panel cannot yet do the one thing that would make it professional-grade for someone tracing "what does row 48 actually say" from any of the citations littering every other view — you have to go back to Recent ledger, set the kind filter, and scroll/read to find it.

### 5. Live-update UX has no affordance and can move content under the reader

[`frontend/src/core/composables/useLiveUpdates.ts`](../../frontend/src/core/composables/useLiveUpdates.ts) is architecturally sound (single SSE connection with watermark-poll fallback, rAF-coalesced), but on any ledger change it silently triggers a full refetch-and-rerender of whatever table is open (`watch(tick, load)` in [`frontend/src/core/components/LedgerTab.vue`](../../frontend/src/core/components/LedgerTab.vue)) — no toast, no "3 new rows, click to load," no highlighting of what changed, no `aria-live` region (confirmed absent via grep). On a long, ungrouped Recent ledger list, a background write during a co-signing review session could shift the exact row the operator is reading. Datadog/Oracle-class consoles pause auto-refresh under active reading or show a discrete "new data available" banner; this app has neither.

### What already meets the bar

- **Correctness of what is implemented is solid.** Kind filter, superseded toggle, and row-limit control all produced results matching the backend's own facet counts exactly, in every combination I tried (bogus kind → 0 rows with a clean message; `kind=decision` → 49, matching `/api/rows/facet-counts`; toggling superseded → 173→185, exactly the delta). No console errors, no failed requests, in any of the six tabs.
- **The no-elision discipline is genuinely honored**, not just claimed — I inspected computed CSS on statement cells (`overflow: visible`, `white-space: normal`) and no text is silently cut off anywhere.
- **The read-only/config honesty is excellent.** The header badge distinguishes `read-only (locked)` from plain `read-only` per the actual `read_only_reason`, and the Profiles tab is refreshingly candid about its own limits ("there is no live-switch control here or anywhere else in this app, by design") rather than presenting a control that would silently do nothing.
- **Review gap and Questions tabs**, while currently empty (no data to show), present a correctly honest empty state ("No review gaps — every countersign obligation is currently discharged") rather than a blank screen.
- **Virtualization is architected correctly** for the scale problem, even though it hasn't kicked in yet at 185 rows — this is future-proofing done right, just not yet observable live.

### Minor findings (not priority, worth a mention)

- Narrow viewports (768px, 390px) don't reflow — the table just compresses; at 390px the statement column is ~90px wide and word-wraps almost character-by-character. Likely low-impact for a desktop ops tool, but a professional console usually degrades to a card layout below some breakpoint.
- The "read-only (locked)" badge has no inline tooltip explaining what "locked" means to a first-time viewer; you'd need the README to know it means "an operator deliberately disabled writes at startup, independent of write-conduit availability."

### Priority ranking

1. [Commission decomposition view silently reports zero progress on commissions that have real, shipped work](#1-the-flagship-view-is-silently-non-functional-against-this-deployments-real-data-most-serious-finding) — this is a trust-breaking defect in the headline feature, not a rough edge.
2. [Recent ledger's navigability gap](#2-recent-ledger-is-the-commissioners-complaint-and-its-worse-than-it-sounds), which is now measurable and about to worsen as row count crosses the virtualization threshold with no facets beyond kind.
3. [Vocabulary leak with no resolution mechanism at all in the codebase](#3-internal-vocabulary-leaks-into-the-ui-with-zero-resolution-mechanism-everywhere) — directly costs the commissioner's stated pain (having someone decode "s33").
4. [Missing ref-hyperlinking / item view](#4-promised-cross-cutting-features-are-not-built-no-hover-synopsis-no-item-view-no-ref-links) — disclosed as not-yet-built, so lower urgency than 1–3, but blocks the natural "click through a citation" workflow every other view's text implies is possible.
5. [Live-update affordance](#5-live-update-ux-has-no-affordance-and-can-move-content-under-the-reader) and the two minor items above are polish, not blockers.
