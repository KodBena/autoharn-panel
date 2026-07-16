# Consult: SPA professionalism audit vs. SAP/Oracle-class enterprise software — cycle 2

This document records a second, independent, single-agent review of this repo's own web panel,
run after cycle 1's 7 work items (fixing the deficiencies [the cycle-1 consult](../2026-07-16-spa-professionalism-audit.md)
identified) had all shipped. It exists to close a real gap: this audit's findings were originally
recorded only as a paraphrased ledger `finding` row (row 379, `./led show 379`) and left un-filed
as a document — a violation of this project's own [CLAUDE.md](../../CLAUDE.md) ADR-0005
instance-bindings rule ("Consult / decision records ... live under `docs/consults/`"), caught only
after the operator asked where the report was. See the note at the bottom for that history,
honestly, rather than silently backfilling this as if it had been done at the time.

- **Date:** 2026-07-16
- **Commissioned via:** ledger row 374 (`./led show 374`), a fresh commission explicitly asking
  for a scout with "the SAME commission as before [row 183], except excluding the items already
  resolved in cycle 1," drawing its own conclusions, unbiased by which way we hoped it would land.
- **Method:** one deliberately unbiased Sonnet subagent, Playwright (headless Chromium) against the
  live deployment at `http://192.168.122.68:8420/`, running in `PANEL_READONLY` (locked) mode, after
  all 7 cycle-1 work items had shipped.
- **Recorded finding:** ledger row 379 (`./led show 379`) — a paraphrase with independent
  corroboration of finding 1 folded in, not this agent's own verbatim words; row 379 is the
  ledger-side record, this file is the durable one.
- **Work item:** `spa-professionalism-cycle-2-scout` (closed shipped, witness row 379, review rows
  381/385, independence `technical`).
- **Raw evidence:** the Playwright scripts and screenshots this agent produced during the audit are
  in [this directory](.) alongside this file (moved here from an ephemeral session scratchpad path
  that was never durably visible to the operator — see the filing-history note below).

This is the agent's own final report, reproduced **verbatim** ([ADR-0005 Rule 9](../../law/adr/0005-documentation-discipline.md)
— a commissioned review's report is recorded verbatim, never paraphrased into a lossier summary).
No wording below has been altered from what the dispatched agent actually returned; only this
surrounding provenance section and the corrective note at the end are the orchestrating session's
own words.

---

## Audit: autoharn-panel live app (http://192.168.122.68:8420)

Conducted via a Playwright-driving subagent that explored every major view, drove filters/pagination/citations/glossary tooltips, checked console/network errors, and tested responsive/edge cases. Full evidence (screenshots, curl repros) is under `[this directory]`.

### Ranked findings

**1. CRITICAL — regression: commission-decomposition still reports 0 items for every commission with real shipped work.** `GET /api/commission/247` and `/216` both return `"items": []` even though the Work items tab shows 15+ shipped items whose titles cite `--refs row:247`/`row:216`. All 12 commissions show "0 item(s)." Notably there's a ledger item titled `fix-commission-decomposition-view` (closed/shipped, witness `row:342`) claiming to have fixed exactly this — the live app contradicts that claim. Root cause: sampled `work_opened` rows show `"refs": null` in the API despite `--refs row:N` appearing in free-text `statement` — the decomposition query and the actual data convention disagree. This is the single most operator-critical feature and it currently misinforms rather than merely underdelivers.

**2. SERIOUS — deep links 404 on reload/bookmark/share.** In-app clicks to `/item/<id>` render correctly, but a hard reload or fresh navigation to that identical URL returns raw, unstyled `{"detail":"Not Found"}` (HTTP 404) with no SPA chrome — confirmed via `page.reload()` and direct curl. No server-side SPA history-fallback route exists. Any bookmarked/shared/pasted permalink is silently broken, and invalid IDs are indistinguishable from this failure mode (no graceful in-app 404 at all).

**3. MODERATE — Recent Ledger is unscannable at default settings.** Unfiltered default view (`limit: 200`) measured `scrollHeight: 54,842px` — ~60 screen-heights — because long free-text statements render with no truncation/expand toggle. Usable only after aggressive filtering.

**4. MINOR-MODERATE — write-refusal messaging is disconnected from the read-only story.** Clicking "co-sign" surfaces a raw `HTTP 405 Method Not Allowed` from FastAPI, while the copy right above the button primes the reader to expect a kernel-level "independence unprovable" refusal instead. An operator can't tell disabled-by-design from broken-endpoint.

**5. MINOR — the "live (SSE)" badge has no tooltip**, unlike its neighboring read-only badge which does.

**6. MINOR — Work items tab has no filter/search/sort**, inconsistent with the polish applied to Recent Ledger (fine at ~26 rows today, won't scale).

### What already meets a professional bar (don't regress)
- Read-only lock badge: precise tooltip, restated contextually on the Profiles tab.
- Glossary/tooltip mechanism for jargon (e.g. ADR-0017) — real hover glosses, confirmed in DOM.
- Row citations render as real `<a href="/item/N">` links with instant in-app navigation.
- Recent Ledger filter/sort/pagination (kind, actor, date range, superseded toggle, sortable ID, Prev/Next) all work correctly including empty-result and end-of-range edge cases.
- Responsive layout at 600px reflows cleanly, no clipping/horizontal scroll.
- SSE "new data available, click to load" affordance confirmed present (not silent refetch).
- Good empty-state messaging throughout; no unexpected console errors or 4xx/5xx during normal navigation.

### Status of the 6 previously-reported items
1. Commission decomposition 0-items — **regressed / not actually fixed live**, despite a ledger row claiming shipped.
2. Recent ledger pagination/sort/filter — **still fixed.**
3. Jargon glossary — **still fixed.**
4. Row citations as deep links — **partially fixed**: in-app works, but hard-reload/bookmark path is broken (finding 2).
5. SSE affordance — **still fixed.**
6. Responsive <800px + lock-badge tooltip — **still fixed** (the *SSE* badge specifically still lacks one — a different, new gap, finding 5).

Note: token/tool-use counts above are the subagent's self-reported numbers (102,850 tokens, 51 tool uses, ~9 min) — not independently verified by any harness mechanism, flagged here for transparency only.

---

## Corrective note on finding 1, and on this document's own filing history

**On finding 1's "regressed" framing:** independently re-checked (ledger rows 379/381/385) via direct `curl`/`psql` against the live deployment. It is **not** a regression of `fix-commission-decomposition-view` — that fix shipped correctly and does exactly what it was built and verified to do. The live `items: []` result is caused by an upstream limitation in autoharn's own `led work open` CLI (a different repository): the `--refs` flag it accepts is never actually written to the structured `refs` column on `work_opened` rows — it is silently swallowed into free-text statement prose instead. Confirmed directly: every cycle-1 child's `refs` column is empty in Postgres, even though the literal string `"row:247"` appears in their statement text. This was already found and disclosed earlier this session (ledger row 328) and the shipped fix's own verification (row 336) already recorded "0 items ... honestly, not fabricated" for exactly this reason. So: still a real, live, operator-visible defect (the flagship view is broken for all 12 real commissions today), just not new, and not something the SPA side can fix without either a CLI patch in the sibling `autoharn` repo or a one-time data backfill — a decision left to the maintainer, not made here.

**On why this file exists at all, written after the fact:** this audit's findings were dispatched, verified, and closed entirely through ledger prose (`./led finding`, `./led work close`) with no `docs/consults/` entry ever created. This was not an ambiguous gap or an emergent habit that quietly lapsed — `docs/consults/` as the filing home for "all kinds of consults" is an explicit, standing, maintainer-issued policy (ledger row 193, the maintainer's own words: "all kinds of consults should land in docs/consults"), codified into this repo's own `CLAUDE.md` the same day (row 200) and re-read into the orchestrating session's context at the start of every turn since. The omission was a plain failure to apply a written rule that was in front of the orchestrator the entire time, not a rule it had no way to know about. This file, and the screenshots/scripts alongside it, were moved here after the operator asked where the report was and found the raw evidence sitting only in an ephemeral, session-local scratchpad path that was never durably visible outside the tool sandbox.
