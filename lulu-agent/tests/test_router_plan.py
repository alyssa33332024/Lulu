from tests.harness_env import SETTINGS  # isort:skip  必须先导入，隔离 DB 与模型调用

import unittest

from app.schemas.dtos import RoutePlan, RouteStep
from app.services.knowledge import IntentHit
from app.services.router import (
    PARALLEL_COORD,
    SEQUENTIAL_COORD,
    SEQUENTIAL_REMINDER_FIRST_COORD,
    RouterService,
)


def _hit(intent_id: str, score: float = 0.9) -> IntentHit:
    return IntentHit(query_id="", query="", intent_id=intent_id, score=score)


def _intents(plan: RoutePlan) -> list[str]:
    return [step.intent_id for step in plan.steps]


class _Boom(RuntimeError):
    pass


class HeuristicRouteTests(unittest.TestCase):
    """带技能关键词时必须走本地启发式——每句都问 LLM 会多花 10s 级延迟。"""

    def setUp(self):
        self.router = RouterService()
        self.llm_calls = 0

        def _forbidden(*_args, **_kwargs):
            self.llm_calls += 1
            raise _Boom("LLM must not be consulted here")

        self.router._llm_route = _forbidden

    def test_small_talk_stays_chat(self):
        plan = self.router.route("你好呀", hits=[], recent=[])
        self.assertEqual(plan.route, "chat")
        self.assertEqual(plan.steps, [])
        self.assertEqual(self.llm_calls, 0)

    def test_single_skill_needs_no_coord_line(self):
        for query, intent in (("唱一首晴天", "sing"), ("提醒我明天开会", "reminder")):
            with self.subTest(query=query):
                plan = self.router.route(query, hits=[], recent=[])
                self.assertEqual(plan.route, "agents")
                self.assertEqual(_intents(plan), [intent])
                self.assertIsNone(plan.coord_line)

    def test_independent_skills_run_in_parallel(self):
        plan = self.router.route("唱首歌同时提醒我喝水", hits=[], recent=[])
        self.assertEqual(plan.execution, "parallel")
        self.assertEqual(set(_intents(plan)), {"sing", "reminder"})
        self.assertEqual(plan.coord_line, PARALLEL_COORD)

    def test_sing_first_when_user_says_after_singing(self):
        plan = self.router.route("唱完再提醒我吃药", hits=[], recent=[])
        self.assertEqual(plan.execution, "sequential")
        self.assertEqual(_intents(plan), ["sing", "reminder"])
        self.assertEqual([s.order for s in plan.steps], [1, 2])
        self.assertEqual(plan.coord_line, SEQUENTIAL_COORD)

    def test_reminder_first_when_user_says_after_scheduling(self):
        plan = self.router.route("提醒设完再唱首歌", hits=[], recent=[])
        self.assertEqual(_intents(plan), ["reminder", "sing"])
        self.assertEqual(plan.coord_line, SEQUENTIAL_REMINDER_FIRST_COORD)

    def test_llm_is_never_consulted_for_keyword_queries(self):
        for query in ("唱一首晴天", "提醒我明天开会", "唱完再提醒我吃药", "你好呀"):
            self.router.route(query, hits=[], recent=[])
        self.assertEqual(self.llm_calls, 0)


class RagEscalationTests(unittest.TestCase):
    """没有关键词、只有检索证据时交给 LLM 复核——「我就是不想看」曾被误判成点歌。"""

    def setUp(self):
        self.router = RouterService()

    def test_keywordless_query_without_evidence_stays_chat(self):
        self.router._llm_route = lambda *a, **k: self.fail("should not escalate")
        plan = self.router.route("今天心情一般", hits=[], recent=[])
        self.assertEqual(plan.route, "chat")

    def test_evidence_only_query_is_reviewed_by_the_model(self):
        plan = self.router.route("放首曲子", hits=[_hit("sing")], recent=[])
        self.assertEqual(plan.route, "agents")
        self.assertEqual(_intents(plan), ["sing"])

    def test_model_failure_degrades_to_chat_not_to_a_wrong_agent(self):
        def _fail(*_args, **_kwargs):
            raise _Boom("router model down")

        self.router._llm_route = _fail
        plan = self.router.route("放首曲子", hits=[_hit("sing")], recent=[])
        self.assertEqual(plan.route, "chat")
        self.assertEqual(plan.steps, [])


class ValidatePlanTests(unittest.TestCase):
    def setUp(self):
        self.router = RouterService()

    def test_chat_plan_is_stripped_of_steps(self):
        plan = self.router._validate(
            RoutePlan(route="chat", steps=[RouteStep(intent_id="sing", order=1)])
        )
        self.assertEqual(plan.route, "chat")
        self.assertEqual(plan.steps, [])

    def test_steps_are_capped_at_two(self):
        plan = self.router._validate(
            RoutePlan(
                route="agents",
                execution="parallel",
                steps=[
                    RouteStep(intent_id="sing", order=1),
                    RouteStep(intent_id="reminder", order=1),
                    RouteStep(intent_id="sing", order=2),
                ],
            )
        )
        self.assertEqual(len(plan.steps), 2)

    def test_chat_inside_steps_is_dropped(self):
        plan = self.router._validate(
            RoutePlan(
                route="agents",
                steps=[RouteStep(intent_id="chat", order=1), RouteStep(intent_id="sing", order=2)],
            )
        )
        self.assertEqual(_intents(plan), ["sing"])

    def test_plan_with_only_chat_steps_is_rejected(self):
        self.assertIsNone(
            self.router._validate(
                RoutePlan(route="agents", steps=[RouteStep(intent_id="chat", order=1)])
            )
        )

    def test_missing_coord_line_gets_a_default(self):
        plan = self.router._validate(
            RoutePlan(
                route="agents",
                execution="parallel",
                steps=[
                    RouteStep(intent_id="sing", order=1),
                    RouteStep(intent_id="reminder", order=1),
                ],
            )
        )
        self.assertEqual(plan.coord_line, PARALLEL_COORD)

    def test_overlong_coord_line_is_truncated(self):
        plan = self.router._validate(
            RoutePlan(
                route="agents",
                execution="sequential",
                steps=[
                    RouteStep(intent_id="sing", order=1),
                    RouteStep(intent_id="reminder", order=2),
                ],
                coord_line="好" * 80,
            )
        )
        self.assertLessEqual(len(plan.coord_line), 40)

    def test_single_step_is_always_sequential_and_uncoordinated(self):
        plan = self.router._validate(
            RoutePlan(
                route="agents",
                execution="parallel",
                steps=[RouteStep(intent_id="sing", order=1)],
                coord_line="一边放歌一边设提醒",
            )
        )
        self.assertEqual(plan.execution, "sequential")
        self.assertIsNone(plan.coord_line)


class RouterConfigTests(unittest.TestCase):
    def test_harness_pins_the_json_backend(self):
        self.assertEqual(SETTINGS.intent_model_backend, "ark_json")


if __name__ == "__main__":
    unittest.main()
