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

from fastapi import APIRouter, FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import PanelConfig, load_config
from core.ledger_adapter import PostgresCoreLedgerReader
from core.ports import CoreLedgerPort
from core.routes import build_profiles_write_router, router as core_router

# Every extension this repo SHIPS is imported unconditionally, top-of-file, like every other
# import (lazy/function-body imports are banned on principle: a module's importers should pay
# its dependency footprint honestly, and a deferred import here would falsify this module's
# real footprint). `extensions.autoharn` costs nothing to import (pure Python, no DB/subprocess
# work at import time) whether or not `"autoharn"` ends up in `cfg.extensions` -- only its USE
# below is conditional on that. A future second extension is imported here the same way.
from extensions.autoharn import cosign as autoharn_cosign
from extensions.autoharn import routes as autoharn_routes
from extensions.autoharn.ledger_read import autoharn_health

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
# ^ `frontend/dist` is Vite's build output (`npm run build` in frontend/), never `frontend/`
# itself -- the Vue port's source is TypeScript/SFCs, unservable as static files, and its own
# `.gitignore` excludes `dist/` (build output, regenerated, not hand-edited or committed source).
# An operator/CI step must run `npm run build` before starting this backend in a fresh checkout;
# see README.md's operator walkthrough.


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
        # CoreLedgerPort-typed, constructed once at startup (core-ledger-adapter, row 933) --
        # every core route pulls this off `request.app.state.panel.reader` instead of importing
        # `core.ledger_read`/`core.backend_surface` as modules (both deleted; their SQL now lives
        # in `core.ledger_adapter.PostgresCoreLedgerReader`, this Protocol's sole implementation).
        self.reader: CoreLedgerPort = PostgresCoreLedgerReader()
        self.broadcaster = Broadcaster()
        self.poll_task: asyncio.Task | None = None


async def _poll_loop(state: AppState) -> None:
    """The ONE background task polling the ledger's watermark every `cfg.poll_interval` --
    core-generic (`state.reader.watermark`, the same `CoreLedgerPort`-typed reader every route
    handler uses), so this loop runs identically whether or not any extension is enabled."""
    last: dict[str, Any] | None = None
    while True:
        try:
            wm = await asyncio.to_thread(state.reader.watermark, state.cfg)
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
    # Mounted unconditionally at the router level (GET /api/profiles is always a read-only
    # view), and then the mutating profiles routes are gated the same way autoharn's write
    # router is below -- decided once, at process start, on the same `cfg` this factory already
    # resolves for the autoharn mount decision, not `cfg.read_only` re-evaluated per request.

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
            "read_only_reason": cfg.read_only_reason,
            "extensions_enabled": list(cfg.extensions),
            "active_profile": cfg.active_profile,
            "available_profiles": list(cfg.available_profiles),
        }
        if cfg.extension_enabled("autoharn"):
            health["autoharn"] = autoharn_health(cfg)
            health["maintainer_principal"] = cfg.maintainer_principal
        return health

    if cfg.extension_enabled("autoharn"):
        app.include_router(autoharn_routes.router)
        if not cfg.read_only:
            app.include_router(autoharn_routes.build_write_router())

    if not cfg.read_only:
        app.include_router(build_profiles_write_router())

    # Static-file mount for frontend/dist (Vite's build output), MOUNTED LAST so every /api/*
    # route above already holds precedence (a mount only ever catches a request no earlier route
    # claimed). `check_dir` left at its FastAPI default (raises if the directory is missing) --
    # a fresh checkout must run `npm run build` in frontend/ before this backend can start; a
    # missing dist/ here is a real packaging/build-order defect, not a mode this backend degrades
    # gracefully around.
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")

    # SPA history-fallback (cycle-2 consult finding 2): a hard reload / bookmark / shared link to
    # a client-side route like /item/<id> is a GET the StaticFiles mount above can't resolve to a
    # real file, so it would otherwise 404 with a raw `{"detail":"Not Found"}` body instead of the
    # SPA shell -- the Vue router never gets a chance to run. FastAPI/Starlette dispatch routes
    # (including `app.mount`, evaluated in registration order) BEFORE falling through to
    # `app.exception_handlers`, so this is registered as a 404 handler, not another route: it only
    # fires once every /api/* route and every real static asset above has already missed, and it
    # always serves index.html so client-side routing (vue-router, history mode) takes over and
    # renders its own in-app 404 or the matched view.
    @app.exception_handler(StarletteHTTPException)
    async def _spa_history_fallback(request: Request, exc: StarletteHTTPException):
        if (
            exc.status_code == 404
            and request.method == "GET"
            and not request.url.path.startswith("/api/")
        ):
            return FileResponse(_FRONTEND_DIR / "index.html")
        # Registering a handler for StarletteHTTPException REPLACES FastAPI's own default
        # handler for every HTTPException, not just this one path's -- re-raising `exc` here
        # would NOT fall through to that default (this handler already IS the terminal exception
        # path), it would propagate as an unhandled exception and turn every real API 404/other
        # HTTPException into a raw 500 (caught in manual verification: GET /api/rows/<bad-id>
        # regressed from its intended 404 to a 500 before this delegation was added). Delegate to
        # FastAPI's own default so every other HTTPException-raising route is unaffected.
        return await http_exception_handler(request, exc)

    return app


app = create_app()
