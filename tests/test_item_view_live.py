"""tests/test_item_view_live.py -- live-DB proof for the item-view backend logic added by
build-item-view (SPEC.md sec 2.2): `extensions.autoharn.ledger_read.reviews_for_row`/
`item_witnesses` and the `GET /api/item/{row_id}/obligations` route they back. Same
scratch-schema fixture pattern as tests/test_cosign_live.py -- SKIPPED, not failed, without a
reachable Postgres host + sibling autoharn checkout. Pure, no-database tests for the sibling
parser (`parse_witness_refs`) live in tests/test_item_view.py, not here (a module-level
`pytestmark` skipif, as used below, applies to every test in ITS module).
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from config import ConnectionFacts, PanelConfig  # noqa: E402
from extensions.autoharn import cosign as panel_cosign  # noqa: E402
from extensions.autoharn import ledger_read  # noqa: E402

PGHOST = os.environ.get("EPISTEMIC_PGHOST") or os.environ.get("PGHOST")
PGDB = os.environ.get("PANEL_TEST_PGDATABASE", "toy")
AUTOHARN_SIBLING = Path(os.environ.get("AUTOHARN_CHECKOUT", str(REPO.parent / "autoharn")))
LED_TMPL = AUTOHARN_SIBLING / "bootstrap" / "templates" / "led.tmpl"
LINEAGE = AUTOHARN_SIBLING / "kernel" / "lineage"

SCHEMA, KERN, ROLE = "pitemview", "pitemview_kernel", "pitemview_rw"
SCRATCH_DEPLOYMENT_PATH = Path(f"/tmp/.{SCHEMA}_deployment.json")

CHAIN_TO_S25 = [
    "s15-schema.sql", "s17-stamp-mechanism.sql", "s17-independence-vocabulary.sql",
    "s19-trigger-search-path.sql", "s20-obligation-grants-and-view-refresh.sql",
    "s21-session-aware-distinctness.sql", "s22-work-item-ledger.sql",
    "s23-per-invocation-stamp-token.sql", "s24-declared-event-time.sql",
    "s25-commission-kind.sql",
]

pytestmark = pytest.mark.skipif(
    not PGHOST or not LED_TMPL.is_file() or not LINEAGE.is_dir(),
    reason=(
        "item-view live fixture needs a reachable PGHOST (EPISTEMIC_PGHOST/PGHOST) and a "
        "sibling autoharn checkout's bootstrap/templates/led.tmpl + kernel/lineage/ (set "
        "AUTOHARN_CHECKOUT if it is not at ../autoharn) -- SKIPPED, not failed, when absent."
    ),
)


def sh(args: list[str], **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, **kw)


def _pg_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def teardown_scratch() -> None:
    sh(["psql", "-h", PGHOST, "-d", PGDB, "-c",
        f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE; DROP SCHEMA IF EXISTS {KERN} CASCADE; "
        f"DROP OWNED BY {ROLE};"])
    sh(["psql", "-h", PGHOST, "-d", PGDB, "-c", f"DROP ROLE IF EXISTS {ROLE};"])
    SCRATCH_DEPLOYMENT_PATH.unlink(missing_ok=True)


def psql(sql: str) -> subprocess.CompletedProcess[str]:
    prefix = f"SET ROLE {ROLE};\nSET search_path = {SCHEMA}, {KERN};\n"
    return sh(["psql", "-h", PGHOST, "-d", PGDB, "-v", "ON_ERROR_STOP=1", "-tA", "-q",
               "-c", prefix + sql])


def insert_note(refs: str, statement: str) -> int:
    r = psql(f"INSERT INTO ledger (kind, statement, refs) VALUES "
             f"('note', {_pg_str(statement)}, {_pg_str(refs)}) RETURNING id;")
    assert r.returncode == 0, f"insert_note failed: {r.stderr}"
    return int(r.stdout.strip())


def build_cfg() -> PanelConfig:
    connection = ConnectionFacts(pg_uri=None, pg_host=PGHOST, pg_port=None, pg_db=PGDB,
                                  pg_user=None, pg_password=None, source="test-scratch")
    return PanelConfig(
        repo_root=REPO, connection=connection, schema=SCHEMA, kern_schema=KERN, role=ROLE,
        led_bin=LED_TMPL, read_only_locked=False, bind_host="127.0.0.1", bind_port=8420, poll_interval=2.0,
        extensions=("autoharn",), config_source="test-scratch", maintainer_principal="maintainer",
        active_profile=None, available_profiles=(),
    )


@pytest.fixture(scope="module")
def scratch_ledger():
    teardown_scratch()
    args = ["psql", "-h", PGHOST, "-d", PGDB, "-v", "ON_ERROR_STOP=1",
            "-v", f"schema={SCHEMA}", "-v", f"kern={KERN}", "-v", f"role={ROLE}"]
    for f in CHAIN_TO_S25:
        args += ["-f", str(LINEAGE / f)]
    r = sh(args)
    assert r.returncode == 0, f"birth chain apply failed: {r.stdout[-1000:]} {r.stderr[-1000:]}"

    SCRATCH_DEPLOYMENT_PATH.write_text(json.dumps(
        {"db": PGDB, "host": PGHOST, "schema": SCHEMA, "kern": KERN, "role": ROLE, "name": SCHEMA}
    ), encoding="utf-8")
    os.environ["PICKUP_DEPLOYMENT"] = str(SCRATCH_DEPLOYMENT_PATH)
    os.environ.pop("LED_ACTOR", None)

    rp = psql("INSERT INTO principal (name, agent_class) VALUES ('maintainer','human') "
              "ON CONFLICT (name) DO NOTHING;")
    assert rp.returncode == 0

    cfg = build_cfg()
    yield cfg
    teardown_scratch()


def test_reviews_for_row_empty_then_populated(scratch_ledger: PanelConfig) -> None:
    cfg = scratch_ledger
    target = insert_note("", "a plain row a review will regard")
    assert ledger_read.reviews_for_row(cfg, target) == []

    res = panel_cosign.cosign(cfg, target, "attest", "self-review", "maintainer endorses this row directly")
    assert res.ok, f"exit={res.exit_code} stderr={res.stderr!r}"

    reviews = ledger_read.reviews_for_row(cfg, target)
    assert len(reviews) == 1
    assert reviews[0]["actor_name"] == "maintainer"
    assert reviews[0]["verdict"] == "attest"
    assert reviews[0]["independence"] == "self-review"


def test_item_witnesses_generic_no_panel_item_wrapper(scratch_ledger: PanelConfig) -> None:
    cfg = scratch_ledger
    w1 = insert_note("", "a witness row, no panel-item wrapper anywhere")
    holder = insert_note(f"row:{w1}", "a row citing a plain row: witness, not a decomposition item")

    witnesses = ledger_read.item_witnesses(cfg, holder)
    assert len(witnesses) == 1
    assert witnesses[0].ref_kind == "row"
    assert witnesses[0].ref == str(w1)
    assert witnesses[0].facts.exists is True
    assert witnesses[0].cosign["cosigned"] is False

    res = panel_cosign.cosign(cfg, w1, "attest", "self-review", "maintainer endorses the witness row")
    assert res.ok
    witnesses_after = ledger_read.item_witnesses(cfg, holder)
    assert witnesses_after[0].cosign["cosigned"] is True
    assert witnesses_after[0].cosign["by"] == "maintainer"


def test_item_witnesses_dangling_ref_reported_not_fabricated(scratch_ledger: PanelConfig) -> None:
    cfg = scratch_ledger
    holder = insert_note("row:999999999", "a row citing a row id that does not exist")
    witnesses = ledger_read.item_witnesses(cfg, holder)
    assert len(witnesses) == 1
    assert witnesses[0].facts.exists is False
    assert witnesses[0].resolved is None


def test_obligations_route_end_to_end(scratch_ledger: PanelConfig) -> None:
    from fastapi.testclient import TestClient

    # app.py resolves config at import time from the SAME PICKUP_DEPLOYMENT env var the
    # scratch_ledger fixture just pointed at this schema (see test_cosign_live.py/
    # test_readonly_lock.py's own comment on why `app` is a deferred, reloaded import here).
    import app as app_module
    importlib.reload(app_module)
    client = TestClient(app_module.create_app())

    cfg = scratch_ledger
    w1 = insert_note("", "a witness row for the end-to-end obligations route check")
    target = insert_note(f"row:{w1}", "the row the item view will be pointed at")

    resp = client.get(f"/api/item/{target}/obligations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["row_id"] == target
    assert body["cosign"] == {"cosigned": False, "by": None, "review_id": None, "verdict": None}
    assert body["reviews"] == []
    assert len(body["witnesses"]) == 1
    assert body["witnesses"][0]["ref_kind"] == "row"
    assert body["witnesses"][0]["ref"] == str(w1)
    # An ordinary note is not a `resource:` statement -- resource_fields degrades to None here,
    # never a fabricated/partial shape (cycle-4 audit finding 6).
    assert body["resource_fields"] is None

    res = panel_cosign.cosign(cfg, target, "attest", "self-review", "maintainer endorses the target row itself")
    assert res.ok
    resp2 = client.get(f"/api/item/{target}/obligations")
    body2 = resp2.json()
    assert body2["cosign"]["cosigned"] is True
    assert len(body2["reviews"]) == 1
    assert body2["reviews"][0]["verdict"] == "attest"


def test_obligations_route_resource_fields_end_to_end(scratch_ledger: PanelConfig) -> None:
    """Live-DB proof that a `resource:` decision row's structured fields (cycle-4 audit finding
    6, SERIOUS) survive the real route, not just the pure parser test_item_view.py already
    covers -- the same `GET /api/item/{row_id}/obligations` end-to-end path
    test_obligations_route_end_to_end above exercises for the ordinary case."""
    from fastapi.testclient import TestClient

    import app as app_module
    importlib.reload(app_module)
    client = TestClient(app_module.create_app())

    resource_row = insert_note(
        "",
        "resource: makespan-scheduler | library | import:makespan_scheduler | "
        "minimum-makespan schedule proof | reach for ordering 3+ work items | "
        "blessed: ordering three or more claimed work items",
    )
    resp = client.get(f"/api/item/{resource_row}/obligations")
    assert resp.status_code == 200
    fields = resp.json()["resource_fields"]
    assert fields is not None
    assert fields["name"] == "makespan-scheduler"
    assert fields["tier_kind"] == "blessed"
    assert fields["tier"] == "blessed: ordering three or more claimed work items"
