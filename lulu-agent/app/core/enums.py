from __future__ import annotations

from enum import Enum


class IntentId(str, Enum):
    CHAT = "chat"
    SING = "sing"
    REMINDER = "reminder"


class RouteKind(str, Enum):
    CHAT = "chat"
    AGENTS = "agents"


class DraftState(str, Enum):
    USED = "used"
    DISCARDED = "discarded"
    SKIPPED = "skipped"
    FAILED = "failed"


class ConfidenceBand(str, Enum):
    HIGH = "high"
    LOW = "low"
    GUEST = "guest"
