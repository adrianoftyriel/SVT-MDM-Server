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
- **Pushes commands** — `locate`, `lock`, `set_password`, `wipe`,
  `refresh_inventory`, `refresh_usage` — over MQTT for instant delivery, with a
  polling fallback when MQTT is unavailable.
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

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r svt_mdm_server/requirements.txt pytest httpx
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
| `MDM_MQTT_*`                 | (from HA)      | Broker host/port/credentials, injected by `run.sh`. |

## Repository layout

```
svt_mdm_server/          The Home Assistant add-on (self-contained build context)
  config.yaml, build.yaml, Dockerfile, run.sh   Add-on packaging
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

## Roadmap

- **Phase 1 (this):** server skeleton — enrollment, telemetry, commands, dashboard. ✅
- **Phase 2:** Android agent, light tier (Device Admin) — location, inventory, usage, force-lock.
- **Phase 3:** Android Device Owner tier — set password, silent grants, provisioning.
- **Phase 4:** Windows agent.
