"""Device authentication for the telemetry/command API.

Devices present their long-lived token as ``Authorization: Bearer <token>``.
We resolve it to a Device by comparing token hashes.

Note: the dashboard/web UI is *not* protected here — it is served behind Home
Assistant's ingress, which enforces HA's own authentication.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Device
from app.util import hash_token


def authenticate_device(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Device:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = authorization.split(" ", 1)[1].strip()
    device = session.scalar(
        select(Device).where(Device.token_hash == hash_token(token))
    )
    if device is None or not device.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device token",
        )
    return device
