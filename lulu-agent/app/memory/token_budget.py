"""Context token budget — aligned with Akashic ContextCompactor.

soft = floor(context_window * 0.74)
hard = context_window - max_output_tokens
estimate ≈ text_chars // 3 (+ tools JSON // 3)
"""

from __future__ import annotations

import json
import math
from typing import Any

SOFT_LIMIT_RATIO = 0.74
KEEP_RECENT_TOKENS = 20_000


def soft_input_limit(context_window: int) -> int:
    cw = int(context_window)
    if cw <= 0:
        return 0
    return math.floor(cw * SOFT_LIMIT_RATIO)


def hard_input_limit(context_window: int, max_output_tokens: int) -> int:
    cw = int(context_window)
    if cw <= 0:
        raise ValueError("context_window 必须是正整数")
    if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool):
        raise ValueError("max_output_tokens 必须是整数")
    if max_output_tokens < 0 or max_output_tokens >= cw:
        raise ValueError("max_output_tokens 必须在 [0, context_window) 内")
    return cw - max_output_tokens


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    """与 Akashic provider._estimate_message_tokens 同口径（chars//3）。"""
    if not messages:
        return 0
    text_chars = 0
    image_tokens = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") in {
                    "image_url",
                    "input_image",
                }:
                    detail = block.get("detail")
                    image = block.get("image_url")
                    if isinstance(image, dict):
                        detail = image.get("detail", detail)
                    image_tokens += 1024 if detail == "low" else 8192
                    continue
                text_chars += len(
                    json.dumps(block, ensure_ascii=False, separators=(",", ":"))
                )
        elif content is not None:
            text_chars += len(str(content))
        text_chars += len(
            json.dumps(
                {k: v for k, v in message.items() if k != "content"},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return max(1, text_chars // 3 + image_tokens)


def estimate_context_tokens(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    system_prompt: str = "",
) -> int:
    full = list(messages)
    if system_prompt and (not full or full[0].get("role") != "system"):
        full = [{"role": "system", "content": system_prompt}, *full]
    fixed = 0
    if tools:
        fixed = len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")))
    return max(1, fixed // 3 + estimate_message_tokens(full))


def split_keep_recent_by_tokens(
    messages: list[dict[str, Any]],
    *,
    keep_recent_tokens: int = KEEP_RECENT_TOKENS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从尾部保留约 keep_recent_tokens；更早部分作为待压缩前缀。"""
    if not messages:
        return [], []
    keep = max(1, int(keep_recent_tokens))
    acc = 0
    cut = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        acc += estimate_message_tokens([messages[i]])
        cut = i
        if acc >= keep:
            break
    # 至少留 1 条在 retained，避免整窗被压空
    if cut == 0 and len(messages) > 1 and acc < keep:
        return [], messages
    if cut >= len(messages):
        return [], messages
    if cut == 0:
        # 单条就超 keep：仍保留最后一条
        return messages[:-1], messages[-1:]
    return messages[:cut], messages[cut:]
