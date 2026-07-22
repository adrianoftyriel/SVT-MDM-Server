"""Home Assistant MQTT-discovery payloads for enrolled devices.

Each device is announced to HA as a device with:
  - buttons: Ring, Locate, Lock  (press -> command queued back to the phone)
  - sensors: Battery, Last seen, Latitude, Longitude

Buttons publish to ``mdm/<id>/ha/<command>``; the bridge subscribes there and
enqueues the command. Sensors read ``mdm/<id>/state`` and ``mdm/<id>/location``,
which the server publishes as telemetry arrives. Destructive commands (wipe,
set_password) are deliberately NOT exposed to HA.
"""

from __future__ import annotations

DISCOVERY_PREFIX = "homeassistant"

# HA button command -> internal command type. Only safe commands.
HA_BUTTONS = {
    "ring": {"name": "Ring", "icon": "mdi:bell-ring"},
    "locate": {"name": "Locate", "icon": "mdi:crosshairs-gps"},
    "lock": {"name": "Lock", "icon": "mdi:cellphone-lock"},
}
HA_ALLOWED_COMMANDS = set(HA_BUTTONS)


def state_topic(device_id: str) -> str:
    return f"mdm/{device_id}/state"


def location_topic(device_id: str) -> str:
    return f"mdm/{device_id}/location"


def command_topic(device_id: str, ha_command: str) -> str:
    return f"mdm/{device_id}/ha/{ha_command}"


def _device_block(device) -> dict:
    return {
        "identifiers": [f"svtmdm_{device.id}"],
        "name": device.name,
        "manufacturer": "SVT MDM",
        "model": device.platform,
    }


def discovery_messages(device) -> list[tuple[str, dict]]:
    """(config_topic, config_payload) pairs to publish (retained) for a device."""
    dev = _device_block(device)
    out: list[tuple[str, dict]] = []

    for cmd, meta in HA_BUTTONS.items():
        uid = f"svtmdm_{device.id}_{cmd}"
        out.append((
            f"{DISCOVERY_PREFIX}/button/{uid}/config",
            {
                "name": meta["name"],
                "unique_id": uid,
                "command_topic": command_topic(device.id, cmd),
                "payload_press": "PRESS",
                "icon": meta["icon"],
                "device": dev,
            },
        ))

    sensors = [
        ("battery", "Battery", {"unit_of_measurement": "%", "device_class": "battery",
                                "value_template": "{{ value_json.battery }}",
                                "state_topic": state_topic(device.id)}),
        ("last_seen", "Last seen", {"device_class": "timestamp",
                                    "value_template": "{{ value_json.last_seen }}",
                                    "state_topic": state_topic(device.id)}),
        ("latitude", "Latitude", {"value_template": "{{ value_json.latitude }}",
                                  "state_topic": location_topic(device.id)}),
        ("longitude", "Longitude", {"value_template": "{{ value_json.longitude }}",
                                    "state_topic": location_topic(device.id)}),
    ]
    for key, name, extra in sensors:
        uid = f"svtmdm_{device.id}_{key}"
        out.append((
            f"{DISCOVERY_PREFIX}/sensor/{uid}/config",
            {"name": name, "unique_id": uid, "device": dev, **extra},
        ))

    return out


def state_payload(device) -> dict:
    return {
        "battery": device.battery,
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        "tier": device.tier.value,
        "name": device.name,
    }
