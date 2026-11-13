from fastapi import APIRouter

from app.services import project_service as svc

router = APIRouter(tags=["buffer"])


@router.get("/ooo-buffer")
def list_ooo_buffer(stream_id: int | None = None):
    return svc.list_ooo_buffer(stream_id=stream_id)
