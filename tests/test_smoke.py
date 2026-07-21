"""End-to-end smoke test of the enrollment → telemetry → command loop.

Runs without MQTT (polling-only mode), against a temporary SQLite database,
using FastAPI's TestClient. No network or broker required.
"""

from __future__ import annotations

# The `client` fixture lives in conftest.py so the database path is set before
# the app package is first imported.


def _create_device(client) -> str:
    """Create a device via the dashboard form and return its enroll token."""
    from sqlalchemy import select

    import app.db as db
    from app.models import Device

    resp = client.post(
        "/devices",
        data={"name": "Test Phone", "platform": "android"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    with db.SessionLocal() as session:
        device = session.scalar(select(Device))
        return device.enroll_token


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_full_enrollment_and_command_flow(client):
    enroll_token = _create_device(client)

    # Enroll as a device-admin-tier device.
    resp = client.post(
        "/api/enroll",
        json={
            "enroll_token": enroll_token,
            "name": "Test Phone",
            "platform": "android",
            "model": "Pixel 7",
            "os_version": "14",
            "capabilities": {
                "device_admin": True,
                "location": True,
                "query_all_packages": True,
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    token = body["device_token"]
    assert body["mqtt"]["username"] == body["device_id"]

    auth = {"Authorization": f"Bearer {token}"}

    # Post telemetry.
    assert client.post(
        "/api/telemetry/location",
        json={"lat": 51.5, "lon": -0.12, "accuracy_m": 10},
        headers=auth,
    ).status_code == 200
    assert client.post(
        "/api/telemetry/usage",
        json={"range_days": 7, "stats": [{"package": "com.x", "foreground_ms": 60000}]},
        headers=auth,
    ).status_code == 200

    # A supported command (lock) should queue and then be pollable.
    device_id = body["device_id"]
    assert client.post(
        f"/devices/{device_id}/commands",
        data={"command_type": "lock"},
        follow_redirects=False,
    ).status_code == 303

    pending = client.get("/api/commands/pending", headers=auth).json()["commands"]
    assert len(pending) == 1
    assert pending[0]["type"] == "lock"

    # Ack it.
    assert client.post(
        "/api/commands/ack",
        json={"id": pending[0]["id"], "status": "acked"},
        headers=auth,
    ).status_code == 200


def test_unsupported_command_rejected(client):
    enroll_token = _create_device(client)
    resp = client.post(
        "/api/enroll",
        json={
            "enroll_token": enroll_token,
            "capabilities": {"device_admin": True, "location": True},
        },
    )
    device_id = resp.json()["device_id"]

    # set_password requires device_owner; this device is device_admin only.
    resp = client.post(
        f"/devices/{device_id}/commands",
        data={"command_type": "set_password", "password": "1234"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_bad_token_rejected(client):
    resp = client.get(
        "/api/commands/pending", headers={"Authorization": "Bearer nope"}
    )
    assert resp.status_code == 401
