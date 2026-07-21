"""MQTT bridge: pushes commands to devices and consumes their acks.

Runs as a single long-lived task in the FastAPI lifespan. If MQTT is not
configured, the bridge stays in a degraded state: commands remain ``pending``
in the database and devices pick them up via the polling fallback
(``GET /api/commands/pending``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl

from sqlalchemy import select

from app.config import settings
from app.util import utcnow

log = logging.getLogger("mdm.mqtt")

TOPIC_PREFIX = "mdm"


def topics_for(device_id: str) -> dict[str, str]:
    base = f"{TOPIC_PREFIX}/{device_id}"
    return {
        "cmd": f"{base}/cmd",
        "ack": f"{base}/ack",
        "status": f"{base}/status",
    }


class MqttBridge:
    def __init__(self) -> None:
        self._client = None  # aiomqtt.Client when connected
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()

    # -- lifecycle ------------------------------------------------------------

    async def run(self) -> None:
        """Connect-and-consume loop with reconnect backoff."""
        if not settings.mqtt_enabled:
            log.warning(
                "MQTT not configured; running in polling-only mode. "
                "Commands will queue until devices poll for them."
            )
            return

        import aiomqtt

        tls_context = ssl.create_default_context() if settings.mqtt_tls else None
        backoff = 1
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=settings.mqtt_host,
                    port=settings.mqtt_port,
                    username=settings.mqtt_username,
                    password=settings.mqtt_password,
                    tls_context=tls_context,
                    identifier="svt-mdm-server",
                ) as client:
                    self._client = client
                    self._ready.set()
                    backoff = 1
                    log.info("MQTT connected to %s:%s", settings.mqtt_host,
                             settings.mqtt_port)
                    await client.subscribe(f"{TOPIC_PREFIX}/+/ack")
                    await client.subscribe(f"{TOPIC_PREFIX}/+/status")
                    async for message in client.messages:
                        await self._handle(str(message.topic), message.payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                log.warning("MQTT connection lost (%s); retrying in %ss", exc, backoff)
            finally:
                self._client = None
                self._ready.clear()
            if self._stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def stop(self) -> None:
        self._stop.set()

    # -- publishing -----------------------------------------------------------

    async def publish_command(self, device_id: str, envelope: dict) -> bool:
        """Publish a command envelope. Returns True if it went out over MQTT."""
        if self._client is None:
            return False
        topic = topics_for(device_id)["cmd"]
        try:
            await self._client.publish(topic, json.dumps(envelope).encode(), qos=1)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to publish command to %s: %s", topic, exc)
            return False

    # -- inbound --------------------------------------------------------------

    async def _handle(self, topic: str, payload: bytes) -> None:
        parts = topic.split("/")
        if len(parts) != 3:
            return
        _, device_id, kind = parts
        try:
            data = json.loads(payload.decode() or "{}")
        except (ValueError, UnicodeDecodeError):
            log.warning("Dropping non-JSON message on %s", topic)
            return

        if kind == "ack":
            await asyncio.to_thread(self._apply_ack, device_id, data)
        elif kind == "status":
            await asyncio.to_thread(self._apply_status, device_id, data)

    def _apply_ack(self, device_id: str, data: dict) -> None:
        # Imported lazily to avoid a circular import at module load.
        from app.db import SessionLocal
        from app.models import Command, CommandStatus

        command_id = data.get("id")
        if not command_id:
            return
        with SessionLocal() as session:
            cmd = session.get(Command, command_id)
            if cmd is None or cmd.device_id != device_id:
                return
            status_str = data.get("status")
            cmd.status = (
                CommandStatus.acked if status_str == "acked" else CommandStatus.failed
            )
            cmd.detail = data.get("detail")
            cmd.completed_at = utcnow()
            session.commit()
            log.info("Command %s -> %s", command_id, cmd.status.value)

    def _apply_status(self, device_id: str, data: dict) -> None:
        from app.db import SessionLocal
        from app.models import Device

        with SessionLocal() as session:
            device = session.get(Device, device_id)
            if device is None:
                return
            device.last_seen = utcnow()
            session.commit()


# Module-level singleton wired up in app.main's lifespan.
bridge = MqttBridge()
