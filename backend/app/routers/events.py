from fastapi import APIRouter

from app.services import project_service as svc

router = APIRouter(tags=["events"])


@router.get("/events")
def list_events(batch_id: int | None = None, stream_id: int | None = None):
    return svc.list_events(batch_id=batch_id, stream_id=stream_id)
