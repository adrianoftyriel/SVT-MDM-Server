"""Commands queued for a device and their lifecycle state."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.util import utcnow


class CommandStatus(str, enum.Enum):
    pending = "pending"   # created, not yet delivered
    sent = "sent"         # published to the device's MQTT topic
    acked = "acked"       # device confirmed success
    failed = "failed"     # device reported failure


# Command types the server understands. Kept in sync with shared/protocol.md.
COMMAND_TYPES = {
    "locate",
    "lock",
    "set_password",
    "wipe",
    "refresh_inventory",
    "refresh_usage",
    "backup_now",
}


def _uuid() -> str:
    return str(uuid.uuid4())


class Command(Base):
    __tablename__ = "commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[CommandStatus] = mapped_column(
        Enum(CommandStatus), default=CommandStatus.pending, index=True
    )
    detail: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    device = relationship("Device", back_populates="commands")

    def envelope(self) -> dict:
        """Serialize to the wire `Command` envelope (see shared/protocol.md)."""
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload or {},
            "issued_at": self.created_at.isoformat(),
        }
