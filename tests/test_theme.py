"""Theme selection: dashboard picker, persistence, and agent distribution."""

from __future__ import annotations

import re

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


def test_topbar_switcher_lists_every_theme_and_marks_the_active_one(client):
    from app.themes import all_themes

    page = client.get("/settings")
    assert 'id="theme-switch"' in page.text
    for theme in all_themes():
        assert f'value="{theme.id}"' in page.text
    # Midnight is active by default, so its option carries `selected`.
    assert '<option value="midnight" selected>' in page.text


def test_switcher_returns_to_the_page_it_was_used_on(client):
    """The topbar posts a `next` path so the operator stays put."""
    resp = client.post(
        "/settings/theme",
        data={"theme": "sprout", "next": "/devices"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/devices"


def test_switcher_rejects_offsite_redirects(client):
    """`next` must not become an open redirect."""
    for hostile in ("https://evil.example/x", "//evil.example", "/\\evil.example"):
        resp = client.post(
            "/settings/theme",
            data={"theme": "sprout", "next": hostile},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "evil.example" not in resp.headers["location"]
        assert resp.headers["location"].endswith("/settings")


def test_mdm_inspired_themes_are_available(client):
    """The three console-inspired themes resolve and carry full token sets."""
    token = _enroll(client)
    auth = {"Authorization": f"Bearer {token}"}

    for theme_id, accent, dark in (
        ("blueprint", "#2563eb", False),
        ("plainsight", "#4f46e5", False),
        ("sprout", "#3ddc84", True),
    ):
        client.post("/settings/theme", data={"theme": theme_id})
        payload = client.get("/api/theme", headers=auth).json()
        assert payload["id"] == theme_id
        assert payload["colors"]["accent"] == accent
        assert payload["dark"] is dark
        assert set(payload["colors"]) >= {
            "bg", "panel", "panel2", "text", "muted",
            "accent", "accent_text", "ok", "warn", "danger", "border",
        }


def test_stylesheet_loads_under_home_assistant_ingress(client):
    """Regression: the dashboard rendered as unstyled HTML under HA ingress.

    HA forwards ingress requests with the prefix already STRIPPED and passes the
    prefix in X-Ingress-Path. Setting scope["root_path"] from that header made
    Starlette strip a prefix that wasn't in the path, so the StaticFiles mount
    resolved the wrong filename and 404'd app.css. HTML routes still worked,
    which is why only the styling disappeared.
    """
    ingress = "/api/hassio_ingress/TOKEN123"
    headers = {"X-Ingress-Path": ingress}

    page = client.get("/", headers=headers)
    assert page.status_code == 200

    # Links must be built under the ingress prefix for the browser to resolve.
    href = re.search(r'href="([^"]*app\.css[^"]*)"', page.text).group(1)
    assert href.startswith(f"{ingress}/static/app.css")

    # ...and the asset must be served when HA forwards it with the prefix gone.
    css = client.get("/static/app.css", headers=headers)
    assert css.status_code == 200, "app.css must load under ingress"
    assert "text/css" in css.headers["content-type"]
    # The stylesheet must consume the injected theme variables.
    assert "var(--bg)" in css.text


def test_theme_switcher_returns_under_ingress_prefix(client):
    """The switcher's `next` must carry the ingress prefix, and be accepted."""
    ingress = "/api/hassio_ingress/TOKEN123"
    headers = {"X-Ingress-Path": ingress}

    page = client.get("/settings", headers=headers)
    assert f'value="{ingress}/settings"' in page.text

    resp = client.post(
        "/settings/theme",
        data={"theme": "sprout", "next": f"{ingress}/devices"},
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"{ingress}/devices"

    # A path outside the ingress prefix is still refused.
    resp = client.post(
        "/settings/theme",
        data={"theme": "sprout", "next": "/somewhere-else"},
        headers=headers,
        follow_redirects=False,
    )
    assert resp.headers["location"] != "/somewhere-else"


def test_font_stack_is_not_html_escaped(client):
    """Regression: autoescaping turned the quotes in font stacks into &#39;,
    which invalidates --font and drops the page to the default serif face."""
    page = client.get("/settings")
    assert "&#39;" not in page.text and "&amp;#39;" not in page.text
    assert "'Segoe UI'" in page.text
    # A quoted family in a non-default theme's preview swatch too.
    client.post("/settings/theme", data={"theme": "lcars"})
    assert "'Antonio'" in client.get("/settings").text


def test_stylesheet_is_cache_busted(client):
    """The app.css link carries a ?v= token so a redeploy can't be masked by a
    stale cached stylesheet (which would hide theme changes)."""
    import re

    page = client.get("/settings")
    assert re.search(r"app\.css\?v=\d+", page.text)
