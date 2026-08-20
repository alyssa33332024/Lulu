from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128), default="LuLu")
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_message_count: Mapped[int] = mapped_column(Integer, default=0)
    # 当前有效 compaction generation（对齐 Akashic sessions.last_consolidated）
    last_compaction_generation: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SessionCompaction(Base):
    """不可变会话压缩账本一代（对齐 Akashic session_compactions）。"""

    __tablename__ = "session_compactions"
    __table_args__ = (
        UniqueConstraint("session_key", "generation", name="uq_session_compaction_gen"),
        UniqueConstraint("session_key", "source_ref", name="uq_session_compaction_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String(64), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    parent_generation: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32))
    trigger: Mapped[str] = mapped_column(String(32))
    summary_format_version: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(Text, default="")
    source_ref: Mapped[str] = mapped_column(String(128))
    source_plan_digest: Mapped[str] = mapped_column(String(64))
    source_from_seq: Mapped[int] = mapped_column(Integer)
    consolidated_through_seq: Mapped[int] = mapped_column(Integer)
    source_message_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    retained_tail_json: Mapped[str] = mapped_column(Text, default="[]")
    model_runtime_id: Mapped[str] = mapped_column(String(64), default="lulu")
    model: Mapped[str] = mapped_column(String(128), default="")
    context_window: Mapped[int] = mapped_column(Integer, default=0)
    threshold_tokens: Mapped[int] = mapped_column(Integer, default=0)
    hard_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    keep_recent_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tokens_before: Mapped[int] = mapped_column(Integer, default=0)
    tokens_after: Mapped[int] = mapped_column(Integer, default=0)
    summary_usage_json: Mapped[str] = mapped_column(Text, default="{}")
    invalidated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    invalidated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SessionCompactionPrepare(Base):
    """压缩提交前的 durable prepare fence（对齐 Akashic session_compaction_prepares）。"""

    __tablename__ = "session_compaction_prepares"
    __table_args__ = (
        UniqueConstraint("session_key", "generation", name="uq_session_compaction_prepare_gen"),
        UniqueConstraint("session_key", "source_ref", name="uq_session_compaction_prepare_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String(64), index=True)
    session_created_at: Mapped[str] = mapped_column(String(32), default="")
    generation: Mapped[int] = mapped_column(Integer)
    parent_generation: Mapped[int] = mapped_column(Integer, default=0)
    source_ref: Mapped[str] = mapped_column(String(128))
    source_from_seq: Mapped[int] = mapped_column(Integer)
    consolidated_through_seq: Mapped[int] = mapped_column(Integer)
    source_message_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    retained_tail_json: Mapped[str] = mapped_column(Text, default="[]")
    prepared_at: Mapped[str] = mapped_column(String(32))


class ReminderItem(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text)
    date_str: Mapped[str] = mapped_column(String(16))
    time_str: Mapped[str] = mapped_column(String(8))
    r_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MemoryItem(Base):
    __tablename__ = "memory_items"
    __table_args__ = (UniqueConstraint("person_id", "key", name="uq_memory_person_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(String(64), index=True)
    layer: Mapped[str] = mapped_column(String(8))  # L2 | L3
    key: Mapped[str] = mapped_column(String(128), default="")
    value: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text)
    text_for_embed: Mapped[str] = mapped_column(Text, default="")
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    source_turn_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    event_date: Mapped[str | None] = mapped_column(String(16), nullable=True)  # YYYY-MM-DD
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    negated: Mapped[bool] = mapped_column(Boolean, default=False)


class CharacterProgress(Base):
    __tablename__ = "character_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    total_turns: Mapped[int] = mapped_column(Integer, default=0)
    active_days: Mapped[int] = mapped_column(Integer, default=0)
    songs_played: Mapped[int] = mapped_column(Integer, default=0)
    reminders_set: Mapped[int] = mapped_column(Integer, default=0)
    active_card_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_active_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TraceRow(Base):
    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    turn_id: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
