from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.assets import router as assets_router
from app.api.scans import router as scans_router
from app.api.remediation import router as remediation_router
from app.api.monitoring import router as monitoring_router
from app.api.chat import router as chat_router
from app.api.models import router as models_router
from app.api.results import router as results_router
from app.api.websocket import router as websocket_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(assets_router)
api_router.include_router(scans_router)
api_router.include_router(remediation_router)
api_router.include_router(monitoring_router)
api_router.include_router(chat_router)
api_router.include_router(models_router)
api_router.include_router(results_router)
api_router.include_router(websocket_router)

__all__ = ["api_router"]
