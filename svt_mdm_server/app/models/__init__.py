"""ORM models. Importing this module registers every table on Base.metadata."""

from app.models.backup import BackupConfig, BackupObject, BackupRun
from app.models.command import Command, CommandStatus
from app.models.device import Device, DeviceTier
from app.models.setting import Setting
from app.models.telemetry import AppInventory, LocationPing, UsageSnapshot

__all__ = [
    "AppInventory",
    "BackupConfig",
    "BackupObject",
    "BackupRun",
    "Command",
    "CommandStatus",
    "Device",
    "DeviceTier",
    "LocationPing",
    "Setting",
    "UsageSnapshot",
]
