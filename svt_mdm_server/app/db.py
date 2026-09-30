"""Database engine, session management, and schema creation.

SQLite via SQLAlchemy 2.0. For a personal MDM the write volume is tiny, so a
single file database on the add-on's persistent volume is the right amount of
machinery. If the deployment ever outgrows it, swapping ``db_url`` for Postgres
is the only change needed here.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# check_same_thread=False: FastAPI serves requests from a threadpool, and the
# MQTT bridge runs on the event loop; both may touch the session factory.
engine = create_engine(
    settings.db_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    # SQLite ignores FOREIGN KEY / ON DELETE CASCADE unless this is set per
    # connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create the SQLite file (and its parent dir) and all tables."""
    db_dir = os.path.dirname(settings.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # Import models so they register on Base.metadata before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
