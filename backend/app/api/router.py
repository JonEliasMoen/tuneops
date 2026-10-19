from fastapi import APIRouter

from . import auth, health, jobs, library, settings, youtube


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(health.router)
api_router.include_router(library.router)
api_router.include_router(settings.router)
api_router.include_router(jobs.router)
api_router.include_router(youtube.router)
