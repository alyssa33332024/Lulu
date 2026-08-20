"""
火山方舟最小连通性检查（文本 Chat Completions）。
用法（在 lulu-agent 目录）:
  pip install openai
  # 确保已设置 ARK_API_KEY，或依赖同目录 .env（需自行 load_dotenv）
  python scripts/smoke_ark.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

from openai import OpenAI


def main() -> int:
    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        print("缺少 ARK_API_KEY", file=sys.stderr)
        return 1

    base_url = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    model = os.getenv("ARK_CHAT_MODEL", "doubao-seed-2-1-pro-260628")

    client = OpenAI(base_url=base_url, api_key=api_key)
    # 文本对话用 chat.completions；产品主路径不依赖 responses + input_image
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是 LuLu，回复一两句口语即可。"},
            {"role": "user", "content": "你好，用一句话介绍你自己。"},
        ],
        max_tokens=64,
    )
    print(resp.choices[0].message.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
