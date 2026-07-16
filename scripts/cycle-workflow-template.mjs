export const meta = {
  name: 'consult-cycle-workflow',
  description: 'Execute one fix-point consult cycle: topologically-batched implementation phases (from a precomputed makespan-scheduler schedule), then a whole-diff ADR-00{00,12,13} compliance review with a bounded review<->countersign convergence loop (max 2 rounds, non-convergence escalates).',
  phases: [
    { title: 'implement' },
    { title: 'compliance-review' },
    { title: 'compliance-countersign' },
  ],
}

// Expected `args` shape (Workflow's `args` input) -- this file is a TEMPLATE, not a
// standalone runnable: a caller (this session, acting as orchestrator) computes the
// schedule with makespan-scheduler BEFORE invoking this script, since a Workflow
// script body has no filesystem/subprocess access of its own -- only agent()/
// parallel()/pipeline()/phase()/log(). See row:340 for the design decision this
// encodes and the alternatives it rejects.
//
// args = {
//   repoRoot: string,                 // e.g. this repo's absolute path
//   adrPaths: string[],               // ADRs the compliance pass must read in full,
//                                      // e.g. ['law/adr/0000-....md', 'law/adr/0012-....md', 'law/adr/0013-....md']
//   schedule: { batches: string[][] },// makespan-scheduler's own batch output, one
//                                      // array of job ids per topological/resource-
//                                      // respecting wave -- NOT hand-picked wave labels
//   specs: {                          // per job id, what to actually run
//     [jobId]: { prompt: string, workRowId?: string, reviewRowId?: string },
//   },
// }

// DURABLE-LANDING-ZONE CONVENTION (ledger row:420, reconciled by row:429): the value
// this script `return`s at the end of a run -- specifically its `complianceRounds`,
// `finalReview`, `finalCountersign`, and `converged` fields -- is held ONLY in-memory
// for the lifetime of this run. This template does NOT persist them anywhere itself,
// and it never will: per the same constraint noted above (no filesystem/subprocess
// access inside the sandbox this script body executes in -- only agent()/parallel()/
// pipeline()/phase()/log() are injected), the script has no means to write a file or a
// ledger row even if it wanted to. Writing them out is the CALLER's responsibility --
// the session/agent that invokes this workflow via the `Workflow` tool -- after the
// run completes: persist the returned object (or the relevant compliance fields from
// it) to a durable location such as a file under `docs/consults/` or a ledgered row
// (e.g. `./led --refs row:<work-item> verification "<summary>" `), the same way the
// caller is already responsible for precomputing `args.schedule` before invoking this
// script (row:340). The returned object below is the full, sufficient payload for that
// write; this template's job ends at producing it, not at landing it durably.

const { repoRoot, adrPaths, schedule, specs } = args

if (!schedule || !Array.isArray(schedule.batches) || schedule.batches.length === 0) {
  throw new Error(
    'consult-cycle-workflow requires a precomputed schedule ({batches: [[jobId,...],...]}) ' +
    'in args -- run makespan-scheduler over this cycle\'s job set (with any real depends_on ' +
    'edges from the ledger\'s work_depends rows) before invoking this workflow.'
  )
}

const results = {}

for (let i = 0; i < schedule.batches.length; i++) {
  const batch = schedule.batches[i]
  phase('implement')
  log(`batch ${i + 1}/${schedule.batches.length}: ${batch.join(', ')}`)

  const batchResults = await parallel(batch.map(id => () => {
    const spec = specs[id]
    if (!spec) throw new Error(`no spec provided for scheduled job id "${id}"`)
    return agent(spec.prompt, { phase: `batch-${i}`, label: id }).then(result => ({ id, result }))
  }))

  // parallel()'s contract resolves a throwing/rejecting thunk to `null` rather than
  // rejecting the whole call -- which means a missing spec (or any other per-job
  // failure) would otherwise vanish silently here, and the cycle would proceed straight
  // into the compliance review as if nothing were missing. Surface it instead: a batch
  // with any failed job id aborts the whole workflow rather than continuing on a
  // partial `results` set.
  const failedIds = batch.filter((id, idx) => !batchResults[idx])
  if (failedIds.length > 0) {
    throw new Error(
      `batch ${i + 1}/${schedule.batches.length} failed for job id(s): ${failedIds.join(', ')} ` +
      '-- each of these threw or rejected inside parallel() (commonly: no spec provided for that ' +
      'scheduled job id); aborting rather than silently continuing with a partial result set.'
    )
  }

  batchResults.forEach(r => { results[r.id] = r.result })
}

// Countersign is a real gate, not decoration: a REJECT means the countersigner
// disagrees with the review's overall verdict, which only makes sense if refusal
// can actually trigger a redo. Bounded exactly like ADR-0017's A:B:C loop --
// max 2 review<->countersign rounds, non-convergence escalates for the orchestrator
// to adjudicate, never a silent 3rd automated round. Each agent() call is a fresh,
// memoryless instance, so "off-hands" convergence requires explicitly serializing
// every prior round's review + countersign text into the next round's prompt --
// there is no shared conversation to lean on.
const MAX_COMPLIANCE_ROUNDS = 2

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    adr_0000: { type: 'string', description: 'Type-driven-design verdict and findings, including any cross-item refactor implication' },
    adr_0012: { type: 'string' },
    adr_0013: { type: 'string', description: 'Execution-integrity verdict: scope-shrinking or self-audit findings, if any' },
    violations: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          line: { type: 'number' },
          description: { type: 'string' },
        },
        required: ['file', 'description'],
      },
    },
    refactor_warranted: { type: 'boolean' },
    refactor_description: { type: 'string' },
  },
  required: ['adr_0000', 'adr_0012', 'adr_0013', 'violations', 'refactor_warranted'],
}

const COUNTERSIGN_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['CONFIRM', 'CONFIRM_WITH_CORRECTIONS', 'REJECT'] },
    corrections: { type: 'array', items: { type: 'string' } },
    rationale: { type: 'string' },
  },
  required: ['verdict', 'rationale'],
}

function reviewPrompt(round, priorRounds) {
  const history = priorRounds.length === 0 ? '' : `

THIS IS ROUND ${round}. An earlier review of this same diff was REJECTED by an independent countersigner -- read exactly why below and produce a genuinely revised review that addresses it, not a repeat of the same pass. Every prior round is included in full so you aren't redoing blind work the first attempt already covered.

${priorRounds.map((r, idx) => `--- ROUND ${idx + 1} REVIEW ---\n${JSON.stringify(r.review, null, 2)}\n--- ROUND ${idx + 1} COUNTERSIGN (verdict: ${r.countersign.verdict}) ---\n${r.countersign.rationale}${r.countersign.corrections?.length ? '\nCorrections named:\n- ' + r.countersign.corrections.join('\n- ') : ''}`).join('\n\n')}`

  return `Working directory: ${repoRoot}. Run 'git diff' and 'git log' yourself to see EVERY change made across this entire cycle -- do not scope your review to a single file or a single work item, read the whole cycle's diff.

Read these ADRs in full before judging anything, for their spirit, not just their letter: ${adrPaths.join(', ')}.

Review the cycle's ENTIRE diff for compliance with those ADRs:
- ADR-0000 (type-driven design): is there a "faculty that corrupts" anywhere -- data ad-hoc-typed or ad-hoc-validated where a real type/invariant should exist instead? Critically: does the COMBINATION of this cycle's changes reveal a refactor that is now warranted, that would NOT have been visible from any single item's diff alone (e.g. two items independently introducing incompatible patterns, or duplicated logic that only becomes obvious once you see every item together)?
- ADR-0012: apply as written.
- ADR-0013 (execution integrity): confirm no item in this cycle shrank its own scope for feasibility reasons dressed as a design decision, and that no item self-audited its own work in place of an independent check.

Report a per-ADR verdict, every violation found (cite exact file:line, quoting the offending code), and -- if and only if you believe a refactor is now warranted per ADR-0000 -- say so explicitly via refactor_warranted/refactor_description, naming concretely what it would change. Do NOT implement it and do NOT assume the current dependency graph still holds -- that is flagged for the orchestrator to re-schedule, since new precedence edges are a load-bearing decision this review pass does not get to make unilaterally.${history}`
}

function countersignPrompt(round, review, priorRounds) {
  const history = priorRounds.length === 0 ? '' : `

Prior rounds, for context on what has already been rejected and why -- judge THIS round's review on its own merits against the diff, don't just check whether it differs from the past:

${priorRounds.map((r, idx) => `--- ROUND ${idx + 1} COUNTERSIGN (verdict: ${r.countersign.verdict}) ---\n${r.countersign.rationale}`).join('\n\n')}`

  return `Working directory: ${repoRoot}. A colleague (a different Sonnet instance) just produced the ADR-00{00,12,13} compliance review below (round ${round}), covering this entire cycle's diff in one pass.

Your job is NOT to re-review the code from scratch. It is to AUDIT THE REVIEW ITSELF for misattribution and error -- a single reviewer covering a whole cycle's diff in one pass can miscite a line, attribute a finding to the wrong file, overstate or understate a violation's severity, or simply miss something the diff plainly shows. Independently re-run 'git diff'/'git log' yourself and check, claim by claim: does every citation actually match what the diff currently shows? Is refactor_warranted (if true) actually supported by what you see, or is it invented, or wrongly omitted when it should be true?

Report your own independent verdict: CONFIRM (the review is accurate as written), CONFIRM_WITH_CORRECTIONS (list precisely what was mis-cited, misattributed, or missed, in "corrections"), or REJECT (the review's overall verdict is wrong -- say why, citing the diff yourself, in "rationale").${history}

THE REVIEW TO AUDIT:

${JSON.stringify(review, null, 2)}`
}

const complianceRounds = []
let round = 1
while (true) {
  phase('compliance-review')
  const review = await agent(reviewPrompt(round, complianceRounds), {
    phase: 'compliance-review',
    label: `sonnet-compliance-review-r${round}`,
    schema: REVIEW_SCHEMA,
  })

  phase('compliance-countersign')
  const countersign = await agent(countersignPrompt(round, review, complianceRounds), {
    phase: 'compliance-countersign',
    label: `sonnet-countersign-r${round}`,
    schema: COUNTERSIGN_SCHEMA,
  })

  complianceRounds.push({ review, countersign })
  log(`compliance round ${round}: countersign verdict = ${countersign.verdict}`)

  if (countersign.verdict !== 'REJECT') break
  if (round >= MAX_COMPLIANCE_ROUNDS) {
    log(`compliance review did NOT converge after ${MAX_COMPLIANCE_ROUNDS} rounds -- stopping, not looping further; this escalates to the orchestrator to adjudicate rather than a silent 3rd automated round`)
    break
  }
  round++
}

const finalRound = complianceRounds[complianceRounds.length - 1]
const converged = finalRound.countersign.verdict !== 'REJECT'

return { results, complianceRounds, converged, finalReview: finalRound.review, finalCountersign: finalRound.countersign }
