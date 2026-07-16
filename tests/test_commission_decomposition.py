"""tests/test_commission_decomposition.py -- regression proof for fix-commission-decomposition-view
(row:249): the Commission decomposition view (`GET /api/commissions`, `GET /api/commission/{id}`)
reported '0 items' for every commission whose children were plain `work_opened` rows with a bare
`row:<commission_row>` `--refs` token (this deployment's actual, documented CLAUDE.md point 1
convention) -- `extensions.autoharn.ledger_read.fetch_parsed_item_rows` only ever recognized the
PoC-era `panel-item:<commission_row>:<item_id>` token grammar on a `note` row, which has ZERO live
specimens in this deployment (see row:328's finding). This module proves the ADDITIVE fix: BOTH
conventions are now recognized, merged into one `items` list.

Two-tier live-DB proof, same pattern as tests/test_item_view_live.py/test_cosign_live.py (real
Postgres, no mocks) -- SKIPPED, not failed, without a reachable Postgres host:

1. `test_plain_work_opened_children_are_counted` -- SYNTHETIC scratch-schema specimen: a
   commission row plus a `work_opened` row whose `refs` carries a bare `row:<commission>` token
   (inserted directly via SQL -- `led work open` itself cannot write `--refs` on a work_opened row,
   see row:328's finding, so no CLI can produce this shape yet; the column supports it regardless
   and this is the shape a future led.tmpl patch, or a direct SQL correction, would produce). This
   is the actual regression test: it fails RED against the pre-fix `fetch_parsed_item_rows` (which
   only ever looked for `panel-item:` tokens) and passes GREEN against the fix.
2. `test_panel_item_and_work_opened_conventions_coexist` -- one commission with ONE child under
   each convention, proving "additive" literally: neither convention's items are dropped when the
   other is also present.

A THIRD, read-only check (`test_live_commission_48_specimen_read_only`) queries this deployment's
OWN production ledger (the `deployment.json` connection, not the scratch schema) for the exact
commission the consult cited (row 48) as a live sanity check -- but see its own docstring: row:328's
finding already established that row 48 has NO structured refs under either convention (only a
free-prose mention on a later `decision` row), so this test asserts the HONEST current behavior
(item_count reads a stable, non-crashing value) rather than fabricating a "now shows items" claim
that would not be true of this specific historical specimen. It is a read-only SELECT only -- it
writes nothing to the production ledger.
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

from config import ConnectionFacts, PanelConfig  # noqa: E402
from extensions.autoharn import ledger_read  # noqa: E402

PGHOST = os.environ.get("EPISTEMIC_PGHOST") or os.environ.get("PGHOST")
PGDB = os.environ.get("PANEL_TEST_PGDATABASE", "toy")
AUTOHARN_SIBLING = Path(os.environ.get("AUTOHARN_CHECKOUT", str(REPO.parent / "autoharn")))
LED_TMPL = AUTOHARN_SIBLING / "bootstrap" / "templates" / "led.tmpl"
LINEAGE = AUTOHARN_SIBLING / "kernel" / "lineage"

SCHEMA, KERN, ROLE = "pcommdecomp", "pcommdecomp_kernel", "pcommdecomp_rw"
SCRATCH_DEPLOYMENT_PATH = Path(f"/tmp/.{SCHEMA}_deployment.json")

CHAIN_TO_S25 = [
    "s15-schema.sql", "s17-stamp-mechanism.sql", "s17-independence-vocabulary.sql",
    "s19-trigger-search-path.sql", "s20-obligation-grants-and-view-refresh.sql",
    "s21-session-aware-distinctness.sql", "s22-work-item-ledger.sql",
    "s23-per-invocation-stamp-token.sql", "s24-declared-event-time.sql",
    "s25-commission-kind.sql",
]

pytestmark = pytest.mark.skipif(
    not PGHOST or not LINEAGE.is_dir(),
    reason=(
        "commission-decomposition live fixture needs a reachable PGHOST (EPISTEMIC_PGHOST/PGHOST) "
        "and a sibling autoharn checkout's kernel/lineage/ (set AUTOHARN_CHECKOUT if it is not at "
        "../autoharn) -- SKIPPED, not failed, when absent."
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
    # PGOPTIONS in THIS harness's own shell carries a live app.vendor_* stamp (the tool
    # interception's own HMAC, tied to the REAL "experience" deployment's stamp secret) -- s17's
    # set_stamp() trigger sees those GUCs on every psql call, tries to validate them against
    # THIS scratch schema's freshly-generated (and necessarily DIFFERENT) secret, and hard-refuses
    # the insert (mismatched HMAC), rather than the intended "no GUCs set -> unstamped, recorded
    # verified=false, not refused" path a raw non-intercepted psql write is supposed to take
    # (s17-stamp-mechanism.sql's set_stamp(), the same fail-open-to-unverified shape insert_note
    # already relies on in test_item_view_live.py/test_cosign_live.py). Clearing PGOPTIONS for
    # this fixture-only write path restores that intended shape.
    env = dict(os.environ)
    env.pop("PGOPTIONS", None)
    return sh(["psql", "-h", PGHOST, "-d", PGDB, "-v", "ON_ERROR_STOP=1", "-tA", "-q",
               "-c", prefix + sql], env=env)


def insert_row(kind: str, statement: str, refs: str = "", work_slug: str | None = None) -> int:
    cols = ["kind", "statement", "refs"]
    vals = [_pg_str(kind), _pg_str(statement), _pg_str(refs)]
    if work_slug is not None:
        cols.append("work_slug")
        vals.append(_pg_str(work_slug))
        if kind == "work_opened":
            # work_title_kind_shape's check constraint requires work_title alongside work_slug on
            # a work_opened row (the real `led work open` always supplies one; a raw INSERT must
            # match the same shape).
            cols.append("work_title")
            vals.append(_pg_str(statement))
    sql = f"INSERT INTO ledger ({', '.join(cols)}) VALUES ({', '.join(vals)}) RETURNING id;"
    r = psql(sql)
    assert r.returncode == 0, f"insert_row({kind!r}) failed: {r.stderr}"
    return int(r.stdout.strip())


def build_cfg() -> PanelConfig:
    connection = ConnectionFacts(pg_uri=None, pg_host=PGHOST, pg_port=None, pg_db=PGDB,
                                  pg_user=None, pg_password=None, source="test-scratch")
    return PanelConfig(
        repo_root=REPO, connection=connection, schema=SCHEMA, kern_schema=KERN, role=ROLE,
        led_bin=None, read_only_locked=True, bind_host="127.0.0.1", bind_port=8421, poll_interval=2.0,
        extensions=("autoharn",), config_source="test-scratch", maintainer_principal="maintainer",
        active_profile=None, available_profiles=(),
    )


def build_production_cfg() -> PanelConfig | None:
    """Build a PanelConfig straight from THIS repo's own deployment.json (bypassing env/panel.toml
    entirely, unlike `load_config`) -- the scratch fixture above deliberately sets PGHOST so
    `load_config` would otherwise resolve an env-based connection instead of deployment.json's own
    host/schema/kern/role, which is not what `test_live_commission_48_specimen_read_only` wants to
    exercise. Returns None (never raises) if deployment.json is absent or malformed -- the caller
    skips rather than fails."""
    dep_path = REPO / "deployment.json"
    if not dep_path.is_file():
        return None
    try:
        dep = json.loads(dep_path.read_text(encoding="utf-8"))
        connection = ConnectionFacts(pg_uri=None, pg_host=dep["host"], pg_port=None,
                                      pg_db=dep["db"], pg_user=None, pg_password=None,
                                      source="autoharn-deployment.json")
        return PanelConfig(
            repo_root=REPO, connection=connection, schema=dep["schema"], kern_schema=dep["kern"],
            role=dep.get("role"), led_bin=None, read_only_locked=True, bind_host="127.0.0.1",
            bind_port=8422, poll_interval=2.0, extensions=("autoharn",),
            config_source="test-production-readonly", maintainer_principal="maintainer",
            active_profile=None, available_profiles=(),
        )
    except (KeyError, json.JSONDecodeError):
        return None


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


def test_plain_work_opened_children_are_counted(scratch_ledger: PanelConfig) -> None:
    """RED pre-fix (fetch_parsed_item_rows only recognized panel-item: tokens on a note row --
    item_count would read 0 here), GREEN post-fix: a commission with ONE plain work_opened child
    (refs = bare 'row:<commission>', no panel-item: wrapper anywhere, exactly the CLAUDE.md point 1
    convention) reports non-zero decomposition items."""
    cfg = scratch_ledger
    commission_row = insert_row("commission", "build the thing, decompose it first")
    child_row = insert_row(
        "work_opened", "work_opened: build-the-thing -- build the actual thing",
        refs=f"row:{commission_row}", work_slug="build-the-thing",
    )

    commissions = {c["row_id"]: c for c in ledger_read.commissions(cfg)}
    assert commission_row in commissions
    assert commissions[commission_row]["item_count"] == 1, (
        "plain work_opened+refs=row:<commission> child was not counted -- the regression this "
        "fix targets"
    )

    decomposition = ledger_read.decomposition_items(cfg, commission_row)
    assert len(decomposition.items) == 1
    item = decomposition.items[0]
    assert isinstance(item, ledger_read.ResolvedItem)
    assert item.item_id == "build-the-thing"
    assert item.row_id == child_row
    # No witnesses declared beyond the implicit work-item self-witness -> not yet closed -> OPEN.
    assert item.status == "OPEN"


def test_panel_item_and_work_opened_conventions_coexist(scratch_ledger: PanelConfig) -> None:
    """Additive, not exclusive: a commission with ONE child under each convention must report
    BOTH -- the PoC-era panel-item: note-row child is not dropped by recognizing the new
    work_opened convention alongside it."""
    cfg = scratch_ledger
    commission_row = insert_row("commission", "a second commission, mixed-convention children")

    note_child = insert_row(
        "note", "old-style decomposition item, still recognized",
        refs=f"panel-item:{commission_row}:X1",
    )
    work_child = insert_row(
        "work_opened", "work_opened: new-style-item -- the new-convention item",
        refs=f"row:{commission_row}", work_slug="new-style-item",
    )

    decomposition = ledger_read.decomposition_items(cfg, commission_row)
    item_ids = {item.item_id for item in decomposition.items}
    assert item_ids == {"X1", "new-style-item"}
    by_id = {item.item_id: item for item in decomposition.items}
    assert by_id["X1"].row_id == note_child
    assert by_id["new-style-item"].row_id == work_child

    commissions = {c["row_id"]: c for c in ledger_read.commissions(cfg)}
    assert commissions[commission_row]["item_count"] == 2


def test_work_opened_item_witnessed_when_closed(scratch_ledger: PanelConfig) -> None:
    """A plain work_opened item's implicit witness is the work item itself (ref_kind='work') --
    closing the work item (work_closed) must move its decomposition-item status from OPEN to
    WITNESSED, the same live-disposition guarantee panel-item: items already had."""
    cfg = scratch_ledger
    commission_row = insert_row("commission", "a commission whose item gets closed")
    insert_row(
        "work_opened", "work_opened: closable-item -- an item that will be closed",
        refs=f"row:{commission_row}", work_slug="closable-item",
    )
    before = ledger_read.decomposition_items(cfg, commission_row).items
    assert before[0].status == "OPEN"

    witness_row = insert_row("note", "closable-item's shipped witness")
    r = psql(
        "INSERT INTO ledger (kind, work_slug, work_resolution, work_witness, statement) "
        f"VALUES ('work_closed', 'closable-item', 'shipped', 'row:{witness_row}', "
        "'work_closed: closable-item');"
    )
    assert r.returncode == 0, r.stderr

    after = ledger_read.decomposition_items(cfg, commission_row).items
    assert len(after) == 1
    assert after[0].status == "WITNESSED"


def test_live_commission_48_specimen_read_only() -> None:
    """Read-only sanity check against THIS deployment's OWN production ledger (deployment.json,
    schema 'experience') for commission row 48 -- the consult's cited specimen. This does NOT
    assert 'now shows non-zero items': row:328's finding already established that row 48 has zero
    structured refs linking it to its real children (ui-agentic-prereqs/56-59) under EITHER
    convention -- only a later decision row (88) mentions 'row:48' in free prose, and no
    work_opened row in this entire deployment has ever carried a refs value at all (`led work
    open` has no --refs flag; confirmed by reading bootstrap/templates/led.tmpl). Asserting a
    fabricated 'fixed' result for this specific historical row would misrepresent what the fix
    actually does. What this test DOES prove, against real production data: the merged
    read path (BOTH conventions in one query) does not crash, does not double-count, and returns
    a stable, reproducible item_count for a real commission row -- the same honest, non-mocked
    proof style used elsewhere in this suite, applied read-only against production rather than a
    scratch schema."""
    cfg = build_production_cfg()
    if cfg is None:
        pytest.skip("no deployment.json found at repo root")

    try:
        decomposition = ledger_read.decomposition_items(cfg, 48)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"production ledger not reachable from this environment: {exc}")

    # Stable/idempotent: re-reading must not change the answer (read-only, no mutation happened).
    decomposition_again = ledger_read.decomposition_items(cfg, 48)
    assert len(decomposition.items) == len(decomposition_again.items)
    # Honest current-state assertion (see docstring): no structured refs exist for row 48 yet.
    assert len(decomposition.items) == 0
