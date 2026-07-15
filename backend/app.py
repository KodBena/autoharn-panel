"""backend.app -- the FastAPI service, assembled per SPEC.md sec 4's extension boundary: core
routes are ALWAYS mounted; the `autoharn` extension (decomposition items, obligation semantics,
cosign via LED_BIN, kernel vocabularies) is mounted only when `"autoharn" in cfg.extensions`
(enabled by default, per SPEC.md sec 1's `PANEL_EXTENSIONS`).

Run directly: `python3 -m uvicorn app:app --host <bind> --port <port>` from this directory (see
README.md for the operator walkthrough and the three config-mode witnesses).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from config import PanelConfig, load_config
from core import ledger_read as core_ledger_read
from core.routes import router as core_router

# Every extension this repo SHIPS is imported unconditionally, top-of-file, like every other
# import (lazy/function-body imports are banned on principle: a module's importers should pay
# its dependency footprint honestly, and a deferred import here would falsify this module's
# real footprint). `extensions.autoharn` costs nothing to import (pure Python, no DB/subprocess
# work at import time) whether or not `"autoharn"` ends up in `cfg.extensions` -- only its USE
# below is conditional on that. A future second extension is imported here the same way.
from extensions.autoharn import cosign as autoharn_cosign
from extensions.autoharn import routes as autoharn_routes
from extensions.autoharn.ledger_read import autoharn_health

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class Broadcaster:
    """Fan-out from ONE background DB poll to N connected SSE clients -- not one poll per
    client. Core-generic: it knows nothing about what changed, only that the watermark moved."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            await q.put(event)


class AppState:
    def __init__(self, cfg: PanelConfig) -> None:
        self.cfg = cfg
        self.broadcaster = Broadcaster()
        self.poll_task: asyncio.Task | None = None


async def _poll_loop(state: AppState) -> None:
    """The ONE background task polling the ledger's watermark every `cfg.poll_interval` --
    core-generic (`core.ledger_read.watermark`), so this loop runs identically whether or not
    any extension is enabled."""
    last: dict[str, Any] | None = None
    while True:
        try:
            wm = await asyncio.to_thread(core_ledger_read.watermark, state.cfg)
        except Exception:  # noqa: BLE001 -- a transient DB hiccup must not kill the poller
            await asyncio.sleep(state.cfg.poll_interval)
            continue
        if wm != last:
            last = wm
            await state.broadcaster.publish({"type": "ledger-change", "watermark": wm})
        await asyncio.sleep(state.cfg.poll_interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = load_config()
    state = AppState(cfg)
    app.state.panel = state

    if cfg.extension_enabled("autoharn") and not cfg.read_only:
        result = await asyncio.to_thread(
            autoharn_cosign.ensure_principal_registered, cfg, cfg.maintainer_principal, "human"
        )
        if not result.ok:
            raise RuntimeError(
                f"panel startup: could not register maintainer principal "
                f"{cfg.maintainer_principal!r} via LED_BIN register-principal "
                f"(exit {result.exit_code}): {result.stderr}"
            )

    state.poll_task = asyncio.create_task(_poll_loop(state))
    try:
        yield
    finally:
        if state.poll_task is not None:
            state.poll_task.cancel()


def create_app() -> FastAPI:
    """App factory (used directly by `tests/test_core_bare_schema.py` to build an app with only
    core mounted, and by `uvicorn app:app` below for normal operation) -- reads
    `cfg.extensions` fresh at call time via the lifespan above, so this factory itself does not
    need to pre-resolve config just to decide what to mount; every route module registers
    itself unconditionally and reads `request.app.state.panel.cfg` per request instead. The one
    exception is the extension MOUNT itself, decided once, at import/startup time, below."""
    app = FastAPI(title="ledger-panel (standalone)", lifespan=lifespan)
    app.include_router(core_router)

    # Extension mount decision: read once, at process start, from the same config resolution
    # the lifespan will use (load_config is cheap and side-effect-free besides its own fail-loud
    # checks, so calling it here and again in lifespan is not a double-resolution hazard -- both
    # calls see the same environment).
    cfg = load_config()

    @app.get("/api/health")
    def api_health() -> dict[str, Any]:
        health: dict[str, Any] = {
            "ok": True,
            "config_source": cfg.config_source,
            "schema": cfg.schema,
            "kern_schema": cfg.kern_schema,
            "read_only": cfg.read_only,
            "extensions_enabled": list(cfg.extensions),
        }
        if cfg.extension_enabled("autoharn"):
            health["autoharn"] = autoharn_health(cfg)
            health["maintainer_principal"] = cfg.maintainer_principal
        return health

    if cfg.extension_enabled("autoharn"):
        app.include_router(autoharn_routes.router)
        if not cfg.read_only:
            app.include_router(autoharn_routes.build_write_router())

    # Static-file mount for frontend/, MOUNTED LAST so every /api/* route above already holds
    # precedence (a mount only ever catches a request no earlier route claimed). `check_dir`
    # left at its FastAPI default (raises if the directory is missing) -- this repo always
    # ships frontend/ alongside backend/, so a missing directory here is a real packaging
    # defect, not a mode this backend degrades gracefully around.
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
