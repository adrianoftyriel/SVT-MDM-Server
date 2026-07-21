"""Command polling and HTTP ack fallback for devices without live MQTT."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.auth import authenticate_device
from app.db import get_session
from app.models import Command, CommandStatus, Device
from app.schemas import CommandAck
from app.util import utcnow

router = APIRouter(prefix="/commands", tags=["commands"])

# Re-deliver a command that was handed out but not acked within this window,
# so a lost poll response or a brief outage doesn't strand the command.
RETRY_AFTER_SECONDS = 45


@router.get("/pending")
def pending(
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> dict:
    """Return commands awaiting delivery and (re)mark them sent. This is the
    primary command channel; devices poll it over HTTPS."""
    now = utcnow()
    retry_cutoff = now - timedelta(seconds=RETRY_AFTER_SECONDS)
    cmds = list(
        session.scalars(
            select(Command)
            .where(
                Command.device_id == device.id,
                Command.completed_at.is_(None),
                or_(
                    Command.status == CommandStatus.pending,
                    and_(
                        Command.status == CommandStatus.sent,
                        Command.sent_at < retry_cutoff,
                    ),
                ),
            )
            .order_by(Command.created_at)
        )
    )
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
