"""tests/test_profiles_write.py -- panel-profiles-write-backend (ledger work item, row 142/143):
write-capable profile management (`backend/core/profiles_write.py` + the `/api/profiles`
routes in `backend/core/routes.py`).

Two layers, mirroring `tests/test_config_profiles.py` (pure config) and
`tests/test_readonly_lock.py` (route-presence-by-inspection, no live Postgres):

  1. Pure-Python tests against `profiles_write.list_profiles/upsert_profile/delete_profile`
     directly (no FastAPI app, no DB) -- these exercise validation, atomic write, and
     [ledger]-table preservation.
  2. FastAPI route-mounting tests, following `test_readonly_lock.py`'s pattern EXACTLY: build
     `app` with `PANEL_EXTENSIONS=""` (so the autoharn extension, and its startup
     `ensure_principal_registered` shell-out, never engages) and either a real or absent
     `LED_BIN`, then use `TestClient` to exercise the actual GET/POST/DELETE handlers -- no live
     Postgres needed since none of these routes touch the ledger DB.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import tomlkit
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import core.profiles_write as profiles_write  # noqa: E402

# `app` is deliberately NOT imported at module top-level -- same reasoning as
# tests/test_readonly_lock.py: its module-level code resolves config at IMPORT time, so env
# vars must be monkeypatched BEFORE app's first import.


# ---------------------------------------------------------------------------
# Layer 1: pure-Python tests against profiles_write directly
# ---------------------------------------------------------------------------

PROFILE_TOML = """
[ledger]
pg_uri = "host=127.0.0.1 dbname=toy"
schema = "s"
kernel_schema = "k"

[profiles.experience]
host = "192.168.122.1"
db = "toy"
schema = "experience"
kern = "experience_kernel"
role = "experience_rw"
"""


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    return tmp_path


def write_panel_toml(root: Path, text: str) -> None:
    (root / "panel.toml").write_text(text, encoding="utf-8")


def test_list_profiles_returns_whats_in_panel_toml(repo_root):
    write_panel_toml(repo_root, PROFILE_TOML)
    profiles = profiles_write.list_profiles(repo_root)
    assert profiles == [
        {
            "name": "experience",
            "host": "192.168.122.1",
            "db": "toy",
            "schema": "experience",
            "kern": "experience_kernel",
            "role": "experience_rw",
        }
    ]


def test_list_profiles_empty_when_no_panel_toml(repo_root):
    assert profiles_write.list_profiles(repo_root) == []


def test_upsert_creates_new_profile_file_if_none_exists(repo_root):
    assert not (repo_root / "panel.toml").exists()
    result = profiles_write.upsert_profile(
        repo_root, "fresh",
        {"host": "10.0.0.1", "db": "d", "schema": "s", "kern": "k"},
    )
    assert (repo_root / "panel.toml").is_file()
    assert result == [
        {"name": "fresh", "host": "10.0.0.1", "db": "d", "schema": "s", "kern": "k", "role": None}
    ]


def test_upsert_preserves_existing_ledger_table_untouched(repo_root):
    write_panel_toml(repo_root, PROFILE_TOML)
    profiles_write.upsert_profile(
        repo_root, "newone",
        {"host": "h", "db": "d", "schema": "s", "kern": "k", "role": "r"},
    )
    doc = tomlkit.parse((repo_root / "panel.toml").read_text(encoding="utf-8"))
    assert doc["ledger"]["pg_uri"] == "host=127.0.0.1 dbname=toy"
    assert doc["ledger"]["schema"] == "s"
    assert doc["ledger"]["kernel_schema"] == "k"
    # the pre-existing profile must still be there too -- upsert adds, never clobbers siblings
    assert doc["profiles"]["experience"]["host"] == "192.168.122.1"
    assert doc["profiles"]["newone"]["host"] == "h"


def test_upsert_overwrites_same_name(repo_root):
    write_panel_toml(repo_root, PROFILE_TOML)
    profiles_write.upsert_profile(
        repo_root, "experience",
        {"host": "changed", "db": "toy", "schema": "experience", "kern": "experience_kernel"},
    )
    profiles = profiles_write.list_profiles(repo_root)
    assert len(profiles) == 1
    assert profiles[0]["host"] == "changed"
    assert profiles[0]["role"] is None


@pytest.mark.parametrize("missing_field", ["host", "db", "schema", "kern"])
def test_upsert_validates_required_fields(repo_root, missing_field):
    fields = {"host": "h", "db": "d", "schema": "s", "kern": "k"}
    del fields[missing_field]
    with pytest.raises(profiles_write.ProfileValidationError):
        profiles_write.upsert_profile(repo_root, "p", fields)
    # a rejected upsert must not have written anything at all
    assert not (repo_root / "panel.toml").exists()


def test_upsert_validates_name_is_non_empty_string():
    with pytest.raises(profiles_write.ProfileValidationError):
        profiles_write.upsert_profile(
            Path("/nonexistent-should-not-be-touched"), "",
            {"host": "h", "db": "d", "schema": "s", "kern": "k"},
        )


def test_upsert_validates_name_safe_as_toml_key(repo_root):
    with pytest.raises(profiles_write.ProfileValidationError):
        profiles_write.upsert_profile(
            repo_root, "not a valid key!",
            {"host": "h", "db": "d", "schema": "s", "kern": "k"},
        )


def test_delete_removes_only_named_profile(repo_root):
    write_panel_toml(repo_root, PROFILE_TOML)
    profiles_write.upsert_profile(
        repo_root, "second", {"host": "h2", "db": "d2", "schema": "s2", "kern": "k2"},
    )
    result = profiles_write.delete_profile(repo_root, "experience")
    assert result == [
        {"name": "second", "host": "h2", "db": "d2", "schema": "s2", "kern": "k2", "role": None}
    ]
    doc = tomlkit.parse((repo_root / "panel.toml").read_text(encoding="utf-8"))
    assert doc["ledger"]["pg_uri"] == "host=127.0.0.1 dbname=toy"  # untouched


def test_delete_missing_profile_raises_keyerror(repo_root):
    write_panel_toml(repo_root, PROFILE_TOML)
    with pytest.raises(KeyError):
        profiles_write.delete_profile(repo_root, "does-not-exist")


# ---------------------------------------------------------------------------
# Layer 2: FastAPI route-mounting + end-to-end handler tests
# ---------------------------------------------------------------------------

def _build_app(monkeypatch, tmp_path: Path, *, led_bin: str | None, panel_readonly: str | None):
    monkeypatch.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")
    # autoharn disabled: its own lifespan startup shells out to LED_BIN register-principal when
    # writable, which this test suite must never trigger.
    monkeypatch.setenv("PANEL_EXTENSIONS", "")
    monkeypatch.setenv("PANEL_CONFIG_FILE", str(tmp_path / "panel.toml"))
    if led_bin is None:
        monkeypatch.delenv("LED_BIN", raising=False)
    else:
        monkeypatch.setenv("LED_BIN", led_bin)
    if panel_readonly is None:
        monkeypatch.delenv("PANEL_READONLY", raising=False)
    else:
        monkeypatch.setenv("PANEL_READONLY", panel_readonly)
    monkeypatch.delenv("LEDGER_ROLE", raising=False)

    import app as app_module
    importlib.reload(app_module)
    return app_module, app_module.create_app()


def _route_paths(app, method: str) -> set[str]:
    paths: set[str] = set()
    for route in app.routes:
        _collect_route_paths(route, method, paths)
    return paths


def _collect_route_paths(route, method: str, paths: set[str]) -> None:
    if hasattr(route, "methods") and route.methods and hasattr(route, "path"):
        if method in route.methods:
            paths.add(route.path)
    for child in getattr(route, "routes", None) or ():
        _collect_route_paths(child, method, paths)
    original_router = getattr(route, "original_router", None)
    if original_router is not None:
        for child in getattr(original_router, "routes", None) or ():
            _collect_route_paths(child, method, paths)


def test_get_profiles_route_always_mounted_even_when_read_only(monkeypatch, tmp_path):
    _, app = _build_app(monkeypatch, tmp_path, led_bin=None, panel_readonly=None)
    assert "/api/profiles" in _route_paths(app, "GET")


def test_write_routes_not_mounted_when_no_write_conduit(monkeypatch, tmp_path):
    _, app = _build_app(monkeypatch, tmp_path, led_bin=None, panel_readonly=None)
    assert "/api/profiles" not in _route_paths(app, "POST")
    assert "/api/profiles/{name}" not in _route_paths(app, "DELETE")


def test_write_routes_not_mounted_when_locked(monkeypatch, tmp_path):
    _, app = _build_app(monkeypatch, tmp_path, led_bin="/usr/local/bin/led", panel_readonly="1")
    assert "/api/profiles" not in _route_paths(app, "POST")
    assert "/api/profiles/{name}" not in _route_paths(app, "DELETE")


def test_write_routes_mounted_when_writable(monkeypatch, tmp_path):
    _, app = _build_app(monkeypatch, tmp_path, led_bin="/usr/local/bin/led", panel_readonly=None)
    assert "/api/profiles" in _route_paths(app, "POST")
    assert "/api/profiles/{name}" in _route_paths(app, "DELETE")


def test_end_to_end_list_upsert_delete_via_client(monkeypatch, tmp_path):
    _, app = _build_app(monkeypatch, tmp_path, led_bin="/usr/local/bin/led", panel_readonly=None)
    with TestClient(app) as client:
        assert client.get("/api/profiles").json() == []

        resp = client.post(
            "/api/profiles",
            json={"name": "e2e", "host": "h", "db": "d", "schema": "s", "kern": "k", "role": "r"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == [
            {"name": "e2e", "host": "h", "db": "d", "schema": "s", "kern": "k", "role": "r"}
        ]

        assert client.get("/api/profiles").json() == resp.json()

        resp = client.delete("/api/profiles/e2e")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

        resp = client.delete("/api/profiles/e2e")
        assert resp.status_code == 404


def test_delete_refuses_active_profile(monkeypatch, tmp_path):
    """row:152's gap, resolved by row:159's decision: deleting the profile PANEL_PROFILE
    currently names is refused (400), not merely warned about -- it would break the next
    restart otherwise (config.py's ConfigError on an unresolvable PANEL_PROFILE)."""
    (tmp_path / "panel.toml").write_text(
        '[profiles.active]\nhost = "h"\ndb = "d"\nschema = "s"\nkern = "k"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PANEL_PROFILE", "active")
    _, app = _build_app(monkeypatch, tmp_path, led_bin="/usr/local/bin/led", panel_readonly=None)
    with TestClient(app) as client:
        resp = client.delete("/api/profiles/active")
        assert resp.status_code == 400
        assert "active" in resp.json()["detail"]
        # untouched -- still listed
        assert any(p["name"] == "active" for p in client.get("/api/profiles").json())


def test_end_to_end_upsert_missing_field_is_400_not_crash(monkeypatch, tmp_path):
    _, app = _build_app(monkeypatch, tmp_path, led_bin="/usr/local/bin/led", panel_readonly=None)
    with TestClient(app) as client:
        resp = client.post(
            "/api/profiles",
            json={"name": "bad", "host": "h", "db": "d", "schema": "s"},  # kern missing
        )
        assert resp.status_code == 400
