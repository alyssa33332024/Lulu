from __future__ import annotations

import asyncio
import gzip
import json
import logging
import struct
import time
import uuid

from typing import Any

import websockets

from app.core.config import get_settings
from app.services.asr_windows import recognize_windows

logger = logging.getLogger(__name__)

_WS_URL_NOSTREAM = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
_WS_URL_ASYNC = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
_PROTOCOL = 0b0001
_HEADER_SIZE = 0b0001
_FULL_CLIENT = 0b0001
_AUDIO_ONLY = 0b0010
_ERROR = 0b1111
_JSON = 0b0001
_RAW = 0b0000
_GZIP = 0b0001
_CHUNK = 6400  # 200ms 16kHz s16le mono
_NO_SEQ = 0b0000
_POS_SEQ = 0b0001
_LAST_NO_SEQ = 0b0010
_NEG_WITH_SEQ = 0b0011
_volc_available: bool | None = None


def _header(msg_type: int, flags: int) -> bytes:
    serialization = _JSON if msg_type == _FULL_CLIENT else _RAW
    return bytes(
        [
            (_PROTOCOL << 4) | _HEADER_SIZE,
            (msg_type << 4) | flags,
            (serialization << 4) | _GZIP,
            0,
        ]
    )


def _frame(msg_type: int, flags: int, payload: bytes, sequence: int | None = None) -> bytes:
    compressed = gzip.compress(payload)
    header = _header(msg_type, flags)
    seq_bytes = b"" if sequence is None else struct.pack(">i", sequence)
    return header + seq_bytes + struct.pack(">I", len(compressed)) + compressed


def _parse(data: bytes) -> dict[str, object]:
    if len(data) < 8:
        raise ValueError("asr frame too short")
    msg_type = data[1] >> 4
    flags = data[1] & 0x0F
    serialization = data[2] >> 4
    compression = data[2] & 0x0F
    header_size = (data[0] & 0x0F) * 4
    payload = data[header_size:]
    if flags & 0x01:
        if len(payload) < 4:
            raise ValueError("asr sequence truncated")
        payload = payload[4:]
    if msg_type == _ERROR:
        if len(payload) < 8:
            raise RuntimeError("asr error frame truncated")
        code = struct.unpack(">I", payload[:4])[0]
        size = struct.unpack(">I", payload[4:8])[0]
        raw = payload[8 : 8 + size]
        if compression == _GZIP and raw:
            raw = gzip.decompress(raw)
        detail = raw.decode("utf-8", errors="replace") if raw else ""
        raise RuntimeError(f"asr error {code}: {detail}")
    if len(payload) < 4:
        return {}
    size = struct.unpack(">I", payload[:4])[0]
    raw = payload[4 : 4 + size]
    if compression == _GZIP and raw:
        raw = gzip.decompress(raw)
    if serialization == _JSON and raw:
        parsed = json.loads(raw.decode("utf-8"))
        if isinstance(parsed, dict):
            return parsed
    return {}


def _volc_url(*, stream: bool) -> str:
    configured = (get_settings().speech_asr_base_url or "").strip()
    if not configured:
        return _WS_URL_ASYNC if stream else _WS_URL_NOSTREAM
    if stream and "nostream" in configured:
        return configured.replace("bigmodel_nostream", "bigmodel_async")
    if stream and configured.rstrip("/").endswith("/sauc/bigmodel"):
        return configured.rstrip("/") + "_async"
    return configured


def _is_definite(payload: dict[str, object]) -> bool:
    result = payload.get("result")
    if isinstance(result, dict):
        utterances = result.get("utterances")
        if isinstance(utterances, list) and any(
            isinstance(item, dict) and item.get("definite") for item in utterances
        ):
            return True
    return False


def _extract_text(payload: dict[str, object]) -> str:
    result = payload.get("result")
    if isinstance(result, dict):
        text = result.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        utterances = result.get("utterances")
        if isinstance(utterances, list):
            parts = [
                str(item.get("text") or "").strip()
                for item in utterances
                if isinstance(item, dict)
            ]
            joined = "".join(parts).strip()
            if joined:
                return joined
    if isinstance(result, list):
        parts = [
            str(item.get("text") or "").strip()
            for item in result
            if isinstance(item, dict)
        ]
        return "".join(parts).strip()
    text = payload.get("text")
    if isinstance(text, str):
        return text.strip()
    return ""


def _auth_headers() -> dict[str, str]:
    s = get_settings()
    headers = {
        "X-Api-Resource-Id": s.asr_resource_id or "volc.seedasr.sauc.duration",
        "X-Api-Connect-Id": str(uuid.uuid4()),
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Sequence": "-1",
    }
    app_id = s.speech_asr_app_id or s.speech_app_id
    token = s.speech_asr_access_token or s.speech_app_key
    if app_id and token:
        headers["X-Api-App-Key"] = app_id
        headers["X-Api-Access-Key"] = token
    elif s.speech_api_key:
        headers["X-Api-Key"] = s.speech_api_key
    else:
        raise RuntimeError("asr credentials missing")
    return headers


def _is_unavailable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "not granted",
            "not allowed",
            "http 400",
            "http 401",
            "http 403",
            "resourceid",
            "resource_id",
        )
    )


async def _recognize_volc(pcm: bytes) -> str:
    samples = len(pcm) // 2
    if samples:
        total = 0
        for i in range(0, len(pcm), 2):
            total += int.from_bytes(pcm[i : i + 2], "little", signed=True) ** 2
        rms = (total / samples) ** 0.5
    else:
        rms = 0.0
    audio_s = samples / 16000
    from app.services.timing import StepWatch

    watch = StepWatch("asr", bytes=len(pcm), audio_s=f"{audio_s:.2f}", rms=f"{rms:.1f}")
    logger.warning("asr pcm bytes=%s rms=%.1f duration=%.2fs", len(pcm), rms, audio_s)

    url = _volc_url(stream=False)
    headers = _auth_headers()
    audio: dict[str, object] = {
        "format": "pcm",
        "codec": "raw",
        "rate": 16000,
        "bits": 16,
        "channel": 1,
    }
    if "nostream" in url:
        audio["language"] = "zh-CN"
    init = {
        "user": {"uid": "lulu-desktop"},
        "audio": audio,
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "show_utterances": True,
            "result_type": "full",
        },
    }
    texts: list[str] = []
    async with websockets.connect(
        url,
        additional_headers=headers,
        max_size=8 * 1024 * 1024,
        open_timeout=6,
        compression=None,
    ) as ws:
        watch.mark("ws_connect")
        await ws.send(
            _frame(_FULL_CLIENT, _POS_SEQ, json.dumps(init, ensure_ascii=False).encode("utf-8"), 1)
        )
        first = _parse(await asyncio.wait_for(ws.recv(), timeout=6))
        watch.mark("init_ack")
        logger.warning("asr init ack: %s", first)
        seq = 2
        for i in range(0, len(pcm), _CHUNK):
            chunk = pcm[i : i + _CHUNK]
            last = i + _CHUNK >= len(pcm)
            if last:
                await ws.send(_frame(_AUDIO_ONLY, _LAST_NO_SEQ, chunk))
            else:
                await ws.send(_frame(_AUDIO_ONLY, _POS_SEQ, chunk, seq))
                seq += 1
        watch.mark("send_pcm")
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                msg = _parse(bytes(raw))
                logger.warning("asr msg: %s", msg)
                text = _extract_text(msg)
                if text:
                    texts.append(text)
                    if _is_definite(msg):
                        break
                    break
        except TimeoutError:
            pass
        except websockets.exceptions.ConnectionClosed:
            pass
        watch.mark("recv_result")
    final = texts[-1] if texts else ""
    watch.log(text=final or "(empty)")
    return final


class VolcAsrSession:
    """Keep one Volc async WS open while the user is speaking."""

    def __init__(self) -> None:
        self.ws: Any = None
        self.seq = 2
        self.latest = ""
        self._definite = asyncio.Event()
        self._pump_task: asyncio.Task[None] | None = None
        self._t0 = time.perf_counter()

    async def start(self) -> None:
        self._t0 = time.perf_counter()
        url = _volc_url(stream=True)
        self.ws = await websockets.connect(
            url,
            additional_headers=_auth_headers(),
            max_size=8 * 1024 * 1024,
            open_timeout=6,
            compression=None,
        )
        init = {
            "user": {"uid": "lulu-desktop"},
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
                "language": "zh-CN",
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": True,
                "show_utterances": True,
                "result_type": "single",
            },
        }
        await self.ws.send(
            _frame(_FULL_CLIENT, _POS_SEQ, json.dumps(init, ensure_ascii=False).encode("utf-8"), 1)
        )
        first = _parse(await asyncio.wait_for(self.ws.recv(), timeout=6))
        logger.warning(
            "[timing] asr_stream init=%.0fms ack=%s",
            (time.perf_counter() - self._t0) * 1000,
            first,
        )
        self._pump_task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        assert self.ws is not None
        try:
            while True:
                raw = await self.ws.recv()
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                msg = _parse(bytes(raw))
                logger.warning("asr stream msg: %s", msg)
                text = _extract_text(msg)
                if text:
                    self.latest = text
                if _is_definite(msg) or msg.get("is_last_package"):
                    self._definite.set()
                    return
        except Exception:
            self._definite.set()

    async def send_audio(self, pcm: bytes, last: bool = False) -> None:
        if self.ws is None:
            return
        if not pcm and not last:
            return
        payload = pcm or b"\x00\x00"
        if last:
            await self.ws.send(_frame(_AUDIO_ONLY, _LAST_NO_SEQ, payload))
            return
        await self.ws.send(_frame(_AUDIO_ONLY, _POS_SEQ, payload, self.seq))
        self.seq += 1

    async def finish(self) -> str:
        t1 = time.perf_counter()
        await self.send_audio(b"\x00" * 640, last=True)
        try:
            await asyncio.wait_for(self._definite.wait(), timeout=2.5)
        except TimeoutError:
            pass
        logger.warning(
            "[timing] asr_stream finish wait=%.0fms session=%.0fms text=%s",
            (time.perf_counter() - t1) * 1000,
            (time.perf_counter() - getattr(self, "_t0", t1)) * 1000,
            self.latest,
        )
        return self.latest

    async def close(self) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
            self._pump_task = None
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None


async def recognize_pcm16(pcm: bytes, mode: str = "wake") -> str:
    """16kHz / 16bit / mono PCM → 文本。"""
    if not pcm:
        return ""
    settings = get_settings()
    if not settings.asr_enabled:
        raise RuntimeError("asr disabled")

    global _volc_available
    t0 = time.perf_counter()
    if _volc_available is not False:
        try:
            text = await _recognize_volc(pcm)
            _volc_available = True
            logger.warning("[timing] asr_engine=volc mode=%s text=%s total=%.0fms", mode, text, (time.perf_counter() - t0) * 1000)
            return text
        except Exception as exc:
            logger.warning(
                "[timing] asr_engine=volc_fail mode=%s elapsed=%.0fms err=%s",
                mode,
                (time.perf_counter() - t0) * 1000,
                exc,
            )
            if _is_unavailable(exc):
                _volc_available = False
                logger.warning("volc asr unavailable, using windows sapi: %s", exc)
            else:
                logger.warning("volc asr failed, try windows sapi: %s", exc)

    t1 = time.perf_counter()
    text = await asyncio.to_thread(recognize_windows, pcm, mode)
    logger.warning("[timing] asr_engine=windows mode=%s text=%s total=%.0fms", mode, text, (time.perf_counter() - t1) * 1000)
    return text
