"""Command polling and HTTP ack fallback for devices without live MQTT."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import authenticate_device
from app.db import get_session
from app.models import Command, CommandStatus, Device
from app.schemas import CommandAck
from app.util import utcnow

router = APIRouter(prefix="/commands", tags=["commands"])


@router.get("/pending")
def pending(
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> dict:
    """Return undelivered commands and mark them sent. Polling fallback for
    devices that cannot maintain an MQTT connection."""
    cmds = list(
        session.scalars(
            select(Command)
            .where(
                Command.device_id == device.id,
                Command.status == CommandStatus.pending,
            )
            .order_by(Command.created_at)
        )
    )
    now = utcnow()
    for cmd in cmds:
        cmd.status = CommandStatus.sent
        cmd.sent_at = now
    device.last_seen = now
    session.commit()
    return {"commands": [c.envelope() for c in cmds]}


@router.post("/ack")
def ack(
    body: CommandAck,
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> dict:
    cmd = session.get(Command, body.id)
    if cmd is None or cmd.device_id != device.id:
        return {"ok": False, "detail": "Unknown command"}
    cmd.status = (
        CommandStatus.acked if body.status == "acked" else CommandStatus.failed
    )
    cmd.detail = body.detail
    cmd.completed_at = body.completed_at or utcnow()
    device.last_seen = utcnow()
    session.commit()
    return {"ok": True}
