from __future__ import annotations

import json
import uuid
from typing import Any, Iterator

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.harness import LuluTurnHarness
from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.dtos import TurnRequest

router = APIRouter(tags=["rtc"])


class ChatMessage(BaseModel):
    role: str
    content: str | list[Any] | None = None


class CustomLLMRequest(BaseModel):
    """OpenAI-compatible body used by Volcengine Conversational AI CustomLLM."""

    model: str | None = None
    stream: bool = True
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float | None = None


def _extract_user_text(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.role != "user":
            continue
        c = msg.content
        if isinstance(c, str) and c.strip():
            return c.strip()
        if isinstance(c, list):
            parts = []
            for item in c:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                elif isinstance(item, str):
                    parts.append(item)
            text = "".join(parts).strip()
            if text:
                return text
    return ""


def _check_auth(authorization: str | None) -> None:
    settings = get_settings()
    expected = (settings.custom_llm_api_key or "").strip()
    if not expected:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer")
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid custom llm key")


def _openai_chunk(content: str, *, finish: bool = False) -> str:
    payload = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {} if finish else {"content": content},
                "finish_reason": "stop" if finish else None,
            }
        ],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat-stream")
@router.post("/rtc/chat-stream")
def custom_llm_chat_stream(
    body: CustomLLMRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    """Volcengine 实时对话式 AI → CustomLLM 回调入口（SSE）。

    控制台 / StartVoiceChat 里把 LLM URL 配到:
      https://<公网>/api/chat-stream
    Authorization: Bearer <CUSTOM_LLM_API_KEY>
    """
    _check_auth(authorization)
    query = _extract_user_text(body.messages)
    if not query:
        raise HTTPException(status_code=400, detail="no user message")

    # 火山侧自己做 TTS，这里不合成音频
    result = LuluTurnHarness(db).run(TurnRequest(query=query, with_tts=False))
    text = result.reply or ""

    def gen() -> Iterator[str]:
        # small chunks for TTS upstream friendliness
        step = 12
        for i in range(0, len(text), step):
            yield _openai_chunk(text[i : i + step])
        yield _openai_chunk("", finish=True)
        yield "data: [DONE]\n\n"

    if body.stream:
        return StreamingResponse(gen(), media_type="text/event-stream")
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }
