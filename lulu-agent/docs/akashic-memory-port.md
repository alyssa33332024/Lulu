# Lulu 记忆系统（融合 Akashic）

人设仍用 [`prompts/characters`](../prompts/characters/)（≈ VEDA，不迁 Akashic 人格文件）。

其余记忆能力已融入 [`app/memory/`](../app/memory/)，不再使用 `third_party/` 或每轮 L2/L3 抽取。

## 包结构

| 路径 | 职责 |
|------|------|
| `app/memory/md_store.py` | MEMORY / PENDING / SELF 文件 |
| `app/memory/markdown.py` | 压缩批次 → event + PENDING 抽取 |
| `app/memory/implicit_extract.py` | 隐式 profile/preference/procedure |
| `app/memory/token_budget.py` | soft≈74% / hard / keep_recent / chars÷3 估 token |
| `app/memory/compaction_ledger.py` | `session_compactions` / prepares 账本 |
| `app/memory/optimizer.py` | PENDING → MEMORY + SELF |
| `app/memory/optimizer_runtime.py` | 多用户定时 Optimizer（默认 18h） |
| `app/memory/memory2/` | 可检索记忆卡 |
| `app/memory/facade.py` | Harness 接线（person_id） |
| `app/services/context.py` | 会话 token Gate + 摘要 |

Prompt 真源在 `app/memory/*.py` 内嵌字符串。

## 运行时闭环

1. **注入**：`MEMORY.md` → `person.md`；memory2 召回 → retrieved_memory context frame
2. **压缩（token Gate + ledger）**：与 Akashic 同口径  
   - `soft = floor(context_window × 0.74)`  
   - `hard = context_window − max_output_tokens`  
   - 估 token ≈ `chars // 3`  
   - 超 soft/hard 时从尾部保留约 `keep_recent_tokens`，更早轮次摘要  
   - 每次压缩 **INSERT 不可变 generation** 到 `session_compactions`（先 `session_compaction_prepares` fence）  
   - 游标：`chat_sessions.summary` / `summary_message_count` / `last_compaction_generation`  
   - **进模型前**与落库后都会跑 Gate
3. **归档**：`consolidate_compressed_batch` → **PENDING + memory2**（不写 MEMORY.md）
4. **定时 Optimizer**：`MultiPersonOptimizerLoop`（默认约 18h）PENDING → MEMORY/SELF
5. **身份**：`IdentityService`（表 `memory_items`）；无称呼时从 MEMORY.md 粗提

每人目录：`data/memory_workspaces/{person_id}/memory/`

角色卡：`prompts/characters` 不变。

会话游标与账本：`chat_sessions` 上的 summary 字段 + 表 `session_compactions` / `session_compaction_prepares`（对齐 Akashic 多代不可变 checkpoint）。

## 配置（`app/core/config.py` / `.env`）

| 键 | 默认 | 说明 |
|----|------|------|
| `memory_backend` | `akashic` | 记忆主路径 |
| `akashic_context_window` | `128000` | 上下文窗口；soft=⌊×0.74⌋ |
| `context_keep_recent_tokens` | `20000` | 压缩后保留的原文尾 token 预算 |
| `context_max_output_tokens` | `4096` | hard = window − 此项 |
| `akashic_optimizer_on_compress` | `false` | 压缩后立刻 Optimizer（调试） |
| `akashic_optimizer_enabled` | `true` | 启动定时 Optimizer |
| `akashic_optimizer_interval_seconds` | `64800` | 约 18 小时 |
