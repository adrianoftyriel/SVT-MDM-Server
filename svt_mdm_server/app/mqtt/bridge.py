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
        self._loop = None  # event loop, for threadsafe publishing from sync handlers
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

        self._loop = asyncio.get_running_loop()
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
                    await client.subscribe(f"{TOPIC_PREFIX}/+/ha/+")
                    await self._announce_all()
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
        if len(parts) < 3:
            return
        device_id, kind = parts[1], parts[2]

        # Home Assistant button press: mdm/<id>/ha/<command>. Payload is the
        # button's press token, not JSON.
        if kind == "ha" and len(parts) >= 4:
            await asyncio.to_thread(self._enqueue_from_ha, device_id, parts[3])
            return

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

    def _enqueue_from_ha(self, device_id: str, ha_command: str) -> None:
        """Queue a command for a device in response to a Home Assistant button.

        Only safe commands are accepted; the device collects it on its next
        poll. Done synchronously (no MQTT publish) since command delivery is
        HTTPS-poll based by default.
        """
        from app.hadiscovery import HA_ALLOWED_COMMANDS
        from app.db import SessionLocal
        from app.models import Command, Device

        if ha_command not in HA_ALLOWED_COMMANDS:
            log.warning("Ignoring disallowed HA command '%s'", ha_command)
            return
        with SessionLocal() as session:
            device = session.get(Device, device_id)
            if device is None or not device.enrolled or not device.can(ha_command):
                return
            session.add(Command(device_id=device_id, type=ha_command))
            session.commit()
            log.info("HA queued '%s' for device %s", ha_command, device_id)

    # -- Home Assistant discovery / state -------------------------------------

    def publish_threadsafe(self, topic: str, payload: dict, retain: bool = False) -> None:
        """Publish JSON from a synchronous context (e.g. an HTTP handler)."""
        client, loop = self._client, self._loop
        if client is None or loop is None or not settings.ha_discovery:
            return
        data = json.dumps(payload).encode()

        async def _pub():
            try:
                await client.publish(topic, data, qos=0, retain=retain)
            except Exception as exc:  # noqa: BLE001
                log.debug("HA publish to %s failed: %s", topic, exc)

        try:
            asyncio.run_coroutine_threadsafe(_pub(), loop)
        except RuntimeError:
            pass

    async def _announce_all(self) -> None:
        if not settings.ha_discovery:
            return
        await asyncio.to_thread(self._announce_all_sync)

    def _announce_all_sync(self) -> None:
        from app.db import SessionLocal
        from app.models import Device
        from sqlalchemy import select

        with SessionLocal() as session:
            for device in session.scalars(select(Device).where(Device.enrolled.is_(True))):
                self._announce_device_sync(device)

    def announce_device(self, device) -> None:
        """Publish HA discovery + current state for one device (thread-safe)."""
        if not settings.ha_discovery:
            return
        self._announce_device_sync(device)

    def _announce_device_sync(self, device) -> None:
        from app import hadiscovery

        for topic, payload in hadiscovery.discovery_messages(device):
            self.publish_threadsafe(topic, payload, retain=True)
        self.publish_threadsafe(
            hadiscovery.state_topic(device.id), hadiscovery.state_payload(device),
            retain=True,
        )

    def publish_device_state(self, device) -> None:
        from app import hadiscovery

        self.publish_threadsafe(
            hadiscovery.state_topic(device.id), hadiscovery.state_payload(device),
            retain=True,
        )

    def publish_device_location(self, device_id: str, lat, lon, accuracy) -> None:
        from app import hadiscovery

        self.publish_threadsafe(
            hadiscovery.location_topic(device_id),
            {"latitude": lat, "longitude": lon, "gps_accuracy": accuracy},
            retain=True,
        )


# Module-level singleton wired up in app.main's lifespan.
bridge = MqttBridge()
