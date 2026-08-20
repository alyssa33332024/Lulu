"""Minimal LLMProvider used by consolidation / optimizer (Akashic call surface)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: ModelUsage | None = None


class LLMProvider:
    def __init__(
        self,
        *,
        chat_fn: Callable[..., Any] | None = None,
        context_window: int = 128000,
        system_prompt: str = "",
        estimate_fn: Callable[[list[dict], list[dict]], int] | None = None,
        model: str = "",
    ) -> None:
        self._chat_fn = chat_fn
        self._context_window = int(context_window)
        self._system = system_prompt
        self._estimate_fn = estimate_fn
        self._model = model

    @property
    def context_window(self) -> int:
        return self._context_window

    def estimate_context_tokens(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> int:
        tools = tools or []
        if self._estimate_fn is not None:
            return int(self._estimate_fn(messages, tools))
        total = sum(len(str(m.get("content") or "")) for m in messages)
        total += sum(len(str(t)) for t in tools)
        return max(1, total // 3)

    def estimate_appended_message_tokens(self, messages: list[dict]) -> int:
        return self.estimate_context_tokens(messages, [])

    async def chat(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        disable_thinking: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        del disable_thinking, kwargs
        if self._chat_fn is None:
            raise RuntimeError("LLMProvider chat_fn 未注入")
        result = self._chat_fn(
            messages=messages,
            tools=tools or [],
            model=model or self._model,
            max_tokens=max_tokens,
        )
        if hasattr(result, "__await__"):
            result = await result
        if isinstance(result, LLMResponse):
            return result
        if isinstance(result, dict):
            return LLMResponse(
                content=result.get("content") or "",
                tool_calls=list(result.get("tool_calls") or []),
            )
        return LLMResponse(content=str(result or ""))
