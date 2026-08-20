from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.core.enums import IntentId


@dataclass(frozen=True)
class AgentProfile:
    """一个专职 Agent：只挂一个 Skill（intent_id），以及该 Skill 可用的工具与预算。"""

    agent_id: str
    intent_id: str
    skill_name: str
    tool_names: tuple[str, ...]
    max_tool_calls: int


class AgentRegistry:
    """agent_id / intent_id → AgentProfile。路由点名的是 Agent；一个 Agent 对应一个 Skill。"""

    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self._profiles: dict[str, AgentProfile] = {
            IntentId.SING.value: AgentProfile(
                agent_id="sing",
                intent_id=IntentId.SING.value,
                skill_name="sing",
                tool_names=("SearchSongCatalog", "PlaySong"),
                max_tool_calls=s.tool_calls_max,
            ),
            IntentId.REMINDER.value: AgentProfile(
                agent_id="reminder",
                intent_id=IntentId.REMINDER.value,
                skill_name="reminder",
                tool_names=("ParseDateTool", "FlexibleScheduleReminder"),
                max_tool_calls=s.tool_calls_max_reminder,
            ),
        }

    def profile(self, agent_id: str) -> AgentProfile:
        return self._profiles.get(
            agent_id,
            AgentProfile(
                agent_id=agent_id,
                intent_id=agent_id,
                skill_name=agent_id,
                tool_names=(),
                max_tool_calls=get_settings().tool_calls_max,
            ),
        )

    def known_agents(self) -> tuple[str, ...]:
        return tuple(self._profiles)


# 兼容旧名
SkillProfile = AgentProfile
SkillRegistry = AgentRegistry
