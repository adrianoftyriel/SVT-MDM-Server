# SVT MDM Protocol

This document is the source of truth for the wire contract between the server
and device agents (Android now, Windows later). Both sides must agree on these
shapes. Keep it in sync with `app/models` and the agent code.

## Transport

- **Telemetry** (device → server): HTTPS `POST` with a `Bearer <device_token>`
  header. Chosen for reliability — survives MQTT reconnects and works behind
  captive portals.
- **Commands** (server → device): MQTT, for instant delivery. The device
  subscribes to its own command topic and publishes acks back.
- Devices that cannot hold an MQTT connection fall back to polling
  `GET /api/commands/pending` on their telemetry check-in.

## Identity & auth

- Each enrolled device has a stable `device_id` (UUID) and a long-lived
  `device_token` (opaque, issued once at enrollment, stored server-side only
  as a hash).
- The `device_token` authenticates HTTPS telemetry and doubles as the MQTT
  password (username = `device_id`). Broker ACLs restrict each device to its
  own topics.

## MQTT topics

| Topic                     | Direction       | Payload                    |
|---------------------------|-----------------|----------------------------|
| `mdm/<device_id>/cmd`     | server → device | `Command` JSON             |
| `mdm/<device_id>/ack`     | device → server | `CommandAck` JSON          |
| `mdm/<device_id>/status`  | device → server | `Presence` JSON (retained) |

## Capability tiers

A device reports which privilege tier it runs in. The server only offers
commands the device's capabilities support.

```json
{
  "tier": "device_owner | device_admin | plain",
  "device_owner": false,
  "device_admin": true,
  "shizuku": true,
  "usage_access": true,
  "location": true,
  "query_all_packages": true
}
```

| Capability          | device_owner | device_admin (+shizuku) | plain |
|---------------------|:------------:|:-----------------------:|:-----:|
| `locate`            | ✅           | ✅                      | ✅    |
| `inventory`         | ✅           | ✅                      | ✅*   |
| `usage_stats`       | ✅           | ✅ (needs shizuku/grant)| ⚠️    |
| `lock` (force)      | ✅           | ✅                      | ❌    |
| `set_password`      | ✅           | ❌                      | ❌    |
| `wipe`              | ✅           | ✅                      | ❌    |

\* plain tier may require a manual permission grant.

## Command envelope

```json
{
  "id": "uuid",
  "type": "locate | lock | set_password | wipe | refresh_inventory | refresh_usage",
  "payload": { },
  "issued_at": "2026-07-21T14:00:00Z"
}
```

Per-type `payload`:

| type               | payload                          |
|--------------------|----------------------------------|
| `locate`           | `{}`                             |
| `lock`             | `{}`                             |
| `set_password`     | `{ "password": "1234" }`         |
| `wipe`             | `{ "confirm": true }`            |
| `refresh_inventory`| `{}`                             |
| `refresh_usage`    | `{ "days": 7 }`                  |

## Command ack

```json
{
  "id": "uuid",
  "status": "acked | failed",
  "detail": "optional human-readable string",
  "completed_at": "2026-07-21T14:00:02Z"
}
```

## Telemetry payloads

### Location ping — `POST /api/telemetry/location`
```json
{ "lat": 51.5, "lon": -0.12, "accuracy_m": 12.0, "captured_at": "..." }
```

### App inventory — `POST /api/telemetry/inventory`
```json
{
  "captured_at": "...",
  "apps": [
    { "package": "com.example", "label": "Example", "version": "1.2.3", "system": false }
  ]
}
```

### Usage stats — `POST /api/telemetry/usage`
```json
{
  "captured_at": "...",
  "range_days": 7,
  "stats": [
    { "package": "com.example", "foreground_ms": 3600000, "last_used": "..." }
  ]
}
```

### Device check-in — `POST /api/telemetry/checkin`
```json
{
  "battery": 82,
  "os_version": "14",
  "model": "Pixel 7",
  "capabilities": { "...": "see above" }
}
```
