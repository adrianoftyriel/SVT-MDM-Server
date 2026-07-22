"""Device Owner QR provisioning payloads.

Builds the JSON the Android setup wizard expects and renders it as an SVG QR
code (via segno, pure-Python). Scanning it on a factory-reset phone downloads
the agent APK, verifies its signing certificate, sets it as Device Owner, and
passes enrollment details through the admin extras bundle so the app can
auto-enroll.
"""

from __future__ import annotations

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
        f"{_EXTRA}PROVISIONING_SKIP_ENCRYPTION": False,
        f"{_EXTRA}PROVISIONING_ADMIN_EXTRAS_BUNDLE": {
            "server_url": server_url,
            "enroll_token": enroll_token,
            "enrollment_secret": enrollment_secret,
        },
    }


def qr_svg(payload: dict) -> str:
    """Render a provisioning payload as an inline SVG QR code."""
    qr = segno.make(json.dumps(payload), error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=4, border=2, dark="#0f1419", light="#ffffff")
    return buf.getvalue().decode("utf-8")
