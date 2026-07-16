"""tests/test_autoharn_routes.py -- HTTP-route-level coverage for the 8 autoharn read routes
`docs/consults/2026-07-16-backend-structural-audit/2026-07-16-backend-structural-audit.md`
(ledger row 894) named as having ZERO test coverage of any kind, live or unit: `recent_ledger`,
`work_items` (its own `blocked_by` merge), `review_gap`, `work_violations`,
`findings_and_snags`, `question_status`, `standing_decisions`, `autoharn_health` -- work item
autoharn-coverage-tests, ledger row 939, part of the backend-remediation decomposition (parent
row 929, audit row 894, countersigned at row 959).

WHY ROUTE-LEVEL, not fake-level: `tests/test_fake_autoharn_ledger_reader.py` already proves
`FakeAutoharnLedgerReader`'s own 25 methods are a faithful in-memory `AutoharnLedgerPort` --
that is coverage of the FAKE, not of the ROUTE WIRING the audit actually flagged as untested
(the FastAPI handler in `extensions/autoharn/routes.py`/`app.py`'s own `/api/health`, the
request/response shape, the `n<1` -> HTTPException(400) translation, etc). This file closes
THAT gap: real `fastapi.testclient.TestClient` requests against a real `create_app()`-built
app, with `FakeAutoharnLedgerReader` swapped into `app.state.panel.autoharn_reader` AFTER
startup (the lifespan constructs a `PostgresAutoharnLedgerReader` unconditionally -- cheap,
fieldless, no I/O at construction per `app.py`'s own `AppState` docstring -- so swapping it out
before any request is issued means no route body here ever touches a real Postgres connection).
No live Postgres needed; nothing here is `pytest.mark.skipif`'d.

Pattern lifted directly from `tests/test_readonly_lock.py`/`tests/test_profiles_write.py`
(monkeypatch env vars, THEN import/reload `app` -- its module-level code resolves config at
import time) and `tests/test_fake_autoharn_ledger_reader.py` (`build_cfg`, the fake's own
`add_*`/`open_work_item`/`seed_*` scenario-builder API).

`review_gap`/`work_violations` specifically seed 2+ genuinely different rows (never an empty
list) so the assertions actually exercise the real multi-row sort/passthrough the kernel views'
own `ORDER BY` clauses perform (`ledger_adapter.PostgresAutoharnLedgerReader.review_gap`:
`ORDER BY rg.id`; `.work_violations`: `ORDER BY target_id, violation, slug`) -- an empty-list
scenario would pass identically whether the route/sort wiring were correct or entirely broken.
`work_items` likewise seeds a real `add_blocks_close_edge` so its own `blocked_by` merge (the
audit's parenthetical `_work_blocked_by`) is proven non-trivially, not merely returning `[]`
for every slug.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "tests"))

# `app` is deliberately NOT imported at module top-level -- same reasoning as
# tests/test_readonly_lock.py and tests/test_core_boundary.py: its module-level code resolves
# config (`create_app()`'s own `load_config()` call) at IMPORT time, so env vars must be
# monkeypatched BEFORE app's first import/reload.

from fakes.fake_autoharn_ledger_reader import FakeAutoharnLedgerReader  # noqa: E402


@pytest.fixture(scope="module")
def autoharn_client():
    """Module-scoped: builds ONE `create_app()`-built app + `TestClient` for this whole file's 9
    route tests, entered ONCE. `app.py`'s ASGI lifespan (unconditionally, regardless of which
    reader ends up serving a request) opens a real, eagerly-`open=True` `psycopg_pool.
    ConnectionPool` and starts a background DB-watermark poll loop against `LEDGER_PG_URI` --
    here a deliberately unreachable `host=127.0.0.1`, since this file needs no live Postgres at
    all. Measured cost: `tests/test_profiles_write.py`'s own PRE-EXISTING
    `test_end_to_end_list_upsert_delete_via_client` (a TestClient test against the very same
    unreachable-host shape) already pays a ~30s pool-teardown cost per `TestClient` entry/exit,
    independent of anything this file adds -- an unavoidable, already-priced-in cost of using
    `TestClient` against this app at all, not a new one. Scoping this fixture to the MODULE
    (rather than re-paying it once per test, as a naive function-scoped fixture would) means
    this file's 9 route tests pay that fixed cost ONCE for the whole file, matching the single
    baseline cost every other TestClient-based test file here already pays (ADR-0015 Rule 1's
    spirit -- a heavy/slow run controls its own envelope -- applied at the smallest correct fix:
    nothing here changes what any route serves, only how many times an unavoidable, unrelated
    startup cost is paid). `pytest.MonkeyPatch()` is used directly (not the function-scoped
    `monkeypatch` fixture, which pytest refuses to inject into a module-scoped fixture) so the
    env vars this needs can be set once and undone once, at module teardown."""
    mp = pytest.MonkeyPatch()
    mp.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    mp.setenv("LEDGER_SCHEMA", "s")
    mp.setenv("LEDGER_KERNEL_SCHEMA", "k")
    mp.setenv("PANEL_EXTENSIONS", "autoharn")
    mp.delenv("LED_BIN", raising=False)
    mp.delenv("LEDGER_ROLE", raising=False)
    mp.delenv("PANEL_READONLY", raising=False)

    import app as app_module
    importlib.reload(app_module)
    app = app_module.create_app()
    with TestClient(app) as client:
        yield app, client
    mp.undo()


@pytest.fixture
def wired(autoharn_client):
    """Yields `(client, fake)`: the module-shared `TestClient` above, with a FRESH
    `FakeAutoharnLedgerReader` swapped into `app.state.panel.autoharn_reader` before every test
    -- so each test's own seeded scenario starts from empty state (no cross-test data leakage)
    despite the app/TestClient/pool/poll-loop themselves being shared across the whole module.
    Every route handler this file exercises reads from this fake, never from a DB connection."""
    app, client = autoharn_client
    fake = FakeAutoharnLedgerReader()
    app.state.panel.autoharn_reader = fake
    return client, fake


# ---------------------------------------------------------------------------------------------
# autoharn_health -- mixed into GET /api/health only when the extension is enabled.
# ---------------------------------------------------------------------------------------------

def test_autoharn_health_route_reflects_fake(wired) -> None:
    client, fake = wired
    fake.set_stamp_secret_armed(False)  # non-default value: proves the route reads the FAKE,
    # not a hardcoded/default True a broken wiring could coincidentally return.

    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["extensions_enabled"] == ["autoharn"]
    assert body["autoharn"]["stamp_secret_armed"] is False
    assert "attest" in body["autoharn"]["verdicts"]
    assert "self-review" in body["autoharn"]["independence_values"]
    assert body["maintainer_principal"] == "maintainer"


# ---------------------------------------------------------------------------------------------
# recent_ledger -- GET /api/ledger/recent
# ---------------------------------------------------------------------------------------------

def test_recent_ledger_route_orders_newest_first_and_limits(wired) -> None:
    client, fake = wired
    for i in range(5):
        fake.add_row("note", f"row {i}", actor_name="alice")

    resp = client.get("/api/ledger/recent", params={"n": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert [r["id"] for r in body] == [5, 4, 3]
    assert body[0]["statement"] == "row 4"
    assert body[0]["actor_name"] == "alice"


def test_recent_ledger_route_rejects_non_positive_n_as_400(wired) -> None:
    client, _fake = wired
    resp = client.get("/api/ledger/recent", params={"n": 0})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------------------------
# work_items (+ its own blocked_by merge) -- GET /api/work
# ---------------------------------------------------------------------------------------------

def test_work_items_route_merges_blocked_by(wired) -> None:
    client, fake = wired
    fake.open_work_item("a", "Item A", claimant_name="alice")
    fake.open_work_item("b", "Item B")
    fake.add_blocks_close_edge("a", "b")  # a genuine, non-empty blocks-close edge

    resp = client.get("/api/work")
    assert resp.status_code == 200
    items = {i["slug"]: i for i in resp.json()}
    assert items["a"]["blocked_by"] == ["b"]
    assert items["a"]["claimant_name"] == "alice"
    assert items["b"]["blocked_by"] == []  # the un-blocked slug proves this isn't a constant


# ---------------------------------------------------------------------------------------------
# review_gap -- GET /api/review-gap. Seeded with 2+ genuinely different rows (never empty) so
# the assertion proves the real `ORDER BY rg.id` passthrough, not a vacuous empty-list pass.
# ---------------------------------------------------------------------------------------------

def test_review_gap_route_nontrivial_scenario(wired) -> None:
    client, fake = wired
    fake.seed_review_gap([
        {"id": 7, "actor": 2, "actor_name": "bob", "scope": "cosign:row:100",
         "assigned_by": 1, "assigned_by_name": "alice"},
        {"id": 3, "actor": 1, "actor_name": "alice", "scope": "cosign:row:88",
         "assigned_by": None, "assigned_by_name": None},
    ])

    resp = client.get("/api/review-gap")
    assert resp.status_code == 200
    body = resp.json()
    # real sort by id (ascending), NOT insertion order -- id=3 must precede id=7
    assert [r["id"] for r in body] == [3, 7]
    assert body[0]["actor_name"] == "alice"
    assert body[0]["assigned_by_name"] is None
    assert body[1]["actor_name"] == "bob"
    assert body[1]["assigned_by_name"] == "alice"


# ---------------------------------------------------------------------------------------------
# work_violations -- GET /api/work-violations. Seeded with 2+ rows differing on every sort key
# component (target_id, violation, slug) to prove the real composite ORDER BY, not just an id.
# ---------------------------------------------------------------------------------------------

def test_work_violations_route_nontrivial_scenario(wired) -> None:
    client, fake = wired
    fake.seed_work_violations([
        {"violation": "dependency_cycle", "slug": "z-slug", "detail": "cycle z<->y", "target_id": 42},
        {"violation": "close_no_witness", "slug": "a-slug", "detail": "shipped close, no witness",
         "target_id": 9},
    ])

    resp = client.get("/api/work-violations")
    assert resp.status_code == 200
    body = resp.json()
    # real composite sort by (target_id, violation, slug) -- target_id=9 precedes target_id=42
    assert [r["target_id"] for r in body] == [9, 42]
    assert body[0]["violation"] == "close_no_witness"
    assert body[0]["slug"] == "a-slug"
    assert body[1]["detail"] == "cycle z<->y"


# ---------------------------------------------------------------------------------------------
# findings_and_snags -- GET /api/findings-snags
# ---------------------------------------------------------------------------------------------

def test_findings_and_snags_route_filters_and_orders(wired) -> None:
    client, fake = wired
    fake.add_row("finding", "a finding", id=1)
    fake.add_row("note", "not a finding or snag", id=2)
    fake.add_row("snag", "a snag", id=3)

    resp = client.get("/api/findings-snags")
    assert resp.status_code == 200
    body = resp.json()
    assert [(r["id"], r["kind"]) for r in body] == [(3, "snag"), (1, "finding")]


# ---------------------------------------------------------------------------------------------
# question_status -- GET /api/questions
# ---------------------------------------------------------------------------------------------

def test_question_status_route_nontrivial_scenario(wired) -> None:
    client, fake = wired
    fake.seed_question_status([
        {"question_id": 12, "statement": "should we ship v2?", "status": "answered"},
        {"question_id": 5, "statement": "is the schema final?", "status": "open"},
    ])

    resp = client.get("/api/questions")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["question_id"] for r in body] == [5, 12]
    assert body[0]["statement"] == "is the schema final?"
    assert body[1]["status"] == "answered"


# ---------------------------------------------------------------------------------------------
# standing_decisions -- GET /api/standing-decisions
# ---------------------------------------------------------------------------------------------

def test_standing_decisions_route_nontrivial_scenario(wired) -> None:
    client, fake = wired
    fake.seed_standing_decisions([
        {"id": 40, "grade": "durable", "statement": "second standing decision"},
        {"id": 11, "grade": "provisional", "statement": "first standing decision"},
    ])

    resp = client.get("/api/standing-decisions")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["id"] for r in body] == [11, 40]
    assert body[0]["grade"] == "provisional"
    assert body[1]["statement"] == "second standing decision"
