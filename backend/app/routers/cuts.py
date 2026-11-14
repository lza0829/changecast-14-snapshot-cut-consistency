from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import errors
from app.services import cut_service as cut_svc
from app.services import project_service as svc

router = APIRouter(tags=["cuts"])


class CutBody(BaseModel):
    stream_id: int
    watermark_seq: int | None = Field(default=None, ge=0)
    batch_no: str | None = None
    policy: str | None = None
    hold_ms: int = Field(default=0, ge=0, le=10_000)
    note: str | None = None


@router.get("/cuts")
def list_cuts(stream_id: int | None = None, limit: int = 50):
    return cut_svc.list_cuts(stream_id=stream_id, limit=limit)


@router.get("/cuts/{cut_id}")
def get_cut(cut_id: int, include_deleted: bool = True):
    cut = cut_svc.get_cut(cut_id, include_deleted=include_deleted)
    if cut is None:
        raise HTTPException(404, "切面不存在")
    return cut


@router.get("/cuts/{cut_id}/verify")
def verify_cut(cut_id: int):
    try:
        return cut_svc.verify_cut(cut_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/cuts")
def create_cut(body: CutBody):
    try:
        return cut_svc.create_cut(
            stream_id=body.stream_id,
            watermark_seq=body.watermark_seq,
            batch_no=body.batch_no,
            policy=body.policy,
            hold_ms=body.hold_ms,
            note=body.note,
        )
    except errors.ConflictError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/concurrency")
def concurrency(stream_id: int | None = None):
    return svc.active_conflicts(stream_id=stream_id)
