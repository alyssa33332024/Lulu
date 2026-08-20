from __future__ import annotations

"""认人：称呼 / 默认主人 / speaker intro。

身份字段仍落在 memory_items 表（历史表名）；长期记忆走 app.memory。
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import ConfidenceBand
from app.models.entities import MemoryItem

DISPLAY_NAME_KEY = "relation.display_name"
PROFILE_BRIEF_KEY = "fact.profile_brief"
_NAME_KEYS = frozenset({DISPLAY_NAME_KEY, "relation.nickname", "fact.name"})

DEFAULT_OWNER_PERSON_ID = "dev_self"
DEFAULT_OWNER_DISPLAY_NAME = "主人"
_DEFAULT_OWNER_BRIEF = "家里的主要用户；未声纹认人前对话记忆先挂在此。"


@dataclass
class SpeakerIdentity:
    person_id: str | None
    display_name: str | None
    band: ConfidenceBand
    is_guest: bool


class IdentityService:
    """认人：有 person_id（日后声纹）用对应称呼；否则挂到默认「主人」。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def resolve(self, person_id: str | None = None) -> SpeakerIdentity:
        if person_id and self.person_exists(person_id):
            return SpeakerIdentity(
                person_id=person_id,
                display_name=self.resolve_display_name(person_id),
                band=ConfidenceBand.HIGH,
                is_guest=False,
            )

        if self.settings.sole_member_fallback:
            pid = self.ensure_default_owner()
            return SpeakerIdentity(
                person_id=pid,
                display_name=self.resolve_display_name(pid),
                band=ConfidenceBand.HIGH,
                is_guest=False,
            )

        return SpeakerIdentity(
            person_id=None,
            display_name=None,
            band=ConfidenceBand.GUEST,
            is_guest=True,
        )

    def get_display_name(self, person_id: str) -> str | None:
        for key in (DISPLAY_NAME_KEY, "relation.nickname", "fact.name"):
            row = (
                self.db.query(MemoryItem)
                .filter(
                    MemoryItem.person_id == person_id,
                    MemoryItem.key == key,
                    MemoryItem.layer == "L3",
                    MemoryItem.negated.is_(False),
                )
                .first()
            )
            if row:
                name = (row.value or row.content).strip()
                if name:
                    return name
        return None

    def resolve_display_name(self, person_id: str) -> str | None:
        name = self.get_display_name(person_id)
        if name:
            return name
        if self.settings.memory_backend == "akashic":
            try:
                from app.memory.facade import AkashicMemoryFacade

                return AkashicMemoryFacade().guess_display_name(person_id)
            except Exception:
                return None
        return None

    def person_exists(self, person_id: str) -> bool:
        return self.get_display_name(person_id) is not None

    def ensure_default_owner(self) -> str:
        """保证默认「主人」存在；无声纹时未指名对话挂在此人上。"""
        pid = DEFAULT_OWNER_PERSON_ID
        if not self.person_exists(pid):
            self.set_display_name(pid, DEFAULT_OWNER_DISPLAY_NAME)
            self.set_profile_brief(pid, _DEFAULT_OWNER_BRIEF)
        return pid

    def set_display_name(self, person_id: str, name: str, *, pinned: bool = True) -> MemoryItem:
        name = (name or "").strip() or "对方"
        return self._upsert_identity(
            person_id,
            key=DISPLAY_NAME_KEY,
            value=name,
            content=f"叫{name}",
            pinned=pinned,
        )

    def set_profile_brief(self, person_id: str, brief: str, *, pinned: bool = True) -> MemoryItem:
        return self._upsert_identity(
            person_id,
            key=PROFILE_BRIEF_KEY,
            value="",
            content=(brief or "").strip(),
            pinned=pinned,
        )

    def _upsert_identity(
        self,
        person_id: str,
        *,
        key: str,
        value: str,
        content: str,
        pinned: bool,
    ) -> MemoryItem:
        if key in _NAME_KEYS:
            key = DISPLAY_NAME_KEY
        now = datetime.utcnow()
        existing = (
            self.db.query(MemoryItem)
            .filter(MemoryItem.person_id == person_id, MemoryItem.key == key)
            .first()
        )
        if existing:
            existing.layer = "L3"
            existing.value = value
            existing.content = content
            existing.confidence = 1.0
            existing.updated_at = now
            existing.negated = False
            existing.expires_at = None
            existing.pinned = pinned or existing.pinned
            row = existing
        else:
            row = MemoryItem(
                person_id=person_id,
                layer="L3",
                key=key,
                value=value,
                content=content,
                confidence=1.0,
                created_at=now,
                updated_at=now,
                expires_at=None,
                pinned=pinned,
            )
            self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def intro_line(self, speaker: SpeakerIdentity) -> str:
        if speaker.is_guest:
            return self._guest_block()
        return self._member_intro(speaker.display_name)

    def _member_intro(self, display_name: str | None) -> str:
        template_path = self.settings.speaker_template
        template = (
            template_path.read_text(encoding="utf-8")
            if template_path.exists()
            else "你现在在和{{ display_name }}说话。"
        )
        return template.replace("{{ display_name }}", display_name or "对方").strip()

    def _guest_block(self) -> str:
        path = self.settings.speaker_guest_template
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return "你现在在和一个还不认识的人说话。可以友好聊天，但不要提这家人的任何私事。"
