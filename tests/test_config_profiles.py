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
    "LEDGER_DEPLOYMENT",
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
