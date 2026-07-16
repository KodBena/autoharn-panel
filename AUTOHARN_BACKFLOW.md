# AUTOHARN_BACKFLOW.md — findings for the autoharn maintainer

## What this file is, and what it is not

This file was written from inside `autoharn-panel`, a deployment ("world") that
adopts the `autoharn` governance harness (checked out as a sibling repo at
`/home/bork/w/vdc/1/experience/autoharn`, and execed live from there — see this
repo's `CLAUDE.md` for how). It records harness behaviors this deployment's own
work surfaced that were genuinely surprising, or dangerous if cargo-culted into
a higher-stakes deployment of the same harness — for the maintainer to carry
back into the `autoharn` project itself. Every finding below was independently
re-verified by reading the actual source/schema/git-history at the time this
file was written, not merely transcribed from a prior session's ledger prose.

**Framing, stated by the maintainer, quoted here on purpose:** this is *not* a
laziness/annoyance complaint file. The end users of systems built this way are
meant to be organizations like the NRC and NIST, where up to hundreds of
millions of lives can depend on correctness (see this repo's
[`law/adr/0013-execution-integrity.md`](law/adr/0013-execution-integrity.md)).
"Annoyance" in this file never means "this was tedious for me" — it means
needless or stupid ceremony, or a silent false-confidence gap, that on its own
could cost lives if cargo-culted into a high-stakes deployment.

In the spirit of [`law/adr/0017-the-zero-context-reader.md`](law/adr/0017-the-zero-context-reader.md),
each finding below is written so a reader with zero prior context on this
deployment or on `autoharn` can follow it: what happened, why it is surprising
(not merely annoying), the concrete evidence, and its severity/blast-radius if
cargo-culted at NRC/NIST-grade stakes. All file paths below are given relative
to this repo's root (`autoharn-panel/`) or, when they point into the sibling
checkout, as an explicit `autoharn/...` path — every one was resolved and
checked before this file was finished.

**Maintenance discipline for this file, per the maintainer's own instruction
(2026-07-16):** an item known to be addressed upstream is removed from this
file entirely, not kept as a "fixed" historical record — this file exists to
tell the autoharn side what still needs surgery, not to log a fix history (the
ledger already does that, append-only, on this deployment's own side). Five
prior findings (silent `informs`-default on `led work depends`; a
`distance-to-clean` coverage gap vs. the stop-gate; a hardcoded scan root in
`link_integrity.py`; the delegation observer's overstated teach-text; a
`doc_attestation` vendor-tree flood) were confirmed fixed upstream — via
`autoharn/orchlog.d/s36-graded-decisions-dsl-and-wave.md` and direct re-reads
of the current source (`led.tmpl`'s `work depends` advisory text,
`distance-to-clean.tmpl`'s five debt functions, `doc_attestation_presence.py`'s
`discover_md()` now calling `git check-ignore`, `pretooluse_delegation_observer.py`'s
`has_session_decision_row()`) — and removed accordingly.

---

## Finding 1 — a fully-discharged composite work item displays as permanently, indistinguishably "open" on every operator-facing surface

**What happened.** s33 (`kernel/lineage/s33-composite-discharge.sql`) gives a
composite parent work item a real, computed `effective_state` column on
`work_item_current` — `discharged-by-obligations` once every child under it
has closed. Confirmed live in this deployment, right now:

```
SELECT slug, state, effective_state FROM experience.work_item_current
WHERE slug = 'spa-professionalism-cycle-1';
              slug              | state |      effective_state
---------------------------------+-------+----------------------------
 spa-professionalism-cycle-1    | open  | discharged-by-obligations
```

All 7 of its children show `state = closed`. The composite parent is, by the
harness's own semantics, completely done. But **`state` — not
`effective_state` — is the only column any operator-facing surface reads**:
`led work list` (`autoharn/bootstrap/templates/led.tmpl` lines 1867/1872,
`SELECT w.slug, w.title, w.state, ...`, filtered `WHERE w.state <> 'closed'`
by default) and `led work asof` (same file, ~line 1911, reconstructing
open/claimed/closed purely from raw `work_opened`/`work_closed` events) never
select or filter on `effective_state` at all — it is a column that exists in
the view and is consulted by *nothing* the operator actually runs to ask "is
this done?" The only way to see the true, discharged state is to write and run
a raw SQL query against `work_item_current` directly, which is not a command
this project's own tooling teaches, surfaces, or hints at anywhere in `led
work`'s own usage text.

**Why it is surprising.** This is a case where the harness computes the exact
fact an operator is asking ("is this parent's obligation actually
discharged?") and then never shows it to them through any command whose whole
job is to answer that question. The result, witnessed directly this session:
**the maintainer asked "why is `spa-professionalism-cycle-1` still open" three
times** across this deployment's lifetime (confirmed live via
`./led question-status` after filing the third ask as its own row — question
515, answered by decision 516) — each time independently re-deriving the same
`effective_state` fact from scratch, because nothing in the ordinary
`led work list`/`led work violations` workflow ever surfaces it. A mechanism
whose entire purpose is to let a composite parent's true state be *computed*
rather than manually tracked is, in its current wiring, strictly worse than no
mechanism at all for the "is this done" question specifically — a plain
`state` column with no composite concept would at least prompt "go check the
children," where this instead prints a **specific, additional, false-seeming
signal** ("open") that a fully-discharged item is not.

**Concrete evidence.**
- `autoharn/kernel/lineage/s33-composite-discharge.sql` lines 87–93, 456–508:
  `effective_state` is added to `work_item_current` specifically so "a
  composite parent's own hand-close re-surfaces... " logic has somewhere to
  live; line 508, `END AS effective_state` — a real, computed column, not
  dead schema.
- `autoharn/bootstrap/templates/led.tmpl` lines 1867/1872 (`work list`) and
  ~1898–1912 (`work asof`): both query `work_item_current`/raw ledger events
  for `state` only; neither file contains the string `effective_state`
  anywhere (confirmed by `grep -c effective_state led.tmpl` → 0 hits outside
  the one usage-text comment at line 203, which merely points a reader
  elsewhere without saying where).
- Live, this deployment: `spa-professionalism-cycle-1` (7/7 children closed,
  `effective_state = discharged-by-obligations`) and the newer
  `spa-professionalism-cycle-2` compound item show identically as `state =
  open` in `led work list` and `led work violations` output, with no
  visible distinction from a genuinely stalled parent with 0/7 children
  closed.
- Ledger rows 515 (question, "why does cycle-1 still show open") and 516
  (decision answering it by re-deriving the live query above) — this
  deployment's own third occurrence of the identical ask, filed specifically
  because the first two were never durably recorded anywhere findable.

**Severity if cargo-culted at NRC/NIST-grade stakes.** This is the "false
still-open" mirror image of the false-clean/false-alarm shapes this file
otherwise names: an operator (or an automated dashboard reading `led work
list`) sees a fully-discharged regulatory decomposition item and reasonably
concludes work remains outstanding, potentially re-assigning, re-auditing, or
escalating work that is genuinely finished — institutional churn caused
entirely by a display gap, not a governance gap (the underlying data is
correct; only the read-path is incomplete). At minimum, `led work list`/`led
work violations` should render `effective_state` alongside (or instead of)
raw `state` for any item where the two differ, with a one-line note
explaining why; better, the raw `state` column itself could be forbidden from
selection anywhere in operator-facing output once `effective_state` exists,
so that no code path can regress to displaying the wrong column, as this one
already has, at least three times over.

---

## Finding 2 (open question, not a verdict) — the stop-gate's "fail open after 3 identical attempts" design

`autoharn/hooks/stop_clean_exit.py`'s circuit breaker (module docstring,
"CIRCUIT BREAKER" section, and `_breaker_transition()`/`DEBT_REPEAT_LIMIT = 3`,
lines 128–145 and 733–771) blocks a Stop event on unresolved governance debt,
but **allows the stop anyway, loudly, the third time the identical debt
fingerprint is seen** — a deliberate design choice, stated explicitly in the
file's own docstring as a trade-off: never let a structurally-unclosable debt
item (e.g., a review obligated to a different principal, or a dependency
cycle) trap a session forever, at the cost of a loud but real governance
bypass.

This is my own independent assessment, flagged as such, not a settled
finding — the maintainer said he is not sure whether the stop-gate's nagging
behavior generally is intentional, so this is offered as an open question for
the maintainer to judge:

- **The pragmatic case for it:** an unconditional block genuinely can trap a
  session on debt it cannot resolve unilaterally (a review that must be
  countersigned by a *different* principal it has no way to invoke; a
  dependency cycle with no single-sided fix). Without an escape valve, the
  only way out is killing the session out-of-band, which discards the
  session's own diagnostic trail entirely. The breaker's escape is loud
  (a large `!`-banner to stderr, a distinct journaled `breaker_fail_open`
  outcome) rather than silent, and `_breaker_transition()`'s "progress does
  not re-arm" logic (lines 733–771) is specifically designed so that an agent
  making real, partial progress on a wide decomposition does not get
  needlessly re-trapped at count 1 every time the debt set merely shrinks.
- **The concerning property:** the trigger condition is "the *identical*
  debt fingerprint has now been seen three times" — and the fingerprint is
  computed purely from the current debt entries, with no requirement that
  three *independent, good-faith* attempts at resolution occurred in between.
  Nothing in the mechanism distinguishes "the operator tried three different
  remediation approaches and all three left the same debt behind" from "the
  operator (or an automated loop) issued the same Stop request three times in
  a row with no remediation attempted at all, specifically to trip the
  breaker." Both produce an identical fingerprint history and both fail open
  identically. For a governance gate whose entire purpose is "the world's own
  ledger, not advice in a context window, decides whether unfinished work can
  be walked away from" (the file's own motivation section), a bypass that can
  be reached by mere repetition — rather than by a distinct, harder-to-forge
  signal such as elapsed wall-clock time, a distinct-actor attestation, or an
  explicit maintainer override — is a property worth naming plainly. It is
  not a bug in the code as written (the trade-off is stated honestly in the
  docstring), but as a *policy* choice it means "the stop-gate's protection
  can be worn down by identical repeated denials" is true by design, and I
  am not certain that is the intended security posture for a mechanism this
  document's own framing says may sit upstream of NRC/NIST-grade correctness
  guarantees.

**Concrete evidence.** `autoharn/hooks/stop_clean_exit.py`, docstring section
"CIRCUIT BREAKER" (lines 128–145) and "BREAKER TRANSITION — PROGRESS DOES NOT
RE-ARM" (lines 147–165); implementation in `_breaker_transition()` (lines
733–771) and `_allow_with_warning()` (lines 821–835); `DEBT_REPEAT_LIMIT = 3`
(line 263).

---

## Finding 3 — a work item's close has no "no review needed" constructor, even for a close with zero judgment content

**What happened.** s29 Element B (`kernel/lineage/s29-obligation-item-key-and-typed-close.sql`)
requires every `led work close` to pick exactly one of two constructors —
`--review-witness <ref>` (a review already exists) or `--review-deferred`
(the close itself becomes a review obligation) — and refuses construction
outright otherwise (`autoharn/bootstrap/templates/led.tmpl` lines 1415–1431:
"`led work close: REFUSED -- a review-silent close is unrepresentable (s29
Element B)`"). This is deliberate and, for substantive work, correct. But it
has no exception for a close whose content is **pure ledger bookkeeping with
no judgment call for anyone to countersign** — concretely, this deployment's
own git-transaction-pairing work items (row:407's policy: a second work unit
whose sole resolution is "the commit landed", e.g. `backflow-finding-rewrite-
commit`, `cycle3-consult-doc-commit`). Closing either of these with `led work
close <slug> shipped --witness commit:<hash>` and nothing else is refused
identically to closing a genuine, judgment-bearing deliverable — there is no
third constructor for "this close has nothing in it a reviewer could
meaningfully attest to or refute."

**Why it is surprising.** The two work items this finding cites exist
*entirely because of the harness's own git-transaction policy* — a
bookkeeping artifact, not a deliverable. Requiring the exact same review
ceremony for "the commit landed, here is its hash" as for "this refactor is
correct" either produces review-gap debt with no genuine content to review
(the countersign can say nothing more than "yes, that hash exists"), or
trains the operator to treat `--review-deferred` + a boilerplate self-review
attestation as a rubber stamp — exactly the "content-free review" shape
`USER-RECIPES-FAQ.md`'s own Review Discipline section already names as a
known failure class, just reliably reproduced here rather than caught by
`audit --review-gap`'s length heuristic (a boilerplate countersign is easily
long enough to pass that heuristic while still being empty of judgment).

**Concrete evidence.** Live, this session: both `led work close
backflow-finding-rewrite-commit shipped --witness commit:df26309` and the
same for `cycle3-consult-doc-commit` were refused with the identical
`REFUSED -- a review-silent close is unrepresentable (s29 Element B)`
message (`autoharn/bootstrap/templates/led.tmpl` line 1425), with no
constructor available that says "this close is bookkeeping, not a
deliverable."

**Severity if cargo-culted at NRC/NIST-grade stakes.** Lower blast-radius than
this file's other findings — the failure mode is ceremony-without-content
rather than a false-clean or false-alarm signal — but worth naming because it
sits exactly where Rule 3 of `law/adr/0013-execution-integrity.md` warns
against: a mechanism whose review requirement cannot distinguish "worth
reviewing" from "nothing to review" invites exactly the demurral this
project is trying to keep out of its own culture (a bookkeeping close review
becomes a rubber stamp, and the discipline that rubber stamp was supposed to
protect gets a little weaker each time).

---

## Verification note

Every file path and line reference above was checked against the actual
on-disk source at the time of writing (both this repo,
`/home/bork/w/vdc/1/experience/autoharn-panel`, and the sibling `autoharn`
checkout at `/home/bork/w/vdc/1/experience/autoharn`), rather than transcribed
solely from prior ledger prose. Ledger rows cited (515, 516) were read via
`./led show <id>` and used as pointers to re-derive the underlying claim, not
as the claim's proof on their own.
