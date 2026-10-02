# SVT MDM Protocol

This document is the source of truth for the wire contract between the server
and device agents (Android now, Windows later). Both sides must agree on these
shapes. Keep it in sync with `app/models` and the agent code.

## Transport

- **Telemetry** (device → server): HTTPS `POST` with a `Bearer <device_token>`
  header. Chosen for reliability — survives MQTT reconnects and works behind
  captive portals.
- **Commands** (server → device): **HTTPS polling is the default** —
  `GET /api/commands/pending`, acked with `POST /api/commands/ack`. A command
  that is handed out but not acked within 45 s is re-delivered, so handlers
  must be idempotent.
- **MQTT push is optional** (server option `mqtt_push`). When enabled, the
  enrollment response advertises a broker; the device subscribes to its own
  command topic for instant delivery and may publish acks back. Polling keeps
  working alongside it.

## Identity & auth

- Each enrolled device has a stable `device_id` (UUID) and a long-lived
  `device_token` (opaque, issued once at enrollment, stored server-side only
  as a hash).
- The `device_token` authenticates HTTPS telemetry and doubles as the MQTT
  password (username = `device_id`) when MQTT push is enabled. **The server does
  not provision broker users or ACLs** — the operator must create them in the
  broker and restrict each device to `mdm/<device_id>/#` (e.g. Mosquitto
  `pattern readwrite mdm/%u/#`). Without that, any broker client can publish
  acks/status for any device, so the server only trusts an ack whose command
  belongs to the topic's device, never re-completes a finished command, and
  accepts only non-destructive commands (`ring`, `stop_ring`, `locate`) from Home Assistant
  buttons.

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
| `ring`              | ✅           | ✅                      | ✅    |
| `stop_ring`         | ✅           | ✅                      | ✅    |
| `backup_now`        | needs `backup` capability (any tier)            ||

\* plain tier may require a manual permission grant.

## Command envelope

```json
{
  "id": "uuid",
  "type": "locate | ring | stop_ring | lock | set_password | wipe | refresh_inventory | refresh_usage | backup_now",
  "payload": { },
  "issued_at": "2026-07-21T14:00:00Z"
}
```

Per-type `payload`:

| type               | payload                          |
|--------------------|----------------------------------|
| `locate`           | `{}`                             |
| `lock`             | `{}`                             |
| `set_password`     | `{ "password": "1234" }` (non-empty; the server rejects an empty password) |
| `wipe`             | `{ "confirm": true }`            |
| `refresh_inventory`| `{}`                             |
| `refresh_usage`    | `{ "days": 7 }`                  |
| `ring`             | `{ "seconds": 30 }`              |
| `stop_ring`        | `{}`                             |
| `backup_now`       | `{}`                             |

`ring` plays a loud alarm-stream sound (ignores silent/vibrate) for the given
duration, and acks as soon as it starts. `stop_ring` silences it early; the
user can also silence it on the device from the "Stop ringing" notification
action or by opening the app. Neither needs special privilege. Devices are also exposed to Home
Assistant via MQTT discovery — Ring, Stop ringing and Locate buttons (plus
battery/last-seen/location sensors) that queue the matching command. Lock,
wipe and set_password are deliberately not exposed to Home Assistant.

`issued_at` and every other server-emitted timestamp are UTC ending in `Z`.

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

## Backups

Files are content-addressed by the SHA-256 of their plaintext and deduped per
device. The server encrypts blobs at rest; transport is protected by TLS.

Per run:
1. `POST /api/backup/run` → `{ "run_id": "..." }`
2. `POST /api/backup/manifest` with `{ "files": [ {sha256, size, rel_path, category, mtime} ] }`
   → `{ "missing": ["sha256", ...] }` (only these need uploading)
3. `PUT /api/backup/object/{sha256}?path=<rel_path>&category=<cat>` with the raw
   plaintext body → `{ "stored": bool, "deduped": bool, "size": int }`.
   The server verifies the received bytes hash to `{sha256}` (else 400).
4. `POST /api/backup/run/{run_id}/complete` with `{ file_count, total_bytes, status }`

`category` is a free-form tag: `media | document | contacts | file`.
The `backup_now` command triggers a run; it requires the `backup` capability.

### Device check-in — `POST /api/telemetry/checkin`
```json
{
  "battery": 82,
  "os_version": "14",
  "model": "Pixel 7",
  "capabilities": { "...": "see above" }
}
```

Response:
```json
{ "ok": true, "tier": "device_admin", "theme": "midnight" }
```

The `theme` field is the id of the operator-selected interface theme (see
below). The agent stores it and restyles the app to match; it is refreshed on
every check-in.

## Interface theme

The operator picks one interface theme on the server dashboard
(**Appearance**). It styles the dashboard *and* is pushed to every device so the
phone app's colours match. The theme catalogue is defined once in the server
(`app/themes.py`) and mirrored in the agent (`ui/theme/Themes.kt`); both sides
key off a stable `theme id`.

Current themes: `midnight` (default), `graphite`, `nord`, `nebula`,
`terminal`, `aurora`, `solar`, `sandstone`, `blueprint`, `plainsight`,
`sprout`, `lcars`.

The operator can switch themes from the dropdown in the dashboard topbar on any
page, or from the **Appearance** page's preview grid.

### Active theme — `GET /api/theme`
Device-authenticated. Returns the full colour token set so an agent can render a
theme even if the id is one it doesn't know locally:
```json
{
  "id": "lcars",
  "name": "LCARS",
  "dark": true,
  "font": "condensed",
  "colors": {
    "bg": "#000000", "panel": "#0b0b0b", "panel2": "#161616",
    "text": "#ffcc99", "muted": "#cc99cc", "accent": "#ff9900",
    "accent_text": "#000000", "ok": "#99cc99", "warn": "#ffcc00",
    "danger": "#cc6666", "border": "#ff9900"
  }
}
```

`font` is one of `system`, `mono`, `condensed`.
