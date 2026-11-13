from fastapi import APIRouter

from app.services import project_service as svc

router = APIRouter(tags=["dashboard"])


@router.get("/health")
def health():
    return {"ok": True, "project": "changecast"}


@router.get("/dashboard")
def dashboard():
    return svc.dashboard_stats()
