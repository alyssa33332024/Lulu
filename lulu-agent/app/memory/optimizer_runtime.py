"""定时把各 person workspace 的 PENDING.md 合并进 MEMORY.md。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Callable

from app.core.config import get_settings
from app.memory.facade import AkashicMemoryFacade
from app.memory.workspace import list_person_ids, person_workspace

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = 64800  # 18h


def pending_chars(person_id: str) -> int:
    from app.memory.md_store import MemoryStore

    store = MemoryStore(person_workspace(person_id))
    return len((store.read_pending() or "").strip())


def run_pending_optimizers(*, force: bool = False) -> list[str]:
    """同步跑一遍：有 PENDING（或 force）的 person 各优化一次。"""
    facade = AkashicMemoryFacade()
    done: list[str] = []
    for person_id in list_person_ids():
        if not force and pending_chars(person_id) == 0:
            continue
        try:
            facade.run_optimizer_once(person_id)
            done.append(person_id)
        except Exception:
            logger.exception("[memory_optimizer] person=%s 失败", person_id)
    return done


class MultiPersonOptimizerLoop:
    """对齐 Akashic MemoryOptimizerLoop：整点间隔扫全部 workspace。"""

    def __init__(
        self,
        interval_seconds: int | None = None,
        *,
        _now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        settings = get_settings()
        self._interval = max(
            60,
            int(interval_seconds or settings.akashic_optimizer_interval_seconds),
        )
        self._now_fn = _now_fn or datetime.now
        self._running = False

    async def run(self) -> None:
        self._running = True
        logger.info(
            "[memory_optimizer] 多用户循环启动 interval=%ds (%.1fh)",
            self._interval,
            self._interval / 3600,
        )
        while self._running:
            secs = self._seconds_until_next_tick()
            logger.info(
                "[memory_optimizer] 距下次 %.0fs (%.1fh)",
                secs,
                secs / 3600,
            )
            await asyncio.sleep(secs)
            if not self._running:
                break
            try:
                done = await asyncio.to_thread(run_pending_optimizers)
                if done:
                    logger.info("[memory_optimizer] 本轮完成 persons=%s", done)
            except Exception:
                logger.exception("[memory_optimizer] 本轮异常")

    def stop(self) -> None:
        self._running = False

    def _seconds_until_next_tick(self) -> float:
        now = self._now_fn()
        now_ts = now.replace(second=0, microsecond=0).timestamp()
        next_ts = (now_ts // self._interval + 1) * self._interval
        return max(1.0, next_ts - now.timestamp())
