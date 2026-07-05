import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.core.initialization import initialize_default_models
from app.api import api_router
from app.orchestrator import orchestrator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_runtime_security()

    # Startup: Initialize database
    await init_db()
    
    # Initialize default model configuration
    async with AsyncSessionLocal() as db:
        await initialize_default_models(db)
        if settings.TASK_EXECUTION_MODE == "inline":
            await orchestrator.recover_incomplete_scan_tasks(db)
    
    yield
    # Shutdown: cleanup


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="智能合规验证平台 API",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
