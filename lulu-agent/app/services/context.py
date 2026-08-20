from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.memory.compaction_ledger import commit_compaction, recover_orphan_prepares
from app.memory.token_budget import (
    KEEP_RECENT_TOKENS,
    estimate_context_tokens,
    estimate_message_tokens,
    hard_input_limit,
    soft_input_limit,
    split_keep_recent_by_tokens,
)
from app.models.entities import ChatMessage, ChatSession
from app.services.ai import AIService

logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    summary: str
    recent: list[dict[str, str]]

    def prompt_messages(self, *, limit: int | None = None) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if self.summary.strip():
            out.append({"role": "system", "content": f"本轮之前聊过：{self.summary.strip()}"})
        recent = self.recent
        if limit is not None:
            recent = recent[-limit:]
        out.extend(recent)
        return out


class ContextService:
    """会话工作记忆：Akashic token Gate + session_compactions ledger。

    压缩出的批次交给 consolidate → PENDING/memory2。
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.ai = AIService()

    def load(self, session: ChatSession) -> ConversationContext:
        rows = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.public_id)
            .order_by(ChatMessage.id.asc())
            .all()
        )
        start = max(0, int(session.summary_message_count or 0))
        live = rows[start:]
        recent = [{"role": r.role, "content": r.content} for r in live]
        return ConversationContext(summary=session.summary or "", recent=recent)

    def maybe_compress(
        self,
        session: ChatSession,
        *,
        system_overhead: str = "",
        force: bool = False,
    ) -> list[dict[str, str]] | None:
        """按 soft/hard 边界压缩；写 ledger generation；返回归档批次。"""
        rows = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.public_id)
            .order_by(ChatMessage.id.asc())
            .all()
        )
        if not rows:
            return None

        cw = int(self.settings.akashic_context_window)
        if cw <= 0:
            return None

        soft = soft_input_limit(cw)
        max_out = int(self.settings.context_max_output_tokens)
        hard = hard_input_limit(cw, max_out)
        keep_recent = int(self.settings.context_keep_recent_tokens or KEEP_RECENT_TOKENS)

        recover_orphan_prepares(self.db, session.public_id)

        start = max(0, int(session.summary_message_count or 0))
        live_rows = rows[start:]
        if not live_rows:
            return None

        summary = session.summary or ""
        payload: list[dict[str, str]] = []
        if summary.strip():
            payload.append({"role": "system", "content": f"本轮之前聊过：{summary.strip()}"})
        payload.extend({"role": r.role, "content": r.content} for r in live_rows)

        estimated = estimate_context_tokens(payload, system_prompt=system_overhead)
        boundary = estimated >= soft or estimated >= hard
        if not force and not boundary:
            return None

        live_msgs = [
            {"role": r.role, "content": r.content, "id": str(r.id)} for r in live_rows
        ]
        to_compact, retained = split_keep_recent_by_tokens(
            live_msgs, keep_recent_tokens=keep_recent
        )
        if not to_compact:
            logger.warning(
                "context_compaction insufficient session=%s estimated=%d soft=%d hard=%d",
                session.public_id,
                estimated,
                soft,
                hard,
            )
            return None

        batch_rows = live_rows[: len(to_compact)]
        new_summary = self._compress(summary, batch_rows)
        through_seq = start + len(to_compact)
        trigger = "force" if force else ("hard" if estimated >= hard else "soft_limit")

        after_msgs: list[dict[str, str]] = []
        if new_summary.strip():
            after_msgs.append(
                {"role": "system", "content": f"本轮之前聊过：{new_summary.strip()}"}
            )
        after_msgs.extend(
            {"role": r.role, "content": r.content} for r in rows[through_seq:]
        )
        after = estimate_context_tokens(after_msgs, system_prompt=system_overhead)

        source_messages = [
            {"role": r.role, "content": r.content, "id": str(r.id)} for r in batch_rows
        ]
        retained_tail = [
            {"role": m.get("role"), "content": m.get("content"), "id": m.get("id")}
            for m in retained
        ]

        commit_compaction(
            self.db,
            session=session,
            trigger=trigger,
            summary=new_summary,
            source_from_seq=start + 1,  # 1-based message position in session history
            consolidated_through_seq=through_seq,
            source_messages=source_messages,
            retained_tail=retained_tail,
            model=self.settings.ark_chat_model,
            context_window=cw,
            threshold_tokens=soft,
            hard_input_tokens=hard,
            keep_recent_tokens=keep_recent,
            tokens_before=estimated,
            tokens_after=after,
            summary_usage={"summary_chars": len(new_summary)},
        )

        return [{"role": m.role, "content": m.content} for m in batch_rows]

    def estimate_live_tokens(
        self,
        session: ChatSession,
        *,
        system_overhead: str = "",
    ) -> int:
        rows = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.public_id)
            .order_by(ChatMessage.id.asc())
            .all()
        )
        start = max(0, int(session.summary_message_count or 0))
        payload: list[dict[str, str]] = []
        if (session.summary or "").strip():
            payload.append(
                {"role": "system", "content": f"本轮之前聊过：{(session.summary or '').strip()}"}
            )
        payload.extend({"role": r.role, "content": r.content} for r in rows[start:])
        return estimate_context_tokens(payload, system_prompt=system_overhead)

    def _compress(self, existing: str, batch: list[ChatMessage]) -> str:
        lines = []
        for msg in batch:
            role = "用户" if msg.role == "user" else "LuLu"
            lines.append(f"{role}：{msg.content}")
        transcript = "\n".join(lines)
        max_chars = max(2000, soft_input_limit(self.settings.akashic_context_window) * 2)
        if len(transcript) > max_chars:
            transcript = transcript[:max_chars] + "\n…(截断)"
        prompt = [
            {
                "role": "system",
                "content": (
                    "把对话压缩成连贯中文摘要，保留人名、时间、情绪、待办、歌名等关键信息。"
                    "不要列表，不要 JSON。若已有摘要，合并更新而非重复。"
                ),
            },
            {
                "role": "user",
                "content": f"已有摘要：{existing or '（无）'}\n\n新增对话：\n{transcript}",
            },
        ]
        try:
            max_tokens = min(800, max(180, estimate_message_tokens(prompt) // 20))
            text = self.ai.chat(prompt, temperature=0.2, max_tokens=max_tokens)["content"].strip()
            return text or existing
        except Exception:
            fallback = existing or ""
            snippet = transcript[:200]
            return (fallback + " " + snippet).strip() if snippet else fallback
