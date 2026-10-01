# SVT MDM Server

Self-hosted Mobile Device Management for personal Android (and, later, Windows)
devices, packaged as a **Home Assistant add-on**.

> **Status: Phase 1 skeleton.** Enrollment, telemetry ingestion, the command
> queue + MQTT bridge, and the operator dashboard are in place. The Android
> agent lives in [`svt-mdm-android`](https://github.com/adrianoftyriel/svt-mdm-android).

## What it does

- **Enrolls devices** with a one-time token and issues each a long-lived
  API token (stored only as a hash).
- **Ingests telemetry**: location pings, installed-app inventory, and app
  usage statistics (HTTPS).
- **Queues commands** — `locate`, `ring`, `lock`, `set_password`, `wipe`,
  `refresh_inventory`, `refresh_usage`, `backup_now`. Devices collect them by
  **polling over HTTPS (the default)**. Optionally, enable `mqtt_push` to also
  push them over MQTT for instant delivery (see "MQTT push and broker ACLs").
- **Gates commands by capability tier.** Each device reports whether it is a
  Device Owner, Device Admin, or plain install; the dashboard only offers what a
  given device can actually do (e.g. `set_password` requires Device Owner).
- **Dashboard** served through Home Assistant **ingress**, so it inherits HA's
  authentication.

See [`shared/protocol.md`](shared/protocol.md) for the full wire contract.

## Architecture

```
 Android agent            HA add-on (this repo)                 Operator
┌──────────────┐        ┌────────────────────────────┐      ┌──────────┐
│ MQTT client ─┼─ cmd ──┤ Mosquitto (HA broker)       │      │ Browser  │
│ location svc │        │        ▲                    │      │ via HA   │
│ inventory    ├─ HTTPS ┤ FastAPI + SQLite            │◄─────┤ ingress  │
│ usage/probe  │  telem.│ dashboard (Jinja + HTMX)    │      │ (HA auth)│
└──────────────┘        └────────────────────────────┘      └──────────┘
```

- **FastAPI** app (`app/`): JSON API for agents, server-rendered dashboard,
  MQTT bridge.
- **SQLite** on the add-on's persistent `/data` volume.
- **MQTT** via Home Assistant's Mosquitto broker (requested through the add-on
  `services: mqtt:need`, credentials injected at runtime).

## Install as a Home Assistant add-on

1. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**,
   add `https://github.com/adrianoftyriel/svt-mdm-server`.
2. Install **SVT MDM Server**. Ensure the **Mosquitto broker** add-on is
   installed (for instant commands; without it the server runs polling-only).
3. Set an **enrollment secret** in the add-on configuration.
4. Start the add-on and open its panel (SVT MDM in the sidebar).

## Exposing the device API

The dashboard is served over Home Assistant **ingress** (HA-authenticated). The
**device agents**, however, need to reach `/api/*` directly, so the add-on also
**publishes port 8099 on the host**.

That published port is **plain HTTP** — do not expose it to the internet as-is.
Put TLS in front:

- **Reverse proxy (recommended).** Terminate TLS at NGINX/Caddy/Traefik (or the
  "NGINX Home Assistant SSL proxy" add-on) with a cert for your domain, and
  proxy to `http://<ha-host>:8099`. Point agents at the `https://` proxy URL.
- **Cloudflare Tunnel.** Expose `http://<ha-host>:8099` through a tunnel; agents
  use the `https://` hostname Cloudflare provides. No router port-forward needed.

For a quick LAN-only test you can point an agent at `http://<ha-host>:8099`
directly, but the Android app blocks cleartext by default — see the agent repo's
network-security note.

### MQTT push and broker ACLs

MQTT is optional. With `mqtt_push` off (the default) commands are delivered only
by HTTPS polling and no broker is advertised to agents.

If you turn `mqtt_push` on, note that **the add-on does not create broker
accounts or ACLs**. Agents are told to log in to the broker as
`username = <device_id>`, `password = <device_token>`, so you must create those
users in Mosquitto yourself and restrict each to its own topics, e.g.
`topic readwrite mdm/%u/#` (Mosquitto `pattern` ACL). Without per-device ACLs,
any broker client can publish acks/status for any device or press the Home
Assistant buttons. For that reason the server only accepts non-destructive
commands (`ring`, `locate`) from Home Assistant buttons — `lock`, `wipe` and
`set_password` are never accepted over the broker — and it ignores acks that
don't match the topic's device. Old retained Lock buttons are removed from HA
automatically.

### Dashboard is ingress-only

The published port serves **only** the device API (`/api/*`, authenticated by
device tokens / the enrollment secret) and `/health`. The operator **dashboard
is refused on the published port** — it is served only through Home Assistant
**ingress**, so it inherits HA's login. Open it from the **SVT MDM sidebar panel
inside Home Assistant**, not from the public proxy URL.

Enforcement uses the real TCP peer address (the HA Supervisor, `172.30.32.2`,
for ingress); the add-on runs uvicorn **without** `--proxy-headers` so a request
arriving through the public proxy cannot spoof that address via
`X-Forwarded-For`. If your ingress uses a different source IP, add it via the
`dashboard_allowed_ips` option.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r svt_mdm_server/requirements.txt cryptography pytest httpx
# Runs against ./mdm.db, no MQTT (polling-only), no auth on the dashboard.
PYTHONPATH=svt_mdm_server MDM_DB_PATH=./mdm.db \
  uvicorn app.main:app --reload --port 8099
# Dashboard: http://localhost:8099/   ·   Health: http://localhost:8099/health
```

Run the tests:

```bash
pytest -q
```

## Configuration

| Env var (add-on option)      | Default        | Purpose                                  |
|------------------------------|----------------|------------------------------------------|
| `MDM_ENROLLMENT_SECRET`      | `""`           | Shared secret an agent must present to enroll. |
| `MDM_DB_PATH`                | `/data/mdm.db` | SQLite database location.                |
| `MDM_LOG_LEVEL`              | `info`         | `debug`/`info`/`warning`/`error`.        |
| `MDM_MQTT_PUSH`              | `false`        | Also push commands over MQTT (polling is always available). |
| `MDM_MQTT_*`                 | (from HA)      | Broker host/port/credentials, injected by `run.sh`. |

## Repository layout

```
svt_mdm_server/          The Home Assistant add-on (self-contained build context)
  config.yaml, Dockerfile, run.sh   Add-on packaging
  requirements.txt
  app/
    api/       JSON API routers: enroll, telemetry, commands
    models/    SQLAlchemy models: device, command, telemetry
    mqtt/      MQTT bridge (command push + ack/status consumption)
    web/       Dashboard (Jinja templates + static assets)
    main.py    App entry, lifespan, ingress middleware
repository.yaml          Add-on store repository descriptor
shared/protocol.md       The device↔server wire contract (source of truth)
tests/                   End-to-end smoke tests (no broker required)
```

> **Note on the layout:** Home Assistant builds an add-on using its own folder
> as the Docker build context, so everything the image needs lives inside
> `svt_mdm_server/`. `tests/` and `shared/` stay at the repo root (dev-only).

## Changelog

- **0.5.8** — Fix the Device Owner provisioning QR being too dense to scan:
  compact payload, lowest error correction, a proper 4-module quiet zone, and a
  larger on-screen render (version-17 code at up to 560px instead of version-21
  at 320px). No change to options, ports, or the API surface.

- **0.5.7** — Review fixes. Deleting a device now removes all its telemetry,
  backup records, commands and encrypted blobs (SQLite foreign keys are now
  enforced). Backup uploads validate `sha256` (64 lowercase hex) before touching
  disk and use unique temp files, so concurrent uploads can't corrupt a blob.
  `set_password` with an empty password is rejected (it would clear the lock
  screen). Backup downloads sanitize the filename (RFC 5987) and return 404 for
  a missing blob. `issued_at` / HA `last_seen` are UTC with a `Z` suffix. MQTT
  bridge: the Home Assistant Lock button is removed (only `ring`/`locate`
  accepted), acks are validated and can't re-complete a finished command, and
  status from unenrolled devices is ignored; broker ACL requirements are now
  documented. Location, accuracy and battery values are range-checked. Docs:
  `cryptography` in the dev install, `ring`/`backup_now` documented, polling
  clarified as the default.

- **0.5.6** — Build-metadata only: clear the two Supervisor build deprecation
  warnings. Drop the deprecated `armv7` arch (the lab HA host is amd64, and
  HA's supported arch list is now `aarch64`/`amd64` only) and delete
  `build.yaml`; the Dockerfile now selects the same per-arch HA base images
  itself via the `BUILD_ARCH` build arg the Supervisor passes on every build.
  No change to options, ports, ingress, or the API surface.

- **0.5.5** — Fix `POST /api/telemetry/usage` returning 500 when a stat entry
  carries `last_used`. The endpoint dumped pydantic models in python mode,
  leaving `last_used` a `datetime` that failed JSON serialization into the
  `usage_snapshots.stats` JSON column. Both telemetry dump sites
  (`/usage`, `/inventory`) now use `model_dump(mode="json")`. Regression test
  added; CI workflow now installs `cryptography` so the suite can import the
  app (the add-on image gets it from Alpine's `py3-cryptography` instead).

## Roadmap

- **Phase 1 (this):** server skeleton — enrollment, telemetry, commands, dashboard. ✅
- **Phase 2:** Android agent, light tier (Device Admin) — location, inventory, usage, force-lock.
- **Phase 3:** Android Device Owner tier — set password, silent grants, provisioning.
- **Phase 4:** Windows agent.
