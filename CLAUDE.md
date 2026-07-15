# CLAUDE.md — autoharn-panel (world experience)

Read .claude/HOOKS.md first. You are the author principal; reviewer and commissioner
principals exist (see point 11 for the commissioner's role).
1. Decompose the ENTIRE commission into ledgered work items BEFORE implementing — every
   increment the task names, including ones you will not start this session
   (./led work open <slug> <title...> per item, titled so a FRESH session could build
   from it; claim only what you begin: ./led work claim <slug>). Close each with
   ./led work close <slug> <resolution> --witness <ref> once delivered. An increment
   left out of the ledger does not exist: resumption cannot see it and point 6's "clean"
   passes vacuously over it (run-8 finding, 2026-07-11). Decompose to the UNIT OF
   INDEPENDENT RESUMPTION, not below it and not above it — no numeric rule (a fixed
   item-count or file-count target is cargo-cultable and wrong as often as right): state
   each item's deliverable and its acceptance handle, and leave the mechanism/HOW to the
   task chartered to own it. Judge granularity by one question — "could a fresh session
   pick up this slug alone and know what to build and how to tell it's done?" — too fine
   adds ledger ceremony with no resumability gain (run10: three items that collapsed to
   one file and one commit); too coarse hides a seam a successor could have picked up
   separately (design/ORCH-RETROSPECTIVE-RUN10.md, Finding 2).
2. Before choosing tools for a task, read the RESOURCES section. If the task's shape
   matches a blessed or mandated entry, reach for that tool — or ledger one line saying
   why not. If the task's shape matches a forbidden entry, do not reach for that tool; if
   you believe the prohibition is wrong for this task, ledger a question to the
   commissioner — never a silent exception. If you used a declared resource, say so in
   the closing row. A mandated-tier task carries a review obligation by convention: its
   work item's close is countersigned by a distinct principal whose review cites the
   resource's declared evidence shape — present or absent — because self-reports are not
   trusted (design/ORCH-SPEC-RESOURCE-REGISTRY.md §4; the forbidden tier is
   design/ORCH-SPEC-RESOURCE-ACCOUNTING.md §3, audit-policed per §5/§7, not yet checked
   at write time).
3. Assign the decomposition's countersign obligation to reviewer; reviewer countersigns
   via LED_ACTOR=reviewer claiming technical independence, AND runs an antecedent audit:
   enumerate design facts the artifacts encode with no antecedent in task text, ledger
   rows, or assumption rows; file each one found as its own `./led assumption "<fact>"
   --refs <artifact>` (assumption, not finding — it's the same unledgered-design-fact
   defect as point 7, just caught by the other principal instead of self-reported).
   `hooks/pretooluse_change_gate.py`'s `decomposition_review` mechanism makes this a
   BLOCKER, not backloggable debt (maintainer ruling 2026-07-12): a substantive edit is
   denied while a claimed work item's own opening row is undischarged. Disclosed-self-
   review fallback (solo worlds only, no second principal genuinely available): register
   a second principal for the SAME operator (`./led register-principal <name>
   human|model|subagent|tool`) — the kernel refuses a review by the SAME actor id
   regardless of the independence label, so a second principal id is required even when
   one human operates both — then countersign
   disclosing it plainly: `LED_ACTOR=<second-principal> ./led review <id> attest
   self-review "<basis; disclose no independent reviewer was available>"`. `self-review`
   is a first-class `independence` value precisely for this case, and `review_gap`'s own
   discharge test does not distinguish it from technical/managerial/financial — it only
   requires a distinct actor and verdict=attest.
4. Pre-register acceptance criteria as their own ledger entry BEFORE implementing;
   record results with --evidence AND --refs row:<criteria-row-id> against that entry
   (refs is the sanctioned channel for a non-review kind to cite an antecedent row,
   so the criteria->result link is queryable, not prose).
5. A task that produces files is complete only when they are committed to git.
6. Done means ./led review-gap, question-status, and ./led work violations are all clean
   (./distance-to-clean composes these same three views into one read, if a single command is
   preferred for a closure check — the three views above remain the documented default).
7. Any design fact you commit to that has no antecedent in the task or an existing ledger
   row gets recorded FIRST via `./led assumption "<the fact and why it was assumed>"` —
   an unledgered load-bearing assumption is a defect, not a convenience.
8. Investigation and delegation are work: ledger them BEFORE doing them. "I lack the
   spec" has more than one honest kind — classify, don't default: a `question` row when
   the operator should answer; a `decision` row when you resolve to excavate or author
   the spec from the context at hand; an `assumption` row when you proceed on an
   inferred reading. Dispatching a subagent is a `decision` row (what is delegated,
   why). A silent investigation leaves a record that claims the session began at its
   first write.
9. Stopping is a ledgered act. Before you stop — done, blocked, or leaving work for
   later — write the disposition a successor resumes from:
   `./led decision "stopping: <why>; stands: <what is done>; remains: <slugs/refs>"`.
   Workers leave their work resumable for whoever picks it up; a stop with no trail
   strands the successor in archaeology.
10. Record as you go — one row at the moment of the act. Batching declarations you are
   making right now (an intake decomposition) is fine; the token declares it. If you
   must record an act after the fact, declare its event time — never narrate the past
   as if live.
11. On RECEIVING a commission (the ask this session was given), your FIRST ledger act —
    before point 1's decomposition — is to record it verbatim as its own row:
    `./led commission "<ask verbatim as received>"`. This is LAZY-mode signing: you are
    the implementer transcribing the ask vicariously, not the commissioner attesting it
    yourself, so the statement carries the prefix "(vicarious transcription by the
    implementer; carries no commissioner guarantee)" IN ADDITION to your own stamped
    invocation already proving the transcription vicarious by construction (a live
    session's stamp is not the commissioner's own signature — say so in the prose too,
    not stamp state alone). Every decomposition row from point 1 onward `--refs
    row:<commission-id>` this row, so the whole session's work traces to the ask that
    started it (design/ORCH-RETROSPECTIVE-RUN10.md, could-not-answer item 4: "the commission
    itself is not in the governed record" — this closes that gap). If the maintainer
    instead signs the commission himself, FULL mode, in his own terminal
    (`LED_ACTOR=commissioner ./led commission "<ask>"`), that row already exists when you
    start — check `./led --recent` before writing your own; do not double-record the
    same ask under two rows. On a world scaffolded before kernel/lineage/
    s25-commission-kind.sql landed, `commission` is refused by the kind vocabulary check
    (the refusal itself names the valid list, live) — record the ask in a `decision` row
    instead and say so in its text, same as any other pre-s25 world. Immediately after the
    commission row exists (either mode), run `./verify-commission` and carry its verdict
    (VERIFIED / UNSIGNED / FORGED-OR-CORRUPT) into the FIRST row of point 1's decomposition —
    a FORGED-OR-CORRUPT verdict is a stop-and-escalate event, never a silently-proceeded-past
    detail (design/MAINT-GPG-TRUST-LAYER.md §3).
12. A load-bearing decision names what was rejected and why, IN THE STATEMENT — not a
    separate row, not left implicit. `./led decision "<the choice>; rejected: <the
    alternative(s)> because <why>"`. Convention only (no kernel column enforces this —
    filed, not built, awaiting a witnessed need before a schema change is warranted);
    the retrospective's could-not-answer item 1 named the gap this closes: "why the two
    app defects arose — oversight vs a considered-but-wrong call — is UNDECIDABLE from
    the record" without the alternatives a decision weighed being on the record too.
13. When a dispatched subagent returns, you SEE its reported token/usage numbers in the tool
    result. If you ledger them, mark them explicitly as an unverified self-report — prefix
    the statement "(self-reported by the subagent; no harness guarantee)" — the same trust
    class as point 11's LAZY-mode commission transcription: an attributable claim, never a
    witnessed fact. The harness has no mechanism that checks a token count the way it checks
    a stamp or a kernel constraint; this is a convention, not a gate, and stays diagnostic-
    grade by design (BACKLOG "Maintainer principle: the action stream is the evidentiary
    basis; session internals are diagnostics", 2026-07-11).

## RESOURCES

Declared resources for this project — source of truth is the deployment's own ledger
(`kind=decision`, `resource:` statement-prefix convention, per autoharn's
`design/USER-BLESSED-TABLE-TEMPLATE.md`); `./pickup`'s RESOURCES section re-derives this table
live from those rows on every hydration, so this table is a durable, human-edited mirror of
what's declared, not the declaration itself — if the two ever disagree, the ledger row wins.

| NAME | CLASS | REACH | WHAT-IT-PROVES | GUIDANCE | TIER |
|---|---|---|---|---|---|
| makespan-scheduler | library | `import: makespan_scheduler` (editable install at `/home/bork/w/vdc/1/experience/makespan-scheduler`, a sibling checkout — not a submodule of this repo — into the shared venv `~/w/vdc/venvs/generic`) | minimum-makespan schedule proof for jobs under resource-conflict (mutual exclusion) and/or concurrency-cap constraints, via OR-Tools CP-SAT | reach for ordering 3+ claimed/claimable work items when the conflict is resource contention (shared file/lock/artifact) or a worker-pool concurrency cap; it proves conflict-freedom and capacity-respecting scheduling, **not** directed A-before-B precedence — a `work_depends`/`constraint: precedes` edge is not natively encodable and must never be presented as guaranteed by this tool's output order; model precedence as a shared-resource conflict only when within-conflict order doesn't matter, or escalate to tsort/ASP for genuine directed precedence at scale; discharge evidence = the emitted schedule JSON (`jobs[].start/end`, `batches`, `optimal` flag), ledgered with `--refs` to the decomposition it ordered | `blessed: ordering three or more claimed/claimable work items under dependency or quota constraints` |

(ledger row id=38, `--refs row:16`; upstream repo: `KodBena/makespan-scheduler`)

## The LAW (portable ADRs — snapshot copy, lifted 2026-07-15)

The ADRs under `law/adr/` govern how you build here, exactly as they do in autoharn itself.
They are a **snapshot copy** taken 2026-07-15 from the autoharn checkout this deployment
execs from (hand-lifted by the maintainer; the mechanized pointer-based delivery replaces
this copy on a future re-scaffold). Two consequences of snapshot-ness, stated honestly:
cross-links from ADR text to autoharn root docs (GLOSSARY.md and the like) dangle here, and
this copy does not move when autoharn's law does. The directory is gitignored — it must
never enter this repository's public history; autoharn is its one home.

- **Read the LAW first, and read it for its spirit.** When work requires the ADRs, read the
  actual files in full *before* you diagnose, design, or touch code — the fix is shaped by
  the law from its first line, not retrofitted to it at the end. The spirit of an ADR
  governs as much as its letter, often more: these are principles written by a colleague to
  be extrapolated from and interpreted judiciously, not rules to satisfy literally. Meeting
  the letter while violating the intent is a failure, not a pass; where letter and spirit
  appear to diverge, the spirit wins and you surface the divergence.

- **The LAW tells you how to build; it does not license stepping over a hazard you can
  see.** A hazard within reach of the work you are touching, you fix or you flag loudly;
  you do not route around it because it wasn't the assigned task. What counts as a hazard
  is deliberately not enumerated — recognizing one is your job, including the kind no one
  has named yet.

{"Project LAW, extrapolate from and interpret judiciously like a professional colleague": ["law/adr/*.md]}

Additional binding inputs for THIS project's frontend work (already in-repo, not snapshots):
`docs/omega-observatory/2026-07-15-frontend-speed-reap.md` (the Don't-list) and
`docs/omega-observatory/2026-07-15-frontend-architecture-reap.md` (the adopt-verdicts), as
`SPEC.md` cites them.

