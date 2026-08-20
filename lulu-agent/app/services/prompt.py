from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.core.config import ROOT, get_settings

SKILL_KEYWORDS = [
    "唱",
    "歌",
    "提醒",
    "闹钟",
    "日程",
    "开会",
]

PROMPTS_DIR = ROOT / "prompts"
PERSON_CONTEXT_PATH = PROMPTS_DIR / "context" / "person.md"
ENV_CONTEXT_PATH = PROMPTS_DIR / "context" / "env.md"

_IF_BLOCK = re.compile(
    r"\{%\s*if\s+(\w+)\s*%\}(.*?)\{%\s*endif\s*%\}",
    re.DOTALL,
)


def _render_optional_template(template: str, values: dict[str, str | None]) -> str:
    """渲染 {{ var }} 与 {% if var %}...{% endif %}；空值整块去掉。"""

    def replace_if(match: re.Match[str]) -> str:
        key = match.group(1)
        body = match.group(2)
        value = (values.get(key) or "").strip()
        if not value:
            return ""
        return body.replace(f"{{{{ {key} }}}}", value).replace(f"{{{{{key}}}}}", value)

    text = _IF_BLOCK.sub(replace_if, template)
    for key, value in values.items():
        token = f"{{{{ {key} }}}}"
        text = text.replace(token, (value or "").strip())
    # 去掉因空 if 留下的多余空行，保留结构
    lines = [line.rstrip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    text = "\n".join(out).strip()
    # 只有标题、没有任何字段时不注入
    if text in {"上下文信息", "## 长期记忆"}:
        return ""
    return text


def _load_template(path: Path, fallback: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


class PromptTemplates:
    """共享 prompt 模板：文案在 prompts/context/，此处负责加载与渲染。"""

    @staticmethod
    def person_context_block(
        *,
        long_term_memory: str | None = None,
        # 兼容旧调用；retrieved 不再进 system，见 build_retrieved_memory_frame
        retrieved_memory: str | None = None,
        user_profile: str | None = None,
        preferences: str | None = None,
    ) -> str:
        """system 末尾：prompts/context/person.md — 仅稳定长期记忆（MEMORY.md）。

        本轮检索记忆走 context frame（role=user + system-reminder），不放这里。
        """
        del retrieved_memory, preferences  # 检索块改走 context frame
        if not long_term_memory and user_profile:
            long_term_memory = user_profile
        template = _load_template(
            PERSON_CONTEXT_PATH,
            "## 长期记忆\n{% if long_term_memory %}{{ long_term_memory }}{% endif %}\n",
        )
        text = _render_optional_template(
            template,
            {"long_term_memory": long_term_memory},
        )
        if text == "## 长期记忆":
            return ""
        return text

    @staticmethod
    def retrieved_memory_frame(retrieved_memory: str | None = None) -> dict[str, str] | None:
        """本轮检索记忆 → history 与真 user 之间的 context frame。"""
        from app.memory.prompting import build_retrieved_memory_frame

        return build_retrieved_memory_frame(retrieved_memory)

    @staticmethod
    def context_block(*, env_context: str | None = None, document_context: str | None = None) -> str:
        """第二条 system 末尾：对应该文件 prompts/context/env.md（设备/外部知识；时间走 user 时间信封）。"""
        template = _load_template(
            ENV_CONTEXT_PATH,
            "上下文信息\n"
            "{% if env_context %}用户当前环境信息：{{ env_context }}{% endif %}\n"
            "{% if document_context %}与问题相关的外部知识：{{ document_context }}{% endif %}\n",
        )
        return _render_optional_template(
            template,
            {"env_context": env_context, "document_context": document_context},
        )

    @staticmethod
    def reminder_complete_nudge() -> str:
        return "请立刻调用 FlexibleScheduleReminder 完成设置，不要只解析日期。"

    @staticmethod
    def final_say_prompt() -> str:
        return "用一两句口语告诉我结果，不要再调工具。"


class PromptService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._catalog = self._load_catalog()
        limit_path = Path(self.settings.character_catalog).parent.parent / "common_limit.md"
        self.common_limit = (
            limit_path.read_text(encoding="utf-8")
            if limit_path.exists()
            else "不要输出格式符号。口语短句。不要说工作流程。"
        )

    def _load_catalog(self) -> dict:
        path = self.settings.character_catalog
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {"default_card_id": "default", "cards": []}

    def _read_card(self, rel: str) -> str:
        base = self.settings.character_catalog.parent
        return (base / rel).read_text(encoding="utf-8")

    def render_card(self, card_id: str, *, speaker_block: str) -> str:
        card = next((c for c in self._catalog.get("cards") or [] if c.get("id") == card_id), None)
        rel = (card or {}).get("prompt") or "cards/default.md"
        text = self._read_card(rel).strip()
        block = (speaker_block or "").strip() or "（暂不确定对方是谁）"
        text = text.replace("{{ speaker_block }}", block)
        # 兼容旧卡
        text = text.replace("{{ user_block }}", block).rstrip()
        return text

    def render_character(self, *, card_id: str, speaker_block: str) -> tuple[str, str]:
        return self.render_card(card_id, speaker_block=speaker_block), card_id

    def should_skip_draft(self, query: str) -> bool:
        if not self.settings.draft_gate_enabled:
            return False
        return any(k in query for k in SKILL_KEYWORDS)
