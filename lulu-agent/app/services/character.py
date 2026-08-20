from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import CharacterProgress
from app.services.identity import SpeakerIdentity


@dataclass
class CharacterResolution:
    card_id: str
    unlocked_ids: list[str]
    metrics: dict[str, int]
    active_policy: str


class CharacterService:
    """角色卡进度：指标累计、解锁判定、active_policy 选卡。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self._catalog = self._load_catalog()

    def _load_catalog(self) -> dict:
        path = self.settings.character_catalog
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {"default_card_id": "default", "active_policy": "user_selected", "cards": []}

    def _cards(self) -> list[dict]:
        return list(self._catalog.get("cards") or [])

    def _card_by_id(self, card_id: str) -> dict | None:
        return next((c for c in self._cards() if c.get("id") == card_id), None)

    def _default_card_id(self) -> str:
        return self._catalog.get("default_card_id") or "default"

    def _active_policy(self) -> str:
        return self._catalog.get("active_policy") or "user_selected"

    def active_policy(self) -> str:
        return self._active_policy()

    def get_or_create_progress(self, person_id: str) -> CharacterProgress:
        row = (
            self.db.query(CharacterProgress)
            .filter(CharacterProgress.person_id == person_id)
            .first()
        )
        if row:
            return row
        row = CharacterProgress(person_id=person_id)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def metrics_for(self, person_id: str) -> dict[str, int]:
        row = self.get_or_create_progress(person_id)
        return {
            "total_turns": row.total_turns,
            "active_days": row.active_days,
            "songs_played": row.songs_played,
            "reminders_set": row.reminders_set,
        }

    def compute_unlocked_ids(self, metrics: dict[str, int]) -> list[str]:
        unlocked: list[str] = []
        for card in self._cards():
            card_id = card.get("id")
            if not card_id:
                continue
            if self._is_unlocked(card, metrics):
                unlocked.append(card_id)
        if not unlocked:
            unlocked.append(self._default_card_id())
        return unlocked

    def _is_unlocked(self, card: dict, metrics: dict[str, int]) -> bool:
        unlock = card.get("unlock")
        if unlock == "always":
            return True
        if not isinstance(unlock, dict):
            return False
        if "require_all" in unlock:
            return all(self._metric_ok(cond, metrics) for cond in unlock["require_all"])
        if "require_any" in unlock:
            return any(self._metric_ok(cond, metrics) for cond in unlock["require_any"])
        return False

    @staticmethod
    def _metric_ok(cond: dict, metrics: dict[str, int]) -> bool:
        metric = cond.get("metric")
        if not metric:
            return False
        value = metrics.get(metric, 0)
        if "gte" in cond:
            return value >= int(cond["gte"])
        if "lte" in cond:
            return value <= int(cond["lte"])
        return False

    def resolve_guest_card_id(self) -> str:
        if self.settings.force_card_id:
            return self.settings.force_card_id
        for card in self._cards():
            if card.get("guest_safe") or card.get("id") == "default":
                return card["id"]
        return self._default_card_id()

    def resolve(self, speaker: SpeakerIdentity) -> CharacterResolution:
        policy = self._active_policy()
        if speaker.is_guest or not speaker.person_id:
            guest_card = self.resolve_guest_card_id()
            return CharacterResolution(
                card_id=guest_card,
                unlocked_ids=[guest_card],
                metrics={},
                active_policy=policy,
            )

        if self.settings.force_card_id:
            metrics = self.metrics_for(speaker.person_id)
            unlocked = self.compute_unlocked_ids(metrics)
            forced = self.settings.force_card_id
            if forced not in unlocked and forced not in {c.get("id") for c in self._cards()}:
                unlocked.append(forced)
            return CharacterResolution(
                card_id=forced,
                unlocked_ids=unlocked,
                metrics=metrics,
                active_policy=policy,
            )

        progress = self.get_or_create_progress(speaker.person_id)
        metrics = self.metrics_for(speaker.person_id)
        unlocked = self.compute_unlocked_ids(metrics)
        card_id = self._pick_active_card(progress, unlocked, policy)
        return CharacterResolution(
            card_id=card_id,
            unlocked_ids=unlocked,
            metrics=metrics,
            active_policy=policy,
        )

    def _pick_active_card(
        self,
        progress: CharacterProgress,
        unlocked_ids: list[str],
        policy: str,
    ) -> str:
        if policy == "highest_unlocked":
            return self._highest_stage_card(unlocked_ids)
        return self._user_selected_card(progress, unlocked_ids)

    def _highest_stage_card(self, unlocked_ids: list[str]) -> str:
        best_id = self._default_card_id()
        best_stage = -1
        for card_id in unlocked_ids:
            card = self._card_by_id(card_id) or {}
            stage = int(card.get("stage", 0))
            if stage > best_stage:
                best_stage = stage
                best_id = card_id
        return best_id

    def _user_selected_card(self, progress: CharacterProgress, unlocked_ids: list[str]) -> str:
        selected = (progress.active_card_id or "").strip()
        if selected and selected in unlocked_ids:
            return selected
        default_id = self._default_card_id()
        if default_id in unlocked_ids:
            return default_id
        return unlocked_ids[0]

    def set_selected_card(self, person_id: str, card_id: str) -> tuple[bool, str]:
        metrics = self.metrics_for(person_id)
        unlocked = self.compute_unlocked_ids(metrics)
        if card_id not in unlocked:
            return False, f"card {card_id!r} not unlocked; unlocked={unlocked}"
        progress = self.get_or_create_progress(person_id)
        progress.active_card_id = card_id
        self.db.commit()
        return True, card_id

    def record_turn(
        self,
        person_id: str,
        *,
        song_played: bool = False,
        reminder_set: bool = False,
    ) -> tuple[list[str], list[str]]:
        """累计本轮指标；返回 (unlocked_ids, new_unlock_ids)。"""
        progress = self.get_or_create_progress(person_id)
        before = self.compute_unlocked_ids(self.metrics_for(person_id))

        progress.total_turns += 1
        today = date.today().isoformat()
        if progress.last_active_date != today:
            progress.active_days += 1
            progress.last_active_date = today
        if song_played:
            progress.songs_played += 1
        if reminder_set:
            progress.reminders_set += 1

        self.db.commit()
        self.db.refresh(progress)

        after_metrics = self.metrics_for(person_id)
        after = self.compute_unlocked_ids(after_metrics)
        new_unlocks = [cid for cid in after if cid not in before]

        policy = self._active_policy()
        if policy == "highest_unlocked" and new_unlocks:
            progress.active_card_id = self._highest_stage_card(after)
            self.db.commit()

        return after, new_unlocks

    def card_prompt_path(self, card_id: str) -> Path:
        card = self._card_by_id(card_id)
        rel = (card or {}).get("prompt") or "cards/default.md"
        return self.settings.character_catalog.parent / rel
