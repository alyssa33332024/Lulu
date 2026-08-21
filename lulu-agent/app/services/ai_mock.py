"""Deterministic replies for AI_PROVIDER=mock (engineering harness)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Iterator


def _blob(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for msg in messages:
        parts.append(str(msg.get("content") or ""))
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") if isinstance(tc, dict) else None
            if isinstance(fn, dict):
                parts.append(str(fn.get("name") or ""))
    return "\n".join(parts)


def _last_user(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _tool_names_offered(tools: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    for tool in tools or []:
        fn = (tool or {}).get("function") or {}
        name = fn.get("name")
        if name:
            names.append(str(name))
    return names


def _tools_already_called(messages: list[dict[str, Any]]) -> set[str]:
    called: set[str] = set()
    for msg in messages:
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
            name = fn.get("name") if isinstance(fn, dict) else None
            if name:
                called.add(str(name))
    return called


def _last_tool_payload(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        raw = msg.get("content") or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"mock_{name}_{uuid.uuid4().hex[:8]}",
        "name": name,
        "arguments": json.dumps(arguments, ensure_ascii=False),
    }


def _route_plan(query: str, hits: list[Any] | None = None) -> dict[str, Any]:
    q = query or ""
    hit_intents = {
        str(h.get("intent_id"))
        for h in (hits or [])
        if isinstance(h, dict) and h.get("intent_id")
    }
    has_sing = any(k in q for k in ("唱", "歌", "音乐")) or "sing" in hit_intents
    has_rem = any(k in q for k in ("提醒", "闹钟", "定时", "叫我")) or "reminder" in hit_intents
    if has_sing and has_rem:
        sequential = any(k in q for k in ("唱完", "放完", "然后再", "之后再"))
        return {
            "route": "agents",
            "execution": "sequential" if sequential else "parallel",
            "steps": [
                {"intent_id": "sing", "order": 1},
                {"intent_id": "reminder", "order": 2 if sequential else 1},
            ],
            "coord_line": "好，我先唱，唱完再帮你设提醒。" if sequential else "好，一边放歌一边帮你设提醒。",
        }
    if has_sing:
        return {"route": "agents", "steps": [{"intent_id": "sing", "order": 1}]}
    if has_rem:
        return {"route": "agents", "steps": [{"intent_id": "reminder", "order": 1}]}
    return {"route": "chat"}


def mock_chat(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    offered = _tool_names_offered(tools)
    if offered:
        return _mock_tools(messages, offered)

    text = _blob(messages)
    last = _last_user(messages)

    if "意图路由" in text or "只输出一个 JSON" in text:
        query = last
        hits: list[Any] = []
        try:
            payload = json.loads(last)
            if isinstance(payload, dict):
                query = str(payload.get("query") or last)
                raw_hits = payload.get("hits") or []
                if isinstance(raw_hits, list):
                    hits = raw_hits
        except json.JSONDecodeError:
            pass
        return {"content": json.dumps(_route_plan(query, hits), ensure_ascii=False), "tool_calls": []}

    if "记忆提取代理" in text or "history_entries" in text:
        return {
            "content": json.dumps(
                {
                    "history_entries": [
                        {
                            "summary": "[2026-08-21 14:00] 用户提到喜欢弹钢琴。",
                            "emotional_weight": 0,
                        }
                    ],
                    "pending_items": [
                        {"tag": "preference", "content": "用户喜欢弹钢琴"},
                    ],
                },
                ensure_ascii=False,
            ),
            "tool_calls": [],
        }

    if "长期记忆提取专家" in text:
        return {
            "content": json.dumps(
                {
                    "profile": [
                        {
                            "summary": "用户喜欢弹钢琴",
                            "category": "personal_fact",
                            "emotional_weight": 0,
                        }
                    ],
                    "preference": [],
                    "procedure": [],
                },
                ensure_ascii=False,
            ),
            "tool_calls": [],
        }

    if "压缩成连贯中文摘要" in text:
        return {"content": "用户聊到近况，并提到喜欢弹钢琴。", "tool_calls": []}

    return {"content": "嗯，我在听，你继续说。", "tool_calls": []}


def mock_chat_stream(messages: list[dict[str, Any]]) -> Iterator[str]:
    text = mock_chat(messages)["content"] or "嗯，我在听。"
    if "。" not in text:
        text = text.rstrip("。") + "。"
    mid = max(1, len(text) // 2)
    yield text[:mid]
    yield text[mid:]


def _mock_tools(messages: list[dict[str, Any]], offered: list[str]) -> dict[str, Any]:
    called = _tools_already_called(messages)
    last = _last_user(messages)
    payload = _last_tool_payload(messages)

    if "SearchSongCatalog" in offered and "SearchSongCatalog" not in called:
        return {
            "content": "",
            "tool_calls": [_tool_call("SearchSongCatalog", {"query": last[:80] or "one last time"})],
        }
    if "PlaySong" in offered and "PlaySong" not in called:
        song_id = "one_last_time"
        matches = payload.get("matches") or []
        if matches and isinstance(matches[0], dict) and matches[0].get("id"):
            song_id = str(matches[0]["id"])
        return {"content": "", "tool_calls": [_tool_call("PlaySong", {"song_id": song_id})]}

    if "ParseDateTool" in offered and "ParseDateTool" not in called:
        unit, offset = "day", 1
        if "分钟" in last or "分钟后" in last:
            unit, offset = "minute", 10
        return {
            "content": "",
            "tool_calls": [_tool_call("ParseDateTool", {"time_unit": unit, "offset": offset})],
        }
    if "FlexibleScheduleReminder" in offered and "FlexibleScheduleReminder" not in called:
        date_str = str(payload.get("date_str") or "")
        if not date_str:
            date_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        return {
            "content": "",
            "tool_calls": [
                _tool_call(
                    "FlexibleScheduleReminder",
                    {
                        "content": "开会",
                        "date_str": date_str,
                        "time_str": "09:30",
                    },
                )
            ],
        }

    if "PlaySong" in called:
        return {"content": "好，给你放 One Last Time。", "tool_calls": []}
    if "FlexibleScheduleReminder" in called:
        return {"content": "提醒设好了，明天上午九点半叫你开会。", "tool_calls": []}
    return {"content": "嗯，我在听。", "tool_calls": []}
