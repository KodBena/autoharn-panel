# Consult: autoharn-panel backend structural/architectural hygiene audit

This document records a backend-focused structural audit, distinct from this project's ongoing
UX/professionalism scout cycles, prompted by a real, witnessed incident this session: the shared
dev backend at `:8420` went genuinely unresponsive (multi-minute hangs, curl timeouts) under
concurrent load from several Playwright-driving verification sessions (ledger row 875's snag,
recorded live during the incident). The maintainer's own hypothesis, stated directly at commission
time: this would have been impossible with proper structural hygiene, and its absence is worth
auditing deliberately rather than patching around (commission row 881).

- **Date:** 2026-07-16
- **Commissioned via:** ledger row 881 (commission, LAZY-mode transcription), decomposed into work
  item `backend-structural-audit` (row 885, claimed row 886), itself citing
  `docs/omega-observatory/2026-07-15-structural-reap.md` entry 2 — a 2026-07-15 scout pass over the
  maintainer's private `omega` codebase that had already flagged, by name, that
  `backend/extensions/autoharn/ledger_read.py` "talks to Postgres directly from what looks like the
  request-handling layer" and recommended "carving a `ports.py` Protocol for the ledger reads panel
  needs before the SQL spreads across handlers" — a prediction this audit checks directly against
  current source, now that the file has grown well past the 538+ lines cited at that time.
- **Method:** one session, read-only — no Playwright, no live-Postgres querying, no dispatched
  subagents. `law/adr/0000-the-alpha-and-the-omega-type-driven-design.md` and
  `law/adr/0012-compositional-and-structural-hygiene.md` read in full (binding LAW, not
  aspirational guidance); `docs/omega-observatory/2026-07-15-structural-reap.md`,
  `2026-07-15-frontend-architecture-reap.md`, and `README.md` read in full (aspirational, per the
  maintainer's own framing); every non-empty `.py` file under `backend/core/` and
  `backend/extensions/autoharn/` (11 files) read line-by-line, plus `backend/app.py`,
  `backend/config.py`, `backend/db.py`, `backend/requirements*.txt`, and all 10 files under
  `tests/`. `psycopg`/`anyio`/`starlette` installed-package source was inspected directly (not
  taken from memory) to confirm version-specific threading behavior claimed below.
- **Recorded finding:** see the closing ledger row cited at the end of this document.
- **Work item:** `backend-structural-audit` (row 885), closed shipped on delivery of this document.

No production code was touched to produce this report — audit only, matching how the UX scouts in
this project operate.

---

# Backend structural/architectural hygiene audit: autoharn-panel

**Scope:** `backend/core/` (5 non-empty files: `backend_surface.py`, `ledger_read.py`,
`profiles_write.py`, `routes.py`, plus an empty `__init__.py`) and `backend/extensions/autoharn/`
(5 non-empty files: `cosign.py`, `disposition.py`, `ledger_read.py`, `routes.py`, plus an empty
`__init__.py`), plus the three top-level modules every route ultimately depends on
(`backend/app.py`, `backend/config.py`, `backend/db.py`). Total: 11 non-empty Python files, roughly
2,100 lines. Every file was read in full; nothing below is inferred from file names or line
counts alone.

## Severity scale

Reusing this project's UX-audit convention (CRITICAL/SERIOUS/MODERATE/MINOR), calibrated for
architecture rather than user-facing defects:

- **CRITICAL** — directly implicated in a witnessed production incident, or would be if load grew
  modestly; fixing it is not optional scope.
- **SERIOUS** — a real structural gap that is already costing something concrete (untestable
  surface, a confirmed doc-prediction now realized) even though it hasn't yet caused an outage.
- **MODERATE** — a defect class this codebase's own governing law (ADR-0012) names explicitly, real
  but not yet biting.
- **MINOR** — small, confirmed, cheap to fix, low blast radius.

---

## CRITICAL

### 1. Zero connection pooling — every request opens and closes a brand-new synchronous Postgres connection

`backend/db.py` is, by its own docstring, "the ONE place this backend opens a Postgres connection."
Both of its functions confirm this literally:

```python
def connect(cfg: PanelConfig) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(cfg.connection.conninfo(), row_factory=dict_row, autocommit=True)
    try:
        ...
        yield conn
    finally:
        conn.close()
```

`connect_unrestricted()` is byte-for-byte the same shape. There is no `psycopg_pool` import
anywhere in `backend/` (grep-confirmed), and `backend/requirements.txt` names only
`psycopg[binary]>=3.1` — no pooling library is even a dependency, let alone in use. Every one of
the ~30 query functions across `core/ledger_read.py`, `core/backend_surface.py`, and
`extensions/autoharn/ledger_read.py` calls `with connect(cfg) as conn, conn.cursor() as cur:` and
therefore pays a full TCP handshake + Postgres authentication handshake + `SET ROLE` + `SET
search_path`, on every single call, with the connection discarded the instant the query returns.
Some call paths compound this: `commissions()` (`extensions/autoharn/ledger_read.py:767`) opens a
fresh connection per commission row via `item_id_groups()` → `fetch_parsed_item_rows()` (two more
connections each), so a page listing C commissions issues roughly `1 + 3C` separate connect/close
cycles sequentially, on one request.

This is the single most concrete, actionable finding in this audit, and is discussed further under
"Diagnosis of the witnessed hang" below.

---

## SERIOUS

### 2. No ACL/Protocol/Ports boundary of any kind between route handlers and raw SQL — the reap doc's 2026-07-15 prediction, now fully realized

The omega structural-reap doc (entry 2, read 2026-07-15) predicted this exact defect from file
counts alone, without reading the file line-by-line: "`panel/backend/ledger_read.py` and
`cosign.py` currently talk to Postgres directly from what looks like the request-handling layer
(not yet verified in depth)." This audit verifies it directly, in full: there is no `ports.py`, no
`typing.Protocol`, no repository/adapter class, no dependency-injection seam of any kind anywhere
in this backend. Every route handler in `backend/core/routes.py` and
`backend/extensions/autoharn/routes.py` imports a `ledger_read` (or `backend_surface`, or
`profiles_write`) module directly and calls its module-level functions, each of which opens its own
connection and writes its own SQL inline as a Python string, e.g.:

```python
@router.get("/api/rows")
def api_rows(request: Request, ...):
    cfg = request.app.state.panel.cfg
    return ledger_read.rows(cfg, kind=kind, ...)
```

`ledger_read.rows()` itself builds a hand-assembled SQL string with an f-string `ORDER BY` clause
and parametrized `WHERE` fragments, executes it, and returns the rows — all in one function, in the
same module the route imports directly. There is no seam at which a test, a future caller, or a
second adapter (an in-memory fake, a different backing store) could substitute for "the thing that
answers `rows()`" without either hitting a live Postgres or monkeypatching `psycopg`/`db.connect`
itself.

The file the reap doc named, `extensions/autoharn/ledger_read.py`, was 538+ lines when the doc's
own follow-up work item was filed a few hours before this audit; it is **823 lines** now — the
predicted trajectory ("if panel's backend grows past its current ~260-line `app.py` ... before the
SQL spreads across handlers") has materialized in full: 30 module-level query functions, none
behind any boundary. This is the same conclusion the reap doc reached, now confirmed by direct
line-by-line reading rather than inferred from file counts, and confirmed against a codebase that
has grown substantially since the original scout pass.

`SPEC.md` §4 does declare one real, tested structural boundary — "the core knows Postgres-ledger-
generic concepts... everything autoharn-semantic... lives in an `extensions/autoharn` module,"
verified live by `tests/test_core_boundary.py` running the core API against a bare schema with the
extension disabled. That boundary is real and worth crediting: it is a genuine module-level seam,
mechanically tested. But it operates one level too high for this finding — it separates *which
ledger vocabulary* a module may reference, not *how* a module reaches Postgres. Both
`core/ledger_read.py` and `extensions/autoharn/ledger_read.py` independently talk to raw SQL
exactly the same (Protocol-free) way; the extension boundary the spec calls "the" architecture
constraint for this repo is silent on the ACL question this audit was commissioned to check.

### 3. `extensions/autoharn/ledger_read.py` is an 823-line god-module by ADR-0012 P3's own test

ADR-0012 P3 ("no god-objects") gives a concrete check: "can you name, in one clause, the single
concern this object owns? If naming its responsibility requires 'and,' it is two collaborators
wearing one class." Applied to this file: it owns commission reads **and** decomposition-item
parsing/grouping **and** witness resolution **and** commission-signature/trust verification (which
shells out to a second binary, `verify-commission`) **and** `resource:`-statement-grammar parsing
**and** work-item reads **and** review-gap/work-violations/question-status/standing-decisions/
findings-and-snags reads **and** the `autoharn_health` armed-check. That is at least eight
independently-nameable responsibilities in one 823-line module, each with its own SQL, its own
parsing regexes, and its own dataclasses. This is not merely a size complaint (that is ADR-0007's
axis, not P3's) — it is that a single file is the union of everything "autoharn-semantic" this
backend does, with no internal seams even within the file, which is exactly the shape P3 exists to
flag.

### 4. Seven of the extension's read routes have zero test coverage of any kind — live or unit

Grepped by function name across every file in `tests/` (10 files, ~2,060 lines): `recent_ledger`,
`work_items`, `review_gap`, `work_violations`, `findings_and_snags`, `question_status`,
`standing_decisions`, `autoharn_health`, `backend_surface`/`is_exposed_by_backend`, and
`count_rows` return **zero matches** anywhere in the test tree, beyond incidental mentions inside
docstrings describing what a *different* function does. The routes these back —
`GET /api/ledger/recent`, `/api/work`, `/api/review-gap`, `/api/questions`, `/api/work-violations`,
`/api/findings-snags`, `/api/standing-decisions` — are exercised by **no** test file, live-Postgres
or otherwise; `GET /api/health`'s `autoharn` sub-payload (backed by `autoharn_health`) and
`GET /api/backend-surface` are in the same position. This is discussed in full under "Unit-test
coverage characterization" below; it is filed as its own SERIOUS finding here because it is a
direct, structural consequence of finding 2: with no Protocol boundary and no fake implementing it,
the *only* way to test any of these functions is against a live Postgres, and for these seven, no
one has done even that.

---

## MODERATE

### 5. Dead code: `count_rows()` is documented as load-bearing SSOT and is never called

`core/ledger_read.py`'s `count_rows()` carries a docstring asserting it is "the SAME filter
`rows()` applies... one home for a facet's count, per SPEC.md sec 2.1's own 'one home per count'
rule." Grepping the entire `backend/` tree shows it is never called from any route, any other
function, or any test — the only three occurrences of the string `count_rows` in the whole
repository are its own definition and its own two docstring self-references. The function is
demonstrably not "the one home" for anything today; it is unreferenced code asserting a
single-source-of-truth claim about a query path nothing currently uses. This is a small ADR-0012 P1
(single-source-of-truth) concern in miniature: a fact-shaped claim ("this is the one home") with no
live caller to keep it honest.

---

## MINOR

### 6. `cosign.py`'s own input validation has zero test coverage, despite being the cheapest possible thing to test

`extensions/autoharn/cosign.py`'s `cosign()` validates `verdict`/`independence`/`basis` against
closed vocabularies and raises `CosignValidationError` **before** touching the database or shelling
out to `LED_BIN` — this is pure, synchronous, dependency-free logic. Grepping `tests/` for
`CosignValidationError` returns matches only inside `backend/extensions/autoharn/{cosign,routes}.py`
themselves; no test file exercises this validation path at all. Every existing cosign test
(`tests/test_cosign_live.py`) requires a live Postgres plus a sibling `autoharn` checkout's
`led.tmpl` binary and is skipped without both. The three or four "bad verdict"/"bad independence"/
"empty basis" cases could be asserted in well under ten lines of plain pytest with zero
infrastructure, and currently are not.

---

## Diagnosis of the witnessed "genuinely hung" incident

**The mechanism, confirmed against actual installed-package source in this checkout:**

Every route handler in this backend — `api_rows`, `api_row`, `api_watermark`,
`api_backend_surface`, `api_profiles_list`, `api_profiles_upsert`, `api_profiles_delete`,
`api_commissions`, `api_commission`, `api_ledger_recent`, `api_work`, `api_review_gap`,
`api_questions`, `api_work_violations`, `api_findings_snags`, `api_standing_decisions`,
`api_item_obligations`, `api_cosign` — is declared as a plain `def`, not `async def`. The one
exception, `api_events` (the SSE endpoint), is `async def` and touches no database connection in
its async path at all (it only reads from an in-memory `asyncio.Queue`).

Confirmed directly against this checkout's installed `starlette==1.3.1`
(`venv/lib64/python3.13/site-packages/starlette/routing.py:54`): a route function is dispatched via
`func if is_async_callable(func) else functools.partial(run_in_threadpool, func)` — every one of
the sync handlers above is therefore wrapped in `run_in_threadpool`, which is `anyio.to_thread.
run_sync` under the hood. This means **the event loop itself is not blocked** by a single slow
`psycopg.connect()` call — the good-news half of the hypothesis in the commissioning brief. But
`anyio`'s own source (`venv/lib64/python3.13/site-packages/anyio/_backends/_asyncio.py:3097`) hard-
codes the default thread limiter to `CapacityLimiter(40)` — **at most 40 of these blocking calls can
run concurrently, process-wide, shared across every route.** A 41st concurrent request does not
fail; it queues, waiting for a thread slot, for as long as it takes the 40 ahead of it to finish
their full connect-authenticate-query-close cycle each.

Layered on top of finding 1 (no pooling, no connection reuse): each of those 40 concurrent slots is
not running a fast, already-established query — each is paying a full fresh TCP + Postgres auth
handshake before it even reaches the SQL. Under "several concurrent Playwright-driving verification
sessions" (the incident's own description), each simulating a real user with multiple tabs/rapid
navigation, it is entirely plausible for request arrival rate to exceed 40 concurrent in-flight
connect-cycles, at which point every *new* request — including the plain `curl` health-checks the
incident report describes timing out — sits in an ever-growing queue behind a backlog that only
gets worse as more requests keep arriving. This produces exactly the witnessed symptom class:
not a deadlock, but unbounded queueing with no backpressure and no visible sign of it beyond
"nothing responds."

Two additional compounding factors, both confirmed in source:

- The background poll loop (`app.py`'s `_poll_loop`, running every `cfg.poll_interval` — default
  2.0s) calls `asyncio.to_thread(core_ledger_read.watermark, state.cfg)`. `asyncio.to_thread` uses
  the stdlib's own default `ThreadPoolExecutor` (via `loop.run_in_executor(None, ...)`), which is a
  **separate** pool from anyio's 40-slot request limiter — so the poller does not itself compete for
  request-serving thread slots, but it does add one more fresh `psycopg.connect()`/close cycle every
  two seconds, indefinitely, layering steady-state connection churn on top of request-driven churn.
- `POST /api/cosign` (when mounted) runs `subprocess.run([led_bin, ...], timeout=30, ...)` inside
  the same sync-handler-in-threadpool path — a slow or hung `led` invocation would hold one of the
  40 slots for up to 30 seconds, further starving read routes during any concurrent write activity.

**Confidence and what remains unconfirmed:** the mechanism above is fully supported by the code as
it exists today and would, under sufficient concurrent load, produce a symptom indistinguishable
from what was witnessed. However, I cannot certify it is *the* root cause of that specific incident,
for an honest reason: the only contemporaneous record of the incident is ledger row 875's own snag,
which itself discloses that the reporting session lost track of its own working directory mid-
recovery and states plainly "I cannot say with certainty whether my kill command caused the
eventual recovery or whether it happened independently." No thread dump, `pg_stat_activity`
snapshot, or access log from the incident window was captured or is available to this audit. The
snag mentions "curl timeouts / zero DB connections" as the observed symptom, which is consistent
with the queueing mechanism above (requests waiting for a thread slot never reach the point of
holding a DB connection at all) but is not, by itself, sufficient to rule out a different or
additional proximate cause (e.g., a genuinely wedged Postgres-side session, a network blip, or
resource exhaustion outside this backend's own process). What this audit **can** state with full
confidence, independent of the specific incident: the architecture as it exists today — zero
pooling, a hard 40-thread ceiling shared by every route, and per-request full-handshake connection
churn — is a real, present defect that would produce exactly this failure class under concurrent
load, regardless of whether it is what happened on this particular occasion.

---

## Unit-test coverage characterization

Grepped every function name in `backend/core/` and `backend/extensions/autoharn/` against all 10
files under `tests/` (~2,060 lines). Two genuinely different coverage populations exist:

**Actually unit-tested (fast, no live Postgres, no subprocess) — the honest, working slice:**
- `extensions/autoharn/disposition.py` (`derive_status`, `group_item_rows`) — fully covered,
  pure functions, `tests/test_disposition.py`.
- `extensions/autoharn/ledger_read.py`'s three pure parsers (`parse_item_refs`,
  `parse_witness_refs`, `parse_resource_fields`) — fully covered, `tests/test_disposition.py` +
  `tests/test_item_view.py`.
- `commission_trust()` (the one function in `ledger_read.py` that shells out to a second binary) —
  fully covered across all five branches (fast-path/signed/forged/unverifiable/unrecognized) via a
  monkeypatched `subprocess.run`, `tests/test_commission_trust.py`. This is the one place in the
  whole backend where "mock the one external dependency, test the logic" is actually done, and it
  is a good, working model for how the rest of this module could be tested if a boundary existed.
- `backend/config.py` — fully covered, pure, `tests/test_config_profiles.py`.
- `core/profiles_write.py` — fully covered (TOML-file-based, no Postgres), plus FastAPI route
  mounting/E2E tests that need no live DB, `tests/test_profiles_write.py`.
- Route-mounting-by-inspection (which routes exist under which config, never executed) —
  `tests/test_readonly_lock.py`, `tests/test_profiles_write.py`'s layer 2.

**Tested only as live-Postgres integration tests, `pytest.mark.skipif`-gated on a reachable
`PGHOST` (silently skipped, not failed, in the ordinary no-DB dev environment) — the majority of
the SQL-issuing surface:**
`core/ledger_read.py`'s `rows`/`facet_counts`/`row_by_id` (via `/api/rows*` in
`tests/test_core_boundary.py`); `extensions/autoharn/ledger_read.py`'s `work_item`,
`maintainer_cosigned`, `latest_review_id`, `resolve_witness`, `reviews_for_row`, `item_witnesses`,
`fetch_parsed_item_rows`, `commissions`, `decomposition_items` (via
`tests/test_commission_decomposition.py`, `tests/test_cosign_live.py`,
`tests/test_item_view_live.py` — each additionally requiring a sibling `autoharn` checkout's
`led.tmpl` + `kernel/lineage/` for several of these).

**Untested by any mechanism, live or unit — confirmed by name, zero matches in `tests/`:**
`autoharn_health`, `recent_ledger`, `_work_blocked_by`/`work_items`, `review_gap`,
`work_violations`, `findings_and_snags`, `question_status`, `standing_decisions`,
`backend_surface`/`is_exposed_by_backend`/`_relation_count`, `core/ledger_read.py`'s `count_rows`
and `supersede_chain` (the latter's *route*, `/api/rows/{id}`, is exercised, but no test ever
constructs an actual supersede chain to exercise the predecessor/successor-walk logic itself —
every existing test asserts the trivial empty-chain case), and `cosign.py`'s own validation-error
branches (finding 6 above).

**Net characterization:** of roughly 30 SQL-issuing functions across the two `ledger_read.py`
modules and `backend_surface.py`, only one (`commission_trust`) has a real, fast, no-infrastructure
unit test exercising its non-trivial branches; the rest are either (a) reachable only through a
live-Postgres integration test that most contributors' local environments skip silently, or (b) not
tested at all, by any mechanism, today. This is the direct, textbook consequence of finding 2: with
no Protocol/Port boundary, "test this query function" and "stand up a real Postgres schema" are the
same sentence — there is no cheaper option on offer.

---

## Recommended remediation shape

Sized for this codebase's actual scale, per the reap doc's own explicit caveat that omega's six
Protocols "probably 2-3, not six" transfer here. This backend already has exactly one real,
load-bearing structural axis — the core/`autoharn`-extension split (`SPEC.md` §4, tested by
`tests/test_core_boundary.py`) — and the remediation should hang off that seam rather than invent a
new, orthogonal one:

1. **Two `Protocol`s, not six, one per existing module boundary:**
   - `core/ports.py`: a `CoreLedgerPort` Protocol declaring the method shapes
     `core/ledger_read.py` already exposes (`watermark`, `rows`, `count_rows`, `facet_counts`,
     `row_by_id`, `supersede_chain`, `generic_row_refs`) — this can, and should, start as a
     near-mechanical extraction: wrap the existing module-level functions as methods on a
     `PostgresCoreLedgerReader` class implementing the Protocol, with the SQL bodies themselves
     moved verbatim (ADR-0004 minimal-touch — this is a seam extraction, not a rewrite).
   - `extensions/autoharn/ports.py`: an `AutoharnLedgerPort` Protocol for the ~30 functions in
     `extensions/autoharn/ledger_read.py`. Given finding 3 (the god-module problem), this is also
     the natural point to split that one file along its own already-visible seams — commission
     reads, decomposition/witness resolution, and the read-only queue views (`review_gap`,
     `work_violations`, `question_status`, `standing_decisions`, `findings_and_snags`) are three
     genuinely separable concerns that could become three adapter classes behind one Protocol, or
     (simpler, and arguably enough on its own) three separate modules each still behind the one
     Protocol — either shape satisfies P3 without over-engineering a second axis of Protocols the
     reap doc's own caveat warns against.
   - Route handlers depend on the Protocol type (injected via `request.app.state`, mirroring how
     `cfg` is already threaded through today), never on the concrete `ledger_read` module import.
     `core/backend_surface.py`'s own module-docstring-declared safety invariant (metadata/count
     only, never row content) is exactly the kind of contract a Protocol method signature can state
     structurally rather than leaving to a comment.

2. **A real connection pool, sequenced independently but naturally sitting behind the Protocol
   boundary once it exists:** replace `db.py`'s per-call `psycopg.connect()` with a
   `psycopg_pool.ConnectionPool` (the synchronous variant — every route is already a plain `def`
   dispatched via `run_in_threadpool`, so there is no reason to also take on `AsyncConnectionPool`
   and rework every handler to `async def` just to fix this), created once at `lifespan` startup
   and stored on `AppState` alongside the existing `Broadcaster`/`poll_task`. This is the highest-
   priority fix given the witnessed incident (finding 1) and does not strictly require the
   Protocol layer to land first — but the Protocol layer is exactly where the pool would be handed
   to every adapter uniformly, rather than threading a pool object through 30 independent call
   sites by hand, which is the concrete reason to sequence them together rather than treat pooling
   as a bolt-on patch to today's `connect()` signature.

3. **In-memory fakes implementing both Protocols** (the reap doc's entry 3, explicitly contingent on
   entry 2 existing first — now that entry 2's prediction is confirmed, entry 3 is the direct
   payoff): a `FakeCoreLedgerReader`/`FakeAutoharnLedgerReader` pair that plain Python objects can
   construct in a test with hand-built row dicts, letting the currently-untested functions (finding
   4's list) get real assertions without a live Postgres.

---

## Unit-test coverage the remediation itself must ship with

Per the maintainer's own direct requirement (ledger row 884): this saga is not finished at "the
Protocol/pool exists," it is finished when the following are also true, and each should be a named
acceptance-criteria row pre-registered before implementation begins (CLAUDE.md point 4):

- Every method on both new Protocols has at least one test driving it through the **fake** adapter,
  not the Postgres one — specifically closing the zero-coverage list from finding 4:
  `autoharn_health`, `recent_ledger`, `work_items`/`_work_blocked_by`, `review_gap`,
  `work_violations`, `findings_and_snags`, `question_status`, `standing_decisions`,
  `backend_surface`/`is_exposed_by_backend`, and `core/ledger_read.py`'s `supersede_chain` (a real
  multi-row chain, not only the trivial empty case existing tests assert) and `count_rows` (or its
  removal, if the remediation instead deletes the dead function per finding 5 rather than adopting
  it — either disposition is acceptable, but it must be a stated choice, not left silent).
- `cosign.py`'s validation-error branches (finding 6) get a plain, infrastructure-free pytest module
  — this needs no Protocol work at all and could ship independently, immediately, at near-zero cost.
- The production Postgres-backed adapter(s) keep at least the live-Postgres coverage that already
  exists today (`tests/test_core_boundary.py`, `tests/test_commission_decomposition.py`,
  `tests/test_cosign_live.py`, `tests/test_item_view_live.py`) — the fakes are additive, a faster
  inner loop, never a replacement for the one place that proves the real SQL is actually correct
  against a real schema.
- The connection pool gets its own test demonstrating the property it exists to prove: that N
  concurrent calls through `db.py`'s entry point do **not** open N new physical connections — a
  scratch-Postgres test asserting a stable, bounded connection count under concurrent load (e.g.
  via `pg_stat_activity` or the pool's own exposed size/stats) is the honest way to substantiate
  "pooling actually works here," not merely "the pool object was constructed."
- Per ADR-0009/ADR-0012 P6's substantiate-your-claims discipline: if the remediation's own PR
  claims "this fixes the hang," that claim needs the same kind of load-bearing evidence this audit
  itself could not produce after the fact — a repeatable, reasonably-concurrent load test against
  the pooled backend showing bounded latency/no unbounded queueing, not merely "the code now has a
  pool" asserted by inspection.
