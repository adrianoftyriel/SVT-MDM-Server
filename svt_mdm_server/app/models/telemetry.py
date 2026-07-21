"""Telemetry records reported by devices: location, app inventory, usage."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.util import utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


class LocationPing(Base):
    __tablename__ = "location_pings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float, default=None)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppInventory(Base):
    """A full installed-app snapshot. Latest per device is what the UI shows."""

    __tablename__ = "app_inventories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # List of {package, label, version, system}.
    apps: Mapped[list] = mapped_column(JSON, default=list)


class UsageSnapshot(Base):
    """A per-app foreground-usage snapshot over a time range."""

    __tablename__ = "usage_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    range_days: Mapped[int] = mapped_column(Integer, default=7)
    # List of {package, foreground_ms, last_used}.
    stats: Mapped[list] = mapped_column(JSON, default=list)
