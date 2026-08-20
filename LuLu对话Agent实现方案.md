# LuLu陪伴机器人 Agent 实现方案

> 目标：复现讨论中的「意图路由 + **多个**专一子 Agent」对话架构。  
> 产品形态：**陪伴机器人**（实体设备对话），不是纯 App 聊天窗。  
> 本文只给实现方案，不写代码。确认后按阶段落地。

---

## 1. 方案结论（先看这个）

这套系统**不是**带主 Agent 循环规划、反思重试的任务型 Agent。它是一套面向**陪伴机器人实时对话**的 DAG 工作流：

1. **没有主 Agent**。意图识别节点承担「调度」职责。
2. **单向不回头**。Query →（向量召回 ∥ 闲聊草稿生成）→ 路由小模型判定闲聊或技能 → 闲聊直接出草稿 / 技能按序执行子 Agent；**执行结果不再回传给路由模型做二次思考**。
3. **子 Agent 有多条，不是只有提醒一条**。讨论里业务侧至少包含：闲聊、做动作、查天气、讲故事、联网搜索、视觉问答、视觉+搜索、设置提醒。提醒只是你贴出完整 prompt 的**样板之一**，用来示范「子 Agent = 人设 + Skill 规则 + 工具链」。
4. **子 Agent 输出即最终回复**（多意图时按序开口，中间不经总 Agent 润色/重规划）。闲聊路径下，**并行预生成的草稿可直接播出**，不再二次进 ChatAgent 重生成（除非草稿失败）。
5. **默认颗粒度**：`1 子 Agent ≈ 1 Skill ≈ 1 Tool`（一次 function call 结束）；提醒例外（两工具有强制顺序）。
6. **多意图靠路由小模型排顺序，不靠主 Agent 循环**。例如「搜一下再讲个故事」→ 小模型输出 `[search, story]`，执行器按序跑完；不是并行拼车，也不是跑完再回炉思考。
7. 架构选择服从三个业务约束：**回复质量不依赖复杂任务规划、时延 2~3 秒（多意图允许按段拉长）、尽量用小模型控成本**。
8. **陪伴感不靠多跳 Agent，靠 UX 层穿插**。听—想—说全过程可穿插**眼神微动作**，与对话链路并行触发，不单独占一条意图路由。

### 1.1 子 Agent 全景（复现范围）

| # | 子 Agent | 讨论出处 | 本期是否复现 |
|---|---|---|---|
| 1 | ChatAgent 闲聊 | 与向量**并行**预生成草稿；路由判闲聊则直接播出 | ✅ 必做（兜底+快路径） |
| 2 | SingAgent 唱歌 | 「唱一个」多轮指代；与肢体动作分开 | ✅ 必做 |
| 3 | ActionAgent 做动作 | 跳舞、左转、俯卧撑、瑜伽等同一类 | ✅ 必做 |
| 4 | WeatherAgent 查天气 | 查天气意图 + 工具调用样例 | ✅ 必做 |
| 5 | StoryAgent 讲故事 | 业务分类里单独一类 | ✅ 必做 |
| 6 | SearchAgent 联网搜索 | 纯文本搜索子 Agent | ✅ 必做 |
| 7 | VisionQAAgent 视觉问答 | 「十万个为什么」、看图即可 | ✅ 必做 |
| 8 | VisionSearchAgent 视觉+搜索 | 指着空调问品牌价格 | ✅ 必做 |
| 9 | ReminderAgent 设置提醒 | 完整 Skill prompt 样板 | ✅ 必做 |

说明：

- **一次请求由路由小模型给出有序意图列表**（多数时候长度为 1；多任务时按序执行），不是并行跑全部子 Agent。
- **系统里常驻配置的是整张子 Agent 表**；路由输出 `intent_id` 序列后，执行器按序调度。
- 业务侧「跳舞和其他动作」可算同一类 Skill；工程上仍是 **ActionAgent 一个节点**，用工具入参区分具体动作，不为每个动作拆一个 Agent。
- 你贴的 Reminder system prompt = **第 8 号子 Agent 的 Skill 全文**，不是整套系统的唯一 Agent。
- **向量不直接定路**：向量只召回相似说法/候选意图，交给小模型综合判断「用谁、谁先谁后」。

可以把它理解为：**预定义多分支 DAG + 每条分支内部发挥模型智能**。和 Codex / ReAct 的差别不在「是不是 workflow」，而在**对模型智能、时延、成本的容忍度不同**。

---

## 2. 设计原则

| 维度 | 本方案取值 | 原因 |
|---|---|---|
| 产品 | 陪伴机器人（实体对话伙伴） | 体感、眼神、身体动作与对话同等重要 |
| 场景 | 实时语音对话 + 在场陪伴 | 不是长任务、不是写报告、不是纯文本窗 |
| 时延 | 端到端 2~3 秒出可感知反馈 | 对话必须丝滑；等待靠眼神/过渡句消化 |
| 成本 | 路由用小模型，子 Agent 按场景配模型 | 闲聊/路由不需要大参数 |
| 规划 | 无循环、无反思、无主 Agent | 加一跳模型调用就会变慢 |
| 入参 | **不单独做抽槽模块**；工具 schema 交给子 Agent 模型，由 function call 填参 | 传统 NLU 槽位已被 FC 取代；sticky/hint 只是多轮助推 |
| 上下文 | **向量只用当前句**；**路由小模型带最近 1~3 轮** | 解决「那你唱一个」这类指代；长期 Memory 不进路由 |
| 复合意图 | 路由小模型输出有序列表，执行器串行跑完 | 下游不再回传思考，顺序必须在路由阶段定死 |
| 向量角色 | 召回证据，不单独拍板 | 给小模型看「像哪些技能说法」 |
| 眼神微动作 | UX 状态机穿插，不进意图表 | 陪伴感连续在场；不与「做动作」Skill 抢路由 |

---

## 3. 概念分层（必须先分清）

讨论里把几个概念混在一起。实现时按三层切开：

```
用户
  │
  ▼
┌─────────────────────────────────────────┐
│ 应用服务器（业务代码）                     │
│  - 拼环境信息 / 工具列表 / 人设 / 上下文     │
│  - 执行 function call                     │
│  - 调 MCP / 内部 API                      │
└─────────────────────────────────────────┘
  │ Function Call（模型能力 / 应用↔模型协议）
  ▼
┌─────────────────────────────────────────┐
│ 模型服务器                                │
│  - 根据工具描述决定是否调工具               │
│  - 产出 tool_call JSON 或最终回复          │
└─────────────────────────────────────────┘
  │ 工具结果回传到应用，再回传模型
  ▼
┌─────────────────────────────────────────┐
│ 工具层                                    │
│  - MCP：应用 ↔ 第三方工具的协议             │
│  - 内部函数 / HTTP API                    │
└─────────────────────────────────────────┘
```

| 概念 | 作用层 | 影响谁 | 本方案怎么用 |
|---|---|---|---|
| Function Call | 应用 ↔ 模型 | 模型厂商 / 应用如何调模型 | 每个子 Agent 调模型时带 tools schema |
| MCP | 应用 ↔ 第三方工具 | 工具厂商接口形态 | 外部天气、搜索等走 MCP 或等价适配器 |
| Skill | 方法层 / 提示词 | 业务方，不改模型本身 | `SKILL.md`：教模型何时调工具、怎么追问、怎么说话 |
| Tool | 函数 I/O | 工程实现 | 一个可调用函数，有明确入参出参 |
| API | 具体接口 | 服务提供方 | 天气服务、日程服务等 |

**Skill ≠ Tool。**  
Tool 只定义「输入什么、返回什么」。Skill 定义「结合业务目标，按什么方法论一步步用这些工具」。在 LangChain 旧架构里，Skill 约等于「教模型怎么用工具的那段提示词」，并用固定目录规范做渐进式披露。

本方案因为**路由已经选定 Skill**，子 Agent 进入后直接加载对应 `SKILL.md`，**不必再让模型扫一遍全部 Skill 的 frontmatter 来决定用不用**。这是省 token 的关键。

---

## 4. 端到端请求链路

从服务器视角，一次带工具的对话如下（以「查天气」为例）：

```
用户语音/文本
    │
    ▼
应用服务器
    │  1. ASR / 会话管理 / 注入环境（时间、设备、画像）
    │  2. 并行：向量召回  +  闲聊草稿生成
    │  3. 路由小模型：闲聊 or 有序技能 steps
    │  4. 闲聊 → 直接输出草稿；技能 → 执行器按序调度（草稿丢弃）
    ▼
子 Agent 所在的应用逻辑
    │  4. 拼 system prompt = 人设 + Skill 规则 + 环境 + 工具列表
    │  5. 调该子 Agent 绑定的模型
    ▼
模型服务器
    │  6. 返回 function call JSON（例如 query_weather(city="深圳")）
    │     或先吐过渡句，再 function call
    ▼
应用服务器
    │  7. 按 MCP / 内部适配器调用天气服务
    │  8. 工具结果写回同一轮 messages
    ▼
模型服务器
    │  9. 结合缓存上下文生成最终自然语言
    ▼
应用服务器
    │  10. TTS / 表情&眼神状态机 / 返回用户
    ▼
用户
```

要点：

- 用户请求**先到应用服务器**，不是直达模型。
- 应用服务器会补充：环境信息、工具列表、人设、Skill 规则、必要上下文。
- 模型**不直接打第三方**。tool_call 先回到应用，由应用调工具，再把结果喂回模型。
- 第二次调模型时，应用侧持有完整 messages；模型侧可按会话缓存上下文。

---

## 5. 总体架构

```
                         ┌─────────────┐
                         │ 用户 Query   │
                         └──────┬──────┘
                                │
              ┌─────────────────┴─────────────────┐
              │ 并行（同一时刻启动）                   │
              ▼                                   ▼
     ┌────────────────┐                  ┌────────────────┐
     │ A. 向量召回      │                  │ B. 闲聊草稿生成   │
     │ 相似说法+候选意图 │                  │ 人设模型流式/缓存 │
     │ （证据，不定路）  │                  │ 先备好一份回复    │
     └────────┬───────┘                  └────────┬───────┘
              │                                   │
              └─────────────────┬─────────────────┘
                                ▼
                       ┌────────────────┐
                       │ 路由小模型        │
                       │ 看 query + 召回   │
                       │ 判定：闲聊 or 技能 │
                       └────────┬───────┘
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
        route = chat                    route = agent steps
        直接输出闲聊草稿                  丢弃闲聊草稿
        （不再重跑 Chat）                 顺序执行器按序调度
                                           做动作/天气/故事/搜索…
                                           视觉/提醒等子 Agent
                                                │
                                                ▼
                                         对用户开口（不回传思考）
```

### 5.1 路由怎么走（按你的实现判断）

**向量召回与闲聊生成并行；路由小模型只做分流：闲聊直接出，技能走 Agent。**

```
用户 Query
        │
        ├─→ A) 向量召回 top_k（相似说法 + intent 证据）
        │
        └─→ B) 同时用闲聊模型按人设生成草稿（可流式写 buffer）
        │
        ▼
路由小模型输入：query + 召回证据（+ 可选环境位）
输出二选一：
  (1) { "route": "chat" }
  (2) { "route": "agents", "steps": [ {intent_id, order, hint?}, ... ] }
        │
        ├─→ chat  → 把 B 的草稿直接 TTS/播出（首包可已在 buffer 里）
        │
        └─→ agents → 丢弃 B 的草稿
                     → 按 steps 串行跑子 Agent，直接对用户开口
                     → 不再回路由模型
```

例子：

| 用户说 | 向量侧 | 闲聊草稿侧（并行） | 路由判定 | 最终 |
|---|---|---|---|---|
| 「你好呀」 | 可能像 chat 语料 | 已生成「嗨～」 | `chat` | **直接播草稿** |
| 「跳个舞」 | 命中动作说法 | 也生成了一句闲聊（浪费可接受） | `agents: [device_action]` | **丢草稿，走 ActionAgent** |
| 「先搜恐龙再讲故事」 | 召回 search/story | 闲聊草稿备着 | `agents: [search, story]` | **丢草稿，按序跑两个 Agent** |

为什么这样拆：

| 环节 | 职责 | 不负责 |
|---|---|---|
| 向量 | 捞技能证据，帮路由判断「像不像要走 Agent」 | 不定最终路、不生成用户长文 |
| 闲聊草稿（并行） | **赌一把是闲聊**，把时延藏进召回窗口 | 不决定是否闲聊 |
| 路由小模型 | **唯一分流点**：闲聊 or 技能列表+顺序 | 不调工具；闲聊时不重写全文（直接用草稿） |
| 执行器 | 仅 `route=agents` 时按序调子 Agent | 不做反思、不改顺序 |
| 子 Agent | 承接技能，输出即对用户 | 不回调路由 |

要点：闲聊路径的体验目标是——**路由判定完成时，话可能已经生成好了**，首包接近「判定延迟」，而不是「判定 + 再生成」。

因为下游是**路由形态且输出不再返回思考**，多技能时 **顺序仍在路由一次定死**；定完只能顺行。

### 5.2 多意图怎么弄（搜索 + 讲故事）

| 场景 | 路由小模型应输出 | 执行器行为 |
|---|---|---|
| 「跳个舞」 | `[device_action]` | 只跑 Action |
| 「先搜恐龙再讲故事」 | `[search, story]` | 先 Search 开口，再 Story 开口 |
| 「讲故事顺便查下雨吗」 | `[weather, story]` 或 `[story, weather]`（模型按语义排序） | 严格按 order |
| 「指着空调问品牌多少钱」 | 优先 `[vision_search]`（强耦合合成路）；或 `[vision_qa, search]` | 见下 |

约束（工程写死，不靠自觉）：

1. **`steps` 最长 N**（建议第一期 N=2，最多 3），防止一次点太多技能拖垮时延。
2. **只允许枚举内的 `intent_id`**，非法标签丢弃或整单降级闲聊。
3. **串行不并行**：同一时刻只跑一个子 Agent；上一个的用户侧播报结束（或明确切段）再启下一个。
4. **上下文传递**：后序 Agent 可带上「用户原句 + 前序 Agent 的对用户文本摘要」，但仍**不回路由模型**。
5. **中间衔接**：执行器可插一句极短过渡（「搜到了，接下来讲故事～」）+ 眼神切换，不经大模型重规划。
6. **失败策略**：某步工具失败 → 该步说失败/降级，**继续下一步**或整单中止（可配）；不要为了重试再调路由模型。

#### 强耦合 vs 弱组合

| 类型 | 例子 | 做法 |
|---|---|---|
| 弱组合（可拆） | 搜索 + 讲故事、跳舞 + 查天气 | 路由输出多 `steps`，执行器串行 |
| 强耦合（共享中间态） | 看见图里物体再搜品牌价格 | 保留 `vision_search` 合成子 Agent 更稳；也可 `vision_qa → search` 并把视觉识别短结果写入下一 Agent 输入 |

第一期建议：**弱组合走多 steps；视觉询价类仍保留 `vision_search` 一条**，减少「看完再说搜什么」的信息丢失。

### 5.3 工程实现（拍板）

**结论：实现为「（向量召回 ∥ 闲聊草稿）→ 路由小模型分流 → 闲聊直出 / Agent 按序执行」。**

| 模块 | 形态 | 职责 |
|---|---|---|
| Embedder + 向量库 | ANN 召回 top_k | 给路由模型喂技能证据 |
| ChatDraft | 人设小/中模型，与召回并行 | 预生成闲聊回复 |
| RouterModel | 小模型，强制 JSON | `chat` 或有序 `steps` |
| PlanExecutor | 纯代码 | 仅 agents 路径按序调子 Agent |

```text
intent/
  embedder.py
  retriever.py         # → hits[]
  chat_draft.py        # 并行生成闲聊草稿（可流式 buffer）
  router_model.py      # query + hits → {route, steps?}
  plan_executor.py     # route=agents 时串行执行
  corpus.csv
```

路由输出 schema：

```json
// 闲聊
{ "route": "chat" }

// 技能（可多步）
{
  "route": "agents",
  "steps": [
    {"intent_id": "search", "order": 1, "hint": "恐龙"},
    {"intent_id": "story", "order": 2, "hint": "恐龙故事"}
  ]
}
```

伪代码：

```text
async def handle(query, env):
    hits_task = retrieve(query, top_k=5)
    draft_task = chat_draft.generate(query, character, history)  # 并行

    hits = await hits_task
    plan = await router_model.infer(query, hits, env)   # 分流，不看草稿内容也行

    if plan.route == "chat":
        text = await draft_task          # 多数时候已生成完/接近完成
        await speak_to_user(text)
        return

    draft_task.cancel()                  # 走 Agent：丢弃闲聊草稿
    for step in sanitize(plan.steps):
        text = await run_agent(step.intent_id, query, hint=step.hint, prior=spoken)
        await speak_to_user(text)
        spoken.append(text)
```

#### 工程细节

1. **并行窗口**：`retrieve` 与 `chat_draft` 同时启动；路由模型等 `hits`（不必等草稿）。草稿与路由判定重叠，闲聊首包最省。
2. **路由输入**：query + hits（+ env）；**默认不把草稿全文喂给路由**，避免路由被草稿带偏，也省 token。
3. **走 Agent 必须 cancel/丢弃草稿**，避免两路同时开口。
4. **草稿失败兜底**：`route=chat` 但草稿超时/报错 → 再同步调一次 Chat 生成，或播固定短句。
5. **steps 校验**：枚举、上限 N=2（最多 3）；非法则降级 `chat`（用草稿）或澄清。
6. **时延**：闲聊目标 ≈ max(召回, 草稿) + 路由；技能路径草稿成本可接受（可被 cancel，已花的算投机执行）。
7. **日志**：`hits`、`route`、`draft_used|discarded`、每步 agent trace。

#### 明确不推荐

| 做法 | 为什么不 |
|---|---|
| 等向量完成再开始生成闲聊 | 丢掉并行红利，闲聊变慢 |
| 走 Agent 仍把闲聊草稿念出去 | 抢麦、语义冲突 |
| 路由模型再写一遍闲聊长文 | 与并行草稿重复，浪费时延 |
| 执行完再回路由模型重规划 | 主 Agent 循环，违背不回头 |
| 多意图并行同时开口 | 抢麦；改为有序串行 |

**一句话：召回和闲聊抢时间；路由只负责「播草稿还是进 Agent」；进 Agent 就扔草稿、按序跑、不回传。**

### 5.4 为什么没有主 Agent

- 路由小模型只做**一次**计划（有序 steps），不是循环 Planner。
- 子 Agent 输出直接对用户，**不回传**路由模型做反思/改序。
- 需要「看+搜」强耦合时，用合成子 Agent 或 steps 间传 `hint`/短结果，而不是上主 Agent。

---

## 6. 意图体系（怎么设计、怎么落库、怎么实现）

### 6.1 设计原则

1. **按用户目标分意图，不按底层 API 分**。  
   「唱歌」「跳舞」是用户目标；`PlaySong(song_id)` 是工具。一个意图可对多个工具入参，不为每首歌建一个 intent。
2. **语料服务向量召回：只存「单句说法 → intent」**。  
   多轮语义交给路由小模型 + 会话短上下文，不要把整段对话塞进向量库。
3. **路由只定 intent（+ 可选 hint），不跑抽槽模型**。  
   工具入参由子 Agent 看 schema 自己 function call 填写；多轮可用 sticky/hint 当上下文提示，不是传统槽位流水线。
4. **先覆盖高频祈使句和省略句**。  
   「唱一个」「再来一首」「换一首」必须进语料，否则向量证据弱，全靠小模型。

### 6.2 意图表（建议版）

业务侧一类技能一个 `intent_id`。唱歌从「做动作」里拆出（播歌/曲库与肢体动作不同工具）。

| intent_id | 用户目标 | 典型说法（语料要覆盖） | 子 Agent | 主工具 |
|---|---|---|---|---|
| `chat` | 闲聊/能力询问未下达执行 | 你好；你是谁；**你能唱好未来吗**（仅问能不能） | 闲聊草稿 / Chat | 无 |
| `sing` | 唱歌/播放歌曲 | 唱首歌；唱好未来；**那你给我唱一个**；再来一首 | SingAgent | `PlaySong` |
| `device_action` | 肢体动作 | 跳舞；左转；俯卧撑；瑜伽 | ActionAgent | `PlayAction`（桌面渲染或真机适配器） |
| `weather` | 查天气 | 深圳天气怎么样；明天出门要带伞吗 | WeatherAgent | `QueryWeather` |
| `story` | 讲故事 | 讲个故事；讲小兔子 | StoryAgent | SearchXimalayaStory + PlayXimalayaTrack |
| `search` | 联网搜索 | 今天有什么新闻；搜一下恐龙 | SearchAgent | `WebSearch` |
| `vision_qa` | 看图问答 | 这是什么 | VisionQAAgent | VL |
| `vision_search` | 看图再搜 | 这空调什么牌子多少钱 | VisionSearchAgent | VL+Search |
| `reminder` | 设提醒 | 明天九点提醒我开会 | ReminderAgent | ParseDate+Reminder |

边界（写进路由小模型的标签说明，减少打架）：

| 用户说 | 应判 | 原因 |
|---|---|---|
| 「你能唱好未来吗」 | `chat`（或 `chat` + 写入粘性候选歌名） | 在问能力，还没下令唱 |
| 「那你给我唱一个」 | `sing` | 下达执行；歌名靠上下文/粘性 |
| 「唱好未来」 | `sing`，hint=好未来 | 目标+实体同句 |
| 「跳个舞」 | `device_action` | 肢体，不进 sing |

> 若产品把「你会不会唱歌」也直接当成要唱，可把能力询问规则改成 `sing`；默认建议：**询问归闲聊（可记下歌名），祈使归 sing**，避免还没说「唱」就播歌。

### 6.3 意图语料库怎么建

#### 文件与字段

```text
data/intent_corpus.csv

query,intent_id,notes
你能唱好未来吗,chat,能力询问-未执行
你会唱歌吗,chat,能力询问
唱一首好未来,sing,同句含歌名
给我唱好未来,sing,
唱好未来,sing,
唱首歌,sing,无歌名
唱一个,sing,省略-依赖上下文
那你给我唱一个,sing,承接上文
再来一首,sing,续唱
换一首,sing,
跳个舞,device_action,
你能不能转个圈,device_action,
深圳今天下雨吗,weather,
提醒我明天下午三点开会,reminder,
```

向量库只索引 `query`，payload 带 `intent_id`。`notes` 仅给人看，不进模型。

#### 每个 intent 的语料配方（建议量）

| 类型 | 占比 | 例子（以 sing 为例） |
|---|---|---|
| 完整祈使 | 40% | 唱一首好未来；请播放小星星 |
| 无实体祈使 | 25% | 唱首歌；来首音乐；唱一个 |
| 承接省略 | 15% | 那你唱一个；唱啊；来吧；再来一首 |
| 口语/方言变体 | 15% | 整一首；整一个好听的 |
| 易混负例对照 | 5% 放在路由说明或 chat 语料 | 「你能唱吗」→chat；「唱」→sing |

同一首歌名不必穷举全部；**歌名实体留给 SingAgent 曲库匹配**。语料重点是「各种下令唱歌的说法」，不是曲库本身。

#### 入库与回流

1. 冷启动：产品+运营按上表人工写 每意图 ≥50 条。  
2. 线上：`route` 判错的 case → 标注正确 `intent_id` → 追加语料 → 定期重建索引。  
3. 多轮难例单独建评测集（见 6.5），不一定整段写入向量。

### 6.4 会话粘性状态（给「唱一个」用）

仅当前 session、短生命周期，**不是长期记忆**：

```yaml
SessionSticky:
  candidate_song: "好未来" | null    # 上轮提到的歌名
  last_skill: sing | null            # 上轮相关技能
  expire_turns: 3                    # 超过 N 轮未用则清空
```

写入时机（应用服务器规则，不靠路由模型自觉）：

| 事件 | 动作 |
|---|---|
| 用户话里出现可匹配曲库的歌名（不论 chat/sing） | `candidate_song = 歌名` |
| 闲聊草稿/模型确认「可以唱」且上文有歌名 | 保留 `candidate_song` |
| SingAgent 成功开唱 | 可保留为「上一首」，供「再来一首」 |
| 用户换话题 / 超过 expire_turns | 清空 |

### 6.5 多轮案例：你能唱好未来吗 → 那你给我唱一个

```
轮次1
  User: 你能唱好未来吗
  并行: 向量召回（像 chat/能力问）∥ 闲聊草稿
  路由: route=chat
        （规则/NER：抽到歌名「好未来」→ sticky.candidate_song=好未来）
  输出: 草稿「可以呀～」直接播

轮次2
  User: 那你给我唱一个
  向量: 当前句召回 → 命中「唱一个」「那你给我唱一个」等 sing 语料（证据）
  闲聊草稿: 并行生成中（可能废）
  路由小模型输入:
    - 当前句: 那你给我唱一个
    - 召回 hits: sing …
    - 最近 1~2 轮对话: …好未来…可以…
    - sticky: candidate_song=好未来
  路由输出:
    { "route": "agents",
      "steps": [{ "intent_id": "sing", "order": 1, "hint": "好未来" }] }
  执行: 丢弃闲聊草稿 → SingAgent
        PlaySong(song="好未来") → 对用户开口/开唱
```

分层职责：

| 层 | 「唱一个」谁负责补全歌名 |
|---|---|
| 向量 | 只负责看出「这是唱歌意图」 |
| 路由小模型 | 结合历史+sticky，输出 `sing`，并尽量带 `hint=好未来` |
| sticky | 兜底把候选歌名传给 SingAgent |
| SingAgent | 最终定歌：hint > sticky > 曲库检索 > 追问「唱哪首」 |

若路由没给 hint、sticky 也空：SingAgent 追问，**不回路由重规划**。

### 6.6 路由实现（意图相关部分）

```text
async def handle(query, session):
    hits_task = retrieve(query)                    # 只用当前句
    draft_task = chat_draft.generate(query, history, character)

    hits = await hits_task
    plan = await router_model.infer(
        query=query,
        hits=hits,
        recent_turns=session.last_turns(2),        # 多轮指代关键
        sticky=session.sticky,
    )

    # 轻量实体：从本轮 query 写 sticky（规则/词典/曲库匹配）
    session.update_sticky_from_text(query)

    if plan.route == "chat":
        text = await draft_task
        session.append("user", query)
        session.append("assistant", text)
        await speak(text)
        return

    draft_task.cancel()
    for step in plan.steps:
        hint = step.hint or session.sticky.candidate_song
        text = await run_agent(step.intent_id, query, hint=hint, history=...)
        await speak(text)
        session.append(...)
        session.touch_sticky(step.intent_id)
```

路由小模型系统提示需写清（摘要）：

- 标签枚举与边界（能力询问=chat，下达演唱=sing）。  
- 当前句若是「唱一个/再来一首」等省略，**必须看 recent_turns / sticky 补全**。  
- 输出 JSON：`route` + `steps`；`hint` 能补则补。  
- 不要生成歌词正文（交给 SingAgent）。

### 6.7 SingAgent 最小规格

```yaml
# agents/sing/agent.yaml
id: sing
model: small-text
tools: [PlaySong, SearchSongCatalog]
```

Skill 要点：

1. 歌名优先级：`hint` → sticky → 从当前句抽取 → `SearchSongCatalog` → 追问。  
2. 未点名：「想听哪一首？」不要瞎唱。  
3. 找到后先短过渡句，再 `PlaySong`。  
4. 不支持的歌：说明并给相近推荐，不假装唱。

### 6.8 还要不要「抽槽」？

**不需要单独的抽槽模块。**

| 旧 NLU | 本方案 |
|---|---|
| 意图分类 + 槽位填充（日期、歌名、地点…）两段式 | 路由只分发 intent；**入参交给模型 function call** |
| 槽位表、BIO 标注、缺槽追问状态机常自建一套 | 工具 JSON schema 即「要哪些字段」；缺了由子 Agent 按 Skill 追问 |

模型侧实际在做的事：

```text
工具: PlaySong(song_name: string, ...)
模型看到用户话 / history / hint / sticky
  → 自己填 song_name="好未来"
  → 不够就先口语追问，再调工具
```

工程上最多保留这些**助推**（都不是抽槽模型）：

1. **tools schema**：告诉模型要哪些参数（必须有）。  
2. **hint / sticky**：多轮时把「好未来」放进上下文，降低漏填概率（可选）。  
3. **曲库校验**：`PlaySong` 执行前查是否在库；不在就返回错误让模型改口（可选）。

结论：**「抽槽」一词可弃用；就是 function call 填参 + Skill 追问。**

### 6.9 意图评测集（必含多轮）

| case_id | 对话 | 期望 route | 期望 hint/sticky |
|---|---|---|---|
| sing_ask | U:你能唱好未来吗 | chat | sticky=好未来 |
| sing_follow | 接上轮 U:那你给我唱一个 | agents/[sing] | hint=好未来 |
| sing_direct | U:唱好未来 | agents/[sing] | hint=好未来 |
| sing_missing | U:唱一个（无上文） | agents/[sing] | 无 hint → Agent 追问 |
| action_vs_sing | U:跳个舞 | agents/[device_action] | — |

---

## 7. 子 Agent 规格

### 7.1 统一结构

每个子 Agent 是一个独立配置单元：

```text
agents/{intent_id}/
  agent.yaml          # 模型、超时、工具列表、是否视觉
  SKILL.md            # 方法论 + 规则 + 过渡句策略
  tools.yaml          # function schema
```

`agent.yaml` 示例：

```yaml
id: reminder
model: small-text          # 或 vision-llm
timeout_ms: 2500
stream: true
tools:
  - ParseDateTool
  - FlexibleScheduleReminder
inject:
  - character              # {{ lulu_skill_character }}
  - common_limit           # {{ common_skill_limit }}
  - user_profile
  - preferences
  - env_context
output: final_user_message # 不再上送总 Agent
```

### 7.2 颗粒度约定

| 视角 | 约定 |
|---|---|
| 产品 / 业务 | 一类能力一个 Skill（所有动作可以算一类） |
| 本期工程 | **一个子 Agent 对应一个 Skill**；多数一个主工具；**提醒**（ParseDate→设提醒）与**讲故事**（喜马拉雅搜索→播放）为两工具强制顺序 |
| 复杂 Skill | 允许多步：先过渡句 → 调工具 → 再组织回复。Skill.md 在这里才发挥「方法层」作用 |

不要为「跳 A 舞 / 跳 B 舞」各建一个 Agent。动作类一个 Agent，工具入参区分 `action_name`。

### 7.3 Prompt 拼装顺序

子 Agent 每次请求按下面顺序拼 messages（与给出的 Reminder 模板一致）：

1. **system / 人设**：`{{ lulu_skill_character }}` + `{{ common_skill_limit }}`
2. **system / 画像**：用户画像、偏好（有则注入）
3. **system / Skill 规则**：该子 Agent 的 `SKILL.md` 全文（路由已选定，整份注入，不再渐进扫描其他 Skill）
4. **system / 环境**：当前时间、设备、时区；可选 `document_context`
5. **user**：当前 `{{ user_query }}`（可附 `hint`）
6. **history**：子 Agent 带最近 N 轮；**路由小模型另带 recent_turns + sticky**（见 §6.5），与「向量只用当前句」不矛盾。

工具 schema 走模型 API 的 `tools` 字段，不要把完整 JSON schema 再抄进 prompt，除非模型不支持原生 function call。

### 7.4 过渡句、表情与眼神微动作（陪伴体感）

陪伴机器人的「在场感」分三层，**并行于** Agent 推理，不占用意图路由：

| 层 | 是什么 | 谁驱动 | 举例 |
|---|---|---|---|
| 语音过渡句 | 工具前先开口 | 子 Agent / Skill | 「稍等」「我看看」 |
| 表情阶段 | 听/想/说三大态 | UX 状态机 | 讨论里的表现 1/2/3 |
| **眼神微动作** | 过程中穿插的小动作 | UX 状态机 + 可选轻量规则 | 注视用户、轻眨眼、目光微偏、听完抬头看一眼 |

工具调用前必须先对用户说话一次（「稍等」「我看看」），同一轮多个工具只说一次。

#### 表情三大态（与对话链路对齐）

| 阶段 | 表情 | 用户体感 |
|---|---|---|
| 听用户说话 | 表现 1 | 我在听 |
| 听完，进入向量/模型/工具 | 表现 2 | 我在干活 |
| 开始吐回复 / TTS | 表现 3 | 我在说 |

优化重点是表现 1、2，用来消化 2~3 秒等待，而不是把链路做成「静默转圈」。

#### 眼神微动作：穿插设计（不新建子 Agent）

眼神是**陪伴层默认行为**，和 ActionAgent 的「跳舞/俯卧撑」不同：

- **ActionAgent**：用户明确指令的身体技能，走意图路由。
- **眼神微动作**：行为过程中自动穿插，**不进意图语料库**，不调大模型决策（避免拖时延）。

建议挂点（可与链路事件一一绑定）：

| 时机 | 眼神小动作（示例） | 目的 |
|---|---|---|
| 空闲 / 唤醒前 | 缓慢扫视或轻眨眼 | 活着、在场 |
| VAD 开始听（表现 1） | 目光看向用户 / 轻微点头感注视 | 我在听你 |
| 用户说话中 | 偶发轻眨眼，避免死盯 | 自然陪伴，不压迫 |
| 听完 → 路由/推理（表现 2） | 目光微偏或「思考眨眼」 | 我在想，消化等待 |
| 即将调工具 / 等工具返回 | 再看用户一眼 + 可叠过渡句 | 可控、在干活 |
| TTS 开始说（表现 3） | 回视用户 | 我对你说话 |
| 说完 / 等待下一轮 | 短暂停视或放松眨眼 | 话轮交接 |

实现约定：

1. **事件驱动**：由 `listening_start` / `thinking_start` / `tool_pending` / `speaking_start` 等钩子触发，不经意图仲裁。
2. **可打断、可降级**：大动作（跳舞）进行时，眼神进入附属轨或暂停，避免抢舵机。
3. **与视觉 Agent 解耦**：VisionQA 用摄像头「看世界」；眼神微动作是「看用户/表现在场」，两套逻辑，不要混成同一 intent。
4. **配置化**：动作名、时长、是否随机抖动放 `ux/gaze_clips.yaml`，产品可调，不必改 Agent Skill。
5. **不写进各 Skill 正文**（除非某技能强依赖，如讲故事时「看你一眼再讲」可在 StoryAgent UX 钩子加一条）。

架构上可理解为双轨：

```
对话轨：Query → 意图 → 子 Agent → TTS 回复
陪伴轨：听/想/说/等工具 事件 → 眼神&表情微动作（穿插）
```

两轨共享时间轴，陪伴轨不改变路由结果。

---

## 8. ReminderAgent（八个子 Agent 之一；完整 Skill 样板）

提醒**不是唯一子 Agent**，只是讨论材料里唯一给出完整 system prompt 的那一条，因此用作「带工具子 Agent」的落地样板。规则已由业务写死，实现时**按原文落地**，不要让模型自由发挥流程。其余七条见第 9 节，结构相同、Skill 更短。

### 8.1 能力边界

- 只支持：设置提醒。
- 不支持：自动取消（引导去 App）、查询提醒列表、按月/按年重复、按节假日、过去时间。
- 重复：仅按星期。
- 精度：到分钟；秒级请求先说明再按分钟设置。
- 「开盘」= 当天 09:30，「收盘」= 当天 15:00，视为明确时刻。

### 8.2 工具

**ParseDateTool**（相对/模糊日期 → `date_str=yyyy-MM-dd`）

- 仅当出现「明天、几天后、下周三」等模糊时间。
- 具体几月几号不调用。
- `time_unit` 禁止 `second`，秒级偏移改按分钟。
- `offset` 必须是整数：
  - 非整数分钟：向上取整（5 分半 → minute, 6）
  - 非整数小时：换算成分钟（两个半小时 → minute, 150）
  - 非整数天：向上取整（1 天半 → day, 2）
  - 非整数月：向上取整（两个半月 → month, 3）

**FlexibleScheduleReminder**（真正落提醒）

- 单次提醒禁止设 `r_type`。
- `content` 只写要做的事，不写「提醒我」、不写日期时间。
- 成功返回后才能告诉用户已设置。

### 8.3 强制工具链（应用层可做硬校验）

```
信息完整性检查（日期 + 具体时刻）
    │ 不完整 → 直接追问，禁止调任何工具
    ▼
相对/模糊日期？
    │ 是 → ParseDateTool → 紧接着同一轮必须调 FlexibleScheduleReminder
    │ 否（具体月日）→ 直接 FlexibleScheduleReminder
    ▼
工具成功 → 自然语言确认
```

应用层兜底（不要只靠 prompt）：

1. 未同时具备日期和时刻，拦截一切 tool_call。
2. 调了 `ParseDateTool` 却没有后续 `FlexibleScheduleReminder`，自动补一次或判失败重试，禁止把「解析出的日期」当设置成功告诉用户。
3. 单次提醒若模型填了 `r_type`，服务端丢掉该字段。
4. 目标时间早于当前时间，不调工具，直接拒。

### 8.4 Prompt 模板结构（与现网一致）

```
system:
  {{ lulu_skill_character }}
  {{ common_skill_limit }}
  用户画像 / 偏好（可选）

system:
  Reminder 规则
  工具链前置检查
  日期提取
  工具调用顺序
  重点注意
  回复风格（先过渡句、每轮只等一次、禁止讲工作流）
  {{ env_context }} / {{ document_context }}

user:
  {{ user_query }}
```

路由已选定 `reminder` 后，Skill 按「当前任务就是设置提醒」执行。取消/查询仍用本 Skill 口头拒绝。仅当路由误入时，才按人设闲聊且不调工具。应用层完整性检查见 8.3，不把「是否提醒」再交给模型单独分类。

---

## 9. 其余子 Agent 的 Skill（与 Reminder 同级，全部要复现）

每个子 Agent：`agent.yaml` + `SKILL.md` + `tools.yaml`。  
拼装顺序同 §7.3：人设 + 公共限制 + 画像/偏好 + **下列 Skill 全文** + 环境 + user_query / hint。  
**路由已选定本技能**：Skill 不要再做九选一意图分类；只处理本能力边界、缺槽追问、工具顺序。误入时才降级为人设闲聊且不调工具。

公共约束（写入 `common_skill_limit` 或各 Skill「重点注意」）：

- 必须按人设说话；回复自然连贯。
- 除非用户要求，禁止在回复中包含用户称呼。
- 不要告诉用户工作流程、工具名、JSON。
- 调工具前让用户稍作等待；同一轮多个工具只说一次等待。
- 禁止虚构工具结果；失败用口语降级，不念报错原文。

---

### 9.1 ChatAgent / 闲聊草稿

**不走本 Skill 的二次生成（默认）。** 与向量召回并行，用人设 + 公共限制 + 最近对话生成草稿；`route=chat` 直接播。

仅当草稿失败/超时时，才用下面这份短 Skill 同步重试一次。

```text
Chat
规则
当前任务是陪伴闲聊，不要调用任何工具。
根据人设回应用户；可以聊感受、鼓励、简单知识，但不要假装已经唱了歌、跳了舞、设了提醒。
用户若明显在下令技能（唱一首、跳个舞、设提醒），不要硬聊；用一句「我这就帮你」即可结束——实际应由路由分走；本节点只作草稿失败兜底。
不编造实时事实（股价、比分、今日新闻）；不知道就说不知道，或建议「要不要让我搜一下」（不要自己调搜索工具）。
回复短：语音场景默认 1～3 句。
重点注意
禁止输出技能执行结果的假成功。
禁止长篇说教。
上下文信息
{% if env_context %}用户当前环境信息：{{ env_context }}{% endif %}
```

- 工具：无。
- 模型：人设小/中模型，与并行草稿同一套。

---

### 9.2 SingAgent 唱歌

```yaml
id: sing
model: small-text
tools: [SearchSongCatalog, PlaySong]
```

```text
Sing
规则
当前任务是为用户唱歌/播放歌曲。不要改去讲故事或闲聊长文。
根据用户输入、hint、历史对话和 sticky 候选歌名确定要唱的歌。
优先级：本轮明确歌名 > 路由 hint > sticky.candidate_song > SearchSongCatalog > 追问「想听哪一首」。
未点名且上下文也没有歌名时，禁止随机挑一首，必须询问。
「再来一首」：优先上一首成功播放的歌所在列表的下一首；没有则追问。
「换一首」：排除上一首再检索；不要再唱同一首。
能力询问（你会不会唱）不应进入本 Agent；若误入，简短说可以唱，并询问唱哪首，不要直接 PlaySong。
工具链前置检查
调用 PlaySong 前必须有可校验的歌曲标识（song_id 或曲库确认过的 song_name）。
禁止编造不在曲库中的歌并声称正在演唱。
工具调用顺序
有明确歌名：可直接 SearchSongCatalog 校验，命中后 PlaySong。
无歌名：先追问，本轮禁止调 PlaySong。
SearchSongCatalog 无结果：告知没有这首，给 1～2 个相近推荐（来自工具返回），请用户选；不要假装唱。
PlaySong 成功后才能说「开始唱啦」类确认；未成功禁止说已经唱完。
重点注意
不要在回复里输出歌词全文（由播放器出声）。
过渡句只说一次，例如「好，我找找这首」。
回复风格
先短过渡 → 调工具 → 一句确认。失败则口语致歉 + 推荐或追问。
上下文信息
{% if env_context %}{{ env_context }}{% endif %}
{% if hint %}路由提示：{{ hint }}{% endif %}
{% if sticky %}会话粘性：{{ sticky }}{% endif %}
```

应用层：PlaySong 前查曲库；不在库则把错误写回模型，禁止空播。

---

### 9.3 ActionAgent 做动作（含桌面渲染方案）

```yaml
id: device_action
model: small-text
tools: [ListActions, PlayAction]
```

**结论：做动作可以在桌面用渲染实现，作为第一期运行时；Skill 和工具不变，换适配器即可。详见 9.3.1。**

```text
Action
规则
当前任务是让形象做身体动作（跳舞、左转、右转、转圈、俯卧撑、瑜伽、挥手等）。
根据用户说法映射到动作库中的 action_name，不要编造库中不存在的动作 id。
一个工具 PlayAction 覆盖所有动作，用入参区分，不要理解成多个技能。
与「唱歌」区分：用户要听歌走唱歌；只要肢体/舞蹈走本技能。眼神、眨眼由系统自动做，用户说「看我」且无大动作需求时，不要调 PlayAction。
工具链前置检查
不确定动作名时，先 ListActions 或根据工具枚举询问「是跳舞、转圈，还是瑜伽？」，禁止瞎猜 action_name。
同一时刻只播放一个动作；用户说「一边跳舞一边俯卧撑」取第一个能映射的动作，并说明一次做一个。
工具调用顺序
能唯一映射 → 先短过渡（「好，看我哦」）→ PlayAction(action_name, repeat?) → 根据返回说「跳好啦」或失败致歉。
PlayAction 返回 unknown_action → 向用户澄清，再允许第二次调用。
禁止在未调用 PlayAction 时声称已经跳完。
重点注意
不要描述一长段动作分解当替代（除非渲染失败降级）。
不支持的动作（飞、变身）明确说做不到，可推荐库内相近动作。
回复风格
过渡一次 + 短确认。
上下文信息
{% if env_context %}{{ env_context }}{% endif %}
{% if hint %}{{ hint }}{% endif %}
```

`PlayAction` schema（设计）：`action_name: enum`（由动作表注入）、`repeat: int?`、`speed: normal|slow|fast?`。  
返回：`ok | unknown_action | renderer_busy | timeout`。

#### 9.3.1 桌面渲染能否实现——设计结论

**能，作为开发期 / 桌面陪伴形态的 ActionRuntime；不能等同真机舵机。**

| | 桌面渲染（本期建议先做） | 实体机器人（后续适配） |
|---|---|---|
| 表现 | 屏幕里 3D/Live2D/Spine 角色播动画片段 | 舵机/底盘执行动作 |
| 「跳舞/瑜伽/俯卧撑」 | **可以**：预制 clip 或骨骼动画 | 可以（需动作编排） |
| 「左转/右转」 | **可以降级**：角色转身或镜头绕转，不是在房间里转向 | 底盘 yaw |
| 与 TTS/口型 | 桌面可叠口型、表情轨 | 真机表情灯/屏幕 |
| 真世界位移 | **不能**装成已走到用户身边 | 视硬件 |

架构：**Skill / 路由 / PlayAction 工具名全部不变**，下面挂运行时适配器。

```
PlayAction(action_name)
    ├─ DesktopActionRuntime   # 第一期
    │     查表 action_name → clip_id
    │     投递到桌面渲染进程（Unity / Godot / WebGL / Live2D）
    │     等 clip 结束或超时 → 返回 ok
    └─ RobotActionRuntime     # 后续
          同一 action_name → 舵机轨迹
```

桌面实现要点（只设计，不选型锁死）：

1. **动作表配置化** `actions.yaml`：`dance_basic / turn_left / push_up / yoga_xxx / wave` → 资源路径、时长、是否循环、是否与 TTS 互斥。  
2. **进程/窗口**：独立渲染端（桌面 App 或 Electron 内 Canvas），Agent 服务用本地 RPC/WebSocket 发 `play_clip`。  
3. **忙碌互斥**：上一段没播完，返回 `renderer_busy`，Skill 告知「等我跳完」。眼神微动作走叠加轨；大动作时暂停眼神大位移。  
4. **没有硬件也能验收**：评测看是否发出正确 `action_name` + 渲染端是否播放对应 clip。  
5. **产品话术**：桌面形态可说「看屏幕上的我」；真机再说「看我」。可用 `env_context.runtime=desktop|robot` 注入一句，不要写两套 Skill。

第一期范围建议：桌面 clip 8～15 个即可覆盖语料里的跳舞/转身/简单健身；不接物理引擎仿真全身力学。

#### 9.3.2 没有实体机器人时：用哪个桌面 3D 载体（推荐）

LuLu **大脑仍是本方案的路由 + 子 Agent**；桌面角色只当 `PlayAction` / 眼神 / 口型的身体。不要整包采用市面上「桌宠自带 LLM」当路由，否则意图体系会被对方产品绑死。

**首选（Mac 可用）：Electron 或 Tauri + Three.js + `@pixiv/three-vrm`**

- 角色：VRoid Studio 免费捏人，导出 `.vrm`；或 VRoid Hub / Booth 下载（注意授权）。
- 动作：Humanoid 骨骼 + `.vrma` / Mixamo 舞蹈、转身、挥手；俯卧撑/瑜伽用对应 clip 或降级为「健身姿势循环」。
- 口型：TTS 音量/ viseme 驱动 VRM 口型 blendshape（`aa/ih/ou`）。
- 眼神：VRM lookAt + blink；挂到现有 `listening/thinking/speaking` 钩子。
- 窗体：透明置顶小窗，点角色说话；Agent 服务本机 WebSocket `play_clip` / `speak` / `gaze`。
- 为何首选：跨 Windows/macOS，不绑 Live2D 商业许可即可出 3D；和 `PlayAction(action_name)` 一一映射清晰。

**次选：Unity + VRM / UniVRM（要更好的动画时间轴）**

- Mixamo → Humanoid Animator Controller，clip 名 = `action_name`。
- Mac 可出包，透明置顶比 Win32 桌宠麻烦，第一期允许普通窗口或游戏视图验收。
- 适合后续真机：同一 Animator 再出机器人仿真，不必改 Skill。

**Live2D Cubism（2.5D 桌宠）**

- 闲置、眨眼、说话、挥手很强；**跳舞/瑜伽/俯卧撑弱**（只有模型自带 motion）。
- Web/Unity SDK 有免费样例（如 Natori），商用要 Live2D 许可。
- 若第一期砍掉复杂肢体、只验闲聊+说话+挥手，可以用；与「做动作」全量需求不完全匹配。

**不建议当身体的**

| 类型 | 原因 |
|---|---|
| 现成 AI 桌宠（Elino、itch 上 Companion 等） | 自带 LLM/记忆，难只当渲染器；不少 **仅 Windows** |
| 纯浏览器页里的 Chat 头像 | 不像「在桌面上的伙伴」，且不好做置顶桌宠 |
| Ready Player Me 网页捏人后不接动作表 | 只有形象没有 `PlayAction` 契约 |

**动作表与桌面 clip 的最低集（验收用）**

| `action_name` | 桌面 3D 怎么演 |
|---|---|
| `wave` | 挥手 |
| `dance_basic` | Mixamo/VRMA 一段舞 |
| `turn_left` / `turn_right` | 角色 yaw ±90° |
| `push_up` | 俯卧撑循环或「撑地姿势」3 秒 |
| `yoga_xxx` | 一个瑜伽 clip 或站立伸展 |
| `idle` | 呼吸+眨眼（默认，不经路由） |

TTS 播喜马拉雅/唱歌时：渲染端切 `talk` 口型或静听；大动作与播放器互斥同 9.3.1。

本地联调协议（设计）：`ws://127.0.0.1:port` JSON `{ "cmd": "play_action", "action_name": "dance_basic" }` / `{ "cmd": "gaze", "event": "thinking_start" }` / `{ "cmd": "viseme", "v": "aa" }`。Agent 不关心 Three 还是 Unity。

---

### 9.4 WeatherAgent 查天气

```yaml
id: weather
model: small-text
tools: [QueryWeather]
```

```text
Weather
规则
当前任务是查询并口语播报天气，不要改去搜索新闻或讲故事。
城市、日期从用户话、hint、env_context（定位/默认城市、当前时间）提取。
本轮已能确定城市则可调工具：缺城市时用环境定位城市；仍没有则追问「查哪个城市」，禁止虚构城市天气。
「明天出不出门带伞」类：先 QueryWeather，再根据降水概率口语建议，不要不查就给建议。
不支持分钟级预报、全球任意小村庄若工具返回空，则说查不到，不要编造气温。
工具链前置检查
禁止在未调用 QueryWeather 时报出具体度数、是否下雨。
工具调用顺序
先短过渡（「我看看天气」）→ QueryWeather(city, date) → 用返回字段组织 1～3 句播报（气温、天气现象、可选穿衣/带伞）。
工具失败：致歉，请稍后再试，不念错误码。
回复风格
口语，不要念一整张气象表。
上下文信息
{% if env_context %}{{ env_context }}{% endif %}
```

对接：内部 HTTP 或 MCP 天气服务；模型不直连第三方。

---

### 9.5 StoryAgent 讲故事（接喜马拉雅）

```yaml
id: story
model: small-text          # 检索+播控用小模型；无结果才允许短生成
tools: [SearchXimalayaStory, PlayXimalayaTrack]
timeout_ms: 4000
```

**内容源默认喜马拉雅开放平台检索 + 播放；生成故事仅作降级。** 两工具顺序类似提醒：先搜后播，应用层硬校验。

```text
Story
规则
当前任务是给用户讲/播放故事（童话、儿童故事、指定IP如小兔子）。
优先使用喜马拉雅内容：先搜索，再播放，不要一上来自己编长篇。
根据用户主题、年龄偏好（preferences / 画像）选适合的专辑或声音；儿童向默认过滤成人内容（交给工具侧 content_rating，模型不要点选未返回的条目）。
用户指定书名/角色：用原话作为检索词，不要擅自换成完全不同的故事。
「再讲一个 / 换一个」：排除上一首已播 track_id 再搜。
「暂停 / 停止」：若运行时支持 StopPlayback 可调；本期若无该工具，告知可以在播放器上点停止，不要假装已停。
不支持付费/VIP 才能播的声音：工具会返回 need_vip，告知换一个免费的并再次搜索或让用户选。
工具链前置检查
调用 PlayXimalayaTrack 前必须已有工具返回的 track_id（来自本轮 Search 或 sticky.last_track）。
禁止虚构 track_id。
禁止在未播放时把模型自己编的故事全文当成「已开始播放喜马拉雅」。
工具调用顺序
有主题或「随便讲个故事」：先过渡（「我去找个好听的故事」）→ SearchXimalayaStory(query, age_tag?) →
  有免费可播条目 → PlayXimalayaTrack(track_id) → 用一句介绍标题/主播，不要朗读全文（声音由播放器出）。
  无结果或接口失败 → 才允许用人口述一段不超过 2 分钟的短故事（安全、正向），并说明是我先讲一段。
用户已指定「就这个」且 sticky 有 track_id：可直接 Play。
Search 只是中间结果，不能对用户说「已经开始讲了」；必须等 Play 成功。
重点注意
不要把专辑列表长篇念完；最多口头推荐 1～2 个让用户选。
不要输出喜马拉雅链接、token、内部 id 给用户。
回复风格
过渡一次；播放成功用「开始啦，你听～」类短句。
上下文信息
{% if env_context %}{{ env_context }}{% endif %}
{% if preferences %}{{ preferences }}{% endif %}
{% if hint %}{{ hint }}{% endif %}
```

#### 9.5.1 喜马拉雅对接设计（不写代码）

```
StoryAgent
  → SearchXimalayaStory     # 应用服务器调开放平台搜索
  → PlayXimalayaTrack       # 取播放地址，交给设备/桌面播放器
```

建议工具入参/出参（字段名实现时可对齐官方 OpenAPI，此处只定 Agent 契约）：

| 工具 | 入参 | 出参（回给模型） |
|---|---|---|
| SearchXimalayaStory | `query`，可选 `age_tag=child\|general`，`exclude_ids[]` | `items[{track_id, title, album, is_free, duration_sec}]`，最多 5 条，已滤敏感 |
| PlayXimalayaTrack | `track_id` | `ok` + `title`；或 `need_vip` / `not_found` / `play_failed` |

应用层职责（不要让模型做）：

1. 持有开放平台 app_key/secret，签名、换播放地址；**播放 URL 与 token 不进模型上下文**。  
2. 儿童模式强制 `content_rating` / 分类白名单（儿童、故事、国学等），搜不到则空列表而非成人内容。  
3. 版权/可播性：不可播、下架、地域限制 → `play_failed`，触发 Skill 降级口述或换一条。  
4. 播放器：机器人音箱或 **桌面同一套播放器**（与 Action 渲染进程可并列：一个播动画，一个播声音）。讲故事时大动作暂停。  
5. 合规：用户协议与喜马拉雅开放平台许可；日志只留 track_id，不缓存整轨音频到模型侧。  
6. 降级开关 Apollo：`story.ximalaya.enable`；关闭则本 Agent 仅短出口述故事，工具调用被拦截。

与路由组合：「先搜恐龙再讲故事」= SearchAgent 开口摘要 → StoryAgent 用摘要当 `hint` 去搜喜马拉雅「恐龙故事」，不要在 Story 里再调 WebSearch。

---

### 9.6 SearchAgent 联网搜索

```yaml
id: search
model: small-text
tools: [WebSearch]
```

```text
Search
规则
当前任务是检索公开事实并口语回答（新闻、百科、常识），不要改去设提醒或讲故事。
用短关键词调用 WebSearch；可结合 hint。不要把用户整段情绪话当检索词。
需要时效的问题必须调工具，禁止用训练记忆编造「今天」的新闻、比分、股价。
工具链前置检查
与天气强相关且路由误入时：仍用搜索也可，但优先一句「我帮你搜」；不要报具体气温（那是 Weather）。
工具调用顺序
过渡（「我搜一下」）→ WebSearch(query) → 综合 1～3 条结果说人话，可提来源名称，不要朗读 URL。
无结果/失败：说没搜到，不要编。
回复风格
短、可引用「据 xx 报道」；儿童场景避免血腥细节。
上下文信息
{% if env_context %}{{ env_context }}{% endif %}
{% if hint %}{{ hint }}{% endif %}
```

---

### 9.7 VisionQAAgent 视觉问答

```yaml
id: vision_qa
model: vision-llm
tools: [DescribeImage]     # 或原生多模态看图，二选一，不要又描述又重复看
```

```text
VisionQA
规则
当前任务是根据摄像头/传入图片回答「这是什么」「为什么」等，不进行联网搜索。
只基于当前画面；看不清就说看不清，请用户靠近或给光，禁止猜品牌价格（价格走 VisionSearch）。
适合儿童科普时语言简单、正向。
工具链前置检查
没有图像输入：告诉用户「把东西放在我看得见的地方」，禁止调工具编造画面。
若使用 DescribeImage：先过渡「我看看」→ 调用 → 再根据描述用口语回答用户问题，不要把内部描述原文整段念出。
若模型原生支持视觉：可直接看图回答，仍先短过渡；不要声称已搜索网页。
重点注意
不识别并朗读证件号、完整银行卡、密码等敏感信息。
回复风格
2～4 句口语。
上下文信息
{% if env_context %}{{ env_context }}{% endif %}
```

---

### 9.8 VisionSearchAgent 视觉+搜索

```yaml
id: vision_search
model: vision-llm
tools: [DescribeImage, WebSearch]
```

```text
VisionSearch
规则
当前任务是「看见物体 → 检索品牌/参数/公开价格区间」。必须先理解画面再搜索。
不要在未看图时直接搜用户口头的「这个」。
看不清：先请用户调整，不要空搜。
工具链前置检查
无图像：同 VisionQA，追问，禁止 WebSearch。
工具调用顺序
过渡只说一次（「我看看再帮你查」）→ DescribeImage 或原生看图得到物体短名 → WebSearch(物体名 + 用户关注点如价格/品牌) → 合并一句回答。
禁止只调搜索不看图；禁止看图后不搜索就报电商价格。
价格必须来自工具结果，并说明是公开信息、可能不准确；不引导下单。
Search 失败：只描述你看到什么，并说查不到价格。
重点注意
敏感物品（证件、处方药）只做模糊描述，不搜索购买渠道。
上下文信息
{% if env_context %}{{ env_context }}{% endif %}
{% if hint %}{{ hint }}{% endif %}
```

应用层可硬校验：本 Agent 本轮必须先视觉后搜索（与 Reminder 的 ParseDate → Schedule 同类）。

---

## 10. 应用服务器模块划分

```
app/
  gateway/          # RTC / HTTP 接入，会话，ASR/TTS 钩子
  context/          # 环境、画像、偏好、设备状态
  intent/
    corpus/         # query-intent 语料
    embedder.py
    retriever.py    # 召回证据
    router_model.py # 综合判断 steps + order
    plan_executor.py
  router/           # intent_id → agent 注册表
  agents/           # 各子 Agent 配置与运行时
  tools/            # 内部函数 + MCP client
  prompt/           # 人设、公共限制、模板渲染
  ux/               # 过渡句、表情状态、眼神微动作、流式分片
    gaze_clips.yaml # 听/想/说/等工具 的眼神片段配置
  eval/             # 过程日志、线上回流
  memory/           # 会话历史；不进路由
```

### 10.1 一次请求的处理时序

```
t0  收到 query，表情=表现2
t0  并行：向量召回 hits  ∥  闲聊草稿生成（buffer）
t1  hits 齐 → 路由小模型分流
t1a route=chat → 等/取草稿 → TTS（表现3）；结束
t1b route=agents → cancel 草稿 → 执行 steps[0]
t2  子 Agent 工具/过渡句…
t3  子 Agent 回复对用户；若有后续 step，短过渡后继续（不回路由）
```

并行是提速的第二杠杆：此处特指 **召回 ∥ 闲聊草稿**；技能路径上草稿作投机执行可丢弃。

### 10.2 Function Call 运行时

统一封装，所有子 Agent 共用：

```
messages + tools → model
  if text: 流式给用户，结束
  if tool_calls:
      若本轮还没发过过渡句 → 先发
      执行 tools（可串行；提醒必须 ParseDate → Reminder）
      append tool results
      再调模型（同一 agent、同一模型）
```

子 Agent 内部允许有限次 tool loop（提醒最多 2 次调用）。**禁止**把结果送回路由节点。

---

## 11. 数据模型

```yaml
TurnRequest:
  session_id: str
  user_id: str
  query: str
  env_context: object      # 当前时间、时区、位置、设备
  user_profile: object?
  preferences: object?
  history: list[Message]   # 仅子 Agent 使用
  image?: bytes            # 视觉类

IntentResult / RoutePlan:
  hits: list[{query, intent_id, score}]
  route: chat | agents
  steps?: list[{intent_id, order, hint?}]
  draft_used: bool
  latency_ms: int

AgentTrace:                # 评测与回流用
  request_id: str
  intent: IntentResult
  agent_id: str
  tool_calls: list
  final_text: str
  error?: str
```

语料：

```yaml
IntentExample:
  query: str
  intent_id: str
  source: seed | online | annotated
```

---

## 12. 评测与数据回流

讨论里现网是「上线前品味兜底，上线后看数」。复现时补最小评测，仍保持轻量。

### 12.1 三层过程指标（对应调试台「最终结果 + 过程结果」）

| 环节 | 指标 | 失败怎么看 |
|---|---|---|
| 1 意图 | Top1 准确率、向量命中率、向量/模型不一致率 | 语料不够、类别重叠 |
| 2 工具 | 应调未调、误调、参数错误、顺序错误（提醒） | Skill 规则或 schema 问题 |
| 3 回复 | 安全违规率、空回复、超时；质量先人工抽检 | 模型与提示词 |

### 12.2 上线前

- 用 LLM 按每个 `intent_id` 生成口语 query，批量跑路由准确率。
- 安全/不该说的话用规则 + 小模型兜底，不幻想自动品味打分。
- 提醒链路用固定 case：缺时刻、明天+开盘、5 分半后、昨天、每月 1 号、中秋节。

### 12.3 上线后

- 全量打 `AgentTrace`。
- 用户 chat 可回流到语料（自动化入库）。
- 难例进人工标注台（对标讨论里的题库标注流）。第一期可先导出表格人工打标，不必上完整平台。

不在本期做：独立评估 Agent、ReAct 反思、内容品味自动打分。

---

## 13. 时延与成本预算

目标：对话场景 **2~3 秒**出第一段可感知反馈（过渡句或正文首包）。

| 手段 | 做法 |
|---|---|
| 模型 | 路由小模型；多数子 Agent 小模型；仅视觉节点用 VL |
| 并行 | **向量召回 ∥ 闲聊草稿**；走 Agent 时丢弃草稿 |
| 硬件 | 推理实例与 RTC 同机房 |
| 网络 | RTC，避免 HTTP 长轮询 |
| 体感 | 过渡句 + 表情 1/2/3 + **眼神微动作穿插** |
| Token | 路由不加载全部 Skill；子 Agent 只加载自己的 SKILL.md |

不做：主 Agent 规划、回复后再润色、多 Agent 投票。

---

## 14. 目录与配置规划

```text
lulu-agent/
  README.md
  configs/
    intents.yaml              # intent_id 列表与阈值
    models.yaml               # small-text / vision-llm endpoint
    rtc.yaml
  data/
    intent_corpus.csv         # query,intent_id
  prompts/
    character.md              # lulu_skill_character
    common_limit.md
  agents/
    chat/
    device_action/
    weather/
    story/
    search/
    vision_qa/
    vision_search/
    reminder/
      agent.yaml
      SKILL.md                # 使用现网 Reminder 全文
      tools.yaml
  src/
    intent/
    router/
    runtime/                  # function call loop
    tools/
    ux/
  eval/
    cases/reminder.json
    cases/intent.json
```

`intents.yaml` 建议含阈值、是否需要图像、合成路由声明：

```yaml
intents:
  - id: vision_search
    agent: vision_search
    need_image: true
    description: 需要先看再搜（品牌/价格等）
vector:
  top_k: 3
  hit_threshold: 0.78
classifier:
  labels: [chat, device_action, weather, story, search, vision_qa, vision_search, reminder]
```

---

## 15. 实现阶段（仍不在本文执行）

### Phase 0 — 骨架

- 会话接入、prompt 渲染、统一 function call runtime、trace 日志。
- 只接通 ChatAgent，验证人设与流式。

### Phase 1 — 意图路由

- 语料、向量召回、**并行闲聊草稿**、路由小模型（`chat` | `agents+steps`）、顺序执行器。
- 闲聊：草稿直出；技能：丢草稿后进 Agent。
- 单意图 + 少量多意图 case；steps 上限 N=2。

### Phase 2 — 八个子 Agent 全部挂上（可按工具复杂度拆迭代）

顺序建议（都要做，不是只做提醒）：

1. Chat 草稿并行链路（验证人设、直出、走 Agent 时 cancel）
2. ActionAgent、WeatherAgent、SearchAgent、StoryAgent（动作走桌面 PlayAction；故事走喜马拉雅搜+播）
3. ReminderAgent（两工具强制顺序，按第 8 节硬校验）
4. VisionQAAgent、VisionSearchAgent（换视觉模型；合成路单独 intent）

每挂一个 Agent：补语料 → 补 `SKILL.md` → 补 tools → 补验收 case。提醒的完整 prompt 只是复杂度最高的样板，不是唯一交付物。

### Phase 3 — 陪伴体感与 RTC

- 表情状态机（听/想/说）
- **眼神微动作事件钩子**（listening / thinking / tool_pending / speaking）+ `gaze_clips.yaml`
- 与 ActionAgent 大动作的优先级/互斥
- 首包过渡句、2~3 秒预算打点

### Phase 4 — 回流

- trace 入库、难例标注、语料增量、阈值重标定。

---

## 16. 明确不做（避免做成另一种架构）

| 不做 | 原因 |
|---|---|
| 向量与小模型并行投票仲裁 | 已改为向量供证据、小模型综合定路与顺序 |
| 执行结果回传路由模型重规划 | 变成主 Agent 循环；本方案明确不回头 |
| 多意图并行同时开口 | 抢麦；改为有序串行 |
| 把眼神做成独立意图/子 Agent | 陪伴微动作应事件驱动；进路由会慢且分类噪声大 |
| 主 Agent / Planner / 润色 Agent | 加时延，对话场景无必要 |
| 单独抽槽模型 / 路由阶段抽槽 | 入参由子 Agent function call 填写即可 |
| 路由带长期记忆 | 无场景，且干扰分类 |
| 动态并行调用两个子 Agent | 改走有序 steps 串行；强耦合用合成 Agent |
| 全量 Skill 渐进式披露扫描 | 路由已选定，再扫浪费 token |
| ReAct / Plan-and-Execute 作为主框架 | 对模型智能和时延要求不匹配 |
| 独立评估 Agent | 可后续做评测，不进在线链路 |
| 上线前自动品味打分 | 先规则兜底 + 线上抽检 |

---

## 17. 验收标准

1. 用户说「你好」→ 路由 `chat` → **直接播并行草稿**，不调工具，< 2.5s 首包。
2. 「跳个舞」→ 路由 `agents` → **丢弃闲聊草稿** → ActionAgent → 过渡句 + `PlayAction`（桌面播对应 clip）。
3. 「讲个小兔子故事」→ SearchXimalayaStory → PlayXimalayaTrack，未 Play 成功不得说已经开始讲。
3. 「提醒我明天关注电力板块」→ **不调工具**，追问具体时刻。
4. 「明天下午三点提醒我开会」→ `ParseDateTool` 后必须 `FlexibleScheduleReminder`，再确认。
5. 「这个空调什么牌子多少钱」（带图）→ `vision_search`，不是两个 Agent 拼车。
6. 任意子 Agent 的回复直接到用户，日志里没有第二段「润色模型」。
7. Trace 能分别看到：意图来源、tool_call、最终文本，便于反查是路由错还是工具错。

---

## 18. 开放点（实现前只需拍板这几项）

1. 向量模型与命中阈值（建议先 0.75~0.80，用不一致日志调）。
2. 意图小模型用哪家、几 B；是否和闲聊共用。
3. MCP 是否第一期就上，还是内部 HTTP 适配器。
4. 「先跳舞再讲故事」第一期是拒绝/只做第一件，还是顺序执行。
5. 人设 `lulu_skill_character`、公共限制 `common_skill_limit` 的最终文案。
6. 喜马拉雅开放平台账号、儿童分类白名单、VIP 不可播时的降级策略（口述 vs 只换免费轨）。
7. Action 第一期锁定桌面运行时（Unity / Live2D / WebGL 三选一）还是只做 clip 表 + 模拟器打日志。
8. 桌面形态下「左转」是角色转身还是仅摇头，产品话术是否区分 desktop/robot。

---

## 19. 下一步

确认本文后，按 Phase 0 → 2 开工：先骨架和意图路由，再**并行/分批落地全部 8 个子 Agent**（闲聊、动作、天气、故事、搜索、视觉问答、视觉+搜索、提醒）。提醒用于打通最完整的工具链样板，但不能替代其它分支。  
未确认前不写业务代码。
