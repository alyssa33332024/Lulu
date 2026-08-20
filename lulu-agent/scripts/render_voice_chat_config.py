# -*- coding: utf-8 -*-
"""Render StartVoiceChat JSON from env + example yaml (for console / OpenAPI)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
load_dotenv(REPO_ROOT / ".env")
load_dotenv(ROOT / ".env")


def _sub(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        return os.getenv(m.group(1), m.group(0))

    return re.sub(r"\$\{([A-Z0-9_]+)\}", repl, text)


def main() -> int:
    src = ROOT / "configs" / "start_voice_chat.example.yaml"
    raw = _sub(src.read_text(encoding="utf-8"))
    data = yaml.safe_load(raw)
    out = ROOT / "configs" / "start_voice_chat.generated.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print("LLM URL =", data.get("Config", {}).get("LLMConfig", {}).get("URL"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
