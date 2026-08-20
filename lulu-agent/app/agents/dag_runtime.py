from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents.registry import AgentRegistry
from app.agents.result import AgentRunResult, ToolCallLog
from app.core.enums import IntentId
from app.services.ai import AIService
from app.services.prompt import PromptTemplates
from app.services.skills import SkillLoader
from app.services.time_context import stamp_user_message
from app.services.tools import ToolRuntime

# 系统级冷兜底：模型空响应 / 超时 / 异常（业务话术在 Skill）
SYSTEM_FALLBACK = "这个我没处理好，你再说一次好吗？"


class AgentExecutor:
    """跑一个专职 Agent：加载其唯一 Skill，在工具预算内完成任务。

    System 拼接对齐产品模板：
    1) character + common_limit + 长期记忆（MEMORY.md，稳定）
    2) skill + 可选 env/document
    3) history
    4) context frame（retrieved_memory，role=user + system-reminder）
    5) 当前 user（时间信封）
    """

    def __init__(self, db: Session) -> None:
        self.ai = AIService()
        self.skills = SkillLoader()
        self.tools = ToolRuntime(db)
        self.registry = AgentRegistry()

    def run(
        self,
        agent_id: str,
        *,
        character: str,
        common_limit: str,
        query: str,
        history: list[dict[str, str]] | None = None,
        user_profile: str | None = None,
        preferences: str | None = None,
        env_context: str | None = None,
        document_context: str | None = None,
        message_timestamp: datetime | None = None,
        max_tool_calls: int | None = None,
    ) -> AgentRunResult:
        profile = self.registry.profile(agent_id)
        budget = profile.max_tool_calls if max_tool_calls is None else max_tool_calls
        skill = self.skills.load_skill_md(profile.skill_name)
        # 稳定长期记忆进 system；本轮检索进 context frame（Akashic 同款）
        person_ctx = PromptTemplates.person_context_block(long_term_memory=user_profile)
        shared_system = f"{character.strip()}\n\n{common_limit.strip()}"
        if person_ctx:
            shared_system = f"{shared_system}\n\n{person_ctx}"
        env_ctx = PromptTemplates.context_block(
            env_context=env_context,
            document_context=document_context,
        )
        skill_system = skill.strip()
        if env_ctx:
            skill_system = f"{skill_system}\n\n{env_ctx}"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": shared_system},
            {"role": "system", "content": skill_system},
        ]
        for h in history or []:
            messages.append(h)
        frame = PromptTemplates.retrieved_memory_frame(preferences)
        if frame:
            messages.append(frame)
        messages.append(
            {
                "role": "user",
                "content": stamp_user_message(query, message_timestamp=message_timestamp),
            }
        )

        tool_schemas = self.tools.schemas_for(profile.tool_names)
        tool_calls: list[ToolCallLog] = []
        calls = 0
        play_path = None

        while True:
            result = self.ai.chat_fast(
                messages,
                tools=tool_schemas or None,
                temperature=0.4,
                max_tokens=400,
            )
            if result["tool_calls"] and calls < budget:
                messages.append(
                    {
                        "role": "assistant",
                        "content": result["content"] or None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {"name": tc["name"], "arguments": tc["arguments"]},
                            }
                            for tc in result["tool_calls"]
                        ],
                    }
                )
                for tc in result["tool_calls"]:
                    calls += 1
                    out = self.tools.execute(tc["name"], tc["arguments"])
                    tool_calls.append(ToolCallLog(name=tc["name"], arguments=tc["arguments"], result=out))
                    if tc["name"] == "PlaySong":
                        play_path = self.tools.last_play_path
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
                names = [call.name for call in tool_calls]
                if (
                    agent_id == IntentId.REMINDER.value
                    and "ParseDateTool" in names
                    and "FlexibleScheduleReminder" not in names
                    and calls < budget
                ):
                    messages.append(
                        {
                            "role": "user",
                            "content": PromptTemplates.reminder_complete_nudge(),
                        }
                    )
                continue

            text = (result["content"] or "").strip()
            if not text and tool_calls:
                text = self._final_say(messages)
            fallback_used = not text
            if fallback_used:
                # 仅系统级冷兜底；业务失败话术由 Skill 要求模型自行说出
                text = SYSTEM_FALLBACK
            return AgentRunResult(
                agent_id=agent_id,
                text=text,
                tool_calls=tool_calls,
                play_song_path=play_path,
                fallback_used=fallback_used,
            )

    def _final_say(self, messages: list[dict[str, Any]]) -> str:
        """工具已跑完但模型没给话术时，不带工具再要一句口语确认。"""
        followup = messages + [{"role": "user", "content": PromptTemplates.final_say_prompt()}]
        try:
            return (self.ai.chat_fast(followup, temperature=0.4, max_tokens=200)["content"] or "").strip()
        except Exception:
            return ""
