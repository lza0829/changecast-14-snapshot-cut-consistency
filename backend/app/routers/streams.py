from fastapi import APIRouter

from app.services import project_service as svc

router = APIRouter(tags=["streams"])


@router.get("/streams")
def list_streams():
    return svc.list_streams()
