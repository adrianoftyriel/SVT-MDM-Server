"""Runtime configuration.

Values come from environment variables, which the Home Assistant add-on's
``run.sh`` populates from the add-on options and the injected MQTT service
credentials. Sensible defaults let the server also run for local development
with ``uvicorn app.main:app``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Storage. In the add-on this lives on the persistent /data volume.
    db_path: str = os.getenv("MDM_DB_PATH", "/data/mdm.db")

    # Shared secret an agent must present to enroll. Empty string disables the
    # check (fine for a trusted LAN / first run, but set one in production).
    enrollment_secret: str = os.getenv("MDM_ENROLLMENT_SECRET", "")

    # MQTT (injected by the Supervisor via `bashio::services mqtt`).
    mqtt_host: str | None = os.getenv("MDM_MQTT_HOST") or None
    mqtt_port: int = int(os.getenv("MDM_MQTT_PORT", "1883"))
    mqtt_username: str | None = os.getenv("MDM_MQTT_USERNAME") or None
    mqtt_password: str | None = os.getenv("MDM_MQTT_PASSWORD") or None
    mqtt_tls: bool = _bool(os.getenv("MDM_MQTT_TLS"), False)

    http_port: int = int(os.getenv("MDM_HTTP_PORT", "8099"))
    log_level: str = os.getenv("MDM_LOG_LEVEL", "info")

    @property
    def db_url(self) -> str:
        return f"sqlite+pysqlite:///{self.db_path}"

    @property
    def mqtt_enabled(self) -> bool:
        return self.mqtt_host is not None


settings = Settings()
