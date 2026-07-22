"""Backup catalog: runs (a backup session) and objects (deduped files)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.util import utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


class BackupRun(Base):
    """A single backup session initiated by a device."""

    __tablename__ = "backup_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    file_count: Mapped[int] = mapped_column(BigInteger, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class BackupObject(Base):
    """A stored, encrypted file, content-addressed per device (deduped)."""

    __tablename__ = "backup_objects"
    __table_args__ = (
        UniqueConstraint("device_id", "sha256", name="uq_backup_device_sha"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(24), default="file")  # media|document|contacts|...
    rel_path: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
