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

    # Push commands to devices over MQTT. Only useful when the broker is
    # reachable *from the devices* (e.g. exposed with TLS). Off by default:
    # devices then collect commands by polling over HTTPS, which works through
    # the same reverse proxy used for the rest of the API.
    mqtt_push: bool = _bool(os.getenv("MDM_MQTT_PUSH"), False)

    # Expose enrolled devices to Home Assistant via MQTT discovery (Ring button,
    # sensors, etc.). Requires the MQTT broker; harmless when it's absent.
    ha_discovery: bool = _bool(os.getenv("MDM_HA_DISCOVERY"), True)

    http_port: int = int(os.getenv("MDM_HTTP_PORT", "8099"))
    log_level: str = os.getenv("MDM_LOG_LEVEL", "info")

    # Where encrypted device backups are stored (mapped host folder).
    backup_dir: str = os.getenv("MDM_BACKUP_DIR", "/share/svt-mdm-backups")

    # Device Owner QR provisioning. external_url is the https base URL devices
    # reach the server at (embedded in the QR). apk_url must be reachable by a
    # phone during setup. do_signature_checksum is the base64url SHA-256 of the
    # APK signing certificate.
    external_url: str = os.getenv("MDM_EXTERNAL_URL", "")
    # `or default` (not getenv default) so an empty add-on option falls back.
    apk_url: str = os.getenv("MDM_APK_URL") or (
        "https://github.com/adrianoftyriel/svt-mdm-android/releases/latest/download/svt-mdm-latest.apk"
    )
    do_signature_checksum: str = (
        os.getenv("MDM_DO_CHECKSUM") or "QGFnYMwe0rezuujokGa9CLb6pJXweG47KqQg6r81ctg"
    )

    @property
    def db_url(self) -> str:
        return f"sqlite+pysqlite:///{self.db_path}"

    @property
    def dashboard_allowed_ips(self) -> set[str]:
        """Source IPs permitted to reach the web dashboard. Ingress requests
        arrive from the HA Supervisor (172.30.32.2); everything else (the
        publicly reachable API port) is refused for dashboard routes. Loopback
        and the TestClient host are allowed for local dev/tests. Extra IPs can
        be added via MDM_DASHBOARD_ALLOWED_IPS (comma-separated)."""
        defaults = {"172.30.32.2", "127.0.0.1", "::1", "localhost", "testclient"}
        extra = os.getenv("MDM_DASHBOARD_ALLOWED_IPS", "")
        return defaults | {ip.strip() for ip in extra.split(",") if ip.strip()}

    @property
    def mqtt_enabled(self) -> bool:
        return self.mqtt_host is not None


settings = Settings()
