"""Regression tests for the 0.5.7 review fixes."""

from __future__ import annotations

import asyncio
import hashlib
import os

from sqlalchemy import func, select

import app.db as db
from app import hadiscovery, storage
from app.config import settings
from app.models import (
    AppInventory,
    BackupConfig,
    BackupObject,
    BackupRun,
    Command,
    CommandStatus,
    Device,
    LocationPing,
    UsageSnapshot,
)
from app.mqtt.bridge import bridge


def _enroll(client, capabilities=None, name="Phone") -> tuple[str, dict]:
    resp = client.post("/devices", data={"name": name, "platform": "android"},
                       follow_redirects=False)
    assert resp.status_code == 303
    with db.SessionLocal() as s:
        enroll_token = s.scalars(
            select(Device).where(Device.name == name)
        ).one().enroll_token
    body = client.post(
        "/api/enroll",
        json={"enroll_token": enroll_token, "capabilities": capabilities or {}},
    ).json()
    return body["device_id"], {"Authorization": f"Bearer {body['device_token']}"}


def _upload(client, auth, content: bytes, path="DCIM/a.jpg") -> str:
    sha = hashlib.sha256(content).hexdigest()
    r = client.put(f"/api/backup/object/{sha}", params={"path": path},
                   content=content, headers=auth)
    assert r.status_code == 200, r.text
    return sha


def _count(model) -> int:
    with db.SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(model))


# --- (1) device delete ---------------------------------------------------------

def test_sqlite_foreign_keys_enabled():
    with db.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_delete_device_removes_all_data_and_blobs(client):
    device_id, auth = _enroll(client, {"backup": True, "location": True})
    client.post("/api/telemetry/location", json={"lat": 1, "lon": 2}, headers=auth)
    client.post("/api/telemetry/inventory", json={"apps": []}, headers=auth)
    client.post("/api/telemetry/usage", json={"stats": []}, headers=auth)
    client.post("/api/backup/run", headers=auth)
    client.post(f"/devices/{device_id}/backup-config", data={"media": "on"},
                follow_redirects=False)
    client.post(f"/devices/{device_id}/commands", data={"command_type": "ring"},
                follow_redirects=False)
    _upload(client, auth, b"hello world")
    blob_dir = os.path.join(settings.backup_dir, device_id)
    assert os.path.isdir(blob_dir)

    for model in (LocationPing, AppInventory, UsageSnapshot, BackupRun,
                  BackupObject, BackupConfig, Command):
        assert _count(model) >= 1, model

    resp = client.post(f"/devices/{device_id}/delete", follow_redirects=False)
    assert resp.status_code == 303

    for model in (Device, LocationPing, AppInventory, UsageSnapshot, BackupRun,
                  BackupObject, BackupConfig, Command):
        assert _count(model) == 0, model
    assert not os.path.exists(blob_dir)


# --- (2) backup sha256 validation ---------------------------------------------

def test_upload_rejects_bad_sha256_before_touching_disk(client):
    device_id, auth = _enroll(client, {"backup": True})
    device_dir = os.path.join(settings.backup_dir, device_id)
    for bad in ("zz" + "0" * 62, "A" * 64, "0" * 63, "a" * 300, "../" + "0" * 61):
        r = client.put(f"/api/backup/object/{bad}", params={"path": "x"},
                       content=b"data", headers=auth)
        assert r.status_code in (400, 404), (bad, r.status_code)
    assert not os.path.exists(device_dir)


def test_manifest_rejects_bad_sha256(client):
    _, auth = _enroll(client, {"backup": True})
    r = client.post("/api/backup/manifest",
                    json={"files": [{"sha256": "nope", "rel_path": "x"}]},
                    headers=auth)
    assert r.status_code == 422


def test_concurrent_identical_stores_do_not_corrupt(client):
    device_id, _ = _enroll(client, {"backup": True})
    content = b"concurrent-" * 50_000
    sha = hashlib.sha256(content).hexdigest()

    async def stream():
        for i in range(0, len(content), 32_768):
            yield content[i:i + 32_768]
            await asyncio.sleep(0)

    async def run():
        return await asyncio.gather(
            storage.store(device_id, sha, stream()),
            storage.store(device_id, sha, stream()),
        )

    results = asyncio.run(run())
    assert all(ok for ok, _, _ in results)
    assert b"".join(storage.open_decrypted(device_id, sha)) == content
    leftovers = [f for f in os.listdir(os.path.dirname(storage.object_path(device_id, sha)))
                 if f.endswith(".tmp")]
    assert leftovers == []


# --- (3) empty set_password ----------------------------------------------------

def test_empty_set_password_rejected(client):
    device_id, _ = _enroll(client, {"device_owner": True})
    for form in ({"command_type": "set_password"},
                 {"command_type": "set_password", "password": ""}):
        r = client.post(f"/devices/{device_id}/commands", data=form,
                        follow_redirects=False)
        assert r.status_code == 400
    assert _count(Command) == 0

    r = client.post(f"/devices/{device_id}/commands",
                    data={"command_type": "set_password", "password": "s3cret"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert _count(Command) == 1


def test_queue_command_rejects_missing_password(client):
    from app.services import CommandError, queue_command

    device_id, _ = _enroll(client, {"device_owner": True})
    with db.SessionLocal() as s:
        device = s.get(Device, device_id)
        for payload in (None, {}, {"password": ""}, {"password": None}):
            try:
                asyncio.run(queue_command(s, device, "set_password", payload))
            except CommandError:
                continue
            raise AssertionError(f"accepted {payload!r}")


# --- (4) download headers ------------------------------------------------------

def test_content_disposition_is_sanitised():
    from app.web import _content_disposition

    hdr = _content_disposition('DCIM/evil"\r\nX-Injected: 1.jpg', "fb.bin")
    assert "\r" not in hdr and "\n" not in hdr
    assert hdr.count('"') == 2  # only the two quoting the filename
    assert _content_disposition("a/b/..", "fb.bin").startswith('attachment; filename="fb.bin"')
    assert "filename*=UTF-8''%E2%82%AC.txt" in _content_disposition("€.txt", "fb.bin")


def test_download_with_hostile_name_and_missing_blob(client):
    device_id, auth = _enroll(client, {"backup": True})
    content = b"payload"
    sha = hashlib.sha256(content).hexdigest()
    r = client.put(f"/api/backup/object/{sha}",
                   params={"path": 'x/a"b\r\nc €.txt'}, content=content,
                   headers=auth)
    assert r.status_code == 200
    with db.SessionLocal() as s:
        obj_id = s.scalars(select(BackupObject)).one().id

    dl = client.get(f"/devices/{device_id}/backups/{obj_id}/download")
    assert dl.status_code == 200 and dl.content == content
    assert "\n" not in dl.headers["content-disposition"]

    storage.object_path(device_id, sha).unlink()
    assert client.get(f"/devices/{device_id}/backups/{obj_id}/download").status_code == 404


# --- (5) timestamps ------------------------------------------------------------

def test_timestamps_are_utc_z(client):
    device_id, auth = _enroll(client, {})
    client.post(f"/devices/{device_id}/commands", data={"command_type": "ring"},
                follow_redirects=False)
    cmds = client.get("/api/commands/pending", headers=auth).json()["commands"]
    assert cmds and cmds[0]["issued_at"].endswith("Z")
    assert "+" not in cmds[0]["issued_at"]

    with db.SessionLocal() as s:  # freshly loaded => naive datetimes from SQLite
        device = s.get(Device, device_id)
        assert device.last_seen is not None
        assert hadiscovery.state_payload(device)["last_seen"].endswith("Z")


# --- (6) MQTT bridge -----------------------------------------------------------

def test_ha_does_not_expose_lock(client):
    assert "lock" not in hadiscovery.HA_ALLOWED_COMMANDS
    device_id, _ = _enroll(client, {"device_admin": True})
    bridge._enqueue_from_ha(device_id, "lock")
    assert _count(Command) == 0
    with db.SessionLocal() as s:
        device = s.get(Device, device_id)
        topics = [t for t, _ in hadiscovery.discovery_messages(device)]
        assert not any(t.endswith("_lock/config") for t in topics)
        assert hadiscovery.retired_discovery_topics(device) == [
            f"homeassistant/button/svtmdm_{device_id}_lock/config"
        ]


def _make_command(device_id: str) -> str:
    with db.SessionLocal() as s:
        cmd = Command(device_id=device_id, type="ring")
        s.add(cmd)
        s.commit()
        return cmd.id


def _status(cmd_id: str):
    with db.SessionLocal() as s:
        cmd = s.get(Command, cmd_id)
        return cmd.status, cmd.completed_at


def test_mqtt_ack_is_scoped_and_validated(client):
    dev_a, _ = _enroll(client, {}, name="A")
    dev_b, _ = _enroll(client, {}, name="B")
    cmd_id = _make_command(dev_a)

    # Wrong device topic, invalid status, non-string id: all ignored.
    bridge._apply_ack(dev_b, {"id": cmd_id, "status": "acked"})
    bridge._apply_ack(dev_a, {"id": cmd_id, "status": "whatever"})
    bridge._apply_ack(dev_a, {"id": ["x"], "status": "acked"})
    assert _status(cmd_id) == (CommandStatus.pending, None)

    bridge._apply_ack(dev_a, {"id": cmd_id, "status": "acked", "detail": "ok"})
    status, completed = _status(cmd_id)
    assert status == CommandStatus.acked and completed is not None

    # A finished command can't be flipped by a later message.
    bridge._apply_ack(dev_a, {"id": cmd_id, "status": "failed"})
    assert _status(cmd_id)[0] == CommandStatus.acked


def test_mqtt_status_ignores_unenrolled_devices(client):
    client.post("/devices", data={"name": "Pending", "platform": "android"},
                follow_redirects=False)
    with db.SessionLocal() as s:
        device_id = s.scalars(select(Device)).one().id
    bridge._apply_status(device_id, {})
    with db.SessionLocal() as s:
        assert s.get(Device, device_id).last_seen is None


# --- (8) telemetry range checks ------------------------------------------------

def test_telemetry_range_checks(client):
    _, auth = _enroll(client, {"location": True})
    post = lambda url, body: client.post(url, json=body, headers=auth).status_code  # noqa: E731
    assert post("/api/telemetry/location", {"lat": 91, "lon": 0}) == 422
    assert post("/api/telemetry/location", {"lat": 0, "lon": -181}) == 422
    assert post("/api/telemetry/location", {"lat": 0, "lon": 0, "accuracy_m": -1}) == 422
    assert post("/api/telemetry/location", {"lat": -90, "lon": 180}) == 200
    assert post("/api/telemetry/checkin", {"battery": 101}) == 422
    assert post("/api/telemetry/checkin", {"battery": -1}) == 422
    assert post("/api/telemetry/checkin", {"battery": 100}) == 200


def test_provisioning_qr_stays_scannable():
    import re

    import segno

    from app import provisioning

    payload = provisioning.provisioning_payload(
        apk_url="https://github.com/adrianoftyriel/svt-mdm-android/releases/latest/download/svt-mdm-latest.apk",
        signature_checksum="Q" * 43,
        server_url="https://mdm.example.com",
        enroll_token="A" * 43,
        enrollment_secret="s" * 24,
    )
    svg = provisioning.qr_svg(payload)
    assert svg.startswith("<?xml") or "<svg" in svg
    compact = __import__("json").dumps(payload, separators=(",", ":"))
    assert segno.make(compact, error="l").version <= 18
    # Quiet zone: viewBox is symbol + 2*4 modules wide.
    modules = segno.make(compact, error="l").symbol_size(scale=1, border=0)[0]
    assert re.search(rf'viewBox="0 0 {modules + 8} {modules + 8}"', svg) or str(modules + 8) in svg
