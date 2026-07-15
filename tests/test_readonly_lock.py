"""tests/test_readonly_lock.py -- panel-readonly-lock (ledger work item, row 58): PANEL_READONLY
is a safety OVERRIDE, independent of whether LED_BIN resolved to a real path (spec: "the
concrete need: agentic UI exploration that must not risk an accidental write while still
letting the operator later flip the lock off").

This suite needs no live Postgres: which routes get MOUNTED is decided once, at `create_app()`
build time (see backend/app.py's own comment on that), never per-request -- so route presence/
absence can be asserted purely by inspecting `app.routes`, the same way test_config_profiles.py
asserts pure config facts with no DB.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

# `app` is deliberately NOT imported at module top-level -- same reasoning as
# tests/test_core_boundary.py: its module-level code resolves config at IMPORT time, so env
# vars must be monkeypatched BEFORE app's first import.


def _route_paths(app, method: str) -> set[str]:
    """Walks `app.routes` recursively: this FastAPI version wraps an `include_router()`'d
    router in an `_IncludedRouter` node whose own children (not the outer node) carry
    `path`/`methods`, so a flat top-level scan misses everything mounted via include_router --
    only a genuinely un-nested `APIRoute` contributes a path/method pair directly."""
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
    original_router = getattr(route, "original_router", None)  # this FastAPI version's
    # `_IncludedRouter` node (from `include_router()`) carries its child routes here, not on
    # `.routes` directly.
    if original_router is not None:
        for child in getattr(original_router, "routes", None) or ():
            _collect_route_paths(child, method, paths)


def _build_app(monkeypatch, *, led_bin: str | None, panel_readonly: str | None):
    monkeypatch.setenv("LEDGER_PG_URI", "host=127.0.0.1 dbname=toy")
    monkeypatch.setenv("LEDGER_SCHEMA", "s")
    monkeypatch.setenv("LEDGER_KERNEL_SCHEMA", "k")
    monkeypatch.setenv("PANEL_EXTENSIONS", "autoharn")
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


def test_led_bin_set_no_lock_mounts_write_route(monkeypatch):
    app_module, app = _build_app(monkeypatch, led_bin="/usr/local/bin/led", panel_readonly=None)
    assert app_module.load_config().read_only is False
    assert app_module.load_config().read_only_reason is None
    assert "/api/cosign" in _route_paths(app, "POST")


def test_panel_readonly_locks_even_with_led_bin_set_and_write_route_absent(monkeypatch):
    """The core assertion this slug exists for: PANEL_READONLY=1 with LED_BIN also SET still
    yields read_only=True, read_only_reason="locked", and the write route is not mounted --
    mirroring test_core_boundary.py's own pattern of asserting a route's ABSENCE (its
    /api/commissions 404-when-extension-disabled case) rather than trying to POST and checking
    for a refusal, since the route does not exist at all in this state."""
    app_module, app = _build_app(monkeypatch, led_bin="/usr/local/bin/led", panel_readonly="1")
    cfg = app_module.load_config()
    assert cfg.led_bin is not None  # still resolved/stored, not suppressed by the lock
    assert cfg.read_only is True
    assert cfg.read_only_reason == "locked"
    assert "/api/cosign" not in _route_paths(app, "POST")


def test_no_led_bin_no_lock_reason_is_no_write_conduit_and_write_route_absent(monkeypatch):
    """Existing default case, unperturbed: no LED_BIN, no PANEL_READONLY."""
    app_module, app = _build_app(monkeypatch, led_bin=None, panel_readonly=None)
    cfg = app_module.load_config()
    assert cfg.read_only is True
    assert cfg.read_only_reason == "no-write-conduit"
    assert "/api/cosign" not in _route_paths(app, "POST")
