# LuLu

桌面陪伴：门户打开桌宠，喊「露露」唤醒；闲聊、唱歌、设提醒。

```text
门户  lulu-portal          
桌宠  Lulu-archive/desktop 
大脑  lulu-agent         
```

密钥只放仓库根目录 **`.env`**（从 `.env.example` 复制）。不要提交 `.env`、`.venv`、`node_modules`、千问模型权重。

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
| `lulu-agent/` | 大脑（FastAPI、记忆、技能） |
| `.env` / `.env.example` | 环境变量 |
| `requirements.txt` | 大脑 Python 依赖 |
| `Dockerfile` / `docker-compose.yml` | 大脑容器 |

人设在 `lulu-agent/prompts/characters`。记忆数据在 `lulu-agent/data`（库文件不进 Git）。可选千问权重在 `lulu-agent/models`（不进 Git）。
