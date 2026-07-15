"""tests/test_config_profiles.py -- panel-profile-storage (ledger work item, row 56): named
connection profiles in panel.toml, activated by PANEL_PROFILE.

Pure-Python config-resolution tests (no Postgres, no FastAPI app) -- `load_config` only reads
env vars and a panel.toml path, so these run everywhere, unlike tests/test_core_boundary.py's
live-Postgres suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import config as config_module  # noqa: E402


PANEL_ENV_VARS = (
    "LEDGER_PG_URI", "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD",
    "LEDGER_SCHEMA", "LEDGER_KERNEL_SCHEMA", "LEDGER_ROLE", "LED_BIN",
    "PANEL_CONFIG_FILE", "PANEL_PROFILE", "PANEL_BIND", "PANEL_PORT",
    "PANEL_POLL_INTERVAL", "PANEL_EXTENSIONS", "PANEL_MAINTAINER_PRINCIPAL",
    "LEDGER_DEPLOYMENT", "PANEL_READONLY",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in PANEL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    return tmp_path


def write_panel_toml(root: Path, text: str) -> None:
    (root / "panel.toml").write_text(text, encoding="utf-8")


PROFILE_TOML = """
[profiles.experience]
host = "192.168.122.1"
db = "toy"
schema = "experience"
kern = "experience_kernel"
role = "experience_rw"

[profiles.bare]
host = "192.168.122.9"
db = "otherdb"
schema = "bareschema"
kern = "barekernel"
"""


def test_no_panel_profile_env_leaves_existing_behavior_untouched(repo_root, monkeypatch):
    """The single most important invariant (spec): PANEL_PROFILE unset => the new code path
    does not run at all."""
    monkeypatch.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")
    write_panel_toml(repo_root, PROFILE_TOML)

    cfg = config_module.load_config(repo_root)
    assert cfg.active_profile is None
    assert cfg.available_profiles == ("bare", "experience")
    assert cfg.connection.source == "uri"
    assert cfg.config_source.startswith("connection=uri")


def test_panel_profile_selects_named_profile(repo_root, monkeypatch):
    monkeypatch.setenv("PANEL_PROFILE", "experience")
    write_panel_toml(repo_root, PROFILE_TOML)

    cfg = config_module.load_config(repo_root)
    assert cfg.active_profile == "experience"
    assert cfg.available_profiles == ("bare", "experience")
    assert cfg.connection.source == "profile:experience"
    assert cfg.connection.pg_host == "192.168.122.1"
    assert cfg.connection.pg_db == "toy"
    assert cfg.schema == "experience"
    assert cfg.kern_schema == "experience_kernel"
    assert cfg.role == "experience_rw"
    assert "connection=profile:experience" in cfg.config_source


def test_panel_profile_missing_role_is_none(repo_root, monkeypatch):
    monkeypatch.setenv("PANEL_PROFILE", "bare")
    write_panel_toml(repo_root, PROFILE_TOML)

    cfg = config_module.load_config(repo_root)
    assert cfg.active_profile == "bare"
    assert cfg.role is None


def test_unset_pg_env_still_wins_over_profile(repo_root, monkeypatch):
    """A discrete PG* env var wins outright over an active profile."""
    monkeypatch.setenv("PANEL_PROFILE", "experience")
    monkeypatch.setenv("PGHOST", "10.0.0.5")
    monkeypatch.setenv("PGDATABASE", "envdb")
    monkeypatch.setenv("LEDGER_SCHEMA", "envschema")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "envkern")
    write_panel_toml(repo_root, PROFILE_TOML)

    cfg = config_module.load_config(repo_root)
    assert cfg.connection.source == "discrete"
    assert cfg.connection.pg_host == "10.0.0.5"
    assert cfg.connection.pg_db == "envdb"
    # schema/kern/role env still independent of the profile too since they were set
    assert cfg.schema == "envschema"
    assert cfg.kern_schema == "envkern"
    # profile is still recorded as "active" (it was named), even though it lost the
    # connection race -- the spec only promises the profile's CONNECTION facts are shadowed.
    assert cfg.active_profile == "experience"


def test_ledger_pg_uri_wins_over_profile(repo_root, monkeypatch):
    monkeypatch.setenv("PANEL_PROFILE", "experience")
    monkeypatch.setenv("LEDGER_PG_URI", "host=1.2.3.4 dbname=uridb")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")
    write_panel_toml(repo_root, PROFILE_TOML)

    cfg = config_module.load_config(repo_root)
    assert cfg.connection.source == "uri"
    assert cfg.connection.pg_uri == "host=1.2.3.4 dbname=uridb"


def test_panel_profile_unset_in_toml_raises(repo_root, monkeypatch):
    monkeypatch.setenv("PANEL_PROFILE", "nonexistent")
    write_panel_toml(repo_root, PROFILE_TOML)

    with pytest.raises(SystemExit, match="PANEL_PROFILE='nonexistent'"):
        config_module.load_config(repo_root)


def test_panel_profile_no_panel_toml_raises(repo_root, monkeypatch):
    monkeypatch.setenv("PANEL_PROFILE", "experience")
    # no panel.toml written at all

    with pytest.raises(SystemExit, match="does not exist"):
        config_module.load_config(repo_root)


def test_panel_profile_incomplete_profile_raises(repo_root, monkeypatch):
    monkeypatch.setenv("PANEL_PROFILE", "incomplete")
    write_panel_toml(repo_root, """
[profiles.incomplete]
host = "1.2.3.4"
db = "d"
""")
    with pytest.raises(SystemExit, match="missing or has an empty/non-string value for: schema, kern"):
        config_module.load_config(repo_root)


def test_no_readonly_lock_no_led_bin_reason_is_no_write_conduit(repo_root, monkeypatch):
    """Existing default case (no LED_BIN, no PANEL_READONLY): read_only stays True as today,
    read_only_reason is the new additive "no-write-conduit" detail -- must not perturb the
    boolean test_core_boundary.py already exercises."""
    monkeypatch.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")

    cfg = config_module.load_config(repo_root)
    assert cfg.led_bin is None
    assert cfg.read_only is True
    assert cfg.read_only_reason == "no-write-conduit"


def test_led_bin_set_no_lock_is_writable(repo_root, monkeypatch):
    monkeypatch.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")
    monkeypatch.setenv("LED_BIN", "/usr/local/bin/led")

    cfg = config_module.load_config(repo_root)
    assert cfg.led_bin == Path("/usr/local/bin/led")
    assert cfg.read_only is False
    assert cfg.read_only_reason is None


def test_panel_readonly_locks_even_with_led_bin_set(repo_root, monkeypatch):
    """The safety override: PANEL_READONLY truthy forces read_only=True even though led_bin
    resolved to a real path -- and led_bin itself is still resolved/stored (config_source stays
    honest about what WOULD have been writable), never silently skipped."""
    monkeypatch.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")
    monkeypatch.setenv("LED_BIN", "/usr/local/bin/led")
    monkeypatch.setenv("PANEL_READONLY", "1")

    cfg = config_module.load_config(repo_root)
    assert cfg.led_bin == Path("/usr/local/bin/led")  # still resolved, not suppressed
    assert cfg.read_only is True
    assert cfg.read_only_reason == "locked"
    assert "PANEL_READONLY=locked" in cfg.config_source


@pytest.mark.parametrize("value", ["true", "TRUE", "yes", "on", "1"])
def test_panel_readonly_truthy_strings(repo_root, monkeypatch, value):
    monkeypatch.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")
    monkeypatch.setenv("PANEL_READONLY", value)

    cfg = config_module.load_config(repo_root)
    assert cfg.read_only_locked is True
    assert cfg.read_only_reason == "locked"


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_panel_readonly_falsy_strings_do_not_lock(repo_root, monkeypatch, value):
    monkeypatch.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")
    monkeypatch.setenv("PANEL_READONLY", value)

    cfg = config_module.load_config(repo_root)
    assert cfg.read_only_locked is False
    assert cfg.read_only_reason == "no-write-conduit"


def test_panel_readonly_from_toml_ledger_table(repo_root, monkeypatch):
    monkeypatch.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")
    monkeypatch.setenv("LED_BIN", "/usr/local/bin/led")
    write_panel_toml(repo_root, """
[ledger]
readonly = true
""")

    cfg = config_module.load_config(repo_root)
    assert cfg.read_only_locked is True
    assert cfg.read_only_reason == "locked"


def test_panel_readonly_env_wins_over_toml(repo_root, monkeypatch):
    monkeypatch.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")
    monkeypatch.setenv("PANEL_READONLY", "false")
    write_panel_toml(repo_root, """
[ledger]
readonly = true
""")

    cfg = config_module.load_config(repo_root)
    assert cfg.read_only_locked is False
    assert cfg.read_only_reason == "no-write-conduit"


def test_profiles_table_nested_correctly_sibling_of_ledger(repo_root, monkeypatch):
    """[profiles] must not be nested inside [ledger] -- and [ledger]'s own semantics must be
    unaffected by the new [profiles] table living alongside it."""
    monkeypatch.setenv("PANEL_PROFILE", "experience")
    write_panel_toml(repo_root, """
[ledger]
schema = "ledger-schema"
kernel_schema = "ledger-kern"

""" + PROFILE_TOML)

    cfg = config_module.load_config(repo_root)
    # [ledger]'s own schema/kernel_schema still win over the profile's (per-key fallback,
    # [ledger] table is tried before the profile per the precedence doc).
    assert cfg.schema == "ledger-schema"
    assert cfg.kern_schema == "ledger-kern"
    assert cfg.connection.source == "profile:experience"  # [ledger] named no connection facts
