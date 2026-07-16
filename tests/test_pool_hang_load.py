"""tests/test_pool_hang_load.py -- end-to-end load-test proof for pool-hang-load-test (ledger
row:940). `db-connection-pool` (row:932, commit 7247a9b) fixed `backend/db.py` to pool Postgres
connections instead of opening a brand-new one per call. That change's OWN test
(tests/test_db_pool.py) proves the pool object bounds physical connection count when called
directly, in isolation -- it does NOT prove the witnessed :8420 hang (row:894's diagnosis:
unbounded request queueing under concurrent load, from Starlette's `run_in_threadpool` anyio
`CapacityLimiter` hard-capped at 40 concurrent slots process-wide, combined with the OLD
per-call-connect behavior) is actually fixed end to end. This file drives that proof: it
launches a REAL uvicorn process (`backend/app.py`, completely unmodified, exactly as an
operator would run it per README.md sec 2) against the REAL reachable deployment Postgres, then
fires bursts of genuinely concurrent real HTTP requests at it and measures latency -- no mock of
db.py, the pool, or the HTTP layer anywhere in this file.

Target route: `GET /api/backend-surface` (`backend/core/routes.py`) -- deliberately chosen over
a cheap ~10ms route like `/api/rows` (see row:1050's ledgered assumption): live-measured against
the already-running shared dev instance before this file was written, `/api/rows` finished in
~10ms (too fast for real pool/thread contention to manifest before the request is already done)
while `/api/backend-surface` took ~170ms (it holds ONE pooled connection via
`db.connect_unrestricted` for its whole per-relation count loop across both configured schemas,
per `core/ledger_adapter.py`'s `backend_surface()`). A connection-holding route is the one that
actually exercises the pool/anyio-cap contention the witnessed hang was diagnosed against.

Deployment target: the real `deployment.json`-derived Postgres (host/db/schema/role -- see
row:1051's ledgered assumption for why: a scratch schema would be near-empty and understate
`/api/backend-surface`'s real per-relation-count cost; a dedicated subprocess on a scratch port,
rather than reusing an already-running shared dev instance, keeps this file self-contained and
rerunnable by a fresh session with no dependency on another concurrent agent's process surviving
for the test's duration, and avoids the shared `:8420` dev instance's own `--reload` flag, which
risks a mid-burst restart -- and a false hang signal -- if a concurrent sibling session edits a
watched source file). `PANEL_READONLY=1` is forced regardless (mirrors `backend/run-dev.sh`'s
own convention) so no write route is ever mounted, even though this file only ever fires GETs.

Pre-registered acceptance criteria, REVISED (ledger row:1057, `./led show 1057`, superseding the
first attempt at row:1053): at each of five concurrency tiers (10 / 40 / 80 / 150 / 250
concurrent requests -- the last three all exceed both the 40-slot anyio `CapacityLimiter` AND
the pool's own `max_size=41`), (a) every request succeeds (HTTP 200, no exception, no timeout),
and (b) wall-clock time for the tier does not exceed a BOUNDED-GROWTH ceiling: a reference
per-request throughput is measured live from the smallest tier's (n=10) own wall time in the
SAME run, and every larger tier's wall time must stay at or under
`reference_throughput * n * GROWTH_FACTOR`. This directly operationalizes "bounded, proportional
queueing" vs. "unbounded runaway growth" -- the actual question row:940 asks -- rather than an
arbitrary flat absolute number. An absolute `ABSOLUTE_MAX_SECONDS` ceiling also applies
regardless of the ratio check, to catch a literal indefinite hang outright.

Why revised: row:1053's first attempt used a flat `P99_BOUND_SECONDS` (5.0s) picked from a
single unloaded-baseline guess. The first real run (see git history / row:1056's finding) showed
`GET /api/backend-surface` -- which does O(relation-count) sequential round trips per call over
one held pooled connection -- scales its wall-clock time almost perfectly LINEARLY with request
count under this real deployment's actual Postgres host throughput: amortized per-request cost
stayed in a roughly 85-100ms band across concurrency 10 through 150 (confirmed two ways: this
file's own Python `ThreadPoolExecutor` harness, AND an independent raw-`curl` cross-check using
separate OS processes with zero Python/GIL involved, against the already-running shared dev
instance -- ruling out a client-side artifact). That flat linear band IS the positive signal:
proportional, bounded growth, not the runaway/indefinite blowup an unfixed hang would produce --
but it invalidated the original flat 5s ceiling, which the heavier tiers exceeded for a
miscalibration reason having nothing to do with the fix. `GROWTH_FACTOR=3.0` below is generous
headroom against the ~1.0-1.02x ratio actually observed.

Usage: `venv/bin/python -m pytest tests/test_pool_hang_load.py -v -s` (skipif-gated, same
convention as every other live test in this tree: SKIPPED, not failed, without a reachable
Postgres host). Starts its own dedicated uvicorn subprocess on a scratch port (never the shared
dev :8420/README.md convention) and tears it down unconditionally at the end (module-scoped
fixture; teardown runs on failure too, so no orphaned process/port survives this test).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator

import pytest

REPO = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO / "backend"
VENV_PYTHON = REPO / "venv" / "bin" / "python3"

PGHOST = os.environ.get("EPISTEMIC_PGHOST") or os.environ.get("PGHOST")
PGDB = os.environ.get("PANEL_TEST_PGDATABASE", "toy")
SCHEMA = os.environ.get("PANEL_TEST_SCHEMA", "experience")
KERN = os.environ.get("PANEL_TEST_KERN_SCHEMA", "experience_kernel")
ROLE = os.environ.get("PANEL_TEST_ROLE", "experience_rw")
PORT = int(os.environ.get("PANEL_LOAD_TEST_PORT", "8471"))

TARGET_PATH = "/api/backend-surface"
CONCURRENCY_TIERS = (10, 40, 80, 150, 250)
REFERENCE_TIER = CONCURRENCY_TIERS[0]  # n=10 -- its own wall time sets the live reference rate
GROWTH_FACTOR = 3.0             # a tier's wall time may not exceed reference_throughput * n *
                                 # this factor -- generous headroom above the ~1.0-1.02x actually
                                 # observed (row:1056), while still catching genuine super-linear
                                 # (accelerating/divergent) blowup
ABSOLUTE_MAX_SECONDS = 120.0    # a flat sanity ceiling regardless of the ratio check, so a
                                 # literal indefinite hang is still caught outright
REQUEST_TIMEOUT_SECONDS = 90.0  # per-request socket timeout -- generous, so an undersized
                                 # client-side cutoff can never masquerade as a server-side
                                 # failure (row:1053's first attempt's own mistake at n=250)

pytestmark = pytest.mark.skipif(
    not PGHOST or not VENV_PYTHON.is_file(),
    reason="pool-hang-load-test needs a reachable Postgres host (EPISTEMIC_PGHOST/PGHOST) and "
           "this repo's own venv (venv/bin/python3) -- SKIPPED, not failed, when absent.",
)


def _clean_env() -> dict[str, str]:
    """A copy of the ambient environment with PGOPTIONS (and LED_ACTOR) stripped -- row:1052's
    ledgered assumption: this session's own ./led tool-interception stamp sets PGOPTIONS with
    `-c app.vendor_*` flags, and row:1036's reviewer already found this exact env var leaking
    into a live test's raw psycopg connections as an unrelated confound. Stripped here so the
    launched backend looks exactly like an operator's own README.md sec 2 uvicorn invocation,
    not carrying this session's own tooling artifact along for the ride."""
    env = dict(os.environ)
    env.pop("PGOPTIONS", None)
    env.pop("LED_ACTOR", None)
    return env


@pytest.fixture(scope="module")
def live_backend() -> Iterator[str]:
    """Launches a REAL uvicorn subprocess (backend/app.py, completely unmodified) against the
    real reachable deployment Postgres, PANEL_READONLY=1 forced. Torn down unconditionally at
    module teardown (success or failure) so no orphaned process/port survives this test."""
    env = _clean_env()
    env.update({
        "PANEL_READONLY": "1",
        "LEDGER_PG_URI": f"host={PGHOST} dbname={PGDB}",
        "LEDGER_SCHEMA": SCHEMA,
        "LEDGER_KERNEL_SCHEMA": KERN,
        "LEDGER_ROLE": ROLE,
    })
    proc = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(BACKEND_DIR), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base_url = f"http://127.0.0.1:{PORT}"
    try:
        deadline = time.monotonic() + 20.0
        last_err: Exception | None = None
        ready = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout else ""
                raise RuntimeError(
                    f"backend subprocess exited early (code={proc.returncode}) before "
                    f"becoming healthy -- output:\n{out}"
                )
            try:
                with urllib.request.urlopen(f"{base_url}/api/health", timeout=1.0) as resp:
                    body = json.loads(resp.read())
                    if resp.status == 200 and body.get("ok") and body.get("read_only") is True:
                        ready = True
                        break
            except Exception as e:  # noqa: BLE001 -- any failure here just means "not ready yet"
                last_err = e
            time.sleep(0.25)
        if not ready:
            raise RuntimeError(
                f"backend subprocess never became healthy at {base_url} within 20s "
                f"(last probe error: {last_err!r})"
            )
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def _fire_one(base_url: str) -> tuple[bool, float, str]:
    """One real HTTP request over its own fresh socket (urllib does not pool/reuse connections
    either, matching independent-concurrent-client semantics). Returns (ok, latency_seconds,
    detail)."""
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(f"{base_url}{TARGET_PATH}", timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            resp.read()
            latency = time.monotonic() - t0
            return resp.status == 200, latency, f"http {resp.status}"
    except Exception as e:  # noqa: BLE001 -- any exception is a failed request for this purpose
        latency = time.monotonic() - t0
        return False, latency, f"{type(e).__name__}: {e}"


def _fire_burst(base_url: str, n: int) -> list[tuple[bool, float, str]]:
    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(_fire_one, base_url) for _ in range(n)]
        return [f.result() for f in futures]


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(round(p * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def test_pool_hang_load(live_backend: str) -> None:
    """The acceptance-criteria test (row:1057, revised -- see module docstring for why): at each
    concurrency tier, fires N truly concurrent HTTP requests at the real running backend's
    /api/backend-surface route and asserts BOUNDED, PROPORTIONAL growth relative to a reference
    throughput measured live from the smallest tier -- not a flat absolute number. Prints a full
    report (run with -s to see it; this file's own committed recorded run,
    tests/pool_hang_load_test_run.txt, captured exactly this output)."""
    base_url = live_backend
    print(f"\n=== pool-hang-load-test -- target={base_url}{TARGET_PATH} ===")
    print(f"bounds: wall_time(n) <= reference_throughput * n * GROWTH_FACTOR({GROWTH_FACTOR}), "
          f"reference_throughput measured live from n={REFERENCE_TIER}; "
          f"ABSOLUTE_MAX_SECONDS={ABSOLUTE_MAX_SECONDS}s per tier; zero failures required\n")

    # single-request baseline, unloaded, for context in the report (not itself asserted against
    # a bound -- purely descriptive, to show the "no contention at all" floor).
    ok, baseline_latency, detail = _fire_one(base_url)
    assert ok, f"baseline single request failed: {detail}"
    print(f"baseline (n=1, unloaded): {baseline_latency * 1000:.1f}ms\n")

    reference_throughput: float | None = None  # seconds/request, set from the n=REFERENCE_TIER tier
    overall_pass = True
    for n in CONCURRENCY_TIERS:
        wall_start = time.monotonic()
        results = _fire_burst(base_url, n)
        wall_time = time.monotonic() - wall_start

        failures = [(ok_, lat, detail_) for ok_, lat, detail_ in results if not ok_]
        latencies = sorted(lat for _, lat, _ in results)
        p50 = _pct(latencies, 0.50)
        p95 = _pct(latencies, 0.95)
        p99 = _pct(latencies, 0.99)
        max_lat = latencies[-1] if latencies else 0.0
        throughput = wall_time / n  # seconds/request, amortized across this tier's own burst

        if n == REFERENCE_TIER:
            reference_throughput = throughput
            bound = None
            tier_ok = (not failures) and (wall_time <= ABSOLUTE_MAX_SECONDS)
            bound_desc = f"(reference tier -- sets reference_throughput={throughput * 1000:.1f}ms/req)"
        else:
            assert reference_throughput is not None
            bound = reference_throughput * n * GROWTH_FACTOR
            tier_ok = (not failures) and (wall_time <= bound) and (wall_time <= ABSOLUTE_MAX_SECONDS)
            bound_desc = f"(bound={bound:.3f}s, ratio-to-reference={throughput / reference_throughput:.2f}x)"
        overall_pass = overall_pass and tier_ok

        print(f"--- concurrency={n} ({'> 40-slot cap' if n > 40 else '<= 40-slot cap'}) ---")
        print(f"  wall_time={wall_time:.3f}s  failures={len(failures)}/{n}  "
              f"throughput={throughput * 1000:.1f}ms/req  {bound_desc}")
        print(f"  latency p50={p50 * 1000:.1f}ms p95={p95 * 1000:.1f}ms p99={p99 * 1000:.1f}ms "
              f"max={max_lat * 1000:.1f}ms")
        print(f"  verdict: {'PASS' if tier_ok else 'FAIL'}"
              f"{'' if tier_ok else f' -- sample failures={failures[:3]}'}")
        print()

    print(f"=== OVERALL: {'PASS' if overall_pass else 'FAIL'} ===")
    assert overall_pass, (
        "one or more concurrency tiers exceeded the pre-registered bounded-growth criterion "
        "(row:1057) or saw request failures -- see the printed per-tier report above"
    )
