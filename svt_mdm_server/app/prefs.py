"""Read/write persisted operator settings (see ``app.models.setting``).

Thin helpers over the key/value ``settings`` table. The only setting today is
the active interface theme.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Setting
from app.themes import DEFAULT_THEME_ID, THEMES

THEME_KEY = "active_theme"


def get_active_theme_id(session: Session) -> str:
    """The selected theme id, or the default when unset/unknown."""
    row = session.get(Setting, THEME_KEY)
    if row and row.value in THEMES:
        return row.value
    return DEFAULT_THEME_ID


def set_active_theme_id(session: Session, theme_id: str) -> None:
    """Persist the selected theme. Unknown ids fall back to the default."""
    if theme_id not in THEMES:
        theme_id = DEFAULT_THEME_ID
    row = session.get(Setting, THEME_KEY)
    if row is None:
        session.add(Setting(key=THEME_KEY, value=theme_id))
    else:
        row.value = theme_id
    session.commit()
