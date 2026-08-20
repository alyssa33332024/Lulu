from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TurnRequest(BaseModel):
    session_id: str | None = None
    query: str
    person_id: str | None = None
    # 语音链路（CustomLLM / Mate-Engine remote）由下游做 TTS，这里不必合成
    with_tts: bool = True


class RouteStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent_id: Literal["chat", "sing", "reminder"]
    order: int = 1


class RoutePlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    route: Literal["chat", "agents"]
    steps: list[RouteStep] = Field(default_factory=list)
    # parallel：互不依赖可同时跑（一边唱一边设提醒）
    # sequential：有先后（唱完再提醒）
    execution: Literal["sequential", "parallel"] = "sequential"
    # 仅多意图时由路由给出的一句协调语；单意图为空
    coord_line: str | None = None


class TurnResponse(BaseModel):
    session_id: str
    turn_id: str
    route: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    draft_state: str
    reply: str
    # 多意图时为路由 coord_line；单意图为 null（开场由子 Agent 说）
    filler: str | None = None
    safety_blocked: bool = False
    character_card_id: str | None = None
    character_unlock_events: list[str] = Field(default_factory=list)
    play_song_path: str | None = None
    tts_audio_base64: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)


class SelectCharacterCardRequest(BaseModel):
    person_id: str
    card_id: str
