export const meta = {
  name: 'consult-cycle-workflow',
  description: 'Execute one fix-point consult cycle: topologically-batched implementation phases (from a precomputed makespan-scheduler schedule), then a single whole-diff ADR-00{00,12,13} compliance review, countersigned by an independent auditor.',
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

  batchResults.filter(Boolean).forEach(r => { results[r.id] = r.result })
}

phase('compliance-review')
const complianceReview = await agent(`Working directory: ${repoRoot}. Run 'git diff' and 'git log' yourself to see EVERY change made across this entire cycle -- do not scope your review to a single file or a single work item, read the whole cycle's diff.

Read these ADRs in full before judging anything, for their spirit, not just their letter: ${adrPaths.join(', ')}.

Review the cycle's ENTIRE diff for compliance with those ADRs:
- ADR-0000 (type-driven design): is there a "faculty that corrupts" anywhere -- data ad-hoc-typed or ad-hoc-validated where a real type/invariant should exist instead? Critically: does the COMBINATION of this cycle's changes reveal a refactor that is now warranted, that would NOT have been visible from any single item's diff alone (e.g. two items independently introducing incompatible patterns, or duplicated logic that only becomes obvious once you see every item together)?
- ADR-0012: apply as written.
- ADR-0013 (execution integrity): confirm no item in this cycle shrank its own scope for feasibility reasons dressed as a design decision, and that no item self-audited its own work in place of an independent check.

Report: a per-ADR verdict, every violation found (cite exact file:line, quoting the offending code), and -- if and only if you believe a refactor is now warranted per ADR-0000 -- say so explicitly, name concretely what it would change, but do NOT implement it and do NOT assume the current dependency graph still holds. Flag it plainly as requiring re-scheduling by the orchestrator, since new precedence edges are a load-bearing decision, not something this review pass gets to decide unilaterally.`, { phase: 'compliance-review', label: 'sonnet-compliance-review' })

phase('compliance-countersign')
const countersign = await agent(`Working directory: ${repoRoot}. A colleague (a different Sonnet instance) just produced the ADR-00{00,12,13} compliance review below, covering this entire cycle's diff in one pass.

Your job is NOT to re-review the code from scratch. It is to AUDIT THE REVIEW ITSELF for misattribution and error -- a single reviewer covering a whole cycle's diff in one pass can miscite a line, attribute a finding to the wrong file, overstate or understate a violation's severity, or simply miss something the diff plainly shows. Independently re-run 'git diff'/'git log' yourself and check, claim by claim: does every citation actually match what the diff currently shows? Is the refactor-warranted verdict (if the review made one) actually supported by what you see, or is it invented, or wrongly omitted?

Report your own independent verdict: CONFIRM (the review is accurate as written), CONFIRM WITH CORRECTIONS (list precisely what was mis-cited, misattributed, or missed), or REJECT (the review's overall verdict is wrong -- say why, citing the diff yourself).

THE REVIEW TO AUDIT:

${complianceReview}`, { phase: 'compliance-countersign', label: 'sonnet-countersign' })

return { results, complianceReview, countersign }
