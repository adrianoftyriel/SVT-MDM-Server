"""Business logic shared between the JSON API and the web dashboard."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Command, CommandStatus, Device, DeviceTier
from app.models.command import COMMAND_TYPES
from app.mqtt.bridge import bridge
from app.util import utcnow


def derive_tier(capabilities: dict) -> DeviceTier:
    """Map a reported capability set to a coarse privilege tier."""
    if capabilities.get("device_owner"):
        return DeviceTier.device_owner
    if capabilities.get("device_admin"):
        return DeviceTier.device_admin
    if capabilities.get("location") or capabilities.get("query_all_packages"):
        return DeviceTier.plain
    return DeviceTier.unknown


class CommandError(ValueError):
    """Raised when a command cannot be queued (unknown type or unsupported)."""


async def queue_command(
    session: Session, device: Device, cmd_type: str, payload: dict | None = None
) -> Command:
    """Validate, persist, and attempt immediate MQTT delivery of a command."""
    if cmd_type not in COMMAND_TYPES:
        raise CommandError(f"Unknown command type: {cmd_type}")
    if not device.can(cmd_type):
        raise CommandError(
            f"Device '{device.name}' ({device.tier.value}) cannot run '{cmd_type}'"
        )

    command = Command(device_id=device.id, type=cmd_type, payload=payload or {})
    session.add(command)
    session.commit()
    session.refresh(command)

    # Best-effort instant delivery when MQTT push is enabled *and* the broker
    # is reachable by the device. Otherwise the command stays pending and the
    # device collects it on its next HTTPS poll (the default delivery path).
    from app.config import settings

    if settings.mqtt_push and await bridge.publish_command(device.id, command.envelope()):
        command.status = CommandStatus.sent
        command.sent_at = utcnow()
        session.commit()

    return command
