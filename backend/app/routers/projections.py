from fastapi import APIRouter

from app.services import project_service as svc

router = APIRouter(tags=["projections"])


@router.get("/projections")
def list_projections(stream_id: int | None = None, include_deleted: bool = True):
    return svc.list_projections(stream_id=stream_id, include_deleted=include_deleted)
