// Mock test harness for scripts/cycle-workflow-template.mjs.
//
// cycle-workflow-template.mjs is NOT a standalone module -- it's a script body meant
// to be executed by a custom "Workflow" tool runtime that injects `args`, `agent`,
// `phase`, `log`, `parallel` (and, hypothetically, `pipeline`) as globals before running
// the file's top-level code (which uses top-level `await` and a top-level `return`).
//
// This harness loads the real source, strips the `export` off `export const meta = {...}`
// (so the object-literal declaration is legal inside a function body), wraps the
// remainder as the body of an AsyncFunction whose parameters are exactly the injected
// names, and then drives that function with scriptable mocks -- so we exercise the
// script's REAL logic, not a reimplementation of it.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import assert from 'node:assert/strict'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SCRIPT_PATH = path.join(__dirname, 'cycle-workflow-template.mjs')

// ---------------------------------------------------------------------------
// 1. Load + transform the script source into a runnable AsyncFunction body.
// ---------------------------------------------------------------------------

function loadScriptBody() {
  const source = readFileSync(SCRIPT_PATH, 'utf8')
  const marker = 'export const meta = {'
  const idx = source.indexOf(marker)
  assert.ok(idx !== -1, 'expected to find "export const meta = {" in the script source')
  // Rename `export const meta` -> `const meta` (drop the illegal-inside-a-function `export`).
  const transformed = source.slice(0, idx) + 'const meta = {' + source.slice(idx + marker.length)
  return transformed
}

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor

function buildRunner() {
  const body = loadScriptBody()
  // Params match exactly the globals the real Workflow runtime injects, plus a
  // no-op `pipeline` stub in case the script ever grows a call to it (not currently used).
  return new AsyncFunction('args', 'agent', 'phase', 'parallel', 'log', 'pipeline', body)
}

// ---------------------------------------------------------------------------
// 2. Scriptable mocks.
// ---------------------------------------------------------------------------

// parallel(): records how it was called (batch sizes) so we can assert batches were
// actually issued as separate calls, and implements the "thunk throws/rejects -> null,
// does not reject the whole call" contract.
function makeParallel(parallelCallLog) {
  return async function parallel(thunks) {
    parallelCallLog.push(thunks.length)
    return Promise.all(
      thunks.map(async (thunk) => {
        try {
          return await thunk()
        } catch (err) {
          return null
        }
      })
    )
  }
}

function makeLog(logLines) {
  return function log(message) {
    logLines.push(message)
  }
}

function makePhase(phaseLog) {
  return function phase(title) {
    phaseLog.push(title)
  }
}

async function pipelineStub() {
  return []
}

// agent() dispatch mock: a function of (prompt, opts) -> value, plus a call log
// capturing every (prompt, opts) pair actually passed, so tests can inspect the real
// prompt strings (needed for scenario d's history-serialization check).
function makeAgent(dispatch) {
  const calls = []
  const agent = async function agent(prompt, opts) {
    calls.push({ prompt, opts })
    const result = dispatch(prompt, opts, calls.length)
    if (result && typeof result.then === 'function') return result
    return result
  }
  agent.calls = calls
  return agent
}

// ---------------------------------------------------------------------------
// Test scaffolding
// ---------------------------------------------------------------------------

const results = []

function test(name, fn) {
  try {
    fn()
    results.push({ name, pass: true })
    console.log(`PASS: ${name}`)
  } catch (err) {
    results.push({ name, pass: false, error: err })
    console.log(`FAIL: ${name}`)
    console.log(`  ${err && err.stack ? err.stack : err}`)
  }
}

async function asyncTest(name, fn) {
  try {
    await fn()
    results.push({ name, pass: true })
    console.log(`PASS: ${name}`)
  } catch (err) {
    results.push({ name, pass: false, error: err })
    console.log(`FAIL: ${name}`)
    console.log(`  ${err && err.stack ? err.stack : err}`)
  }
}

const REPO_ROOT = '/fake/repo'
const ADR_PATHS = ['law/adr/0000-fake.md']

// ---------------------------------------------------------------------------
// Scenario (a): guard clause on missing/malformed schedule.
// ---------------------------------------------------------------------------

async function scenarioGuardClause() {
  const runner = buildRunner()
  const logLines = []
  const phaseLog = []
  const parallelCallLog = []
  const agent = makeAgent(() => {
    throw new Error('agent() should never be called when the guard clause fires')
  })

  const cases = [
    { label: 'schedule missing entirely', args: { repoRoot: REPO_ROOT, adrPaths: ADR_PATHS, specs: {} } },
    { label: 'schedule.batches missing', args: { repoRoot: REPO_ROOT, adrPaths: ADR_PATHS, schedule: {}, specs: {} } },
    {
      label: 'schedule.batches not an array',
      args: { repoRoot: REPO_ROOT, adrPaths: ADR_PATHS, schedule: { batches: 'nope' }, specs: {} },
    },
    {
      label: 'schedule.batches empty array',
      args: { repoRoot: REPO_ROOT, adrPaths: ADR_PATHS, schedule: { batches: [] }, specs: {} },
    },
  ]

  for (const c of cases) {
    let threw = false
    let message = ''
    try {
      await runner(c.args, agent, makePhase(phaseLog), makeParallel(parallelCallLog), makeLog(logLines), pipelineStub)
    } catch (err) {
      threw = true
      message = String(err && err.message)
    }
    assert.ok(threw, `expected a throw for case: ${c.label}`)
    assert.match(message, /precomputed schedule/i, `expected a clear error message for case: ${c.label}, got: ${message}`)
  }

  assert.equal(agent.calls.length, 0, 'agent() must never be invoked when the guard clause fires')
}

// ---------------------------------------------------------------------------
// Scenario (b): missing spec for a scheduled job id.
// ---------------------------------------------------------------------------

async function scenarioMissingSpec() {
  const runner = buildRunner()
  const logLines = []
  const phaseLog = []
  const parallelCallLog = []
  const agent = makeAgent(() => {
    throw new Error('agent() should not be reached for a job with no spec')
  })

  const args = {
    repoRoot: REPO_ROOT,
    adrPaths: ADR_PATHS,
    schedule: { batches: [['jobA']] },
    specs: {}, // no entry for "jobA"
  }

  let threw = false
  let message = ''
  try {
    await runner(args, agent, makePhase(phaseLog), makeParallel(parallelCallLog), makeLog(logLines), pipelineStub)
  } catch (err) {
    threw = true
    message = String(err && err.message)
  }

  // Post-fix behavior: the missing spec must be SURFACED as a thrown error naming the
  // job id, not silently absorbed by parallel()'s null-on-throw contract.
  assert.ok(threw, 'a missing spec must surface as a thrown error from the workflow, not be silently swallowed')
  assert.match(message, /jobA/, `expected the surfaced error to name the missing job id, got: ${message}`)
}

// ---------------------------------------------------------------------------
// Scenario (c): happy path, 2 batches, all specs present, single compliance round.
// ---------------------------------------------------------------------------

async function scenarioHappyPath() {
  const runner = buildRunner()
  const logLines = []
  const phaseLog = []
  const parallelCallLog = []

  const dispatch = (prompt, opts) => {
    if (opts.label === 'a') return 'RESULT_A'
    if (opts.label === 'b') return 'RESULT_B'
    if (opts.label === 'c') return 'RESULT_C'
    if (opts.label === 'sonnet-compliance-review-r1') {
      return {
        adr_0000: 'compliant',
        adr_0012: 'compliant',
        adr_0013: 'compliant',
        violations: [],
        refactor_warranted: false,
      }
    }
    if (opts.label === 'sonnet-countersign-r1') {
      return { verdict: 'CONFIRM', rationale: 'looks correct' }
    }
    throw new Error(`unexpected agent() call in happy path: label=${opts.label}`)
  }

  const agent = makeAgent(dispatch)

  const args = {
    repoRoot: REPO_ROOT,
    adrPaths: ADR_PATHS,
    schedule: { batches: [['a', 'b'], ['c']] },
    specs: {
      a: { prompt: 'do a' },
      b: { prompt: 'do b' },
      c: { prompt: 'do c' },
    },
  }

  const out = await runner(args, agent, makePhase(phaseLog), makeParallel(parallelCallLog), makeLog(logLines), pipelineStub)

  assert.deepEqual(out.results, { a: 'RESULT_A', b: 'RESULT_B', c: 'RESULT_C' }, 'results should contain all 3 job ids with correct values')
  assert.equal(out.complianceRounds.length, 1, 'exactly one compliance round expected')
  assert.equal(out.converged, true, 'should have converged on CONFIRM')
  assert.equal(out.finalCountersign.verdict, 'CONFIRM')

  // Batches must be issued as separate parallel() calls: sizes [2, 1], not [3].
  assert.deepEqual(parallelCallLog, [2, 1], `expected two separate parallel() calls of sizes [2,1], got: ${JSON.stringify(parallelCallLog)}`)
}

// ---------------------------------------------------------------------------
// Scenario (d): REJECT on round 1, CONFIRM on round 2 -- verify convergence AND
// that round-2 prompts really serialize round-1's review/countersign text.
// ---------------------------------------------------------------------------

async function scenarioConvergenceAfterRetry() {
  const runner = buildRunner()
  const logLines = []
  const phaseLog = []
  const parallelCallLog = []

  const ROUND1_RATIONALE = 'ROUND1_RATIONALE_MARKER: adr_0000 finding was overstated'

  const dispatch = (prompt, opts) => {
    if (opts.label === 'a') return 'RESULT_A'
    if (opts.label === 'sonnet-compliance-review-r1') {
      return {
        adr_0000: 'issue found',
        adr_0012: 'compliant',
        adr_0013: 'compliant',
        violations: [{ file: 'x.js', description: 'bad thing' }],
        refactor_warranted: false,
      }
    }
    if (opts.label === 'sonnet-countersign-r1') {
      return { verdict: 'REJECT', rationale: ROUND1_RATIONALE }
    }
    if (opts.label === 'sonnet-compliance-review-r2') {
      // Assert the round-2 REVIEW prompt actually includes round-1's rationale text.
      assert.match(prompt, new RegExp(ROUND1_RATIONALE), 'round-2 review prompt must serialize round-1 countersign rationale')
      return {
        adr_0000: 'resolved',
        adr_0012: 'compliant',
        adr_0013: 'compliant',
        violations: [],
        refactor_warranted: false,
      }
    }
    if (opts.label === 'sonnet-countersign-r2') {
      // Assert the round-2 COUNTERSIGN prompt actually includes round-1's rationale text.
      assert.match(prompt, new RegExp(ROUND1_RATIONALE), 'round-2 countersign prompt must serialize round-1 countersign rationale')
      return { verdict: 'CONFIRM_WITH_CORRECTIONS', corrections: ['tightened wording'], rationale: 'now accurate' }
    }
    throw new Error(`unexpected agent() call in convergence-after-retry: label=${opts.label}`)
  }

  const agent = makeAgent(dispatch)

  const args = {
    repoRoot: REPO_ROOT,
    adrPaths: ADR_PATHS,
    schedule: { batches: [['a']] },
    specs: { a: { prompt: 'do a' } },
  }

  const out = await runner(args, agent, makePhase(phaseLog), makeParallel(parallelCallLog), makeLog(logLines), pipelineStub)

  assert.equal(out.complianceRounds.length, 2, 'expected exactly 2 compliance rounds')
  assert.equal(out.converged, true, 'should have converged after round 2 (CONFIRM_WITH_CORRECTIONS is not REJECT)')
  assert.equal(out.finalCountersign.verdict, 'CONFIRM_WITH_CORRECTIONS')

  // Double-check the actual captured prompts (not just that dispatch's own inline
  // assertions ran) really contain the round-1 text end-to-end.
  const round2ReviewCall = agent.calls.find((c) => c.opts.label === 'sonnet-compliance-review-r2')
  const round2CountersignCall = agent.calls.find((c) => c.opts.label === 'sonnet-countersign-r2')
  assert.ok(round2ReviewCall, 'round-2 review call must have happened')
  assert.ok(round2CountersignCall, 'round-2 countersign call must have happened')
  assert.match(round2ReviewCall.prompt, new RegExp(ROUND1_RATIONALE))
  assert.match(round2CountersignCall.prompt, new RegExp(ROUND1_RATIONALE))
}

// ---------------------------------------------------------------------------
// Scenario (e): REJECT on both rounds -- non-convergence, stops at MAX_COMPLIANCE_ROUNDS.
// ---------------------------------------------------------------------------

async function scenarioNonConvergence() {
  const runner = buildRunner()
  const logLines = []
  const phaseLog = []
  const parallelCallLog = []

  const reviewLabelsSeen = []
  const countersignLabelsSeen = []

  const dispatch = (prompt, opts) => {
    if (opts.label === 'a') return 'RESULT_A'
    if (opts.label && opts.label.startsWith('sonnet-compliance-review-r')) {
      reviewLabelsSeen.push(opts.label)
      return {
        adr_0000: 'issue found',
        adr_0012: 'compliant',
        adr_0013: 'compliant',
        violations: [{ file: 'x.js', description: 'still bad' }],
        refactor_warranted: false,
      }
    }
    if (opts.label && opts.label.startsWith('sonnet-countersign-r')) {
      countersignLabelsSeen.push(opts.label)
      return { verdict: 'REJECT', rationale: `rejected at ${opts.label}` }
    }
    throw new Error(`unexpected agent() call in non-convergence: label=${opts.label}`)
  }

  const agent = makeAgent(dispatch)

  const args = {
    repoRoot: REPO_ROOT,
    adrPaths: ADR_PATHS,
    schedule: { batches: [['a']] },
    specs: { a: { prompt: 'do a' } },
  }

  const out = await runner(args, agent, makePhase(phaseLog), makeParallel(parallelCallLog), makeLog(logLines), pipelineStub)

  assert.equal(out.complianceRounds.length, 2, 'expected exactly 2 compliance rounds (MAX_COMPLIANCE_ROUNDS), not 3')
  assert.equal(out.converged, false, 'should NOT have converged -- both rounds rejected')
  assert.deepEqual(reviewLabelsSeen, ['sonnet-compliance-review-r1', 'sonnet-compliance-review-r2'], 'exactly 2 review calls, no 3rd round')
  assert.deepEqual(countersignLabelsSeen, ['sonnet-countersign-r1', 'sonnet-countersign-r2'], 'exactly 2 countersign calls, no 3rd round')

  const escalationLine = logLines.find((l) => /did NOT converge|non-convergen|escalat/i.test(l))
  assert.ok(escalationLine, `expected a log() call announcing non-convergence/escalation, got log lines: ${JSON.stringify(logLines)}`)
}

// ---------------------------------------------------------------------------
// Run everything.
// ---------------------------------------------------------------------------

async function main() {
  await asyncTest('(a) guard clause on missing/malformed schedule', scenarioGuardClause)
  await asyncTest('(b) missing spec for scheduled job id', scenarioMissingSpec)
  await asyncTest('(c) happy path: 2 batches, 3 jobs, single compliance round', scenarioHappyPath)
  await asyncTest('(d) convergence after retry: round1 REJECT, round2 CONFIRM_WITH_CORRECTIONS', scenarioConvergenceAfterRetry)
  await asyncTest('(e) non-convergence: REJECT both rounds, stops at MAX_COMPLIANCE_ROUNDS', scenarioNonConvergence)

  console.log('')
  console.log('--- SUMMARY ---')
  let anyFail = false
  for (const r of results) {
    console.log(`${r.pass ? 'PASS' : 'FAIL'}: ${r.name}`)
    if (!r.pass) anyFail = true
  }

  if (anyFail) {
    console.log('\nRESULT: FAIL')
    process.exit(1)
  } else {
    console.log('\nRESULT: PASS')
    process.exit(0)
  }
}

main().catch((err) => {
  console.error('Harness crashed unexpectedly:', err)
  process.exit(1)
})
