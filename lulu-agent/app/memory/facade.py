"""Lulu facade over fused Akashic memory core in app.memory.

- characters cards remain Lulu persona (VEDA equivalent) — not owned here
- MEMORY / PENDING / memory2 / extract prompts live under app.memory
- scoped by person_id
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from app.core.config import get_settings
from app.memory.adapters import LuluMemoryEmbedder, build_llm_provider
from app.memory.workspace import person_workspace

logger = logging.getLogger(__name__)

_DISPLAY_NAME_PATTERNS = (
    re.compile(r"(?:姓名|名字|称呼)[：:]\s*([^\s，。、；;]{1,12})"),
    re.compile(r"(?:叫|称呼)[「『\"']?([^\s」』\"'，。、]{1,12})"),
    re.compile(r"用户(?:名叫|是|叫)\s*([^\s，。、]{1,12})"),
)


@dataclass
class PromptMemoryFields:
    """注入 person.md 的字段（对齐 Akashic：MEMORY.md + 检索块）。"""

    long_term_memory: str | None
    retrieved_memory: str | None
    memory_keys: list[str]

    # 兼容 harness / 旧调用仍解包 (profile, prefs, keys)
    @property
    def user_profile(self) -> str | None:
        return self.long_term_memory

    @property
    def preferences(self) -> str | None:
        return self.retrieved_memory


class AkashicMemoryFacade:
    """Harness-facing API."""

    def guess_display_name(self, person_id: str) -> str | None:
        """从 MEMORY.md 粗提称呼；Identity 在 DB 无 display_name 时回退。"""
        from app.memory.md_store import MemoryStore

        text = (MemoryStore(person_workspace(person_id)).read_long_term() or "").strip()
        if not text:
            return None
        for pat in _DISPLAY_NAME_PATTERNS:
            m = pat.search(text)
            if m:
                name = m.group(1).strip()
                if name and name not in {"用户", "对方", "主人", "LuLu", "Lulu"}:
                    return name
        return None

    def render_person_fields(self, person_id: str, *, query: str = "") -> PromptMemoryFields:
        from app.memory.md_store import MemoryStore

        ws = person_workspace(person_id)
        store = MemoryStore(ws)
        # 与 Akashic get_memory_context 一致：整份 MEMORY.md 进长期记忆块
        memory_md = (store.read_long_term() or "").strip()
        if memory_md.startswith("#"):
            # 去掉顶层标题行，外层 person.md 已有「## 长期记忆」
            lines = memory_md.splitlines()
            if lines and lines[0].lstrip().startswith("#"):
                memory_md = "\n".join(lines[1:]).strip()

        keys: list[str] = []
        retrieved = ""
        if query.strip():
            recalled = self.recall(person_id, query)
            if recalled:
                retrieved = "\n".join(f"- {line}" for line in recalled[:4] if line.strip())
                keys.extend([f"recall:{i}" for i in range(len(recalled[:4]))])

        return PromptMemoryFields(
            long_term_memory=memory_md or None,
            retrieved_memory=retrieved or None,
            memory_keys=keys,
        )

    def recall(self, person_id: str, query: str, *, top_k: int = 4) -> list[str]:
        try:
            return asyncio.run(self._arecall(person_id, query, top_k=top_k))
        except Exception:
            logger.exception("memory recall failed person=%s", person_id)
            return []

    async def _arecall(self, person_id: str, query: str, *, top_k: int) -> list[str]:
        from app.memory.memory2.retriever import Retriever
        from app.memory.memory2.store import MemoryStore2

        ws = person_workspace(person_id)
        embedder = LuluMemoryEmbedder()
        store = MemoryStore2(ws / "memory" / "memory2.db", vec_dim=embedder.output_dim)
        retriever = Retriever(store, embedder, top_k=top_k)
        hits = await retriever.retrieve(
            query,
            top_k=top_k,
            scope_channel="lulu",
            scope_chat_id=person_id,
        )
        return [str(h.get("summary") or "") for h in hits if h.get("summary")]

    def consolidate_compressed_batch(
        self,
        *,
        person_id: str,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        if not messages:
            return
        try:
            asyncio.run(
                self._aconsolidate(
                    person_id=person_id,
                    session_id=session_id,
                    messages=messages,
                )
            )
        except Exception:
            logger.exception(
                "memory consolidate failed person=%s session=%s", person_id, session_id
            )

    async def _aconsolidate(
        self,
        *,
        person_id: str,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        from app.memory.implicit_extract import _build_long_term_prompt, _dict_items
        from app.memory.markdown import (
            MarkdownMemoryStore,
            _ConsolidationFailure,
            _MarkdownConsolidationWorker,
        )
        from app.memory.memory2.memorizer import Memorizer
        from app.memory.memory2.store import MemoryStore2

        settings = get_settings()
        ws = person_workspace(person_id)
        provider = build_llm_provider()
        store = MarkdownMemoryStore(ws)
        worker = _MarkdownConsolidationWorker(
            profile_maint=store,
            provider=provider,
            model=settings.ark_chat_model,
            provider_input_budget=max(1024, settings.akashic_context_window - 2048),
        )
        source_ref = f"lulu:{session_id}:{person_id}"
        rows = [{"role": m["role"], "content": m["content"]} for m in messages]
        draft = await worker.prepare_page(
            rows,
            source_ref=source_ref,
            scope_channel="lulu",
            scope_chat_id=person_id,
        )
        if isinstance(draft, _ConsolidationFailure):
            raise RuntimeError(f"event_extract failed: {draft.step}: {draft.error}")

        if draft.pending_items.strip():
            store.append_pending_once(
                draft.pending_items,
                source_ref=source_ref,
                kind="pending_items",
            )

        embedder = LuluMemoryEmbedder()
        v2 = MemoryStore2(ws / "memory" / "memory2.db", vec_dim=embedder.output_dim)
        memorizer = Memorizer(v2, embedder)

        for entry, weight in draft.history_entry_payloads:
            await memorizer.save_from_consolidation(
                history_entry=entry,
                behavior_updates=[],
                source_ref=f"{source_ref}#h:{hash(entry) & 0xFFFFFFFF:x}",
                scope_channel="lulu",
                scope_chat_id=person_id,
                emotional_weight=weight,
            )

        prompt = _build_long_term_prompt(
            conversation=draft.conversation,
            existing_profile="",
        )
        resp = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            model=settings.ark_chat_model,
            max_tokens=600,
            disable_thinking=True,
        )
        text = (resp.content or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        import json_repair

        result = json_repair.loads(text)
        if not isinstance(result, dict):
            return

        for item in _dict_items(result.get("profile")):
            summary = str(item.get("summary") or "").strip()
            if not summary:
                continue
            await memorizer.save_item(
                summary=summary,
                memory_type="profile",
                extra={
                    "category": str(item.get("category") or "personal_fact"),
                    "scope_channel": "lulu",
                    "scope_chat_id": person_id,
                },
                source_ref=f"{source_ref}#profile",
                emotional_weight=int(item.get("emotional_weight") or 0),
            )
        for memory_type in ("preference", "procedure"):
            for item in _dict_items(result.get(memory_type)):
                summary = str(item.get("summary") or "").strip()
                if not summary:
                    continue
                await memorizer.save_item(
                    summary=summary,
                    memory_type=memory_type,
                    extra={
                        "scope_channel": "lulu",
                        "scope_chat_id": person_id,
                        "tool_requirement": item.get("tool_requirement"),
                        "steps": item.get("steps") or [],
                    },
                    source_ref=f"{source_ref}#implicit",
                    emotional_weight=int(item.get("emotional_weight") or 0),
                )

        logger.info(
            "memory consolidate ok person=%s events=%d pending_chars=%d",
            person_id,
            len(draft.history_entry_payloads),
            len(draft.pending_items),
        )

    def run_optimizer_once(self, person_id: str) -> None:
        try:
            asyncio.run(self._aoptimize(person_id))
        except Exception:
            logger.exception("memory optimizer failed person=%s", person_id)

    async def _aoptimize(self, person_id: str) -> None:
        from app.memory.markdown import MarkdownMemoryStore
        from app.memory.optimizer import MemoryOptimizer

        settings = get_settings()
        ws = person_workspace(person_id)
        store = MarkdownMemoryStore(ws)
        provider = build_llm_provider()
        optimizer = MemoryOptimizer(
            memory=store,
            provider=provider,
            model=settings.ark_chat_model,
        )
        await optimizer.optimize()
