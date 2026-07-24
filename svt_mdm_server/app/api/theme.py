"""Active-theme endpoint (device-authenticated).

Agents fetch the operator-selected interface theme so the phone app's colours
match the server dashboard. The check-in response also carries the theme id (see
``app.api.telemetry``); this endpoint returns the full colour token set.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import authenticate_device
from app.db import get_session
from app.models import Device
from app.prefs import get_active_theme_id
from app.themes import get_theme

router = APIRouter(prefix="/theme", tags=["theme"])


@router.get("")
def active_theme(
    device: Device = Depends(authenticate_device),  # auth gate only
    session: Session = Depends(get_session),
) -> dict:
    theme = get_theme(get_active_theme_id(session))
    return theme.as_api()
