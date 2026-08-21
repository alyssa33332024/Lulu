# LuLu

桌面陪伴：门户打开桌宠，喊「露露」唤醒；闲聊、唱歌、设提醒。

```text
门户  lulu-portal
桌宠  Lulu-archive/desktop  Electron 窗口
大脑  lulu-agent            FastAPI :8000
```

密钥只放仓库根目录 **`.env`**（从 `.env.example` 复制）。不要提交 `.env`、`.venv`、`node_modules`、千问模型权重。

---

## 大脑方案

入口是 `lulu-agent`：桌宠把一句用户话打到 `/api/turn` 或 `/api/turn/stream`，由 `LuluTurnHarness` 跑完一整轮。语音走火山 ASR / TTS；认人、人设、记忆、路由、闲聊草稿、技能 Agent 都在这一轮里完成。

### 一轮对话

1. **安全 / 快路径**：敏感内容直接拦截；「你好」「露露」这类短问候走缓存 TTS，不再调模型。
2. **认人 + 人设**：无声纹时挂到默认主人（`dev_self`）。人设卡来自 `prompts/characters`（初见 / 熟络 / 活泼，按互动解锁）。
3. **会话压缩**：进模型前按 Akashic 口径做 token Gate（窗口约 74% 触发），超了就摘要更早轮次、保留最近原文。
4. **三路并行**
   - 记忆：读 `MEMORY.md` + 按当前句检索 memory2
   - 意图：本地语料 RAG → 路由（闲聊 / 唱歌 / 提醒）
   - 闲聊草稿：等记忆回来后，用 Mini 先写一句口语（技能路由确定后草稿丢掉）
5. **出口**
   - `chat`：用草稿；失败则短兜底
   - `agents`：专职子 Agent 调工具（点歌 / 设提醒；双意图可并行或先后，带一句协调语）
6. **落库 + TTS**：回复落会话；压缩与记忆归档挪出首包路径。流式接口按句切，桌宠可先开口再等全文。

```text
用户话
  ├─ 记忆（MEMORY.md + memory2 召回）  ─┐
  ├─ 意图 RAG             → 路由                  ─┤ 并行
  └─ 闲聊草稿（等记忆）                 ─┘
                            │
                            ├─ chat    → 闲聊
                            └─ agents  → 唱歌/提醒

定时 Optimizer（约 18h）：PENDING → MEMORY.md
```

### 模型怎么分

| 用途 | 默认 | 说明 |
|------|------|------|
| 闲聊草稿 | 方舟 Mini `doubao-seed-2-0-mini-260428` | `CHAT_DRAFT_BACKEND=ark`，**thinking 关闭** |
| 技能 Agent | 同上 Mini | `CHAT_AGENT_BACKEND=ark`，thinking 同样关闭；提醒最多 3 次工具调用 |
| 意图路由（含糊时） | Mini JSON，或本机 Ollama | 有「唱 / 歌 / 提醒」等关键词时启发式直接定，不调 LLM |
| 主对话模型 | 同上 Mini `doubao-seed-2-0-mini-260428` | `ARK_CHAT_MODEL`，记忆压缩 / Optimizer；thinking 关闭 |
| 意图向量 | 本地 HashingEmbedder | `ARK_EMBEDDING_MODEL` 为空时不走方舟向量 |

意图复核也可改 `INTENT_MODEL_BACKEND=ollama`，用本机 `qwen2.5:3b`。

### 意图路由

语料在 `lulu-agent/data/intent_corpus.csv`。检索是 **dense + BM25 → RRF 融合**，再按关键词加权。路由只产出 `chat` 或 `agents`（`sing` / `reminder`），不抽歌名、时刻——槽位留给下游 Agent。

### 技能 Agent

框架是单向 DAG：一个 Agent 只挂一个 Skill，工具跑完再说话。

| Agent | Skill | 工具 |
|-------|-------|------|
| 唱歌 | `skills/sing/SKILL.md` | `SearchSongCatalog` → `PlaySong`（本地曲库） |
| 提醒 | `skills/reminder/SKILL.md` | `ParseDateTool` → `FlexibleScheduleReminder` |

发给模型的两条 system：人设卡 + 公共限制 + 长期记忆；再拼 Skill。历史带时间信封（今天 / 昨天 / 明天…）。细节见 `lulu-agent/prompts/README.md`。

### 记忆（Akashic 口径）

人设不进记忆文件，仍用角色卡。每人一份目录：`lulu-agent/data/memory_workspaces/{person_id}/memory/`。

| 层 | 作用 |
|----|------|
| `MEMORY.md` | 稳定长期记忆，注入人设旁的 person 块 |
| memory2 | 可检索记忆卡，本轮按 query 召回 |
| `PENDING.md` | 压缩后先归档到这里，不立刻改 MEMORY |
| Optimizer | 默认约 18 小时，PENDING 合并进 MEMORY / SELF |

压缩阈值：`soft ≈ context_window × 0.74`，尾部约保留 2 万 token 原文。库文件不进 Git。实现说明见 `lulu-agent/docs/akashic-memory-port.md`。

### 语音

桌宠本机唤醒后，PCM 送到 `/api/asr`（火山流式识别）；回复走 `/api/tts` 或句级流式合成。说话人是 `TTS_SPEAKER`。可选 RTC 把大脑当自定义 LLM（`CUSTOM_LLM_PUBLIC_URL`）。声纹认人尚未接上，`VOICEPRINT_ENABLED` 现在不起作用。

---

## 本机使用

```bash
copy .env.example .env
# 至少填 ARK_API_KEY，以及语音相关变量

cd lulu-portal
npm install
npm start
```

浏览器打开，点「打开桌宠」。会同时拉起大脑和 Electron。

单独跑大脑（调试）：

```bash
cd lulu-agent
python -m venv .venv
.\.venv\Scripts\activate
pip install -r ..\requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

测试（全部离线，`AI_PROVIDER=mock` + 独立 sqlite，不碰真实库与 Ark）：

```bash
cd lulu-agent
python -m unittest discover -s tests -t .
```

单跑工程验收（11 个 suite：安全、路由、技能、RAG 命中率、草稿门、身份、角色解锁、API、整轮、流式、记忆）：

```bash
cd lulu-agent
python -m app.harness.runner --suite all
python -m app.harness.runner --suite turn --suite memory   # 也可只跑其中几个
```

---

## Docker（仅大脑）

需已安装 Docker，且根目录有 `.env`。

```bash
docker compose up -d --build
```

映射 `8000`。桌宠仍在本机开，连 `127.0.0.1:8000`。不要和门户再启一份本机 uvicorn 抢端口。

可选本机 Ollama：`docker compose --profile ollama up -d --build`。上云闲聊走方舟时不必开。

---

## 目录

| 路径 | 作用 |
|------|------|
| `lulu-portal/` | 落地页，启动桌宠 |
| `Lulu-archive/desktop/` | 桌宠窗口 |
| `lulu-agent/` | 大脑（见上文「大脑方案」） |
| `.env` / `.env.example` | 环境变量 |
| `requirements.txt` | 大脑 Python 依赖 |
| `Dockerfile` / `docker-compose.yml` | 大脑容器 |

人设在 `lulu-agent/prompts/characters`。记忆数据在 `lulu-agent/data`（库文件不进 Git）。可选千问权重在 `lulu-agent/models`（不进 Git）。
