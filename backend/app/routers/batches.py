from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import project_service as svc

router = APIRouter(tags=["batches"])


class RunBody(BaseModel):
    stream_id: int
    note: str | None = None


@router.get("/batches")
def list_batches(limit: int = 50):
    return svc.list_batches(limit=limit)


@router.post("/project")
def run_project(body: RunBody):
    try:
        return svc.run_project(body.stream_id, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
