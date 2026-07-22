"""JSON API routers for device agents."""

from fastapi import APIRouter

from app.api import backup, commands, enroll, telemetry

api_router = APIRouter(prefix="/api")
api_router.include_router(enroll.router)
api_router.include_router(telemetry.router)
api_router.include_router(commands.router)
api_router.include_router(backup.router)

__all__ = ["api_router"]
