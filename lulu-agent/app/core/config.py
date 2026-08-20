from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "lulu-agent"
    debug: bool = True

    # SQLite by default so MVP runs without Docker MySQL
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'lulu.db').as_posix()}"

    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_chat_model: str = "doubao-seed-2-1-pro-260628"
    # 方舟 Flash：闲聊草稿 / 技能 Agent（CHAT_DRAFT_BACKEND / CHAT_AGENT_BACKEND=ark）
    ark_chat_fast_model: str = "doubao-seed-2-0-mini-260428"
    # 兼容旧名：未设 CHAT_DRAFT_BACKEND 时回落于此
    chat_fast_backend: str = "ark"  # ark | ollama
    # 闲聊草稿：ark | ollama
    chat_draft_backend: str = "ark"
    # 技能 Agent：ark | ollama（长提示 + 工具，本机小模型易卡）
    chat_agent_backend: str = "ark"
    # ollama 模型名；空则回落 intent_model_name
    chat_fast_ollama_model: str = ""
    # 方舟 embedding：文本模型走 /embeddings；含 vision/multimodal 走 /embeddings/multimodal
    ark_embedding_model: str = ""
    # 本地向量模型（可选，如 bge-m3）；空则跳过。本机 Ollama GPU 不可用时保持空
    ollama_embedding_model: str = ""

    # Speech (Volcengine openspeech / Ark API Key)
    speech_api_key: str = ""
    speech_app_id: str = ""
    speech_app_key: str = ""
    speech_asr_app_id: str = ""
    speech_asr_access_token: str = ""
    speech_tts_app_id: str = ""
    speech_tts_access_token: str = ""
    speech_tts_base_url: str = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
    speech_asr_base_url: str = ""
    tts_resource_id: str = "seed-tts-2.0"
    tts_speaker: str = "saturn_zh_female_tiaopigongzhu_tob"
    tts_cluster: str = "volcano_tts"
    asr_resource_id: str = "volc.seedasr.sauc.duration"
    asr_enabled: bool = True
    tts_enabled: bool = True
    voiceprint_enabled: bool = False
    # RTC（实时对话式 AI / 进房）
    rtc_app_id: str = ""
    rtc_app_key: str = ""
    custom_llm_api_key: str = "lulu-custom-llm-local"
    custom_llm_public_url: str = "http://127.0.0.1:8000"
    volc_access_key_id: str = ""
    volc_secret_access_key: str = ""

    intent_model_backend: str = "ark_json"  # ollama | ark_json
    intent_model_name: str = "mindbridge-qwen2.5-7b-ft"
    ollama_host: str = "http://127.0.0.1:11434"
    intent_min_score: float = 0.55

    # 并行阶段的等待上限：召回不拖路由，草稿超时就当失败
    recall_timeout_ms: int = 800
    draft_timeout_ms: int = 8000

    # 子 Agent 工具调用预算；reminder 需 ParseDate + Schedule 两步，多留一次
    tool_calls_max: int = 2
    tool_calls_max_reminder: int = 3

    # False：每轮都跑 chat 草稿；True：命中唱/提醒等关键词时跳过草稿（省一次调用）
    draft_gate_enabled: bool = False
    max_history_messages: int = 12
    # 无 person_id 时挂到默认「主人」；有声纹后上游传各 person_id
    sole_member_fallback: bool = True
    force_card_id: str | None = None

    # 记忆：会话压缩（Akashic token Gate）+ 归档（app/memory）
    # soft = floor(context_window * 0.74)；保留约 keep_recent_tokens 原文尾
    context_keep_recent_tokens: int = 20000
    context_max_output_tokens: int = 4096

    # 融合记忆（characters 仍是人设真源）
    memory_backend: str = "akashic"
    akashic_memory_root: Path = ROOT / "data" / "memory_workspaces"
    akashic_context_window: int = 128000
    # False（默认）：对齐 Akashic — 压缩只写 PENDING/memory2，MEMORY 交给定时 Optimizer
    # True：调试/急用时可压缩后立刻 PENDING→MEMORY（多一次 LLM）
    akashic_optimizer_on_compress: bool = False
    akashic_optimizer_enabled: bool = True
    akashic_optimizer_interval_seconds: int = 64800  # 18h

    speaker_template: Path = ROOT / "prompts" / "speaker.md"
    speaker_guest_template: Path = ROOT / "prompts" / "speaker_guest.md"

    songs_config: Path = ROOT / "configs" / "songs.yaml"
    character_catalog: Path = ROOT / "prompts" / "characters" / "catalog.yaml"
    # Skill 配置目录（对齐 mindbridge-py 的 skills/；≠ app/agents 运行时）
    skills_dir: Path = ROOT / "skills"
    safety_path: Path = ROOT / "configs" / "safety.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
