"""Per-person workspace for MEMORY.md / PENDING / memory2.db."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def person_workspace(person_id: str) -> Path:
    settings = get_settings()
    root = Path(settings.akashic_memory_root)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (person_id or "unknown"))
    ws = root / safe
    (ws / "memory").mkdir(parents=True, exist_ok=True)
    return ws


def list_person_ids() -> list[str]:
    """扫描已有 memory workspace 目录名（即 person_id）。"""
    root = Path(get_settings().akashic_memory_root)
    if not root.exists():
        return []
    out: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "memory").is_dir():
            out.append(child.name)
    return out


def ensure_person_workspace(person_id: str) -> Path:
    """确保 workspace 与空 PENDING/MEMORY 骨架存在。"""
    from app.memory.md_store import MemoryStore

    ws = person_workspace(person_id)
    MemoryStore(ws)  # 创建 PENDING 等
    return ws
