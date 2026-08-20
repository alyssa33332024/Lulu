from __future__ import annotations

from pathlib import Path

import yaml

from app.core.config import get_settings


class SkillLoader:
    def __init__(self) -> None:
        self.root = get_settings().skills_dir

    def load_skill_md(self, intent_id: str) -> str:
        path = self.root / intent_id / "SKILL.md"
        if not path.exists():
            return f"你是 LuLu 的 {intent_id} 技能。用口语完成用户请求。"
        text = path.read_text(encoding="utf-8")
        # strip frontmatter
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return text

    def list_ready(self) -> list[dict]:
        out = []
        if not self.root.exists():
            return out
        for d in sorted(self.root.iterdir()):
            skill = d / "SKILL.md"
            if d.is_dir() and skill.exists():
                out.append({"id": d.name, "path": str(skill), "status": "READY"})
        return out
