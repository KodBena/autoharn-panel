"""extensions.autoharn.routes -- the autoharn extension's FastAPI router (SPEC.md sec 4).
Mounted by app.py ONLY when `"autoharn" in cfg.extensions` (enabled by default). The write
route (`POST /api/cosign`) is registered only when `cfg.led_bin` is set -- a read-only
deployment (LED_BIN unset) gets every read route here but no write route at all, rather than a
write route that would always 500.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from extensions.autoharn import cosign, ledger_read
from extensions.autoharn.ledger_read import AmbiguousItem, ResolvedItem

router = APIRouter()


def _witness_wire(rw: ledger_read.ResolvedWitness) -> dict[str, Any]:
    return {
        "ref_kind": rw.ref_kind,
        "ref": rw.ref,
        "resolved": rw.resolved,
        "substantive": rw.facts.exists and rw.facts.substantive,
        "cosign_target_row": rw.cosign_target_row,
        "cosign": rw.cosign,
    }


def _item_wire(item: ledger_read.Item) -> dict[str, Any]:
    if isinstance(item, AmbiguousItem):
        return {
            "row_id": None,
            "item_id": item.item_id,
            "label": None,
            "status": "AMBIGUOUS",
            "cosign": None,
            "witnesses": [],
            "ambiguous_row_ids": list(item.candidate_row_ids),
        }
    assert isinstance(item, ResolvedItem)
    return {
        "row_id": item.row_id,
        "item_id": item.item_id,
        "label": item.label,
        "status": item.status,
        "cosign": item.item_cosign,
        "witnesses": [_witness_wire(rw) for rw in item.witnesses],
        "ambiguous_row_ids": None,
    }


@router.get("/api/commissions")
def api_commissions(request: Request) -> list[dict[str, Any]]:
    cfg = request.app.state.panel.cfg
    return ledger_read.commissions(cfg)


@router.get("/api/commission/{commission_row:int}")
def api_commission(request: Request, commission_row: int) -> dict[str, Any]:
    cfg = request.app.state.panel.cfg
    commission = ledger_read.ledger_row(cfg, commission_row)
    decomposition = ledger_read.decomposition_items(cfg, commission_row)
    return {
        "commission_row": commission_row,
        "commission": commission,
        "items": [_item_wire(item) for item in decomposition.items],
    }


@router.get("/api/ledger/recent")
def api_ledger_recent(request: Request, n: int = 50) -> list[dict[str, Any]]:
    cfg = request.app.state.panel.cfg
    try:
        return ledger_read.recent_ledger(cfg, n)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/work")
def api_work(request: Request) -> list[dict[str, Any]]:
    cfg = request.app.state.panel.cfg
    return ledger_read.work_items(cfg)


@router.get("/api/review-gap")
def api_review_gap(request: Request) -> list[dict[str, Any]]:
    cfg = request.app.state.panel.cfg
    return ledger_read.review_gap(cfg)


@router.get("/api/questions")
def api_questions(request: Request) -> list[dict[str, Any]]:
    cfg = request.app.state.panel.cfg
    return ledger_read.question_status(cfg)


@router.get("/api/item/{row_id:int}/obligations")
def api_item_obligations(request: Request, row_id: int) -> dict[str, Any]:
    """The item view's (SPEC.md sec 2.2) autoharn-semantic enrichment, fetched IN ADDITION to
    core's `GET /api/rows/{row_id}` (which knows nothing of obligations/cosign/review --
    SPEC.md sec 4's extension boundary): review/co-sign history against this row, whether this
    row itself is maintainer-cosigned, and this row's own `refs` read generically as witness
    tokens (`row:`/`work:`) and resolved the same way a decomposition item's witnesses are.
    Does not 404 on an unknown row_id -- every sub-query here degrades to an empty/false answer
    for a row that does not exist, and core's own row fetch is the one that 404s."""
    cfg = request.app.state.panel.cfg
    return {
        "row_id": row_id,
        "cosign": ledger_read.cosign_fact(cfg, row_id),
        "reviews": ledger_read.reviews_for_row(cfg, row_id),
        "witnesses": [_witness_wire(rw) for rw in ledger_read.item_witnesses(cfg, row_id)],
    }


class CosignRequest(BaseModel):
    row_id: int
    verdict: str
    independence: str
    basis: str


def build_write_router() -> APIRouter:
    """Returns a FRESH `APIRouter` carrying only `POST /api/cosign` -- called by app.py ONLY
    when `cfg.led_bin` is set (spec sec 1: LED_BIN absent => read-only, and a read-only
    deployment must not even expose a write route that would 500 on every call). A fresh
    router per call (never a mutation of the shared, module-level `router` above) so calling
    `create_app()` more than once in one process -- as this repo's own test suite does, e.g.
    `tests/test_core_boundary.py` reloading `app` under different env -- can never accumulate
    duplicate route registrations on a shared object."""
    write_router = APIRouter()

    @write_router.post("/api/cosign")
    def api_cosign(request: Request, req: CosignRequest) -> dict[str, Any]:
        cfg = request.app.state.panel.cfg
        try:
            result = cosign.cosign(cfg, req.row_id, req.verdict, req.independence, req.basis)
        except cosign.CosignValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {
            "ok": result.ok,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "review_id": result.review_id,
        }

    return write_router
