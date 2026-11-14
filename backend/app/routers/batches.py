from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import errors
from app.services import project_service as svc

router = APIRouter(tags=["batches"])


class RunBody(BaseModel):
    stream_id: int
    note: str | None = None
    hold_ms: int = Field(default=0, ge=0, le=10_000)
    up_to_seq: int | None = Field(default=None, ge=0)


@router.get("/batches")
def list_batches(limit: int = 50):
    return svc.list_batches(limit=limit)


@router.post("/project")
def run_project(body: RunBody):
    try:
        return svc.run_project(
            body.stream_id, body.note, body.hold_ms, body.up_to_seq
        )
    except errors.ConflictError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

