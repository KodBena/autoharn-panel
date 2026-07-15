"""tests/test_cosign_live.py -- both-polarity, live-ledger proof for this repo's `autoharn`
extension write path (`extensions/autoharn/cosign.py`) and its live disposition read path
(`extensions/autoharn/ledger_read.py`'s `decomposition_items`/`commissions`), against a scratch
schema/kernel pair. Ported from the autoharn PoC's `seen-red/panel-cosign/run_fixtures.py` (same
cases, same ordering) into this repo's own pytest suite.

Real infra, no mocks: a scratch schema/kern/role is created and torn down around this test.
Since this standalone repo does not ship its own ledger-writing CLI (SPEC.md sec 4: `LED_BIN` is
supplied by the deployment this repo is configured against, never bundled here), this fixture
needs SOME conformant `led`-grammar binary to drive the co-sign write path end to end -- it uses
the autoharn checkout's `bootstrap/templates/led.tmpl` if a sibling autoharn checkout is found
next to this repo (the maintainer's own convention, `autoharn-panel` beside `autoharn`), and
SKIPS (never fails) if neither the binary nor a reachable Postgres host is available. This is a
test-fixture convenience only -- nothing under `backend/` imports or depends on that path; a
deployment adopting this repo supplies its OWN `LED_BIN`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import config as panel_config  # noqa: E402
from config import ConnectionFacts, PanelConfig  # noqa: E402
from extensions.autoharn import cosign as panel_cosign  # noqa: E402
from extensions.autoharn import ledger_read  # noqa: E402

# --- fixture-only environment resolution (standalone: no hardcoded host) -----------------------
PGHOST = os.environ.get("EPISTEMIC_PGHOST") or os.environ.get("PGHOST")
PGDB = os.environ.get("PANEL_TEST_PGDATABASE", "toy")
AUTOHARN_SIBLING = Path(os.environ.get("AUTOHARN_CHECKOUT", str(REPO.parent / "autoharn")))
LED_TMPL = AUTOHARN_SIBLING / "bootstrap" / "templates" / "led.tmpl"
LINEAGE = AUTOHARN_SIBLING / "kernel" / "lineage"

SCHEMA, KERN, ROLE = "ppanelfx", "ppanelfx_kernel", "ppanelfx_rw"
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
        "live cosign fixture needs a reachable PGHOST (EPISTEMIC_PGHOST/PGHOST) and a sibling "
        "autoharn checkout's bootstrap/templates/led.tmpl + kernel/lineage/ (set "
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


def insert_commission(statement: str) -> int:
    r = psql(f"INSERT INTO ledger (kind, statement) VALUES ('commission', {_pg_str(statement)}) RETURNING id;")
    assert r.returncode == 0, f"insert_commission failed: {r.stderr}"
    return int(r.stdout.strip())


def build_cfg() -> PanelConfig:
    connection = ConnectionFacts(pg_uri=None, pg_host=PGHOST, pg_port=None, pg_db=PGDB,
                                  pg_user=None, pg_password=None, source="test-scratch")
    return PanelConfig(
        repo_root=REPO, connection=connection, schema=SCHEMA, kern_schema=KERN, role=ROLE,
        led_bin=LED_TMPL, read_only_locked=False, bind_host="127.0.0.1", bind_port=8420, poll_interval=2.0,
        extensions=("autoharn",), config_source="test-scratch", maintainer_principal="maintainer",
    )


def _item_count(cfg: PanelConfig, commission_row: int) -> int:
    commissions_list = ledger_read.commissions(cfg)
    entry = next((c for c in commissions_list if c["row_id"] == commission_row), None)
    assert entry is not None
    return entry["item_count"]


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


def test_green_item_row_fast_path(scratch_ledger: PanelConfig) -> None:
    cfg = scratch_ledger
    cid = insert_commission("panel test-suite specimen commission")
    item1_row = insert_note(f"panel-item:{cid}:ITEM1", "ITEM1 -- no witnesses yet, item row itself co-signable")

    res1 = panel_cosign.cosign(cfg, item1_row, "attest", "self-review", "maintainer endorses ITEM1 directly")
    assert res1.ok, f"exit={res1.exit_code} stderr={res1.stderr!r}"

    disc1 = ledger_read.maintainer_cosigned(cfg, item1_row)
    assert disc1 is not None and disc1["actor_name"] == "maintainer" and disc1["verdict"] == "attest"

    decomp1 = ledger_read.decomposition_items(cfg, cid)
    item1 = next(i for i in decomp1.items if getattr(i, "item_id", None) == "ITEM1")
    assert isinstance(item1, ledger_read.ResolvedItem)
    assert item1.status == "COSIGNED"


def test_greenc_per_witness_tally(scratch_ledger: PanelConfig) -> None:
    cfg = scratch_ledger
    cid = insert_commission("panel test-suite specimen commission (greenc)")
    w1 = insert_note("", "a plain note row, ITEM2's first row: witness")
    w2 = insert_note("", "a plain note row, ITEM2's second row: witness")
    insert_note(f"panel-item:{cid}:ITEM2 row:{w1} row:{w2}", "ITEM2 -- two row: witnesses, neither cosigned yet")

    decomp_pre = ledger_read.decomposition_items(cfg, cid)
    item2_pre = next(i for i in decomp_pre.items if getattr(i, "item_id", None) == "ITEM2")
    assert item2_pre.status == "WITNESSED"

    res_w1 = panel_cosign.cosign(cfg, w1, "attest", "self-review", "maintainer endorses ITEM2's first witness")
    assert res_w1.ok
    decomp_partial = ledger_read.decomposition_items(cfg, cid)
    item2_partial = next(i for i in decomp_partial.items if getattr(i, "item_id", None) == "ITEM2")
    assert item2_partial.status == "PARTIAL"

    res_w2 = panel_cosign.cosign(cfg, w2, "attest", "self-review", "maintainer endorses ITEM2's second witness")
    assert res_w2.ok
    decomp_cosigned = ledger_read.decomposition_items(cfg, cid)
    item2_cosigned = next(i for i in decomp_cosigned.items if getattr(i, "item_id", None) == "ITEM2")
    assert item2_cosigned.status == "COSIGNED"


def test_red_a_managerial_refused_unstamped(scratch_ledger: PanelConfig) -> None:
    cfg = scratch_ledger
    cid = insert_commission("panel test-suite specimen commission (reda)")
    item_row = insert_note(f"panel-item:{cid}:ITEMA", "ITEMA target row for a refused co-sign")
    res = panel_cosign.cosign(cfg, item_row, "attest", "managerial", "claiming independence with no stamp")
    assert not res.ok
    assert "claiming independence" in res.stderr
    assert "self-review" in res.stderr


def test_red_b_no_actor_self_review_refused(scratch_ledger: PanelConfig) -> None:
    cfg = scratch_ledger
    cid = insert_commission("panel test-suite specimen commission (redb)")
    item_row = insert_note(f"panel-item:{cid}:ITEMB", "ITEMB target row for the no-actor probe")
    assert "LED_ACTOR" not in os.environ
    res = panel_cosign._run_led(
        cfg, ["review", str(item_row), "attest", "self-review", "unset-actor probe"], actor=None,
    )
    assert not res.ok
    assert "author may not countersign it" in res.stderr


def test_redcprime_ambiguous_and_greend_prefix_adjacent(scratch_ledger: PanelConfig) -> None:
    cfg = scratch_ledger
    cid = insert_commission("panel test-suite specimen commission (redc/greend)")
    item1_row = insert_note(f"panel-item:{cid}:ITEM1", "ITEM1 original claim")

    item_count_before_dup = _item_count(cfg, cid)
    item1_dup_row = insert_note(f"panel-item:{cid}:ITEM1", "a duplicate ITEM1 claim, via a fresh row, NOT --supersedes")

    decomp_amb = ledger_read.decomposition_items(cfg, cid)
    item1_amb = next(i for i in decomp_amb.items if getattr(i, "item_id", None) == "ITEM1")
    assert isinstance(item1_amb, ledger_read.AmbiguousItem)
    assert set(item1_amb.candidate_row_ids) == {item1_row, item1_dup_row}

    res_amb_cosign = panel_cosign.cosign(cfg, item1_dup_row, "attest", "self-review",
                                          "endorsing one of the ambiguous candidates directly")
    assert res_amb_cosign.ok

    item_count_after_dup = _item_count(cfg, cid)
    # the pair's item_id contributes exactly one slot both before and after the duplicate lands
    assert item_count_after_dup == item_count_before_dup

    x1_row = insert_note(f"panel-item:{cid}:X1", "X1 -- minimal, no witnesses, renders OPEN")
    x10_row = insert_note(f"panel-item:{cid}:X10", "X10 -- X1 is a literal substring of this token")

    commissions_list = ledger_read.commissions(cfg)
    this_commission = next(c for c in commissions_list if c["row_id"] == cid)
    decomp_final = ledger_read.decomposition_items(cfg, cid)
    assert this_commission["item_count"] == len(decomp_final.items)

    ids_final = [i.item_id for i in decomp_final.items]
    assert ids_final.count("X1") == 1
    assert ids_final.count("X10") == 1
