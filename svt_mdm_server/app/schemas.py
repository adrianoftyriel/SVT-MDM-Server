"""Pydantic request/response schemas for the JSON API.

Mirror shared/protocol.md. Kept in one module so the contract is easy to read.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# --- Enrollment ---------------------------------------------------------------

class EnrollRequest(BaseModel):
    enroll_token: str
    enrollment_secret: str | None = None
    name: str | None = None
    platform: str = "android"
    model: str | None = None
    os_version: str | None = None
    capabilities: dict = Field(default_factory=dict)


class MqttInfo(BaseModel):
    host: str | None
    port: int
    tls: bool
    username: str
    password: str
    cmd_topic: str
    ack_topic: str
    status_topic: str


class EnrollResponse(BaseModel):
    device_id: str
    device_token: str
    mqtt: MqttInfo


# --- Telemetry ----------------------------------------------------------------

class CheckinRequest(BaseModel):
    battery: int | None = None
    os_version: str | None = None
    model: str | None = None
    capabilities: dict = Field(default_factory=dict)


class LocationRequest(BaseModel):
    lat: float
    lon: float
    accuracy_m: float | None = None
    captured_at: datetime | None = None


class AppEntry(BaseModel):
    package: str
    label: str | None = None
    version: str | None = None
    system: bool = False


class InventoryRequest(BaseModel):
    captured_at: datetime | None = None
    apps: list[AppEntry] = Field(default_factory=list)


class UsageEntry(BaseModel):
    package: str
    foreground_ms: int = 0
    last_used: datetime | None = None


class UsageRequest(BaseModel):
    captured_at: datetime | None = None
    range_days: int = 7
    stats: list[UsageEntry] = Field(default_factory=list)


# --- Commands -----------------------------------------------------------------

class CommandCreate(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)


class CommandAck(BaseModel):
    id: str
    status: str  # "acked" | "failed"
    detail: str | None = None
    completed_at: datetime | None = None


# --- Backups ------------------------------------------------------------------

class BackupFileMeta(BaseModel):
    sha256: str
    size: int = 0
    rel_path: str
    category: str = "file"
    mtime: datetime | None = None


class ManifestRequest(BaseModel):
    files: list[BackupFileMeta] = Field(default_factory=list)


class ManifestResponse(BaseModel):
    missing: list[str] = Field(default_factory=list)  # sha256 the server still needs


class RunStartResponse(BaseModel):
    run_id: str


class RunCompleteRequest(BaseModel):
    file_count: int = 0
    total_bytes: int = 0
    status: str = "complete"  # "complete" | "failed"
