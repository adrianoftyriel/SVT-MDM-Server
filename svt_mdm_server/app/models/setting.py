"""A tiny key/value store for server-wide operator settings.

Most configuration comes from the add-on options (env vars, see
``app.config``). A few things, though, must be changeable at runtime from the
dashboard and persisted across restarts — the selected interface theme being
the first. Those live here, one row per key.
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
