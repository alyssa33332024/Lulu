"""Wrap Lulu AIService / Embedder for app.memory provider & memory2."""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import get_settings
from app.memory.provider import LLMProvider, LLMResponse
from app.services.ai import AIService
from app.services.embedding import get_embedder


def build_llm_provider(*, context_window: int | None = None) -> Any:
    settings = get_settings()
    ai = AIService()
    window = context_window if context_window is not None else settings.akashic_context_window

    def chat_fn(
        *,
        messages: list[dict],
        tools: list[dict],
        model: str,
        max_tokens: int,
    ) -> LLMResponse:
        del model
        payload = [
            {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
            for m in messages
        ]
        out = ai.chat(payload, temperature=0.2, max_tokens=max_tokens, tools=tools or None)
        return LLMResponse(content=out.get("content") or "", tool_calls=out.get("tool_calls") or [])

    return LLMProvider(
        chat_fn=chat_fn,
        context_window=window,
        model=settings.ark_chat_model,
    )


class LuluMemoryEmbedder:
    """Duck-type compatible with memory2.embedder.Embedder async API."""

    MAX_BATCH = 10
    MAX_TEXT_LEN = 2000

    def __init__(self) -> None:
        self._inner = get_embedder()
        self._dim = getattr(self._inner, "dim", None)

    @property
    def model_id(self) -> str:
        return getattr(self._inner, "name", type(self._inner).__name__)

    @property
    def output_dim(self) -> int:
        if self._dim:
            return int(self._dim)
        vec = self._inner.embed(["dim-probe"])[0]
        self._dim = len(vec)
        return int(self._dim)

    async def embed(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        truncated = [t[: self.MAX_TEXT_LEN] for t in texts]

        def _run() -> list[list[float]]:
            out: list[list[float]] = []
            for i in range(0, len(truncated), self.MAX_BATCH):
                batch = truncated[i : i + self.MAX_BATCH]
                out.extend(self._inner.embed(batch))
            return out

        return await asyncio.to_thread(_run)

    async def aclose(self) -> None:
        return None
