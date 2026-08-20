from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.core.config import get_settings


class SafetyService:
    def __init__(self) -> None:
        settings = get_settings()
        path = settings.safety_path
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            data = {}
        self.crisis_terms: list[str] = list(data.get("crisis_terms") or [
            "不想活了", "结束生命", "自杀", "自残", "kill myself",
        ])
        self.fallback = data.get(
            "fallback_reply",
            "我有点担心你现在的状态。你愿意的话，先跟身边信任的人说说，或者打心理援助热线。我会陪着你。",
        )

    def check_input(self, text: str) -> tuple[bool, str | None]:
        lower = text.lower()
        for term in self.crisis_terms:
            if term.lower() in lower or term in text:
                return True, self.fallback
        return False, None
