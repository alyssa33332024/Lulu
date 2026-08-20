from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.enums import IntentId
from app.schemas.dtos import RoutePlan, RouteStep
from app.services.ai import AIService
from app.services.knowledge import IntentHit


ROUTER_SYSTEM = """你是 LuLu 的意图路由。只输出一个 JSON 对象，不要解释、不要 markdown。

## 输出格式（二选一）

闲聊：
{"route":"chat"}

技能：
{"route":"agents","execution":"parallel|sequential","steps":[{"intent_id":"sing|reminder","order":1}],"coord_line":null或短句}

字段约束：
- steps 最多 2 个；intent_id 只能是 sing 或 reminder（禁止把 chat 放进 steps）
- 单意图时不要写 coord_line（省略或 null）；execution 可写 sequential
- 双意图时必须写 execution，并给出 coord_line

## 判定顺序（按此决策，不要跳步）

1) 是否纯闲聊 / 问候 / 能力询问（未下令执行）？
   → route=chat
   例：「你好」「今天怎么样」「你会唱歌吗」「你能设提醒吗」

2) 是否只有一个可执行技能？
   - 点歌/放歌/唱一首 → steps=[{sing}]，coord_line=null
   - 设提醒/闹钟（含「提醒我…」）→ steps=[{reminder}]，coord_line=null
   歌名、时刻等槽位不要抽，留给下游 Agent。

3) 是否同时要唱歌和设提醒？
   a. 有明确先后（唱完/放完/听完/然后再/之后再…）
      → execution=sequential
      → steps 按先后排 order（先发生的 order=1）
      → coord_line：一句说明「先…再…」的短口语
   b. 同时/一边/一起，或无明显先后
      → execution=parallel
      → steps 含 sing 与 reminder（order 可都为 1）
      → coord_line：一句说明「一边…一边…」的短口语

## coord_line 规则

- 只在双意图（steps 长度为 2）时出现；单意图与 chat 禁止输出有效 coord_line
- 10~20 字口语，只协调执行关系，不承诺具体歌名/时刻，不提工具/流程
- parallel 参考：「好，一边放歌一边帮你设提醒。」
- sequential 参考：「好，我先唱，唱完再帮你设提醒。」
  （若用户明确「先设提醒再唱」，顺序与 coord_line 要一致）

## 反例（不要这样）

- 「唱一首晴天」却带 coord_line
- 「提醒我明天开会」却 route=chat（除非明显只是闲聊提到提醒二字）
- 双意图却省略 coord_line
- steps 里出现 chat，或抽 date/song 等槽位字段
"""

PARALLEL_COORD = "好，一边放歌一边帮你设提醒。"
SEQUENTIAL_COORD = "好，我先唱，唱完再帮你设提醒。"
SEQUENTIAL_REMINDER_FIRST_COORD = "好，我先帮你设提醒，设完再唱。"


class RouterService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.ai = AIService()

    def route(self, query: str, hits: list[IntentHit], recent: list[str] | None = None) -> RoutePlan:
        # 本地启发式优先，省掉每句都问 LLM（那会多花 10s 级）
        heuristic = self._heuristic(query, hits)
        # 只有 query 里出现明确技能词才敢直接进子 Agent；
        # 仅靠 RAG 召回命中容易误判（「我就是不想看」曾被当成点歌），交给 LLM 复核
        if self._has_skill_keyword(query):
            return heuristic
        if heuristic.route == "chat" and not self._maybe_skill(query, hits):
            return heuristic
        try:
            plan = self._llm_route(query, hits, recent)
            return self._validate(plan) or RoutePlan(route="chat", steps=[])
        except Exception:
            # LLM 不可用时宁可当闲聊，也别误跑技能 Agent
            return RoutePlan(route="chat", steps=[])

    @staticmethod
    def _has_skill_keyword(query: str) -> bool:
        q = (query or "").strip()
        return any(k in q for k in ("唱", "歌", "提醒", "闹钟", "定时"))

    def _maybe_skill(self, query: str, hits: list[IntentHit]) -> bool:
        if not (query or "").strip():
            return False
        intents = {h.intent_id for h in hits}
        return IntentId.SING.value in intents or IntentId.REMINDER.value in intents

    def _heuristic(self, query: str, hits: list[IntentHit]) -> RoutePlan:
        intents = [h.intent_id for h in hits]
        has_sing = IntentId.SING.value in intents or any(k in query for k in ("唱", "歌"))
        has_rem = IntentId.REMINDER.value in intents or "提醒" in query or "闹钟" in query
        if has_sing and has_rem:
            sing_first = any(
                k in query
                for k in ("唱完", "放完", "听完", "唱后再", "放后再")
            )
            rem_first = any(
                k in query
                for k in ("设完", "定完", "提醒后再", "设好再", "定好再")
            )
            sequential = sing_first or rem_first or any(
                k in query for k in ("之后再", "然后再", "完再", "完后")
            )
            if sequential and rem_first and not sing_first:
                return RoutePlan(
                    route="agents",
                    execution="sequential",
                    steps=[
                        RouteStep(intent_id="reminder", order=1),
                        RouteStep(intent_id="sing", order=2),
                    ],
                    coord_line=SEQUENTIAL_REMINDER_FIRST_COORD,
                )
            if sequential:
                return RoutePlan(
                    route="agents",
                    execution="sequential",
                    steps=[
                        RouteStep(intent_id="sing", order=1),
                        RouteStep(intent_id="reminder", order=2),
                    ],
                    coord_line=SEQUENTIAL_COORD,
                )
            return RoutePlan(
                route="agents",
                execution="parallel",
                steps=[
                    RouteStep(intent_id="sing", order=1),
                    RouteStep(intent_id="reminder", order=1),
                ],
                coord_line=PARALLEL_COORD,
            )
        if has_sing:
            return RoutePlan(route="agents", steps=[RouteStep(intent_id="sing", order=1)])
        if has_rem:
            return RoutePlan(route="agents", steps=[RouteStep(intent_id="reminder", order=1)])
        return RoutePlan(route="chat", steps=[])

    def _default_coord(self, execution: str, steps: list[RouteStep]) -> str:
        if execution == "parallel":
            return PARALLEL_COORD
        if len(steps) >= 2 and steps[0].intent_id == "reminder":
            return SEQUENTIAL_REMINDER_FIRST_COORD
        return SEQUENTIAL_COORD

    def _llm_route(self, query: str, hits: list[IntentHit], recent: list[str] | None) -> RoutePlan:
        evidence = [
            {
                "query_id": h.query_id,
                "intent_id": h.intent_id,
                "score": h.score,
                "matched_query": h.query,
            }
            for h in hits
        ]
        user = {
            "query": query,
            "hits": evidence,
            "recent_turns": (recent or [])[-4:],
        }
        if self.settings.intent_model_backend == "ollama":
            data = self._ollama_json(user)
        else:
            data = self.ai.chat_json(
                [
                    {"role": "system", "content": ROUTER_SYSTEM},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                ],
                fast=True,
            )
        return RoutePlan.model_validate(data)

    def _ollama_json(self, user: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.settings.ollama_host.rstrip('/')}/api/chat"
        payload = {
            "model": self.settings.intent_model_name,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            "options": {"temperature": 0},
        }
        # 冷启动可能稍慢；热路径应 <1s。失败则上层回退启发式。
        # trust_env=False：避免 Windows 系统代理把本机 Ollama 打成 502
        with httpx.Client(timeout=8.0, trust_env=False) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            content = r.json()["message"]["content"]
        return json.loads(content)

    def _validate(self, plan: RoutePlan) -> RoutePlan | None:
        if plan.route == "chat":
            return RoutePlan(route="chat", steps=[])
        steps = []
        for i, s in enumerate(plan.steps[:2], start=1):
            if s.intent_id not in ("sing", "reminder"):
                continue
            steps.append(RouteStep(intent_id=s.intent_id, order=s.order or i))
        if not steps:
            return None
        execution = plan.execution if plan.execution in ("parallel", "sequential") else "sequential"
        if len(steps) < 2:
            execution = "sequential"
            return RoutePlan(route="agents", execution=execution, steps=steps, coord_line=None)

        coord = (plan.coord_line or "").strip() or None
        if not coord:
            coord = self._default_coord(execution, steps)
        if len(coord) > 40:
            coord = coord[:40].rstrip()
        return RoutePlan(
            route="agents",
            execution=execution,
            steps=steps,
            coord_line=coord,
        )
