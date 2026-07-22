"""Device enrollment endpoint.

Flow:
1. An admin pre-registers a device from the dashboard, which mints a short
   one-time ``enroll_token``.
2. The agent calls ``POST /api/enroll`` with that token (and the shared
   enrollment secret, if configured). On success it receives its stable
   ``device_id``, a long-lived ``device_token``, and MQTT connection details.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import Device
from app.mqtt.bridge import bridge, topics_for
from app.ratelimit import enroll_throttle
from app.schemas import EnrollRequest, EnrollResponse, MqttInfo
from app.services import derive_tier
from app.util import hash_token, new_token, utcnow

router = APIRouter(tags=["enrollment"])


@router.post("/enroll", response_model=EnrollResponse)
def enroll(body: EnrollRequest, session: Session = Depends(get_session)) -> EnrollResponse:
    # Global brute-force throttle on failed attempts (protects the secret).
    retry_after = enroll_throttle.retry_after()
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed enrollment attempts; try again later.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    # Timing-safe secret comparison.
    if settings.enrollment_secret and not secrets.compare_digest(
        body.enrollment_secret or "", settings.enrollment_secret
    ):
        enroll_throttle.record_failure()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid enrollment secret",
        )

    device = session.scalar(
        select(Device).where(Device.enroll_token == body.enroll_token)
    )
    if device is None:
        enroll_throttle.record_failure()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown or already-used enrollment token",
        )

    # Successful enrollment clears the failure counter.
    enroll_throttle.reset()

    # Issue the long-lived device token (returned once, stored only as a hash).
    token = new_token()
    device.token_hash = hash_token(token)
    device.enroll_token = None
    device.enrolled = True
    device.platform = body.platform
    device.capabilities = body.capabilities
    device.tier = derive_tier(body.capabilities)
    if body.name:
        device.name = body.name
    device.model = body.model
    device.os_version = body.os_version
    device.last_seen = utcnow()
    session.commit()

    # Expose the newly enrolled device to Home Assistant.
    bridge.announce_device(device)

    topics = topics_for(device.id)
    return EnrollResponse(
        device_id=device.id,
        device_token=token,
        mqtt=MqttInfo(
            # Only advertise a broker when MQTT push is enabled; otherwise the
            # agent skips MQTT and relies on HTTPS command polling.
            host=settings.mqtt_host if settings.mqtt_push else None,
            port=settings.mqtt_port,
            tls=settings.mqtt_tls,
            username=device.id,
            password=token,
            cmd_topic=topics["cmd"],
            ack_topic=topics["ack"],
            status_topic=topics["status"],
        ),
    )
