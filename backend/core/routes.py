"""backend.core.routes -- the core, ledger-generic FastAPI router (SPEC.md sec 4). Mounted
unconditionally by app.py; knows nothing about `PANEL_EXTENSIONS` or any extension router --
app.py decides what else gets mounted alongside this one.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from core import ledger_read, profiles_write

router = APIRouter()


class ProfileUpsertRequest(BaseModel):
    # panel.toml's own field is named `schema` (per config.py's `_resolve_active_profile`), but
    # a bare `schema` attribute name shadows `BaseModel`'s own `schema` attribute in this
    # pydantic version -- alias the wire field to `schema` while keeping the Python attribute
    # `schema_` collision-free; `populate_by_name` also accepts the Python name directly (e.g.
    # from tests constructing this model in-process).
    model_config = ConfigDict(populate_by_name=True)

    name: str
    host: str | None = None
    db: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    kern: str | None = None
    role: str | None = None


@router.get("/api/rows")
def api_rows(
    request: Request,
    kind: str | None = None,
    actor: str | None = None,
    q: str | None = None,
    since_id: int | None = None,
    include_superseded: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    cfg = request.app.state.panel.cfg
    return ledger_read.rows(
        cfg, kind=kind, actor_name=actor, q=q, since_id=since_id,
        include_superseded=include_superseded, limit=limit, offset=offset,
    )


@router.get("/api/rows/facet-counts")
def api_facet_counts(request: Request) -> dict[str, int]:
    cfg = request.app.state.panel.cfg
    return ledger_read.facet_counts(cfg)


@router.get("/api/rows/{row_id:int}")
def api_row(request: Request, row_id: int) -> dict[str, Any]:
    cfg = request.app.state.panel.cfg
    row = ledger_read.row_by_id(cfg, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no ledger row {row_id}")
    chain = ledger_read.supersede_chain(cfg, row_id)
    row["ref_row_ids"] = ledger_read.generic_row_refs(row.get("refs"))
    row["predecessors"] = list(chain.predecessors)
    row["successor"] = chain.successor
    return row


@router.get("/api/watermark")
def api_watermark(request: Request) -> dict[str, Any]:
    cfg = request.app.state.panel.cfg
    return ledger_read.watermark(cfg)


@router.get("/api/events")
async def api_events(request: Request) -> StreamingResponse:
    state = request.app.state.panel
    queue = state.broadcaster.subscribe()

    async def gen() -> AsyncIterator[bytes]:
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n".encode()
        finally:
            state.broadcaster.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/api/profiles")
def api_profiles_list(request: Request) -> list[dict[str, Any]]:
    """Always available (read-only view), even when the write routes below are not mounted --
    reuses `profiles_write.list_profiles`, the SAME tomlkit-based read `config.py`'s own profile
    resolution logic conceptually mirrors, so this repo has one profile-listing implementation,
    not two independently-drifting TOML readers."""
    cfg = request.app.state.panel.cfg
    return profiles_write.list_profiles(cfg.repo_root)


def build_profiles_write_router() -> APIRouter:
    """Returns a FRESH `APIRouter` carrying `POST /api/profiles` and `DELETE /api/profiles/{name}`
    -- called by app.py ONLY when `not cfg.read_only`, mirroring
    `extensions.autoharn.routes.build_write_router()`'s exact gating pattern and its reason: a
    read-only deployment must not even expose a write route that would either 500 on every call
    or (worse, here) actually mutate panel.toml despite the read-only contract. A fresh router
    per call (never a mutation of the shared, module-level `router` above) for the same reason
    `build_write_router` documents: `create_app()` may be called more than once in one process
    (this repo's own test suite reloads `app` under different env), and a shared object would
    accumulate duplicate route registrations across those calls."""
    write_router = APIRouter()

    @write_router.post("/api/profiles")
    def api_profiles_upsert(request: Request, req: ProfileUpsertRequest) -> list[dict[str, Any]]:
        cfg = request.app.state.panel.cfg
        fields = {"host": req.host, "db": req.db, "schema": req.schema_, "kern": req.kern, "role": req.role}
        try:
            return profiles_write.upsert_profile(cfg.repo_root, req.name, fields)
        except profiles_write.ProfileValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @write_router.delete("/api/profiles/{name}")
    def api_profiles_delete(request: Request, name: str) -> list[dict[str, Any]]:
        cfg = request.app.state.panel.cfg
        if cfg.active_profile is not None and name == cfg.active_profile:
            # row:152's gap, resolved by row:159's decision: PANEL_PROFILE is resolved only at
            # startup (config.py, no runtime re-validation) -- deleting the profile it currently
            # names would guarantee the NEXT restart fails loud with a ConfigError. Refuse
            # outright rather than merely warn, since a UI-only warning cannot stop a direct API
            # caller from doing this anyway.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{name!r} is the active profile (PANEL_PROFILE) -- deleting it would break "
                    f"the next restart; unset PANEL_PROFILE or switch it to a different profile "
                    f"first."
                ),
            )
        try:
            return profiles_write.delete_profile(cfg.repo_root, name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no profile named {name!r}") from None

    return write_router
