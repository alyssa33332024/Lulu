from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy.orm import Session

from app.agents.dag_runtime import AgentExecutor, SYSTEM_FALLBACK
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.enums import DraftState
from app.models.entities import ChatMessage, ChatSession
from app.schemas.dtos import TurnRequest, TurnResponse, RoutePlan
from app.services.ai import AIService
from app.services.character import CharacterService
from app.services.context import ContextService
from app.services.identity import IdentityService
from app.services.knowledge import KnowledgeService
from app.memory import AkashicMemoryFacade
from app.services.privacy import PrivacySanitizer
from app.services.prompt import PromptService, PromptTemplates
from app.services.router import RouterService
from app.services.safety import SafetyService
from app.services.time_context import stamp_user_message
from app.services.timing import StepWatch
from app.services.trace import TraceService
from app.services.voice import GREET_REPLY, VoiceService

logger = logging.getLogger(__name__)
_BRIEF_GREET = re.compile(
    r"^(你好啊?|嗨|哈喽|hello|hi|lulu|噜噜|露露|璐璐)[。.!！？?\s]*$",
    re.I,
)
# 口播切句：标点优先；首包太长无标点时按字数软切，便于早点开 TTS
_SENTENCE_END = re.compile(r"[^。！？!?]*[。！？!?]+")
_FIRST_FLUSH_CHARS = 16
# 设置提醒 Agent 工具链慢：路由确定后先口播，再跑工具
REMINDER_WAIT_LINE = "稍等一下哦，马上给你设置好哦。"


def _plan_has_reminder(plan: RoutePlan) -> bool:
    return any(getattr(s, "intent_id", None) == "reminder" for s in (plan.steps or []))


def _pop_speakable(buffer: str, *, force: bool = False) -> tuple[list[str], str]:
    """从流式缓冲里切出可送 TTS 的片段，返回 (片段们, 剩余)。"""
    out: list[str] = []
    buf = buffer
    while True:
        m = _SENTENCE_END.match(buf)
        if not m:
            break
        piece = m.group(0).strip()
        buf = buf[m.end() :]
        if piece:
            out.append(piece)
    if force and buf.strip():
        out.append(buf.strip())
        buf = ""
    elif not out and len(buf) >= _FIRST_FLUSH_CHARS:
        # 尚无句读，先吐前半，降低首声等待
        cut = _FIRST_FLUSH_CHARS
        for i, ch in enumerate(buf):
            if i >= _FIRST_FLUSH_CHARS and ch in "，,、 ":
                cut = i + 1
                break
        piece = buf[:cut].strip()
        buf = buf[cut:]
        if piece:
            out.append(piece)
    return out, buf


class LuluTurnHarness:
    """双流水线：记忆∥(RAG→路由)，草稿接在记忆后；非 chat 只等记忆进子 Agent，chat 才等草稿。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.privacy = PrivacySanitizer()
        self.safety = SafetyService()
        self.prompt = PromptService()
        self.ai = AIService()
        self.knowledge = KnowledgeService()
        self.router = RouterService()
        self.voice = VoiceService()
        self.trace = TraceService(db)
        self.identity = IdentityService(db)
        self.akashic_memory = AkashicMemoryFacade()
        self.character = CharacterService(db)
        self.context = ContextService(db)
        self.executor = AgentExecutor(db)

    def run(self, req: TurnRequest) -> TurnResponse:
        watch = StepWatch("turn", query=(req.query or "")[:40])
        turn_id = uuid.uuid4().hex
        original = req.query.strip()
        query = self.privacy.sanitize(original)
        session = self._session(req.session_id, query)
        watch.mark("session")

        blocked, safe_reply = self.safety.check_input(query)
        watch.mark("safety")
        if blocked:
            self._save_msg(session.public_id, "user", original)
            self._save_msg(session.public_id, "assistant", safe_reply or "")
            payload = {"safety_blocked": True, "query": query}
            self.trace.save(turn_id, payload)
            audio = self.voice.audio_b64(safe_reply) if (safe_reply and req.with_tts) else None
            watch.mark("tts")
            watch.log(route="safety")
            return TurnResponse(
                session_id=session.public_id,
                turn_id=turn_id,
                route="safety",
                draft_state=DraftState.SKIPPED.value,
                reply=safe_reply or "",
                safety_blocked=True,
                tts_audio_base64=audio,
                trace=payload,
            )

        if _BRIEF_GREET.match(re.sub(r"\s+", "", query)):
            reply = GREET_REPLY
            self._save_msg(session.public_id, "user", original)
            self._save_msg(session.public_id, "assistant", reply)
            watch.mark("persist")
            # 问候固定短句：始终带回缓存音频，避免桌宠再走慢速 TTS 流
            audio = self.voice.cached_greet_b64()
            watch.mark("tts_greet")
            watch.log(route="greet", reply=reply)
            logger.info("greet fast-path")
            return TurnResponse(
                session_id=session.public_id,
                turn_id=turn_id,
                route="greet",
                draft_state=DraftState.SKIPPED.value,
                reply=reply,
                tts_audio_base64=audio,
                trace={"fast_path": "greet"},
            )

        speaker = self.identity.resolve(req.person_id)
        watch.mark("identity")

        char_res = self.character.resolve(speaker)
        card_id = char_res.card_id
        character, _ = self.prompt.render_character(
            card_id=card_id,
            speaker_block=self.identity.intro_line(speaker),
        )
        common = self.prompt.common_limit
        watch.mark("character")
        # 业务 call 前 Gate（对齐 Akashic soft≈74%），再装 history
        system_overhead = f"{character.strip()}\n\n{common.strip()}"
        pre_batch = self.context.maybe_compress(session, system_overhead=system_overhead)
        if speaker.person_id and not speaker.is_guest and pre_batch:
            self._schedule_akashic_consolidate(
                person_id=speaker.person_id,
                session_id=session.public_id,
                messages=pre_batch,
            )

        ctx = self.context.load(session)
        prompt_history = ctx.prompt_messages()
        recent_user = [h["content"] for h in ctx.recent if h["role"] == "user"]
        skip_draft = self.prompt.should_skip_draft(query)
        watch.mark("context")

        user_profile: str | None = None
        preferences: str | None = None
        memory_keys: list[str] = []
        hits: list = []
        draft_text = ""
        draft_state = DraftState.SKIPPED if skip_draft else DraftState.FAILED
        lane_ms: dict[str, float] = {}

        recall_s = self.settings.recall_timeout_ms / 1000
        draft_s = self.settings.draft_timeout_ms / 1000

        def load_memory() -> tuple[str | None, str | None, list[str]]:
            t0 = time.perf_counter()
            try:
                if speaker.person_id and not speaker.is_guest:
                    fields = self.akashic_memory.render_person_fields(
                        speaker.person_id,
                        query=query,
                    )
                    return fields.user_profile, fields.preferences, fields.memory_keys
                return None, None, []
            except Exception:
                return None, None, []
            finally:
                lane_ms["memory"] = (time.perf_counter() - t0) * 1000

        def lane_route():
            """RAG 意图 → 路由判断。"""
            local_hits: list = []
            t0 = time.perf_counter()
            try:
                local_hits = self.knowledge.recall(query)
            except Exception:
                local_hits = []
            lane_ms["rag"] = (time.perf_counter() - t0) * 1000
            t1 = time.perf_counter()
            plan_local = self.router.route(query, local_hits, recent_user)
            lane_ms["router"] = (time.perf_counter() - t1) * 1000
            return local_hits, plan_local

        def lane_draft_after_memory(fut_mem) -> tuple[str, DraftState]:
            """等记忆就绪后写 chat 草稿；记忆超时/失败时仍要出稿，不能整轮变兜底句。"""
            t_wait = time.perf_counter()
            profile: str | None = None
            prefs: str | None = None
            try:
                profile, prefs, _keys = fut_mem.result(timeout=recall_s)
            except Exception:
                # 记忆慢或向量维度不匹配时，宁可无记忆闲聊，也不要卡死草稿
                profile, prefs = None, None
            lane_ms["draft_wait_mem"] = (time.perf_counter() - t_wait) * 1000
            if skip_draft:
                lane_ms["draft_llm"] = 0.0
                return "", DraftState.SKIPPED
            person_ctx = PromptTemplates.person_context_block(long_term_memory=profile)
            shared_system = f"{character.strip()}\n\n{common.strip()}"
            if person_ctx:
                shared_system = f"{shared_system}\n\n{person_ctx}"
            messages: list[dict[str, str]] = [
                {"role": "system", "content": shared_system},
                *prompt_history,
            ]
            frame = PromptTemplates.retrieved_memory_frame(prefs)
            if frame:
                messages.append(frame)
            messages.append({"role": "user", "content": stamp_user_message(query)})
            t_llm = time.perf_counter()
            try:
                text = self.ai.chat_draft(messages, temperature=0.7, max_tokens=200)["content"].strip()
                lane_ms["draft_llm"] = (time.perf_counter() - t_llm) * 1000
                return text, (DraftState.USED if text else DraftState.FAILED)
            except Exception:
                lane_ms["draft_llm"] = (time.perf_counter() - t_llm) * 1000
                return "", DraftState.FAILED

        # 记忆 / RAG→路由 /（记忆→草稿）并行
        # 非 chat：只等记忆进子 Agent；chat：再等草稿
        plan = RoutePlan(route="chat", steps=[])
        t_par = time.perf_counter()
        pool = ThreadPoolExecutor(max_workers=3)
        try:
            fut_memory = pool.submit(load_memory)
            fut_route = pool.submit(lane_route)
            fut_draft = pool.submit(lane_draft_after_memory, fut_memory)

            try:
                hits, plan = fut_route.result(timeout=recall_s + draft_s)
            except Exception:
                hits, plan = [], self.router.route(query, [], recent_user)

            if plan.route == "chat":
                try:
                    user_profile, preferences, memory_keys = fut_memory.result(timeout=recall_s)
                except Exception:
                    user_profile, preferences, memory_keys = None, None, []
                try:
                    draft_text, draft_state = fut_draft.result(timeout=draft_s)
                except Exception:
                    draft_text, draft_state = "", DraftState.FAILED
            else:
                # 技能：记忆好了就进子 Agent；草稿不 wait（cancel 未开始的）
                _ = fut_draft.cancel()
                draft_state = DraftState.DISCARDED
                draft_text = ""
                try:
                    user_profile, preferences, memory_keys = fut_memory.result(timeout=recall_s)
                except Exception:
                    user_profile, preferences, memory_keys = None, None, []
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        watch.lap("parallel_wall", t_par)

        filler = None
        play_path = None
        tool_logs: list[dict] = []
        steps_out: list[dict] = []

        if plan.route == "chat":
            if draft_state == DraftState.USED and draft_text:
                reply = draft_text
            else:
                reply = "嗯，我在听，你继续说。"
                if draft_state != DraftState.SKIPPED:
                    draft_state = DraftState.FAILED
            route_name = "chat"
        else:
            t_agent = time.perf_counter()
            reply, filler, play_path, tool_logs, steps_out = self._run_agent_steps(
                plan,
                character=character,
                common=common,
                query=query,
                prompt_history=prompt_history,
                user_profile=user_profile,
                preferences=preferences,
            )
            watch.lap("agent", t_agent)
            route_name = "agents"
            # filler 仅承载路由多意图协调语（coord_line）

        # reply 已定：若本请求要带 TTS，先开合成线程，与落库并行
        # 桌宠 with_tts=false 时靠「更快返回 /turn」提前开 /tts/stream
        tts_fut: threading.Thread | None = None
        tts_box: dict[str, str | None] = {"audio": None}
        t_tts = 0.0
        if req.with_tts and reply:
            t_tts = time.perf_counter()

            def _run_tts() -> None:
                tts_box["audio"] = self.voice.audio_b64(reply)

            tts_fut = threading.Thread(target=_run_tts, daemon=True)
            tts_fut.start()

        self._save_msg(session.public_id, "user", original)
        self._save_msg(session.public_id, "assistant", reply)
        watch.mark("persist")

        # 会话压缩可能触发 LLM，挪出首包关键路径；桌宠可更早拿到 reply 去开 TTS
        self._schedule_post_turn_compress(
            session_id=session.public_id,
            system_overhead=system_overhead,
            person_id=speaker.person_id if (speaker.person_id and not speaker.is_guest) else None,
        )

        unlock_events: list[str] = []
        if speaker.person_id and not speaker.is_guest:
            reminder_set = any(tc.get("name") == "FlexibleScheduleReminder" for tc in tool_logs)
            _unlocked, unlock_events = self.character.record_turn(
                speaker.person_id,
                song_played=bool(play_path),
                reminder_set=reminder_set,
            )

        # 放歌与口播确认可同时存在：一边放歌一边说「提醒设好了」
        # TTS 继续与 trace 并行，join 放在返回前

        trace_payload: dict[str, Any] = {
            "safety_blocked": False,
            "speaker": {
                "person_id": speaker.person_id,
                "band": speaker.band.value,
                "is_guest": speaker.is_guest,
            },
            "memory_used": memory_keys,
            "session_summary": session.summary or "",
            "hits": [
                {
                    "query_id": h.query_id,
                    "query": h.query,
                    "intent_id": h.intent_id,
                    "score": h.score,
                    "dense_score": h.dense_score,
                    "bm25_score": h.bm25_score,
                    "rrf_score": h.rrf_score,
                }
                for h in hits
            ],
            "route": route_name,
            "execution": getattr(plan, "execution", "sequential") if plan.route == "agents" else None,
            "coord_line": getattr(plan, "coord_line", None) if plan.route == "agents" else None,
            "steps": steps_out,
            "draft_state": draft_state.value,
            "character_card_id": card_id,
            "character_unlocked_ids": char_res.unlocked_ids,
            "character_metrics": char_res.metrics,
            "character_active_policy": char_res.active_policy,
            "character_unlock_events": unlock_events,
            "tool_calls": tool_logs,
            "final_text": reply,
        }
        self.trace.save(turn_id, trace_payload)
        for label, ms in lane_ms.items():
            watch.steps.append((label, ms))
        watch.log(route=route_name, draft=draft_state.value, reply=(reply or "")[:40])

        audio = None
        if tts_fut is not None:
            tts_fut.join()
            audio = tts_box["audio"]
            watch.lap("tts", t_tts)

        return TurnResponse(
            session_id=session.public_id,
            turn_id=turn_id,
            route=route_name,
            steps=steps_out,
            draft_state=draft_state.value,
            reply=reply,
            filler=filler,
            character_card_id=card_id,
            character_unlock_events=unlock_events,
            play_song_path=play_path,
            tts_audio_base64=audio,
            trace=trace_payload,
        )

    def iter_events(self, req: TurnRequest):
        """流式一轮：chat 路径边生成边吐 sentence，桌宠可首句开 TTS。

        事件（NDJSON）：
        - route: 路由已定
        - sentence: 一段可合成口播
        - done: 完整 TurnResponse 字段（与 /turn 对齐）
        - error: 失败
        """
        watch = StepWatch("turn_stream", query=(req.query or "")[:40])
        turn_id = uuid.uuid4().hex
        original = req.query.strip()
        query = self.privacy.sanitize(original)
        session = self._session(req.session_id, query)
        watch.mark("session")

        blocked, safe_reply = self.safety.check_input(query)
        watch.mark("safety")
        if blocked:
            self._save_msg(session.public_id, "user", original)
            self._save_msg(session.public_id, "assistant", safe_reply or "")
            payload = {"safety_blocked": True, "query": query}
            self.trace.save(turn_id, payload)
            watch.log(route="safety")
            yield {
                "type": "done",
                "session_id": session.public_id,
                "turn_id": turn_id,
                "route": "safety",
                "draft_state": DraftState.SKIPPED.value,
                "reply": safe_reply or "",
                "safety_blocked": True,
                "steps": [],
                "filler": None,
                "character_card_id": None,
                "character_unlock_events": [],
                "play_song_path": None,
                "tts_audio_base64": None,
                "trace": payload,
            }
            return

        if _BRIEF_GREET.match(re.sub(r"\s+", "", query)):
            reply = GREET_REPLY
            self._save_msg(session.public_id, "user", original)
            self._save_msg(session.public_id, "assistant", reply)
            audio = self.voice.cached_greet_b64()
            watch.mark("tts_greet")
            watch.log(route="greet", reply=reply)
            yield {
                "type": "done",
                "session_id": session.public_id,
                "turn_id": turn_id,
                "route": "greet",
                "draft_state": DraftState.SKIPPED.value,
                "reply": reply,
                "safety_blocked": False,
                "steps": [],
                "filler": None,
                "character_card_id": None,
                "character_unlock_events": [],
                "play_song_path": None,
                "tts_audio_base64": audio,
                "trace": {"fast_path": "greet"},
            }
            return

        speaker = self.identity.resolve(req.person_id)
        watch.mark("identity")
        char_res = self.character.resolve(speaker)
        card_id = char_res.card_id
        character, _ = self.prompt.render_character(
            card_id=card_id,
            speaker_block=self.identity.intro_line(speaker),
        )
        common = self.prompt.common_limit
        watch.mark("character")
        system_overhead = f"{character.strip()}\n\n{common.strip()}"
        pre_batch = self.context.maybe_compress(session, system_overhead=system_overhead)
        if speaker.person_id and not speaker.is_guest and pre_batch:
            self._schedule_akashic_consolidate(
                person_id=speaker.person_id,
                session_id=session.public_id,
                messages=pre_batch,
            )

        ctx = self.context.load(session)
        prompt_history = ctx.prompt_messages()
        recent_user = [h["content"] for h in ctx.recent if h["role"] == "user"]
        watch.mark("context")

        lane_ms: dict[str, float] = {}
        recall_s = self.settings.recall_timeout_ms / 1000

        def load_memory() -> tuple[str | None, str | None, list[str]]:
            t0 = time.perf_counter()
            try:
                if speaker.person_id and not speaker.is_guest:
                    fields = self.akashic_memory.render_person_fields(
                        speaker.person_id,
                        query=query,
                    )
                    return fields.user_profile, fields.preferences, fields.memory_keys
                return None, None, []
            except Exception:
                return None, None, []
            finally:
                lane_ms["memory"] = (time.perf_counter() - t0) * 1000

        def lane_route():
            local_hits: list = []
            t0 = time.perf_counter()
            try:
                local_hits = self.knowledge.recall(query)
            except Exception:
                local_hits = []
            lane_ms["rag"] = (time.perf_counter() - t0) * 1000
            t1 = time.perf_counter()
            plan_local = self.router.route(query, local_hits, recent_user)
            lane_ms["router"] = (time.perf_counter() - t1) * 1000
            return local_hits, plan_local

        # 流式路径：先并行记忆+路由，定 chat 后再流式草稿（不再整段等草稿）
        plan = RoutePlan(route="chat", steps=[])
        hits: list = []
        user_profile: str | None = None
        preferences: str | None = None
        memory_keys: list[str] = []
        t_par = time.perf_counter()
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            fut_memory = pool.submit(load_memory)
            fut_route = pool.submit(lane_route)
            try:
                hits, plan = fut_route.result(timeout=recall_s + 2.0)
            except Exception:
                hits, plan = [], self.router.route(query, [], recent_user)
            try:
                user_profile, preferences, memory_keys = fut_memory.result(timeout=recall_s)
            except Exception:
                user_profile, preferences, memory_keys = None, None, []
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        watch.lap("parallel_wall", t_par)

        yield {
            "type": "route",
            "session_id": session.public_id,
            "turn_id": turn_id,
            "route": "chat" if plan.route == "chat" else "agents",
        }

        filler = None
        play_path = None
        tool_logs: list[dict] = []
        steps_out: list[dict] = []
        draft_state = DraftState.SKIPPED
        reply = ""

        if plan.route == "chat":
            person_ctx = PromptTemplates.person_context_block(long_term_memory=user_profile)
            shared_system = f"{character.strip()}\n\n{common.strip()}"
            if person_ctx:
                shared_system = f"{shared_system}\n\n{person_ctx}"
            messages: list[dict[str, str]] = [
                {"role": "system", "content": shared_system},
                *prompt_history,
            ]
            frame = PromptTemplates.retrieved_memory_frame(preferences)
            if frame:
                messages.append(frame)
            messages.append({"role": "user", "content": stamp_user_message(query)})

            t_llm = time.perf_counter()
            buf = ""
            parts: list[str] = []
            first_sentence_at: float | None = None
            try:
                for delta in self.ai.chat_stream_fast(messages, temperature=0.7, max_tokens=200):
                    parts.append(delta)
                    buf += delta
                    speakable, buf = _pop_speakable(buf, force=False)
                    for piece in speakable:
                        if first_sentence_at is None:
                            first_sentence_at = time.perf_counter()
                            lane_ms["draft_ttft_speakable"] = (first_sentence_at - t_llm) * 1000
                        yield {"type": "sentence", "text": piece}
                leftovers, _ = _pop_speakable(buf, force=True)
                for piece in leftovers:
                    if first_sentence_at is None:
                        lane_ms["draft_ttft_speakable"] = (time.perf_counter() - t_llm) * 1000
                    yield {"type": "sentence", "text": piece}
                reply = "".join(parts).strip()
                draft_state = DraftState.USED if reply else DraftState.FAILED
            except Exception:
                logger.exception("stream draft failed")
                reply = ""
                draft_state = DraftState.FAILED
            lane_ms["draft_llm"] = (time.perf_counter() - t_llm) * 1000
            if not reply:
                reply = "嗯，我在听，你继续说。"
                yield {"type": "sentence", "text": reply}
            route_name = "chat"
        else:
            # 设置提醒：先吐等待语开 TTS，再跑 Agent（ParseDate+Schedule 常要数秒）
            if _plan_has_reminder(plan):
                yield {"type": "sentence", "text": REMINDER_WAIT_LINE}
            t_agent = time.perf_counter()
            reply, filler, play_path, tool_logs, steps_out = self._run_agent_steps(
                plan,
                character=character,
                common=common,
                query=query,
                prompt_history=prompt_history,
                user_profile=user_profile,
                preferences=preferences,
            )
            watch.lap("agent", t_agent)
            draft_state = DraftState.DISCARDED
            route_name = "agents"
            if reply:
                yield {"type": "sentence", "text": reply}

        self._save_msg(session.public_id, "user", original)
        self._save_msg(session.public_id, "assistant", reply)
        watch.mark("persist")
        self._schedule_post_turn_compress(
            session_id=session.public_id,
            system_overhead=system_overhead,
            person_id=speaker.person_id if (speaker.person_id and not speaker.is_guest) else None,
        )

        unlock_events: list[str] = []
        if speaker.person_id and not speaker.is_guest:
            reminder_set = any(tc.get("name") == "FlexibleScheduleReminder" for tc in tool_logs)
            _unlocked, unlock_events = self.character.record_turn(
                speaker.person_id,
                song_played=bool(play_path),
                reminder_set=reminder_set,
            )

        trace_payload: dict[str, Any] = {
            "safety_blocked": False,
            "speaker": {
                "person_id": speaker.person_id,
                "band": speaker.band.value,
                "is_guest": speaker.is_guest,
            },
            "memory_used": memory_keys,
            "session_summary": session.summary or "",
            "hits": [
                {
                    "query_id": h.query_id,
                    "query": h.query,
                    "intent_id": h.intent_id,
                    "score": h.score,
                    "dense_score": h.dense_score,
                    "bm25_score": h.bm25_score,
                    "rrf_score": h.rrf_score,
                }
                for h in hits
            ],
            "route": route_name,
            "execution": getattr(plan, "execution", "sequential") if plan.route == "agents" else None,
            "coord_line": getattr(plan, "coord_line", None) if plan.route == "agents" else None,
            "steps": steps_out,
            "draft_state": draft_state.value,
            "character_card_id": card_id,
            "character_unlocked_ids": char_res.unlocked_ids,
            "character_metrics": char_res.metrics,
            "character_active_policy": char_res.active_policy,
            "character_unlock_events": unlock_events,
            "tool_calls": tool_logs,
            "final_text": reply,
            "streamed": True,
        }
        self.trace.save(turn_id, trace_payload)
        for label, ms in lane_ms.items():
            watch.steps.append((label, ms))
        watch.log(route=route_name, draft=draft_state.value, reply=(reply or "")[:40])

        yield {
            "type": "done",
            "session_id": session.public_id,
            "turn_id": turn_id,
            "route": route_name,
            "draft_state": draft_state.value,
            "reply": reply,
            "safety_blocked": False,
            "steps": steps_out,
            "filler": filler,
            "character_card_id": card_id,
            "character_unlock_events": unlock_events,
            "play_song_path": play_path,
            "tts_audio_base64": None,
            "trace": trace_payload,
        }

    def _run_agent_steps(
        self,
        plan,
        *,
        character: str,
        common: str,
        query: str,
        prompt_history: list[dict[str, str]],
        user_profile: str | None = None,
        preferences: str | None = None,
    ) -> tuple[str, str | None, str | None, list[dict], list[dict]]:
        steps = list(plan.steps)
        if not steps:
            return "嗯，我在听。", None, None, [], []

        # 多意图协调语来自路由；单意图开场由子 Agent Skill 自己说
        coord = (getattr(plan, "coord_line", None) or "").strip() or None
        if len(steps) < 2:
            coord = None

        if plan.execution == "parallel" and len(steps) > 1:
            return self._run_steps_parallel(
                steps,
                coord_line=coord,
                character=character,
                common=common,
                query=query,
                prompt_history=prompt_history,
                user_profile=user_profile,
                preferences=preferences,
            )
        return self._run_steps_sequential(
            steps,
            coord_line=coord,
            character=character,
            common=common,
            query=query,
            prompt_history=prompt_history,
            user_profile=user_profile,
            preferences=preferences,
        )

    def _run_steps_sequential(
        self,
        steps,
        *,
        coord_line: str | None,
        character: str,
        common: str,
        query: str,
        prompt_history: list[dict[str, str]],
        user_profile: str | None = None,
        preferences: str | None = None,
    ) -> tuple[str, str | None, str | None, list[dict], list[dict]]:
        parts: list[str] = []
        play_path = None
        tool_logs: list[dict] = []
        steps_out: list[dict] = []
        for step in steps:
            out = self.executor.run(
                step.intent_id,
                character=character,
                common_limit=common,
                query=query,
                history=prompt_history,
                user_profile=user_profile,
                preferences=preferences,
            )
            parts.append(out.text)
            tool_logs.extend(out.tool_calls_as_dicts())
            if out.play_song_path:
                play_path = out.play_song_path
            steps_out.append(
                {
                    "agent_id": step.intent_id,
                    "intent_id": step.intent_id,
                    "order": step.order,
                    "mode": "sequential",
                }
            )
        reply = "\n".join([p for p in parts if p])
        return reply, coord_line, play_path, tool_logs, steps_out

    def _run_steps_parallel(
        self,
        steps,
        *,
        coord_line: str | None,
        character: str,
        common: str,
        query: str,
        prompt_history: list[dict[str, str]],
        user_profile: str | None = None,
        preferences: str | None = None,
    ) -> tuple[str, str | None, str | None, list[dict], list[dict]]:
        results_by_id: dict[str, Any] = {}

        def _one(agent_id: str):
            db = SessionLocal()
            try:
                return AgentExecutor(db).run(
                    agent_id,
                    character=character,
                    common_limit=common,
                    query=query,
                    history=prompt_history,
                    user_profile=user_profile,
                    preferences=preferences,
                )
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=len(steps)) as pool:
            futs = {
                pool.submit(_one, step.intent_id): step
                for step in steps
            }
            for fut, step in futs.items():
                results_by_id[step.intent_id] = fut.result()

        tool_logs: list[dict] = []
        steps_out: list[dict] = []
        play_path = None
        for step in steps:
            out = results_by_id[step.intent_id]
            tool_logs.extend(out.tool_calls_as_dicts())
            if out.play_song_path:
                play_path = out.play_song_path
            steps_out.append(
                {
                    "agent_id": step.intent_id,
                    "intent_id": step.intent_id,
                    "order": step.order,
                    "mode": "parallel",
                }
            )

        # 并行：歌用 play_song_path 播；口播优先报提醒完成确认
        rem = results_by_id.get("reminder")
        sing = results_by_id.get("sing")
        if rem and rem.text:
            reply = rem.text.strip()
        elif sing and sing.text:
            reply = sing.text.strip()
        else:
            reply = SYSTEM_FALLBACK
        return reply, coord_line, play_path, tool_logs, steps_out

    def _schedule_post_turn_compress(
        self,
        *,
        session_id: str,
        system_overhead: str,
        person_id: str | None,
    ) -> None:
        """轮次结束后的会话压缩：独立 Session 后台跑，不挡 /turn 返回。"""

        def job() -> None:
            db = SessionLocal()
            try:
                refreshed = (
                    db.query(ChatSession).filter(ChatSession.public_id == session_id).first()
                )
                if not refreshed:
                    return
                batch = ContextService(db).maybe_compress(
                    refreshed,
                    system_overhead=system_overhead,
                )
                if person_id and batch:
                    AkashicMemoryFacade().consolidate_compressed_batch(
                        person_id=person_id,
                        session_id=session_id,
                        messages=batch,
                    )
                    if self.settings.akashic_optimizer_on_compress:
                        AkashicMemoryFacade().run_optimizer_once(person_id)
            except Exception:
                logger.exception("post-turn compress failed session=%s", session_id)
            finally:
                db.close()

        threading.Thread(target=job, daemon=True).start()

    def _schedule_akashic_consolidate(
        self,
        *,
        person_id: str,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        def job() -> None:
            try:
                self.akashic_memory.consolidate_compressed_batch(
                    person_id=person_id,
                    session_id=session_id,
                    messages=messages,
                )
                if self.settings.akashic_optimizer_on_compress:
                    self.akashic_memory.run_optimizer_once(person_id)
            except Exception:
                logger.exception(
                    "akashic consolidate failed person=%s session=%s",
                    person_id,
                    session_id,
                )

        threading.Thread(target=job, daemon=True).start()

    def _session(self, public_id: str | None, title: str) -> ChatSession:
        if public_id:
            s = self.db.query(ChatSession).filter(ChatSession.public_id == public_id).first()
            if s:
                return s
        s = ChatSession(public_id=uuid.uuid4().hex, title=title[:36] or "LuLu")
        self.db.add(s)
        self.db.commit()
        self.db.refresh(s)
        return s

    def _save_msg(self, session_id: str, role: str, content: str) -> None:
        self.db.add(ChatMessage(session_id=session_id, role=role, content=content))
        self.db.commit()
