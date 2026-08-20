from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.harness import LuluTurnHarness
from app.core.database import get_db
from app.schemas.dtos import SelectCharacterCardRequest, TurnRequest
from app.services.character import CharacterService
from app.services.skills import SkillLoader

logger = logging.getLogger(__name__)

router = APIRouter()


class AsrBody(BaseModel):
    pcm_b64: str
    mode: str = "wake"


@router.get("/health")
def health():
    return {"status": "UP", "service": "lulu-agent"}


@router.get("/agent/status")
def agent_status():
    skills = SkillLoader().list_ready()
    return {"framework": "dag_unidirectional", "skills": skills}


@router.post("/turn")
def turn(req: TurnRequest, db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    result = LuluTurnHarness(db).run(req)
    payload = result.model_dump()
    tts_len = len(payload.get("tts_audio_base64") or "")
    logger.warning(
        "[timing] http_turn query=%s route=%s reply_chars=%s tts_b64=%s total=%.0fms",
        (req.query or "")[:40],
        payload.get("route"),
        len(payload.get("reply") or ""),
        tts_len,
        (time.perf_counter() - t0) * 1000,
    )
    return payload


@router.post("/turn/stream")
def turn_stream(req: TurnRequest, db: Session = Depends(get_db)):
    """NDJSON 流：route → sentence* → done。桌宠可在首句开 TTS。"""
    t0 = time.perf_counter()
    first_sentence_ms: float | None = None

    def gen():
        nonlocal first_sentence_ms
        try:
            for event in LuluTurnHarness(db).iter_events(req):
                if event.get("type") == "sentence" and first_sentence_ms is None:
                    first_sentence_ms = (time.perf_counter() - t0) * 1000
                    logger.warning(
                        "[timing] turn_stream_first_sentence=%.0fms query=%s text=%s",
                        first_sentence_ms,
                        (req.query or "")[:40],
                        str(event.get("text") or "")[:40],
                    )
                if event.get("type") == "done":
                    logger.warning(
                        "[timing] turn_stream_done query=%s route=%s reply_chars=%s first_sentence=%.0fms total=%.0fms",
                        (req.query or "")[:40],
                        event.get("route"),
                        len(event.get("reply") or ""),
                        first_sentence_ms or -1,
                        (time.perf_counter() - t0) * 1000,
                    )
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            logger.exception("turn stream failed")
            yield json.dumps({"type": "error", "error": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.post("/asr")
async def asr(body: AsrBody):
    import base64

    from app.services.asr import recognize_pcm16

    t0 = time.perf_counter()
    raw = (body.pcm_b64 or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio")
    try:
        pcm = base64.b64decode(raw)
        decode_ms = (time.perf_counter() - t0) * 1000
        mode = (body.mode or "wake").strip() or "wake"
        text = await recognize_pcm16(pcm, mode)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    logger.warning(
        "[timing] http_asr mode=%s pcm=%s text=%s decode=%.0fms total=%.0fms",
        mode,
        len(pcm),
        text,
        decode_ms,
        (time.perf_counter() - t0) * 1000,
    )
    return {"text": text}


class TtsBody(BaseModel):
    text: str = ""


@router.post("/tts/stream")
def tts_stream(body: TtsBody):
    from app.services.voice import GREET_REPLY, VoiceService

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty text")
    t0 = time.perf_counter()
    first = True
    svc = VoiceService()

    def gen():
        nonlocal first
        if text == GREET_REPLY:
            cached = svc.cached_greet_bytes()
            if cached:
                logger.warning(
                    "[timing] tts_stream greet_cache bytes=%s total=%.0fms",
                    len(cached),
                    (time.perf_counter() - t0) * 1000,
                )
                yield cached
                return
        for chunk in svc.iter_mpeg_chunks(text):
            if first:
                logger.warning(
                    "[timing] tts_stream first_chunk=%.0fms chars=%s",
                    (time.perf_counter() - t0) * 1000,
                    len(text),
                )
                first = False
            yield chunk
        logger.warning(
            "[timing] tts_stream total=%.0fms chars=%s",
            (time.perf_counter() - t0) * 1000,
            len(text),
        )

    return StreamingResponse(gen(), media_type="audio/mpeg")


@router.websocket("/asr/stream")
async def asr_stream(ws: WebSocket):
    from app.services.asr import VolcAsrSession

    await ws.accept()
    session = VolcAsrSession()
    inbox: asyncio.Queue = asyncio.Queue()

    async def read_client() -> None:
        try:
            while True:
                message = await ws.receive()
                await inbox.put(message)
                if message.get("type") == "websocket.disconnect":
                    return
                text = message.get("text")
                if text:
                    try:
                        if json.loads(text).get("event") in {"end", "cancel"}:
                            return
                    except json.JSONDecodeError:
                        pass
        except WebSocketDisconnect:
            await inbox.put({"type": "websocket.disconnect"})
        except Exception:
            await inbox.put({"type": "websocket.disconnect"})

    reader = asyncio.create_task(read_client())
    t0 = time.perf_counter()
    try:
        await session.start()
        logger.warning("[timing] asr_stream ready=%.0fms", (time.perf_counter() - t0) * 1000)
        while True:
            message = await inbox.get()
            if message.get("type") == "websocket.disconnect":
                break
            raw = message.get("bytes")
            if raw:
                await session.send_audio(raw)
                continue
            text = message.get("text") or ""
            try:
                payload = json.loads(text) if text else {}
            except json.JSONDecodeError:
                payload = {}
            if payload.get("event") == "cancel":
                break
            if payload.get("event") == "end":
                result = await session.finish()
                logger.warning(
                    "[timing] asr_stream done=%.0fms text=%s",
                    (time.perf_counter() - t0) * 1000,
                    result,
                )
                await ws.send_json({"text": result})
                break
    except Exception as exc:
        logger.warning("asr stream failed: %s", exc)
        try:
            await ws.send_json({"text": "", "error": "asr_stream_failed"})
        except Exception:
            pass
    finally:
        reader.cancel()
        await session.close()


@router.get("/character/progress")
def character_progress(person_id: str, db: Session = Depends(get_db)):
    svc = CharacterService(db)
    metrics = svc.metrics_for(person_id)
    unlocked = svc.compute_unlocked_ids(metrics)
    progress = svc.get_or_create_progress(person_id)
    return {
        "person_id": person_id,
        "metrics": metrics,
        "unlocked_ids": unlocked,
        "active_card_id": progress.active_card_id,
        "active_policy": svc.active_policy(),
    }


@router.post("/character/select")
def select_character_card(req: SelectCharacterCardRequest, db: Session = Depends(get_db)):
    svc = CharacterService(db)
    ok, detail = svc.set_selected_card(req.person_id, req.card_id)
    if not ok:
        return JSONResponse({"ok": False, "error": detail}, status_code=400)
    return {"ok": True, "person_id": req.person_id, "card_id": detail}
