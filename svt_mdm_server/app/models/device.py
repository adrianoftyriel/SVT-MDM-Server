"""The enrolled device and its reported capabilities."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.util import utcnow


class DeviceTier(str, enum.Enum):
    device_owner = "device_owner"
    device_admin = "device_admin"
    plain = "plain"
    unknown = "unknown"


def _uuid() -> str:
    return str(uuid.uuid4())


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), default="Unnamed device")
    platform: Mapped[str] = mapped_column(String(16), default="android")

    # Long-lived per-device auth token, stored only as a hash.
    token_hash: Mapped[str | None] = mapped_column(String(64), default=None)

    # One-time enrollment token (short) issued when the device is pre-registered
    # from the dashboard; cleared once the device completes enrollment.
    enroll_token: Mapped[str | None] = mapped_column(String(64), default=None)
    enrolled: Mapped[bool] = mapped_column(default=False)

    tier: Mapped[DeviceTier] = mapped_column(
        Enum(DeviceTier), default=DeviceTier.unknown
    )
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)

    # Last check-in device info.
    model: Mapped[str | None] = mapped_column(String(120), default=None)
    os_version: Mapped[str | None] = mapped_column(String(40), default=None)
    battery: Mapped[int | None] = mapped_column(Integer, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    commands = relationship(
        "Command", back_populates="device", cascade="all, delete-orphan"
    )

    def can(self, command_type: str) -> bool:
        """Whether this device's capabilities permit a given command type."""
        # Ringing needs no special privilege — any enrolled device can do it.
        if command_type == "ring":
            return True
        caps = self.capabilities or {}
        required = {
            "locate": "location",
            "lock": "device_admin",
            "wipe": "device_admin",
            "set_password": "device_owner",
            "refresh_inventory": "query_all_packages",
            "refresh_usage": "usage_access",
            "backup_now": "backup",
        }.get(command_type)
        if required is None:
            return False
        return bool(caps.get(required, False))
