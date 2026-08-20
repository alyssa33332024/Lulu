"""Session compaction ledger — Akashic session_compactions / prepares 对齐实现。"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import (
    ChatSession,
    SessionCompaction,
    SessionCompactionPrepare,
)

logger = logging.getLogger(__name__)

SUMMARY_FORMAT_VERSION = 1


@dataclass(frozen=True)
class CompactionHead:
    session_key: str
    parent_generation: int
    next_generation: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_source_plan_digest(messages: list[dict[str, Any]]) -> str:
    """SHA-256 of canonical source plan（64 位小写 hex）。"""
    plan = [
        {
            "role": str(m.get("role") or ""),
            "content": str(m.get("content") or ""),
            "id": str(m.get("id") or ""),
        }
        for m in messages
    ]
    raw = json.dumps(plan, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_compaction_head(db: Session, session_key: str) -> CompactionHead:
    active = (
        db.query(SessionCompaction)
        .filter(
            SessionCompaction.session_key == session_key,
            SessionCompaction.invalidated_at.is_(None),
        )
        .order_by(SessionCompaction.generation.desc())
        .first()
    )
    parent = int(active.generation) if active else 0
    return CompactionHead(
        session_key=session_key,
        parent_generation=parent,
        next_generation=parent + 1,
    )


def get_active_compaction(db: Session, session_key: str) -> SessionCompaction | None:
    return (
        db.query(SessionCompaction)
        .filter(
            SessionCompaction.session_key == session_key,
            SessionCompaction.invalidated_at.is_(None),
        )
        .order_by(SessionCompaction.generation.desc())
        .first()
    )


def list_compactions(db: Session, session_key: str) -> list[SessionCompaction]:
    return (
        db.query(SessionCompaction)
        .filter(SessionCompaction.session_key == session_key)
        .order_by(SessionCompaction.generation.asc())
        .all()
    )


def recover_orphan_prepares(db: Session, session_key: str) -> int:
    """启动/压缩前：清掉未提交的 prepare fence。"""
    rows = (
        db.query(SessionCompactionPrepare)
        .filter(SessionCompactionPrepare.session_key == session_key)
        .all()
    )
    n = len(rows)
    for row in rows:
        db.delete(row)
    if n:
        db.commit()
        logger.info(
            "session_compaction recover session=%s release_orphan_prepare count=%d",
            session_key,
            n,
        )
    return n


def commit_compaction(
    db: Session,
    *,
    session: ChatSession,
    trigger: str,
    summary: str,
    source_from_seq: int,
    consolidated_through_seq: int,
    source_messages: list[dict[str, Any]],
    retained_tail: list[dict[str, Any]],
    model: str,
    context_window: int,
    threshold_tokens: int,
    hard_input_tokens: int,
    keep_recent_tokens: int,
    tokens_before: int,
    tokens_after: int,
    summary_usage: dict[str, Any] | None = None,
) -> SessionCompaction:
    """prepare → ledger INSERT → 推进 session 游标（同一事务）。"""
    session_key = session.public_id
    recover_orphan_prepares(db, session_key)
    head = get_compaction_head(db, session_key)
    generation = head.next_generation
    parent = head.parent_generation
    source_ids = [str(m.get("id") or "") for m in source_messages]
    digest = canonical_source_plan_digest(source_messages)
    source_ref = f"lulu:{session_key}:g{generation}"
    now = _utc_now()
    created_at = (
        session.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        if session.created_at
        else now
    )
    ids_json = json.dumps(source_ids, ensure_ascii=False)
    tail_json = json.dumps(retained_tail, ensure_ascii=False)
    usage_json = json.dumps(summary_usage or {}, ensure_ascii=False)

    prepare = SessionCompactionPrepare(
        session_key=session_key,
        session_created_at=created_at,
        generation=generation,
        parent_generation=parent,
        source_ref=source_ref,
        source_from_seq=source_from_seq,
        consolidated_through_seq=consolidated_through_seq,
        source_message_ids_json=ids_json,
        retained_tail_json=tail_json,
        prepared_at=now,
    )
    db.add(prepare)
    db.flush()

    row = SessionCompaction(
        session_key=session_key,
        generation=generation,
        parent_generation=parent,
        created_at=now,
        trigger=trigger,
        summary_format_version=SUMMARY_FORMAT_VERSION,
        summary=summary,
        source_ref=source_ref,
        source_plan_digest=digest,
        source_from_seq=source_from_seq,
        consolidated_through_seq=consolidated_through_seq,
        source_message_ids_json=ids_json,
        retained_tail_json=tail_json,
        model_runtime_id="lulu",
        model=model or "",
        context_window=int(context_window),
        threshold_tokens=int(threshold_tokens),
        hard_input_tokens=int(hard_input_tokens),
        keep_recent_tokens=int(keep_recent_tokens),
        tokens_before=int(tokens_before),
        tokens_after=int(tokens_after),
        summary_usage_json=usage_json,
    )
    db.add(row)

    session.summary = summary
    session.summary_message_count = int(consolidated_through_seq)
    session.last_compaction_generation = generation

    db.query(SessionCompactionPrepare).filter(
        SessionCompactionPrepare.session_key == session_key,
        SessionCompactionPrepare.generation == generation,
    ).delete()
    db.commit()
    db.refresh(row)

    logger.info(
        "session_compaction commit session=%s generation=%d parent=%d "
        "trigger=%s before=%d after=%d through_seq=%d digest=%s",
        session_key,
        generation,
        parent,
        trigger,
        tokens_before,
        tokens_after,
        consolidated_through_seq,
        digest[:12],
    )
    return row


def invalidate_from_generation(
    db: Session,
    session_key: str,
    generation: int,
    *,
    reason: str,
) -> int:
    """逻辑失效 generation 及其后代；游标回退到最近有效 ancestor。"""
    rows = (
        db.query(SessionCompaction)
        .filter(
            SessionCompaction.session_key == session_key,
            SessionCompaction.generation >= generation,
            SessionCompaction.invalidated_at.is_(None),
        )
        .all()
    )
    now = _utc_now()
    for row in rows:
        row.invalidated_at = now
        row.invalidated_reason = reason
    active = get_active_compaction(db, session_key)
    session = (
        db.query(ChatSession).filter(ChatSession.public_id == session_key).first()
    )
    if session is not None:
        if active:
            session.summary = active.summary
            session.summary_message_count = active.consolidated_through_seq
            session.last_compaction_generation = active.generation
        else:
            session.summary = ""
            session.summary_message_count = 0
            session.last_compaction_generation = 0
    db.commit()
    return len(rows)
