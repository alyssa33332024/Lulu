from __future__ import annotations

import json
from typing import Any, Iterator

import httpx
from openai import OpenAI

from app.core.config import get_settings


def _ollama_http_client(*, timeout: float = 120.0) -> httpx.Client:
    # Windows 系统代理常把 127.0.0.1 打成 502；本机 Ollama 必须直连
    return httpx.Client(trust_env=False, timeout=httpx.Timeout(timeout, connect=10.0))


class AIService:
    def __init__(self) -> None:
        s = get_settings()
        self.model = s.ark_chat_model
        self.client = OpenAI(base_url=s.ark_base_url, api_key=s.ark_api_key or "missing")
        self._ollama_http: httpx.Client | None = None
        self._ollama_client: OpenAI | None = None

        draft_backend = (s.chat_draft_backend or s.chat_fast_backend or "ark").strip().lower()
        agent_backend = (s.chat_agent_backend or "ark").strip().lower()
        self.draft_backend = draft_backend
        self.agent_backend = agent_backend

        self.draft_client, self.draft_model, self._draft_extra_body = self._resolve_lane(
            draft_backend, s
        )
        self.fast_client, self.fast_model, self._fast_extra_body = self._resolve_lane(
            agent_backend, s
        )

    def _resolve_lane(
        self,
        backend: str,
        s: Any,
    ) -> tuple[OpenAI, str, dict[str, Any] | None]:
        if backend == "ollama":
            if self._ollama_client is None:
                host = s.ollama_host.rstrip("/")
                self._ollama_http = _ollama_http_client()
                self._ollama_client = OpenAI(
                    base_url=f"{host}/v1",
                    api_key="ollama",
                    http_client=self._ollama_http,
                )
            model = (s.chat_fast_ollama_model or s.intent_model_name or "qwen2.5:3b").strip()
            return self._ollama_client, model, None
        model = (s.ark_chat_fast_model or s.ark_chat_model).strip()
        return self.client, model, {"thinking": {"type": "disabled"}}

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 400,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        extra_body: dict[str, Any] | None = None,
        client: OpenAI | None = None,
    ) -> dict[str, Any]:
        api = client or self.client
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if extra_body:
            kwargs["extra_body"] = extra_body
        resp = api.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                )
        return {"content": msg.content or "", "tool_calls": tool_calls}

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 400,
        model: str | None = None,
        extra_body: dict[str, Any] | None = None,
        client: OpenAI | None = None,
    ) -> Iterator[str]:
        api = client or self.client
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        stream = api.chat.completions.create(**kwargs)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield delta

    def chat_stream_fast(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 200,
    ) -> Iterator[str]:
        """闲聊草稿流式（CHAT_DRAFT_BACKEND）。"""
        return self.chat_stream(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=self.draft_model,
            extra_body=self._draft_extra_body,
            client=self.draft_client,
        )

    def chat_draft(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 200,
    ) -> dict[str, Any]:
        """闲聊草稿非流式（CHAT_DRAFT_BACKEND）。"""
        return self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=self.draft_model,
            extra_body=self._draft_extra_body,
            client=self.draft_client,
        )

    def chat_fast(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 200,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """技能 Agent 等快路径（CHAT_AGENT_BACKEND，默认方舟 Flash）。"""
        return self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            model=self.fast_model,
            extra_body=self._fast_extra_body,
            client=self.fast_client,
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        fast: bool = False,
    ) -> dict[str, Any]:
        if fast:
            raw = self.chat_fast(messages, temperature=temperature, max_tokens=256)["content"]
        else:
            raw = self.chat(messages, temperature=temperature, max_tokens=256)["content"]
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start : end + 1])
            raise
