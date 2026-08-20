"""Lulu 记忆子系统：融合 Akashic 记忆核心（除角色卡 / VEDA 外）。

人设仍用 prompts/characters；本包负责 MEMORY / PENDING / memory2 /
压缩归档抽取 / Optimizer。
"""

from __future__ import annotations

from app.memory.facade import AkashicMemoryFacade, PromptMemoryFields

__all__ = ["AkashicMemoryFacade", "PromptMemoryFields"]
