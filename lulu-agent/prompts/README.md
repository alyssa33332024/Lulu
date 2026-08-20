# 子 Agent Prompt 拼装（显式对照）

发给模型的两条 system，对应产品模板：

## system 1 — 人设共享前缀

1. `characters/cards/*.md`（人设，含 `{{ speaker_block }}` 眼前是谁）
2. `common_limit.md`（公共限制）
3. `context/person.md`（长期记忆 = MEMORY.md；本轮检索走 context frame，不在此文件）

## system 2 — Skill + 可选上下文

1. `skills/{sing|reminder}/SKILL.md`
2. `context/env.md`（可选：客户端设备信息 / RAG 外部知识）

## 之后

- history：会话摘要 + 未压缩原文尾（token Gate 后的 live 窗口）
- **context frame**（可选）：`retrieved_memory`（role=user + `<system-reminder>`）
- user：当前 query，前缀 **时间信封**（`stamp_user_message`，与 akashic 一致）

时间锚点格式示例：

```text
[当前消息时间: 2026-08-19 16:36:00 CST | request_time=… | 今天=… | 昨天=… | 明天=… | 后天=… | 相对时间以此为准]
那考试是哪天来着？
```

认人模板：`speaker.md` / `speaker_guest.md` → 填进人设卡的 `{{ speaker_block }}`。

记忆抽取 prompt 真源在 `app/memory/`（markdown / default_engine / optimizer），不再使用每轮 L2/L3 extract。
