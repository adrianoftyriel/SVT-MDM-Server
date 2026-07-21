"""Server-rendered dashboard (HTMX-friendly, no build step).

Served behind Home Assistant ingress, which provides authentication. A
per-request middleware (see app.main) sets ``root_path`` from the
``X-Ingress-Path`` header so generated URLs resolve under the ingress prefix.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import (
    AppInventory,
    Command,
    Device,
    LocationPing,
    UsageSnapshot,
)
from app.services import CommandError, queue_command
from app.util import new_token

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(tags=["dashboard"], include_in_schema=False)


def _redirect(request: Request, name: str, **params) -> RedirectResponse:
    url = request.url_for(name, **params)
    return RedirectResponse(url=str(url), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/", response_class=HTMLResponse, name="index")
def index(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    devices = list(session.scalars(select(Device).order_by(Device.name)))
    return templates.TemplateResponse(
        request, "index.html", {"devices": devices}
    )


@router.post("/devices", name="add_device")
def add_device(
    request: Request,
    name: str = Form(...),
    platform: str = Form("android"),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    device = Device(name=name, platform=platform, enroll_token=new_token(8))
    session.add(device)
    session.commit()
    return _redirect(request, "device_detail", device_id=device.id)


@router.get("/devices/{device_id}", response_class=HTMLResponse, name="device_detail")
def device_detail(
    request: Request, device_id: str, session: Session = Depends(get_session)
) -> HTMLResponse:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    latest_location = session.scalar(
        select(LocationPing)
        .where(LocationPing.device_id == device_id)
        .order_by(desc(LocationPing.captured_at))
    )
    latest_inventory = session.scalar(
        select(AppInventory)
        .where(AppInventory.device_id == device_id)
        .order_by(desc(AppInventory.captured_at))
    )
    latest_usage = session.scalar(
        select(UsageSnapshot)
        .where(UsageSnapshot.device_id == device_id)
        .order_by(desc(UsageSnapshot.captured_at))
    )
    recent_commands = list(
        session.scalars(
            select(Command)
            .where(Command.device_id == device_id)
            .order_by(desc(Command.created_at))
            .limit(20)
        )
    )

    # Build usage bars (top 10 by foreground time) for the CSS chart.
    usage_bars: list[dict] = []
    if latest_usage and latest_usage.stats:
        top = sorted(
            latest_usage.stats, key=lambda s: s.get("foreground_ms", 0), reverse=True
        )[:10]
        peak = max((s.get("foreground_ms", 0) for s in top), default=0) or 1
        for s in top:
            ms = s.get("foreground_ms", 0)
            usage_bars.append(
                {
                    "package": s.get("package", "?"),
                    "minutes": round(ms / 60000, 1),
                    "pct": round(ms / peak * 100),
                }
            )

    # Which command buttons to enable, based on capabilities.
    command_types = [
        "locate",
        "lock",
        "set_password",
        "wipe",
        "refresh_inventory",
        "refresh_usage",
    ]
    supported = {ct: device.can(ct) for ct in command_types}

    return templates.TemplateResponse(
        request,
        "device.html",
        {
            "device": device,
            "latest_location": latest_location,
            "latest_inventory": latest_inventory,
            "usage_bars": usage_bars,
            "recent_commands": recent_commands,
            "supported": supported,
        },
    )


@router.post("/devices/{device_id}/commands", name="issue_command")
async def issue_command(
    request: Request,
    device_id: str,
    command_type: str = Form(...),
    password: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    payload: dict = {}
    if command_type == "set_password":
        payload = {"password": password}
    elif command_type == "wipe":
        payload = {"confirm": True}

    try:
        await queue_command(session, device, command_type, payload)
    except CommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _redirect(request, "device_detail", device_id=device_id)


@router.post("/devices/{device_id}/delete", name="delete_device")
def delete_device(
    request: Request, device_id: str, session: Session = Depends(get_session)
) -> RedirectResponse:
    device = session.get(Device, device_id)
    if device is not None:
        session.delete(device)
        session.commit()
    return _redirect(request, "index")
