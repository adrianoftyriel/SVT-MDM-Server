"""Test configuration.

Sets the database path (and disables MQTT / enrollment secret) via environment
variables *before* the application package is imported, so ``app.config`` reads
them at import time. A single engine is used throughout; each test gets a fresh
schema.
"""

from __future__ import annotations

import os
import tempfile

_tmp_dir = tempfile.mkdtemp(prefix="mdm-test-")
os.environ["MDM_DB_PATH"] = os.path.join(_tmp_dir, "test.db")
os.environ["MDM_ENROLLMENT_SECRET"] = ""
os.environ.pop("MDM_MQTT_HOST", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client():
    import app.db as db
    import app.main as main
    import app.models  # noqa: F401 - register tables on Base.metadata

    # Fresh schema for each test.
    db.Base.metadata.drop_all(db.engine)
    db.Base.metadata.create_all(db.engine)

    with TestClient(main.app) as c:
        yield c
