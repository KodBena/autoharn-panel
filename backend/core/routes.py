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

from core import ledger_read

router = APIRouter()


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
