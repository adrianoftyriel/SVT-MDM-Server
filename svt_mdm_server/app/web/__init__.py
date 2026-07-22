"""Server-rendered dashboard (HTMX-friendly, no build step).

Served behind Home Assistant ingress, which provides authentication. A
per-request middleware (see app.main) sets ``root_path`` from the
``X-Ingress-Path`` header so generated URLs resolve under the ingress prefix.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app import provisioning, storage
from app.api.backup import BACKUP_CATEGORIES, resolve_categories
from app.config import settings
from app.db import get_session
from app.models import (
    AppInventory,
    BackupConfig,
    BackupObject,
    BackupRun,
    Command,
    Device,
    LocationPing,
    UsageSnapshot,
)
from app.services import CommandError, queue_command
from app.util import new_token

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _path_for(request: Request, name: str, **params) -> str:
    """Build a host-relative URL that includes the ingress path prefix.

    Absolute URLs (request.url_for) break under Home Assistant ingress: the app
    can't know HA's external scheme/host. A host-relative path like
    ``/api/hassio_ingress/<token>/devices/<id>`` is resolved by the browser
    against the current ingress URL, which is correct.
    """
    root_path = request.scope.get("root_path", "")
    return f"{root_path}{request.app.url_path_for(name, **params)}"


# Expose to templates as `path_for(request, 'name', ...)`.
templates.env.globals["path_for"] = _path_for

# Defence in depth: device-reported strings (app labels, package names, model,
# etc.) are rendered in the operator's authenticated dashboard, so force HTML
# auto-escaping to prevent stored XSS from a malicious/compromised device.
templates.env.autoescape = True

router = APIRouter(tags=["dashboard"], include_in_schema=False)


def _redirect(request: Request, name: str, **params) -> RedirectResponse:
    return RedirectResponse(
        url=_path_for(request, name, **params),
        status_code=status.HTTP_303_SEE_OTHER,
    )


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

    # Backup summary.
    latest_backup_run = session.scalar(
        select(BackupRun)
        .where(BackupRun.device_id == device_id)
        .order_by(desc(BackupRun.started_at))
    )
    backup_count, backup_bytes = session.execute(
        select(func.count(BackupObject.id), func.coalesce(func.sum(BackupObject.size), 0))
        .where(BackupObject.device_id == device_id)
    ).one()
    backup_categories = resolve_categories(session, device_id)

    # Device Owner provisioning QR for a not-yet-enrolled device.
    provisioning_svg = None
    if not device.enrolled and device.enroll_token and settings.external_url:
        payload = provisioning.provisioning_payload(
            apk_url=settings.apk_url,
            signature_checksum=settings.do_signature_checksum,
            server_url=settings.external_url,
            enroll_token=device.enroll_token,
            enrollment_secret=settings.enrollment_secret,
        )
        provisioning_svg = provisioning.qr_svg(payload)

    # Which command buttons to enable, based on capabilities.
    command_types = [
        "locate",
        "ring",
        "lock",
        "set_password",
        "wipe",
        "refresh_inventory",
        "refresh_usage",
        "backup_now",
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
            "latest_backup_run": latest_backup_run,
            "backup_count": backup_count,
            "backup_bytes": backup_bytes,
            "backup_categories": backup_categories,
            "backup_all_categories": BACKUP_CATEGORIES,
            "provisioning_svg": provisioning_svg,
        },
    )


@router.post("/devices/{device_id}/backup-config", name="save_backup_config")
def save_backup_config(
    request: Request,
    device_id: str,
    media: str = Form(None),
    contacts: str = Form(None),
    sms: str = Form(None),
    calllog: str = Form(None),
    calendar: str = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    # An unchecked checkbox is simply absent from the form submission.
    values = {
        "media": media is not None,
        "contacts": contacts is not None,
        "sms": sms is not None,
        "calllog": calllog is not None,
        "calendar": calendar is not None,
    }
    cfg = session.get(BackupConfig, device_id)
    if cfg is None:
        session.add(BackupConfig(device_id=device_id, categories=values))
    else:
        cfg.categories = values
    session.commit()
    return _redirect(request, "device_detail", device_id=device_id)


@router.get("/devices/{device_id}/backups", response_class=HTMLResponse, name="backups_browse")
def backups_browse(
    request: Request, device_id: str, session: Session = Depends(get_session)
) -> HTMLResponse:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    objects = list(
        session.scalars(
            select(BackupObject)
            .where(BackupObject.device_id == device_id)
            .order_by(desc(BackupObject.last_seen))
            .limit(500)
        )
    )
    runs = list(
        session.scalars(
            select(BackupRun)
            .where(BackupRun.device_id == device_id)
            .order_by(desc(BackupRun.started_at))
            .limit(10)
        )
    )
    return templates.TemplateResponse(
        request,
        "backups.html",
        {"device": device, "objects": objects, "runs": runs},
    )


@router.get("/devices/{device_id}/backups/{object_id}/download", name="backup_download")
def backup_download(
    device_id: str, object_id: str, session: Session = Depends(get_session)
) -> StreamingResponse:
    obj = session.get(BackupObject, object_id)
    if obj is None or obj.device_id != device_id:
        raise HTTPException(status_code=404, detail="Backup object not found")
    filename = os.path.basename(obj.rel_path) or f"{obj.sha256}.bin"
    return StreamingResponse(
        storage.open_decrypted(device_id, obj.sha256),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
