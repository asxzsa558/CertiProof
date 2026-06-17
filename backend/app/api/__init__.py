from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.assets import router as assets_router
from app.api.scans import router as scans_router
from app.api.mock_scan import router as mock_scan_router
from app.api.real_scan import router as real_scan_router
from app.api.remediation import router as remediation_router
from app.api.monitoring import router as monitoring_router
from app.api.chat import router as chat_router
from app.api.models import router as models_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(assets_router)
api_router.include_router(scans_router)
api_router.include_router(mock_scan_router)
api_router.include_router(real_scan_router)
api_router.include_router(remediation_router)
api_router.include_router(monitoring_router)
api_router.include_router(chat_router)
api_router.include_router(models_router)

__all__ = ["api_router"]
