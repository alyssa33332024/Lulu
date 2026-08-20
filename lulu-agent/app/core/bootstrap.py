from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.models import entities as _entities  # noqa: F401
from app.models.entities import MemoryItem
from app.services.identity import (
    DEFAULT_OWNER_PERSON_ID,
    PROFILE_BRIEF_KEY,
    IdentityService,
)


def _sqlite_add_column(table: str, column: str, ddl: str) -> None:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column in cols:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def migrate_db() -> None:
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        return

    _sqlite_add_column("chat_sessions", "summary", "TEXT DEFAULT ''")
    _sqlite_add_column("chat_sessions", "summary_message_count", "INTEGER DEFAULT 0")
    _sqlite_add_column("chat_sessions", "last_compaction_generation", "INTEGER DEFAULT 0")

    memory_cols = [
        ("value", "TEXT DEFAULT ''"),
        ("text_for_embed", "TEXT DEFAULT ''"),
        ("importance", "REAL DEFAULT 0.5"),
        ("confidence", "REAL DEFAULT 0.8"),
        ("source_turn_id", "TEXT DEFAULT ''"),
        ("created_at", "DATETIME"),
        ("updated_at", "DATETIME"),
        ("expires_at", "DATETIME"),
        ("event_date", "TEXT"),
        ("last_accessed_at", "DATETIME"),
        ("pinned", "BOOLEAN DEFAULT 0"),
    ]
    for col, ddl in memory_cols:
        _sqlite_add_column("memory_items", col, ddl)


def _migrate_family_members(db) -> None:
    """一次性：旧 family_members 行迁入身份字段。"""
    insp = inspect(engine)
    if "family_members" not in insp.get_table_names():
        return

    identity = IdentityService(db)
    rows = db.execute(
        text("SELECT person_id, display_name, profile_brief, enabled FROM family_members")
    ).fetchall()
    for person_id, display_name, profile_brief, enabled in rows:
        if not enabled:
            continue
        if not identity.person_exists(person_id):
            identity.set_display_name(person_id, display_name or "对方")
        if profile_brief and profile_brief.strip():
            existing = (
                db.query(MemoryItem)
                .filter(
                    MemoryItem.person_id == person_id,
                    MemoryItem.key == PROFILE_BRIEF_KEY,
                )
                .first()
            )
            if not existing:
                row = identity.set_profile_brief(person_id, profile_brief.strip())
                row.pinned = True
                db.commit()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_db()
    db = SessionLocal()
    try:
        _migrate_family_members(db)
        identity = IdentityService(db)
        identity.ensure_default_owner()
        if not (
            db.query(MemoryItem)
            .filter(
                MemoryItem.person_id == DEFAULT_OWNER_PERSON_ID,
                MemoryItem.key == PROFILE_BRIEF_KEY,
                MemoryItem.negated.is_(False),
            )
            .first()
        ):
            row = identity.set_profile_brief(
                DEFAULT_OWNER_PERSON_ID,
                "家里的主要用户；未声纹认人前对话记忆先挂在此。",
            )
            row.pinned = True
            db.commit()
        try:
            from app.memory.workspace import ensure_person_workspace

            ensure_person_workspace(DEFAULT_OWNER_PERSON_ID)
        except Exception:
            pass
    finally:
        db.close()
