"""Theme selection: dashboard picker, persistence, and agent distribution."""

from __future__ import annotations

from sqlalchemy import select


def _enroll(client) -> str:
    """Create + enroll a device; return its long-lived device token."""
    import app.db as db
    from app.models import Device

    client.post(
        "/devices",
        data={"name": "Test Phone", "platform": "android"},
        follow_redirects=False,
    )
    with db.SessionLocal() as session:
        enroll_token = session.scalar(select(Device)).enroll_token
    resp = client.post(
        "/api/enroll",
        json={"enroll_token": enroll_token, "capabilities": {"location": True}},
    )
    return resp.json()["device_token"]


def test_default_theme_is_midnight(client):
    token = _enroll(client)
    auth = {"Authorization": f"Bearer {token}"}

    theme = client.get("/api/theme", headers=auth).json()
    assert theme["id"] == "midnight"
    assert theme["dark"] is True
    assert set(theme["colors"]) >= {"bg", "accent", "accent_text", "danger"}

    # Check-in echoes the active theme id.
    checkin = client.post("/api/telemetry/checkin", json={}, headers=auth).json()
    assert checkin["theme"] == "midnight"


def test_operator_can_select_theme_and_it_propagates(client):
    token = _enroll(client)
    auth = {"Authorization": f"Bearer {token}"}

    # Operator picks LCARS on the dashboard.
    resp = client.post(
        "/settings/theme", data={"theme": "lcars"}, follow_redirects=False
    )
    assert resp.status_code == 303

    # Dashboard now renders with the LCARS theme.
    page = client.get("/settings")
    assert page.status_code == 200
    assert 'data-theme="lcars"' in page.text
    assert "theme-lcars" in page.text

    # The agent sees the new theme, with full colour tokens.
    theme = client.get("/api/theme", headers=auth).json()
    assert theme["id"] == "lcars"
    assert theme["font"] == "condensed"
    assert theme["colors"]["accent"] == "#ff9900"

    # And it is echoed on check-in.
    checkin = client.post("/api/telemetry/checkin", json={}, headers=auth).json()
    assert checkin["theme"] == "lcars"


def test_unknown_theme_falls_back_to_default(client):
    _enroll(client)
    client.post("/settings/theme", data={"theme": "does-not-exist"})
    page = client.get("/settings")
    assert 'data-theme="midnight"' in page.text


def test_theme_endpoint_requires_auth(client):
    assert client.get("/api/theme").status_code == 401


def test_stylesheet_is_cache_busted(client):
    """The app.css link carries a ?v= token so a redeploy can't be masked by a
    stale cached stylesheet (which would hide theme changes)."""
    import re

    page = client.get("/settings")
    assert re.search(r"app\.css\?v=\d+", page.text)
