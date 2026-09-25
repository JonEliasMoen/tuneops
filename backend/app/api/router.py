from fastapi import APIRouter

from . import health, jobs, library, settings


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(library.router)
api_router.include_router(settings.router)
api_router.include_router(jobs.router)
