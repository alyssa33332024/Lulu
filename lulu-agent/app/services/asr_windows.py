from __future__ import annotations

import logging
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

_PS1 = Path(__file__).with_name("asr_windows.ps1")


def _pcm_to_wav_file(pcm: bytes, rate: int = 16000) -> Path:
    pad = bytes(int(rate * 0.12) * 2)
    body = pad + pcm + pad
    tmp = tempfile.NamedTemporaryFile(prefix="lulu-asr-", suffix=".wav", delete=False)
    tmp.close()
    path = Path(tmp.name)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(body)
    return path


class _SapiProcess:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        creation = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation = subprocess.CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(_PS1),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation,
        )
        assert self._proc.stdout is not None
        ready = self._proc.stdout.readline().strip()
        if ready != "READY":
            raise RuntimeError(f"windows sapi start failed: {ready!r}")
        logger.info("windows sapi helper ready")

    def recognize(self, pcm: bytes, mode: str) -> str:
        wav = _pcm_to_wav_file(pcm)
        try:
            with self._lock:
                if self._proc.poll() is not None:
                    raise RuntimeError("windows sapi helper exited")
                assert self._proc.stdin is not None
                assert self._proc.stdout is not None
                self._proc.stdin.write(f"{mode}|{wav}\n")
                self._proc.stdin.flush()
                line = self._proc.stdout.readline()
            return (line or "").strip()
        finally:
            try:
                wav.unlink(missing_ok=True)
            except OSError:
                pass


_helper: _SapiProcess | None = None
_lock = threading.Lock()


def recognize_windows(pcm: bytes, mode: str = "wake") -> str:
    if not pcm:
        return ""
    global _helper
    with _lock:
        if _helper is None:
            _helper = _SapiProcess()
    return _helper.recognize(pcm, mode)
