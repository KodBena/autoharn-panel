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

---

## Finding 1 — `led work depends` silently defaults to an *unenforced* edge type

**What happened.** `./led work depends <slug> <on-slug>` records a dependency
edge between two work items. If the caller omits `--type`, the command does
not refuse and does not warn-then-ask — it silently writes `edge_type =
informs`, an **advisory-only** edge that is never checked at close time. The
*enforced* option, `--type blocks-close`, must be typed explicitly by the
caller to get real gating (`autoharn/kernel/lineage/s30-typed-dependency-edges.sql`
is the schema that distinguishes the two edge types at all; a pre-s30 kernel
has no `edge_type` column and the flag is refused outright).

**Why it is surprising.** The natural-language command name — "work depends
on" — reads exactly like a precedence constraint ("this can't close before
that"). Nothing in the bare invocation signals that the *unqualified* form is
advisory-only. A caller who writes every dependency edge in a decomposition
without ever typing `--type` walks away believing they have recorded real
ordering constraints; they have recorded notes.

**Concrete evidence.**
- `autoharn/bootstrap/templates/led.tmpl`, the live-executed `led` command
  template, lines ~1058–1120: the `--type` parsing block. Line 1085 probes for
  the `edge_type` column; when `--type` is omitted, the INSERT (line ~1118)
  still runs and writes `informs` — confirmed by reading the literal SQL text
  and the surrounding stderr advisories at lines 1109–1110 ("recorded as
  informs (advisory only — never enforced at close); if `<on-slug>` must be
  finished before `<slug>` may close, use `--type blocks-close`.").
- Live, in this deployment's own ledger: row 220 (`./led show 220`) is itself a
  `work_depends_on` edge (`autoharn-adoption-history-doc` depends on
  `abc-loop-adoption`) written without `--type`, and its stored `edge_type`
  column reads `informs` — a real specimen of the default firing, not a
  hypothetical.
- Row 178 (`./led show 178`, this deployment's own ledger, `finding` kind)
  independently surfaced this via `./orchlog`, noting: "every `work_depends_on`
  edge I created earlier this session used no `--type` flag, so their
  enforcement status needs checking, not assumed."

**Severity if cargo-culted at NRC/NIST-grade stakes.** A team building a
regulatory decomposition (e.g., "safety review B cannot close before hazard
analysis A closes") who uses the obvious, unqualified command form gets a
*ledger row that looks like a dependency but enforces nothing* — the successor
item can close with the antecedent still open, and nothing about the ledger
state says so unless someone thinks to ask "was this typed `blocks-close`?"
This is a silent false-confidence gap of exactly the kind the framing above
warns about: the ledger *looks* governed and is not, on a class of edge most
operators would assume is the strict one by default.

---

## Finding 2 — the closure-debt summary tool reads different, and *fewer*, views than the stop-gate that actually blocks

**What happened.** `./distance-to-clean` (this repo's shim at
`distance-to-clean`, which execs `autoharn/bootstrap/templates/distance-to-clean.tmpl`)
is documented and intended as a one-pass summary of "how far am I from a clean
stop." Its own module docstring states it reads "the SAME THREE EXISTING
VIEWS" `led review-gap`, `led question-status`, and `led work violations`
already read. Independently confirmed by reading the tool's source
(`autoharn/bootstrap/templates/distance-to-clean.tmpl`, functions
`review_gap_debt` at line 200, `question_status_debt` at line 214,
`work_violations_debt` at line 230, wired together in `main()` at line 244):
it queries exactly `review_gap`, `question_status`, and `work_item_violations`
— and, when `mechanisms.doc_attestation.mode` is `observe`, a fourth,
opt-in doc-attestation check.

But the Stop hook that actually enforces "clean before you stop" —
`autoharn/hooks/stop_clean_exit.py` — checks **five** categories
(`_collect_debt()`, lines 518–678): the same `review_gap` and
`question_status`, plus **`work_item_current`** (open items claimed by *this*
session, undischarged and unbequeathed — lines 564–636) and
**`work_review_gap`** (deferred-review obligations from a typed close — lines
666–676). `distance-to-clean` has **no query against either of those two
views at all** — not a naming collision alone, but a genuine coverage gap:
even a caller who knows to look for `work_review_gap` specifically will not
find it queried anywhere in `distance-to-clean.tmpl`, and the tool also never
looks at claimed-but-open work items, which is exactly the condition the
stop-gate's Finding-name ("OPEN WORK ITEMS ... claimed by this session") most
commonly blocks on in practice.

**Why it is surprising.** The tool's entire purpose, stated in its own
docstring, is to answer "how far am I from a clean stop" in one call, because
run-10's retrospective found operators bare-polling `review-gap` alone 47
times for lack of exactly this composed view. But the composition it actually
ships checks a strict *subset* of what the Stop hook checks — so a caller who
trusts "TOTAL debt: 0 (0 = clean)" and tries to stop can still be blocked
moments later by categories `distance-to-clean` never looked at. This was
**witnessed live, repeatedly, this session**: the tool reported 0/clean while
the stop-gate then found and blocked on real debt (a claimed open item and/or
a deferred-review obligation) moments later.

**Concrete evidence.**
- View definitions confirmed distinct by grep:
  `grep -n "CREATE OR REPLACE VIEW.*review_gap\|CREATE OR REPLACE VIEW.*work_review_gap" autoharn/kernel/lineage/*.sql`
  shows `review_gap` defined in `s13-schema.sql:406`, `s14-schema.sql:455`,
  `s15-schema.sql:307`, `s32-edge-views-single-home.sql:376`, and
  `work_review_gap` defined separately in
  `s29-obligation-item-key-and-typed-close.sql:719`,
  `s31-supersession-uniform-retraction.sql:359`, and
  `s32-edge-views-single-home.sql:406` — two different view names, two
  different definitions, not an alias.
- `distance-to-clean.tmpl` line 203: `SELECT id FROM {dep.schema}.review_gap
  ORDER BY id;` — no reference to `work_review_gap` anywhere in the file.
- `distance-to-clean.tmpl`'s `main()` (lines 244–302) calls exactly
  `review_gap_debt`, `question_status_debt`, `work_violations_debt`, and
  (conditionally) `doc_attestation_debt` — no fifth function, no query against
  `work_item_current`.
- `stop_clean_exit.py` lines 564–678 (`_collect_debt`): the fourth and fifth
  categories, `work_item_current` (claimed-open items) and `work_review_gap`,
  both queried and both capable of producing blocking `debt_lines`.
- Row 220 (`./led show 220`) records this exact finding from this deployment's
  own work, independently.

**Severity if cargo-culted at NRC/NIST-grade stakes.** This is the sharpest
finding in this file: a tool whose entire advertised purpose is "tell me
truthfully whether I am clean to stop" can report **0/clean** while the
authoritative gate blocks on real, uncounted debt. In a regulatory context
where "clean" is read as a go/no-go signal by a human or a downstream process
that trusts the summary tool rather than re-deriving from the Stop hook
itself, this is exactly the "silent false-confidence gap" the framing above
names as the one class of finding that belongs in this file. It is not fixed
as of this writing.

---

## Finding 3 — fixed: `gates/link_integrity.py`'s scan root was hardcoded to autoharn's own checkout

**Status: already fixed**, recorded here as a fixed finding per the
maintainer's explicit instruction, not as an open item.

**What happened.** `autoharn/gates/link_integrity.py` checks that documentation
cross-links resolve. Its `ROOT` was derived from `__file__` — i.e., it always
scanned autoharn's own checkout, regardless of which project's `cwd` invoked
it. For an adopting deployment (like this one) checking its *own* docs for
dangling links, this silently scanned the wrong repository and could report a
false "clean ✓" for the calling project's own docs, because it was never
looking at them.

**Why it was surprising.** A gate named `link_integrity` with no `--repo` or
similar target flag reads, on its face, as "checks the docs of whatever
invoked it" — the opposite of a gate hardwired to check only its own source
tree's docs regardless of caller. An adopting deployment running this gate
against itself would see a pass with zero actual coverage of its own
documentation.

**Concrete evidence of the fix.**
`git -C autoharn log --oneline -1 gates/link_integrity.py` →
`14ffcae gates/link_integrity.py: add --repo to check a target other than
this checkout`. This is a real, committed change (not a working-tree edit),
verified live at the time of writing. The maintainer requested this fix
directly, and the ledgered note describing this finding states it was
"verified both directions" (the gate now correctly scans the target repo when
`--repo` is passed, and still scans its own checkout by default when it is
not).

**Severity if cargo-culted at NRC/NIST-grade stakes (historical, now closed).**
Had this shipped unfixed into a high-stakes deployment, a team invoking this
gate as "our documentation's cross-links are verified clean" would have been
looking at a report about a *different* repository's documentation. This is
the same silent-false-confidence shape as Finding 2, now closed upstream.

---

## Finding 4 — the delegation observer's own teach-text overstates what it actually checks

**What happened.** `autoharn/hooks/pretooluse_delegation_observer.py` fires on
every subagent dispatch (`Task`/`Agent` tool calls) and, in `observe` mode,
prints a warning when it judges delegation to be under-governed. Its own
module docstring (lines 32–39) and the warning text it emits (`_emit_warning`,
lines 331–345) both frame the obligation as two things: "ledger the delegation
[as a `decision` row] AND/OR claim a work item." But the actual firing
condition, read directly from the code (`main()`, line 420):

```python
if has_work_item_layer() and not has_open_claimed_work_item():
    _emit_warning(description)
```

checks **only** whether an open, claimed work item exists
(`has_open_claimed_work_item()`, lines 280–290: `state = 'open' AND claimant
IS NOT NULL`). It never queries the ledger for a `decision` row recording what
was delegated or why — despite the warning text it prints naming exactly that
as one of the two acceptable remedies, and despite CLAUDE.md's own point 7
("Dispatching a subagent is a `decision` row (what is delegated, why)") being
quoted verbatim inside the warning banner itself (line 334–335).

**Why it is surprising.** The hook's own printed guidance tells the operator
two ways to be compliant; only one of them is actually checked. A fully
compliant operator (files the `decision` row *and* has a claimed work item)
and a partially compliant one (has a claimed work item, never filed the
`decision` row explaining the delegation) receive **the identical warning
outcome**: no warning at all, in both cases, because the code only ever tests
`has_open_claimed_work_item()`. The reverse is also true: an operator who
diligently files the `decision` row but has no open+claimed work item still
gets warned, as if they'd done nothing. The signal this hook exists to
produce — "was the delegation properly recorded?" — is eroded to "is there an
open, claimed item?", a materially weaker and different question than the one
its own teach-text describes.

**Concrete evidence.**
- `autoharn/hooks/pretooluse_delegation_observer.py` line 420: the sole
  conditional gating `_emit_warning`, calling only `has_open_claimed_work_item()`.
  No call anywhere in the file queries `kind = 'decision'` or any decision-row
  content.
- Same file, `_emit_warning()`, lines 331–345: the printed banner names both
  remedies ("ledger the delegation BEFORE it starts, and/or cover it with an
  open+claimed work item") and shows `./led decision "<what is delegated,
  why>"` as the first line of `DENY_HINT` (line 326–328) — i.e., the tool's
  own text describes a check it does not perform.
- Row 220 (`./led show 220`) independently names this exact gap, from reading
  this same source file.

**Severity if cargo-culted at NRC/NIST-grade stakes.** This is a governance
*signal-degradation* risk rather than a silent-pass risk: the hook never
claims to block anything (it is explicitly observer-only — see the file's own
"OBSERVER ONLY" docstring section), so nothing is falsely marked clean. But an
audit process built on the assumption that "this warning fires iff the
delegation-recording discipline was skipped" would be measuring the wrong
thing — a team could pass this check every time by opening a throwaway
work-item claim, with the actual "what/why" narrative CLAUDE.md's point 7
demands never recorded anywhere, and no warning would ever say so.

---

## Finding 5 (open question, not a verdict) — the stop-gate's "fail open after 3 identical attempts" design

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

## Finding 6 — flipping `doc_attestation` to `observe`, exactly as its own note instructs, floods the debt count with vendor dependency files ADR-0017 never intended to cover

**What happened.** `.claude/apparatus.json`'s `mechanisms.doc_attestation` ships `mode:
"off"` with a note that reads, verbatim: "Flip to 'observe' once you're actually
running the loop ... so `./distance-to-clean` surfaces its debt alongside
review-gap/question-status/work-violations." Following that instruction literally —
flipping `mode` to `observe` and running `./distance-to-clean` — produced `TOTAL debt:
155`, immediately after the flip, with **no other change to the repo**. Running
`./attest-doc check` directly confirms the same 155: `attest-doc check: 1 ATTESTED, 0
STALE, 155 NO-ATTESTATION`. Of those 155, 118 are files under `frontend/node_modules/**`
or `venv/lib/python3.13/site-packages/**` — e.g. `frontend/node_modules/vite/README.md`,
`frontend/node_modules/typescript/SECURITY.md`,
`venv/lib/python3.13/site-packages/pip/_vendor/idna/LICENSE.md` — confirmed both
gitignored (`git check-ignore -v` resolves both to their respective `.gitignore` rules,
`frontend/.gitignore:10:node_modules` and `venv/.gitignore:2:*`). This is not the scope
ADR-0017 itself names: `law/adr/0017-the-zero-context-reader.md`'s own Scope section
(line 37) reads "Every **maintainer-facing document** authored or edited from
ratification onward — READMEs, design notes, rulings, briefs, capability and operating
documents, BACKLOG entries, ADRs themselves" — a vendored dependency's own upstream
README or LICENSE is authored and edited by neither this deployment nor its maintainer,
and was never plausibly meant to fall under a fresh-context legibility audit obligation
scoped to *this project's own* documentation. The disposition: I (the orchestrator, this
session) reverted the flip back to `off` immediately upon seeing the 155-item flood,
rather than leave a misleading debt count live in the deployment's own apparatus state.

**Why it is surprising.** The switch's own note frames flipping it as the intended,
expected next step once a maintainer starts running the A:B:C loop — not as something
that needs a scope patch first. A maintainer who does exactly what the note tells them to
do gets, on the very first `distance-to-clean` run afterward, a debt count dominated
15-to-1 by files they will never plausibly attest (an npm package's own upstream
CHANGELOG, a pip-vendored license file), rather than debt for their own project prose.

**Concrete evidence — root cause, confirmed by reading both scope-detection paths.**
`autoharn/gates/link_integrity.py`'s `tracked_md()` (line 98–102) restricts its entire
scan to `git ls-files '*.md'` — git-TRACKED files only — so a gitignored vendor tree
never enters its scope at all; `doc_attestation_presence.py`'s *own* commit-time gate
path does the identical restriction, via its own `_tracked_md()` (lines 296–299), same
`git ls-files '*.md'` call. **But that is not the function this deployment's tooling
actually calls.** `doc_attestation_presence.py` additionally exports `discover_md()`
(lines 436–462), whose own docstring states the design choice explicitly: "a plain
on-disk walk, unconditionally, never `git ls-files`" — and names why, calling out a
prior version that preferred `git ls-files` and got caught, in an out-of-frame
hack-rationalization audit, silently returning `[]` on a git-initialized-but-nothing-
committed tree (a false-CLEAN). The fix chosen was to make `discover_md()` walk raw
disk unconditionally instead — sound for its stated worry (an uncommitted-but-real new
`.md` file should not be invisible), but it does not consult `.gitignore` at all, so a
`node_modules/` or `site-packages/` tree — always present on disk, never git-tracked,
and enormous — is swept in on equal footing with the maintainer's own docs. Both
`bootstrap/templates/attest-doc.tmpl`'s `cmd_check()` (line 145: `targets =
dap.discover_md(PROJECT_ROOT)`) and `bootstrap/templates/distance-to-clean.tmpl`'s
DOC-ATTESTATION section (line 160: the identical call) call `discover_md()` — the raw-
filesystem walker — not `_tracked_md()`, the git-restricted one already proven correct
and already used by this same module's own commit-time gate and by
`link_integrity.py`'s sibling gate. The asymmetry is real and file:line-confirmed, not a
naming collision: the one scope-detector in this module that already solves this
problem correctly (`_tracked_md()`) is simply not the one wired into the two
deployment-facing entry points that produce the debt count a maintainer actually reads.

**Severity if cargo-culted at NRC/NIST-grade stakes.** Same silent-false-confidence shape
this file's framing exists to name, but inverted: this is not a false-clean, it is a
false-*alarm* flood, and the framing above holds that failure mode is just as dangerous
as false-clean. A maintainer who flips this switch expecting to see debt for their own
work instead gets a governance dashboard whose headline number is 87% dependency noise —
a strong, rational incentive to conclude the mechanism is broken and either (a) stop
trusting the debt count on sight going forward ("it's always full of npm garbage, ignore
the number"), which is crying wolf against exactly the discipline `distance-to-clean`
exists to make legible, or (b) leave `doc_attestation` permanently `off`, which defeats
the entire point of ADR-0017's fresh-context audit loop having a commit-time-blockable,
zero-cost enforcement floor at all. Both outcomes are the opposite of what flipping the
switch, as instructed, was meant to produce.

---

## Verification note

Every file path and line reference above was checked against the actual
on-disk source at the time of writing (both this repo,
`/home/bork/w/vdc/1/experience/autoharn-panel`, and the sibling `autoharn`
checkout at `/home/bork/w/vdc/1/experience/autoharn`), rather than transcribed
solely from prior ledger prose. Ledger rows cited (178, 220) were read via
`./led show <id>` and used as pointers to re-derive the underlying claim, not
as the claim's proof on their own.
