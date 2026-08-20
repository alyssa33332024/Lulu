from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from app.core.config import ROOT, get_settings
from app.models.entities import ReminderItem


PARSE_DATE_TOOL = {
    "type": "function",
    "function": {
        "name": "ParseDateTool",
        "description": "把相对/模糊日期转成 yyyy-MM-dd",
        "parameters": {
            "type": "object",
            "properties": {
                "time_unit": {"type": "string", "enum": ["minute", "hour", "day", "week", "month"]},
                "offset": {"type": "integer"},
            },
            "required": ["time_unit", "offset"],
        },
    },
}

SCHEDULE_TOOL = {
    "type": "function",
    "function": {
        "name": "FlexibleScheduleReminder",
        "description": "真正落提醒",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "date_str": {"type": "string"},
                "time_str": {"type": "string"},
                "r_type": {"type": "string"},
            },
            "required": ["content", "date_str", "time_str"],
        },
    },
}

SEARCH_SONG_TOOL = {
    "type": "function",
    "function": {
        "name": "SearchSongCatalog",
        "description": "在本地曲库搜索歌曲",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

PLAY_SONG_TOOL = {
    "type": "function",
    "function": {
        "name": "PlaySong",
        "description": "播放本地曲库中的歌曲",
        "parameters": {
            "type": "object",
            "properties": {"song_id": {"type": "string"}},
            "required": ["song_id"],
        },
    },
}


TOOL_SCHEMAS = {
    "ParseDateTool": PARSE_DATE_TOOL,
    "FlexibleScheduleReminder": SCHEDULE_TOOL,
    "SearchSongCatalog": SEARCH_SONG_TOOL,
    "PlaySong": PLAY_SONG_TOOL,
}


class ToolRuntime:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self._songs = self._load_songs()
        self.last_play_path: str | None = None

    def _load_songs(self) -> dict:
        path = self.settings.songs_config
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        return data or {}

    def schemas_for(self, names: tuple[str, ...] | list[str]) -> list[dict]:
        """按 AgentRegistry 登记的工具名取 schema；agent→工具的映射只在 registry 维护。"""
        return [TOOL_SCHEMAS[name] for name in names if name in TOOL_SCHEMAS]

    def execute(self, name: str, arguments: str | dict) -> str:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        if name == "ParseDateTool":
            return json.dumps(self._parse_date(args), ensure_ascii=False)
        if name == "FlexibleScheduleReminder":
            return json.dumps(self._schedule(args), ensure_ascii=False)
        if name == "SearchSongCatalog":
            return json.dumps(self._search_song(args.get("query", "")), ensure_ascii=False)
        if name == "PlaySong":
            return json.dumps(self._play_song(args.get("song_id", "")), ensure_ascii=False)
        return json.dumps({"ok": False, "error": f"unknown tool {name}"})

    def _parse_date(self, args: dict) -> dict:
        unit = args.get("time_unit", "day")
        offset = int(args.get("offset", 0))
        now = datetime.now()
        delta_map = {
            "minute": timedelta(minutes=offset),
            "hour": timedelta(hours=offset),
            "day": timedelta(days=offset),
            "week": timedelta(weeks=offset),
            "month": timedelta(days=30 * offset),
        }
        target = now + delta_map.get(unit, timedelta(days=offset))
        return {
            "date_str": target.strftime("%Y-%m-%d"),
            "now": now.isoformat(timespec="seconds"),
        }

    def _schedule(self, args: dict) -> dict:
        content = (args.get("content") or "").strip()
        date_str = args.get("date_str")
        time_str = args.get("time_str")
        r_type = args.get("r_type")
        if not content or not date_str or not time_str:
            return {"ok": False, "error": "missing fields"}
        # past check
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if dt < datetime.now():
                return {"ok": False, "error": "past_time"}
        except ValueError:
            return {"ok": False, "error": "bad_datetime"}
        item = ReminderItem(
            content=content,
            date_str=date_str,
            time_str=time_str,
            r_type=r_type or None,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return {
            "ok": True,
            "id": item.id,
            "content": content,
            "date_str": date_str,
            "time_str": time_str,
        }

    def _search_song(self, query: str) -> dict:
        songs = self._songs.get("songs") or []
        q = (query or "").lower().strip()
        matches = []
        for s in songs:
            blob = " ".join([s.get("title", ""), s.get("artist", ""), *s.get("aliases", [])]).lower()
            if not q or q in blob or any(a.lower() in q or q in a.lower() for a in s.get("aliases", [])):
                matches.append({"id": s["id"], "title": s["title"], "artist": s.get("artist")})
        if not matches and self._songs.get("single_track_autoplay") and len(songs) == 1:
            s = songs[0]
            matches = [{"id": s["id"], "title": s["title"], "artist": s.get("artist")}]
        return {"ok": True, "matches": matches}

    def _play_song(self, song_id: str) -> dict:
        songs = self._songs.get("songs") or []
        song = next((s for s in songs if s.get("id") == song_id), None)
        if song is None and self._songs.get("single_track_autoplay") and len(songs) == 1:
            song = songs[0]
        if song is None:
            return {"ok": False, "error": "not_found"}
        path = Path(song["path"])
        candidates = []
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.extend(
                [
                    ROOT / path,
                    ROOT / "data" / "songs" / "one_last_time.mp3",
                    ROOT / "data" / "songs" / path.name,
                ]
            )
        resolved = next((c for c in candidates if c.exists()), None)
        if resolved is None:
            return {"ok": False, "error": "file_missing", "tried": [str(c) for c in candidates]}
        self.last_play_path = str(resolved)
        return {"ok": True, "song_id": song["id"], "title": song["title"], "path": str(resolved)}
