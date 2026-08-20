from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCallLog:
    name: str
    arguments: str | dict
    result: str

    def as_dict(self) -> dict:
        return {"name": self.name, "arguments": self.arguments, "result": self.result}


@dataclass
class AgentRunResult:
    """单个 Agent（一个 Skill）跑完一轮的返回契约。"""

    agent_id: str
    text: str
    tool_calls: list[ToolCallLog] = field(default_factory=list)
    play_song_path: str | None = None
    fallback_used: bool = False

    @property
    def intent_id(self) -> str:
        return self.agent_id

    @property
    def tool_names(self) -> list[str]:
        return [call.name for call in self.tool_calls]

    def tool_calls_as_dicts(self) -> list[dict]:
        return [call.as_dict() for call in self.tool_calls]


# 兼容旧名
SkillRunResult = AgentRunResult
