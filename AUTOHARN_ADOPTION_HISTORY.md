# AUTOHARN_ADOPTION_HISTORY.md — how this deployment adopted ADR-0017's A:B:C fresh-context doc-review loop

This file is for a reader who was not present when this deployment (`autoharn-panel`) first ran
its documentation-review discipline — this project's own maintainer coming back later, or a fresh
session picking the project up cold. It answers four questions in order: what the discipline is
and why this deployment adopted it now; how it was actually run, round by round; what happened
when the review did not converge; and how to run the same loop yourself going forward. It is a
narrative, deliberately narrower than [`AUTOHARN_BACKFLOW.md`](AUTOHARN_BACKFLOW.md) — that sibling
document records harness behaviors this session found surprising or dangerous enough to report
back to the autoharn maintainer (including one behavior this adoption tripped over, cited by name
in point 5 below); this document only tells the adoption story.

## 1. What the loop is, and why this deployment adopted it now

[`law/adr/0017-the-zero-context-reader.md`](law/adr/0017-the-zero-context-reader.md) ("ADR-0017",
lifted into this repo as one of the [LAW](law/adr/) snapshot copies this project's
[`CLAUDE.md`](CLAUDE.md) describes) states a single test: a maintainer-facing document is finished
only when a reader with **none** of the author's conversational context can parse every sentence,
resolve every reference, and tell from the document itself what it is and why it exists. An
author's own re-read can never certify this, because the author is structurally the one reader who
still has the context the test is checking for.

ADR-0017's primary enforcement transport for that test is the **A:B:C fresh-context audit loop**,
proposed by the autoharn maintainer near-verbatim and recorded in the ADR's own "The fresh-context
audit loop" section: **A** writes or edits a document; **B** — a separately forked reviewer given
*only* the document and the ADR's test, never A's conversation — judges it fresh; **C** repairs
whatever B found. Two rounds of B→C are allowed; if B still finds real defects after the second
round, the loop does not grind a third pass — it is recorded as a non-converging review and
escalated to a higher-authority adjudicator instead (point 3 below is exactly that case, and it is
why this deployment's own experience is worth recording rather than assumed-clean).

This deployment adopted the loop now because of a concrete, dated trigger, not a scheduled rollout:
a just-shipped consult document, [`docs/consults/2026-07-16-spa-professionalism-audit.md`](docs/consults/2026-07-16-spa-professionalism-audit.md),
turned out to contain real broken links — the kind of defect ADR-0017's loop almost never lets
through in autoharn itself. That observation was the commission this session received (ledger row
216, `./led show 216`): adopt the loop, run it for real on that document, and write down how, for a
future reader — which is this file.

## 2. How it was actually run here: genuinely blind fresh B invocations, not a "verify these fixes" pass

The loop was run as **two full rounds over the whole document**, not as a targeted "check that the
specific broken links are fixed" pass. This distinction matters because autoharn's own operating
guidance for the loop — cited in the ADR's Related section and unpacked at length in a companion
walkthrough this deployment's checkout does not carry a local copy of
(`design/USER-DOC-AUDIT-LOOP.md`, in the sibling `autoharn` checkout this project execs from, not
under this repo's own root) — names a specific, real failure mode: briefing a round-2 reviewer with
*both* "confirm these known findings are fixed" *and* "also sweep for anything else" in the same
message collapses the sweep into the verification pass, because attention anchors on the named
findings and the "anything else" clause gets the same thin coverage a checklist's trailing "and
anything else you notice" always gets. The documented, measured cost of that anchoring failure
(same walkthrough, citing a dated 2026-07-13 incident on a document inside the `autoharn` checkout
itself) is stark: two ordinary "were the fixes applied" rounds both reported the document CLEAN,
and both times the maintainer, reading cold with no briefing, caught a real defect the confirmation
passes had missed; two genuinely blind fresh sweeps, run instead, found four defects and then seven
more that the confirmation-mode rounds never surfaced at all.

This deployment's own two rounds followed the guard against that failure mode, not the failure
itself:

- **Round 1.** A fresh `Agent` invocation was given the document's text and ADR-0017's Rule 1 test
  only — no mention of what A had intended, no framing beyond "judge this fresh." It reported a
  DEFECT verdict with concrete, quoted findings: dangling referents, zero markdown-linked paths
  (every in-repo path in the document was bare prose or backticks), three filenames cited in the
  wrong shape, and positional section references. C repaired each one.
- **Round 2.** A **second, brand-new** `Agent` invocation reviewed the repaired document. It was
  told nothing about round 1 — not that a repair pass had happened, not what round 1 found. It
  independently found five *new* real defects in the repaired text: two sentence fragments, two
  unlinked bare mentions of `SPEC.md`, and one cross-repo referent whose disambiguation, stated
  earlier in the document, did not travel to a later mention of the same term.

Both rounds are recorded verbatim, findings included, in the attestation record itself
([`attestations/doc-legibility-attestations.jsonl`](attestations/doc-legibility-attestations.jsonl) —
point 4 below explains the record format) rather than only in ledger prose, so a reader does not
have to trust a summary of what B said; the record carries B's own quoted findings.

## 3. Round 2 did not converge — and that was escalated honestly, not ground through a third round

Round 2 still found real defects. Per the loop's own designed behavior for exactly this outcome —
two rounds is the cap, and a still-DEFECT verdict at the cap is a **non-converging review**, not
license for a quiet third pass — this session recorded that outcome as its own ledger finding
(row 233, `./led show 233`) rather than immediately dispatching a third B: *"Per USER-DOC-AUDIT-LOOP.md's
own rule ('if B still finds defects after a second pass, stop — don't run a third round... record
the DEFECT verdict as escalated... get a second opinion before touching the document again'), this
is being recorded as a non-converging review, escalated, with a second opinion dispatched before
any further edit."*

The escalation was then adjudicated (row 234, `./led show 234`): the orchestrating session, acting
as this deployment's designated escalation recipient, decided to apply round 2's own five suggested
repairs verbatim, adding no independent judgment beyond that — a defensible call precisely because
the five findings were small, mechanical fixes (two fragments, two unlinked mentions, one repeated
disambiguation) rather than a symptom that the document needed a fresh, independent re-diagnosis.
The actual repair work was then dispatched to a subagent rather than performed by the orchestrating
session itself (row 235, `./led show 235`), consistent with this project's standing
orchestrator-never-does-the-work convention. The closing verification (row 242, `./led show 242`)
records the whole arc in one place: two genuinely blind rounds, an honest non-convergence finding
instead of a third round, and an adjudicated repair.

## 4. Recording the attestation, and checking status

Once the loop was fully dispositioned — for an escalated loop, that means *after* the recipient's
adjudication, never before — the result was recorded with `./attest-doc record`, writing one JSON
line to this deployment's own ledger,
[`attestations/doc-legibility-attestations.jsonl`](attestations/doc-legibility-attestations.jsonl)
(see [`attestations/README.md`](attestations/README.md) for what this ledger is and why it is kept
separate from autoharn's own copy of the same mechanism). The ledger currently carries **exactly
one** entry — this one loop, over `docs/consults/2026-07-16-spa-professionalism-audit.md` — because
this is the only document this deployment has run the loop over so far.

That record is written in the **`doc-attestation/2`** schema, which is the version this project's
`./attest-doc record` writes by default. The reason the escalated case specifically needed `/2`
rather than the older `/1` format is a real, dated gap `/1` had: `/1` had no typed field for an
escalation recipient's adjudication, so the "who decided, and what they applied" fact had nowhere
structured to live and earlier records were forced to bury it as free text inside `b_id`, a field
never meant to carry it. `/2` adds a dedicated `adjudication` object with exactly three required
fields — `adjudicated_by`, `disposition`, `adjudicated_at` — and refuses a record that either
claims escalation with no adjudication, or claims an adjudication on a loop that never escalated.
(The full rationale and the closure-statement enumeration of every admitted/refused record shape
lives in `design/ORCH-SPEC-DOC-ATTESTATION-2.md`, in the sibling `autoharn` checkout this project
execs from — not a path that resolves inside this repo.) The recorded entry's own `adjudication`
object reads exactly as the ledger prose above describes it: `adjudicated_by: "orchestrator (main
session), escalation recipient"`, `disposition: "applied round-2 B's own 5 suggested repairs
verbatim, adding nothing of my own"`.

To check where a project's documents stand against this ledger at any time, run `./attest-doc
check`. With no arguments it reports every in-scope markdown file, classified `ATTESTED` (a record
exists for the file's exact current bytes), `STALE` (a record exists but the file has since
changed), or `NO-ATTESTATION` (never reviewed). Running it in this deployment right now reports the
one reviewed document as `ATTESTED`, and — importantly, this is the honest state, not a defect in
the review itself — a large number of other in-scope `.md` files as `NO-ATTESTATION`, because this
deployment has so far only run the loop on the one document the trigger in point 1 named. Point 5
below explains why that `NO-ATTESTATION` count is currently **not** counted as debt anywhere.

## 5. The current live state of `doc_attestation`: `off`, and why

[`.claude/apparatus.json`](.claude/apparatus.json)'s `mechanisms.doc_attestation.mode` reads
**`"off"`** right now. `off` means `./distance-to-clean` does not count any `NO-ATTESTATION` or
`STALE` document as debt at all — it is a pure opt-in switch (see
[`.claude/APPARATUS.md`](.claude/APPARATUS.md)'s own entry for this mechanism), never a cost
switch: checking or recording an attestation spends nothing, no `claude -p` call, no network.

This is the shipped default, and it is also where this session left it after a real, dated
detour: mid-session, the switch was flipped to `"observe"` — exactly what its own note in
`apparatus.json` instructs a maintainer to do once they start running the loop for real — and doing
so surfaced a live defect in the mechanism itself, not in this deployment's documentation: the
resulting debt count was dominated by files under `frontend/node_modules/` and
`venv/lib/python3.13/site-packages/`, vendor dependency trees ADR-0017's own Scope section was
never written to cover. That defect, its root cause, and the decision to revert the flip back to
`off` rather than leave a misleading debt count live are written up in full — file:line evidence,
the exact scope-detection code path responsible, and the severity assessment — as **Finding 6** of
[`AUTOHARN_BACKFLOW.md`](AUTOHARN_BACKFLOW.md#finding-6). This file does not repeat that finding's
content; it only notes that the switch's current `off` state is a deliberate reversion, not an
oversight, and points there for the reason.

## 6. Running this yourself, next time

The six-step version, for a maintainer or a fresh session that wants to run the same loop over a
different document:

1. Finish writing or editing the `.md` document you want reviewed.
2. Spawn a fresh subagent as B — a brand-new invocation, never a resumed one — and give it *only*
   the document's current text and [`law/adr/0017-the-zero-context-reader.md`](law/adr/0017-the-zero-context-reader.md)'s
   Rule 1 test. Do not tell it anything about your own editing session, and never front-load it
   with a list of findings you expect it to confirm — that collapses a fresh sweep into a
   confirmation pass, the exact failure point 2 above describes avoiding.
3. Read B's verdict: either an explicit CLEAN naming all four clauses it checked, or a list of
   concrete findings (each with a quote and a suggested repair). A bare "looks fine" is not a valid
   verdict — ask B to redo it with specifics.
4. If B found anything, fix it, then send the repaired document to a **second fresh** B invocation.
   This is round 2, and it is the last round: if B still finds defects, stop — don't run a third
   round. Record the non-convergence honestly and get a second opinion (an adjudicator) before
   touching the document again, exactly as point 3 above describes.
5. Record the outcome with `./attest-doc record <json-file>` — build a small JSON file naming the
   document, an id for B's invocation, one object per round, and, if the loop escalated, the
   `adjudication` object described in point 4 above. The command refuses loudly and writes nothing
   if the JSON is malformed (for example, a DEFECT round with an empty `findings` list); fix the
   JSON and re-run the same command.
6. Check overall status any time with `./attest-doc check` (every in-scope document, classified
   ATTESTED/STALE/NO-ATTESTATION). If you want that debt folded into `./distance-to-clean`'s
   overall reading, flip `mechanisms.doc_attestation.mode` to `"observe"` in
   [`.claude/apparatus.json`](.claude/apparatus.json) — but read point 5 above first, since the
   vendor-tree flood it describes will very likely recur until the underlying scope-detection gap
   named in `AUTOHARN_BACKFLOW.md`'s Finding 6 is fixed upstream.

The fuller step-by-step reference this summary is drawn from — including the exact wording to hand
a spawned reviewer, the record's full JSON schema, and the dated evidence behind the
never-fuse-verify-with-sweep rule in point 2 — is `design/USER-DOC-AUDIT-LOOP.md`, in the sibling
`autoharn` checkout this deployment execs from (see this repo's own
[`CLAUDE.md`](CLAUDE.md) for how that checkout relationship works); it is not a path that resolves
inside this repository itself.
