"""FastAPI application entry point.

Wires together the JSON API (for device agents), the web dashboard (for the
operator, behind HA ingress), and the MQTT bridge (started as a background
task for the lifetime of the app).
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import api_router
from app.config import settings
from app.db import init_db
from app.mqtt.bridge import bridge
from app.web import router as web_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("mdm")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("SVT MDM server %s starting (db=%s)", __version__, settings.db_path)
    bridge_task = asyncio.create_task(bridge.run())
    try:
        yield
    finally:
        await bridge.stop()
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="SVT MDM Server", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def ingress_root_path(request: Request, call_next):
    """Honor Home Assistant ingress by generating URLs under its path prefix."""
    ingress_path = request.headers.get("X-Ingress-Path")
    if ingress_path:
        request.scope["root_path"] = ingress_path
    return await call_next(request)


@app.middleware("http")
async def restrict_dashboard_to_ingress(request: Request, call_next):
    """Serve the operator dashboard only to Home Assistant ingress.

    The device API (/api/*) and /health stay open on the published port —
    they authenticate with device tokens / the enrollment secret. Everything
    else (the dashboard and its assets) is refused unless the request comes
    from an allowed source (the HA Supervisor), so the dashboard is reachable
    only through HA's authenticated ingress panel, never the public URL.

    Note: uvicorn runs without --proxy-headers, so request.client.host is the
    real TCP peer and cannot be spoofed via X-Forwarded-For.
    """
    path = request.url.path
    if path == "/health" or path.startswith("/api"):
        return await call_next(request)

    client_host = request.client.host if request.client else ""
    if client_host not in settings.dashboard_allowed_ips:
        log.info("Blocked dashboard access from %s (%s)", client_host, path)
        return PlainTextResponse(
            "The SVT MDM dashboard is only available through Home Assistant.",
            status_code=403,
        )
    return await call_next(request)


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"status": "ok", "version": __version__, "mqtt": settings.mqtt_enabled}


app.include_router(api_router)
app.include_router(web_router)

_static_dir = os.path.join(os.path.dirname(__file__), "web", "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")
