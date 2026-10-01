"""Device Owner QR provisioning payloads.

Builds the JSON the Android setup wizard expects and renders it as an SVG QR
code (via segno, pure-Python). Scanning it on a factory-reset phone downloads
the agent APK, verifies its signing certificate, sets it as Device Owner, and
passes enrollment details through the admin extras bundle so the app can
auto-enroll.
"""

from __future__ import annotations

import base64
import io
import json

import segno

# package/fully-qualified-receiver-class
ADMIN_COMPONENT = "org.svt.mdm/org.svt.mdm.admin.MdmDeviceAdminReceiver"
_EXTRA = "android.app.extra."


def provisioning_payload(
    apk_url: str,
    signature_checksum: str,
    server_url: str,
    enroll_token: str,
    enrollment_secret: str,
) -> dict:
    return {
        f"{_EXTRA}PROVISIONING_DEVICE_ADMIN_COMPONENT_NAME": ADMIN_COMPONENT,
        f"{_EXTRA}PROVISIONING_DEVICE_ADMIN_PACKAGE_DOWNLOAD_LOCATION": apk_url,
        f"{_EXTRA}PROVISIONING_DEVICE_ADMIN_SIGNATURE_CHECKSUM": signature_checksum,
        f"{_EXTRA}PROVISIONING_ADMIN_EXTRAS_BUNDLE": {
            "server_url": server_url,
            "enroll_token": enroll_token,
            "enrollment_secret": enrollment_secret,
        },
    }


def payload_json(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"))


def qr_svg(payload: dict) -> str:
    """Render a provisioning payload as an inline SVG QR code."""
    # Keep the code as sparse as possible: the setup wizard's camera is low-res.
    qr = segno.make(payload_json(payload), error="l")
    buf = io.BytesIO()
    # border=4 is the quiet zone the QR spec requires; scanners often fail below it.
    qr.save(buf, kind="svg", scale=4, border=4, dark="#000000", light="#ffffff")
    return buf.getvalue().decode("utf-8")


def qr_png_data_uri(payload: dict) -> str:
    """Large raster QR with whole-pixel modules.

    The dashboard scales the image down smoothly; a vector QR scaled to a
    fractional pixels-per-module gave uneven modules the Pixel camera ignored.
    """
    qr = segno.make(payload_json(payload), error="l")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=10, border=4, dark="#000000", light="#ffffff")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
