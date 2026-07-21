"""Telemetry ingestion endpoints (device-authenticated)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import authenticate_device
from app.db import get_session
from app.models import AppInventory, Device, LocationPing, UsageSnapshot
from app.schemas import (
    CheckinRequest,
    InventoryRequest,
    LocationRequest,
    UsageRequest,
)
from app.services import derive_tier
from app.util import utcnow

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


def _touch(session: Session, device: Device) -> None:
    device.last_seen = utcnow()
    session.commit()


@router.post("/checkin")
def checkin(
    body: CheckinRequest,
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> dict:
    if body.capabilities:
        device.capabilities = body.capabilities
        device.tier = derive_tier(body.capabilities)
    if body.battery is not None:
        device.battery = body.battery
    if body.os_version:
        device.os_version = body.os_version
    if body.model:
        device.model = body.model
    _touch(session, device)
    return {"ok": True, "tier": device.tier.value}


@router.post("/location")
def location(
    body: LocationRequest,
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> dict:
    session.add(
        LocationPing(
            device_id=device.id,
            lat=body.lat,
            lon=body.lon,
            accuracy_m=body.accuracy_m,
            captured_at=body.captured_at or utcnow(),
        )
    )
    _touch(session, device)
    return {"ok": True}


@router.post("/inventory")
def inventory(
    body: InventoryRequest,
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> dict:
    session.add(
        AppInventory(
            device_id=device.id,
            captured_at=body.captured_at or utcnow(),
            apps=[a.model_dump() for a in body.apps],
        )
    )
    _touch(session, device)
    return {"ok": True, "count": len(body.apps)}


@router.post("/usage")
def usage(
    body: UsageRequest,
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> dict:
    session.add(
        UsageSnapshot(
            device_id=device.id,
            captured_at=body.captured_at or utcnow(),
            range_days=body.range_days,
            stats=[s.model_dump() for s in body.stats],
        )
    )
    _touch(session, device)
    return {"ok": True, "count": len(body.stats)}
