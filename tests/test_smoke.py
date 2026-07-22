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


def test_security_headers_present(client):
    resp = client.get("/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "no-referrer"


def test_enrollment_throttle_blocks_brute_force(client):
    # 20 bad-token attempts are allowed (404), the 21st is throttled (429).
    for _ in range(20):
        r = client.post("/api/enroll", json={"enroll_token": "nope"})
        assert r.status_code == 404
    r = client.post("/api/enroll", json={"enroll_token": "nope"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_backup_flow(client):
    import hashlib

    from sqlalchemy import select

    import app.db as db
    from app.models import BackupObject

    # Enroll a device.
    enroll_token = _create_device(client)
    token = client.post(
        "/api/enroll",
        json={"enroll_token": enroll_token, "capabilities": {"backup": True}},
    ).json()["device_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # A multi-chunk payload (>256 KiB) to exercise chunked AES-GCM.
    content = b"svt-backup-" * 70_000
    sha = hashlib.sha256(content).hexdigest()

    # Start a run.
    run_id = client.post("/api/backup/run", headers=auth).json()["run_id"]

    # Manifest: the file is missing.
    missing = client.post(
        "/api/backup/manifest",
        json={"files": [{"sha256": sha, "size": len(content), "rel_path": "DCIM/a.jpg",
                         "category": "media"}]},
        headers=auth,
    ).json()["missing"]
    assert missing == [sha]

    # Upload it.
    up = client.put(
        f"/api/backup/object/{sha}?path=DCIM/a.jpg&category=media",
        content=content,
        headers=auth,
    )
    assert up.status_code == 200, up.text
    assert up.json()["stored"] is True

    # Now the manifest reports nothing missing (deduped).
    missing2 = client.post(
        "/api/backup/manifest",
        json={"files": [{"sha256": sha, "size": len(content), "rel_path": "DCIM/a.jpg"}]},
        headers=auth,
    ).json()["missing"]
    assert missing2 == []

    client.post(
        f"/api/backup/run/{run_id}/complete",
        json={"file_count": 1, "total_bytes": len(content), "status": "complete"},
        headers=auth,
    )

    # Download via the dashboard and confirm decryption round-trips exactly.
    with db.SessionLocal() as s:
        obj = s.scalar(select(BackupObject))
        device_id, object_id = obj.device_id, obj.id
    dl = client.get(f"/devices/{device_id}/backups/{object_id}/download")
    assert dl.status_code == 200
    assert dl.content == content

    # A corrupted upload (wrong sha) is rejected.
    bad = client.put(
        "/api/backup/object/" + "0" * 64 + "?path=x&category=media",
        content=b"nope",
        headers=auth,
    )
    assert bad.status_code == 400


def test_dashboard_escapes_device_strings(client):
    # A device name containing markup must be HTML-escaped on the dashboard,
    # not rendered as live HTML (stored-XSS defense).
    client.post(
        "/devices",
        data={"name": "<script>alert(1)</script>", "platform": "android"},
        follow_redirects=False,
    )
    body = client.get("/").text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
