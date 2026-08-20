from __future__ import annotations

import base64
import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GREET_REPLY = "我在呢，你说。"
_greet_lock = threading.Lock()
_greet_audio: bytes | None = None

_client_lock = threading.Lock()
_http_client: httpx.Client | None = None


def _shared_client() -> httpx.Client:
    """进程级 keep-alive：避免每轮 TTS 重新 TLS 握手。"""
    global _http_client
    with _client_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = httpx.Client(
                timeout=httpx.Timeout(30.0, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
            )
        return _http_client


class VoiceService:
    """Volcengine TTS: try V3 (X-Api-Key) then V1 (AppId/AppKey)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.last_error: str | None = None

    def synthesize(self, text: str) -> bytes | None:
        audio = bytearray()
        for chunk in self.iter_mpeg_chunks(text):
            audio.extend(chunk)
        return bytes(audio) if audio else None

    def audio_b64(self, text: str) -> str | None:
        t0 = time.perf_counter()
        raw = self.synthesize(text)
        logger.warning(
            "[timing] tts chars=%s audio_bytes=%s err=%s total=%.0fms",
            len(text or ""),
            len(raw or b""),
            self.last_error,
            (time.perf_counter() - t0) * 1000,
        )
        if not raw:
            return None
        return base64.b64encode(raw).decode("ascii")

    def warmup(self) -> None:
        """启动预热：建连 + 问候缓存，把首轮握手挪出用户路径。"""
        _shared_client()
        self.warmup_greet()

    def warmup_greet(self) -> None:
        global _greet_audio
        with _greet_lock:
            if _greet_audio is None:
                _greet_audio = self.synthesize(GREET_REPLY)

    def cached_greet_bytes(self) -> bytes | None:
        t0 = time.perf_counter()
        hit = _greet_audio is not None
        self.warmup_greet()
        logger.warning(
            "[timing] tts_greet cache_hit=%s total=%.0fms",
            hit,
            (time.perf_counter() - t0) * 1000,
        )
        return _greet_audio

    def cached_greet_b64(self) -> str | None:
        raw = self.cached_greet_bytes()
        if not raw:
            return None
        return base64.b64encode(raw).decode("ascii")

    def iter_mpeg_chunks(self, text: str) -> Iterator[bytes]:
        if not self.settings.tts_enabled:
            return
        text = (text or "").strip()[:300]
        if not text:
            return
        yielded = False
        for chunk in self._iter_tts_v3(text):
            yielded = True
            yield chunk
        if yielded:
            return
        fallback = self._tts_v1(text)
        if fallback:
            yield fallback

    def _iter_tts_v3(self, text: str) -> Iterator[bytes]:
        # Prefer 豆包语音 AppId + AccessToken; Agent Plan ark Key often lacks TTS grant.
        app_id = (
            self.settings.speech_tts_app_id
            or self.settings.speech_app_id
            or self.settings.rtc_app_id
        )
        access = (
            self.settings.speech_tts_access_token
            or self.settings.speech_app_key
            or self.settings.rtc_app_key
        )
        headers = {
            "X-Api-Request-Id": str(uuid.uuid4()),
            "Content-Type": "application/json",
            "X-Api-Resource-Id": self.settings.tts_resource_id,
        }
        if app_id and access:
            headers["X-Api-App-Key"] = app_id
            headers["X-Api-Access-Key"] = access
        elif self.settings.speech_api_key:
            headers["X-Api-Key"] = self.settings.speech_api_key
        else:
            self.last_error = "no_speech_credentials"
            return

        body = {
            "user": {"uid": "lulu"},
            "req_params": {
                "text": text,
                "speaker": self.settings.tts_speaker,
                "audio_params": {"format": "mp3", "sample_rate": 24000},
            },
        }
        url = self.settings.speech_tts_base_url or "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
        try:
            client = _shared_client()
            with client.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code >= 400:
                    self.last_error = f"v3_{resp.status_code}:{resp.read()[:200]!r}"
                    return
                buf = ""
                for chunk in resp.iter_text():
                    buf += chunk
                    while True:
                        try:
                            obj, idx = json.JSONDecoder().raw_decode(buf)
                        except json.JSONDecodeError:
                            break
                        buf = buf[idx:].lstrip()
                        data = obj.get("data")
                        if isinstance(data, str) and data:
                            self.last_error = None
                            yield base64.b64decode(data)
        except Exception as exc:
            self.last_error = f"v3_exc:{exc}"
            return

    def _tts_v1(self, text: str) -> bytes | None:
        app_id = self.settings.speech_app_id or self.settings.rtc_app_id
        token = self.settings.speech_app_key or self.settings.rtc_app_key
        if not app_id or not token:
            return None
        headers = {
            "Authorization": f"Bearer;{token}",
            "Content-Type": "application/json",
        }
        body = {
            "app": {"appid": app_id, "token": token, "cluster": self.settings.tts_cluster},
            "user": {"uid": "lulu"},
            "audio": {
                "voice_type": self.settings.tts_speaker,
                "encoding": "mp3",
                "speed_ratio": 1.0,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "query",
            },
        }
        try:
            resp = _shared_client().post(
                "https://openspeech.bytedance.com/api/v1/tts",
                headers=headers,
                json=body,
            )
            data = resp.json()
            if resp.status_code >= 400 or data.get("code", 0) not in (0, 3000, None):
                if "data" not in data:
                    self.last_error = f"v1:{resp.status_code}:{data}"
                    return None
            b64 = data.get("data")
            if not b64:
                self.last_error = f"v1_no_data:{data}"
                return None
            self.last_error = None
            return base64.b64decode(b64)
        except Exception as exc:
            self.last_error = f"v1_exc:{exc}"
            return None
