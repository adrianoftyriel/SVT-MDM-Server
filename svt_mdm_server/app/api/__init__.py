"""JSON API routers for device agents."""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.config import settings

from app.api import backup, commands, enroll, telemetry, theme

api_router = APIRouter(prefix="/api")
api_router.include_router(enroll.router)
api_router.include_router(telemetry.router)
api_router.include_router(commands.router)
api_router.include_router(backup.router)
api_router.include_router(theme.router)

__all__ = ["api_router"]


@api_router.get("/apk", include_in_schema=False)
def apk_redirect() -> RedirectResponse:
    """Short, stable APK URL for the provisioning QR (keeps the code sparse)."""
    return RedirectResponse(settings.apk_url, status_code=302)
