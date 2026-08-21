"""离线跑完整一轮：AI_PROVIDER=mock 下 /turn 的路由、落库与产物。"""

from tests.harness_env import session  # isort:skip  必须先导入，隔离 DB 与模型调用

import unittest

from app.agents.harness import LuluTurnHarness
from app.models.entities import ChatMessage, ReminderItem
from app.schemas.dtos import TurnRequest
from app.services.voice import GREET_REPLY


def _tool_names(response) -> list[str]:
    return [call.get("name") for call in (response.trace or {}).get("tool_calls") or []]


class TurnPipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.db = session()
        self.addCleanup(self.db.close)
        self.harness = LuluTurnHarness(self.db)

    def turn(self, query: str, **kwargs):
        return self.harness.run(TurnRequest(query=query, with_tts=False, **kwargs))


class GreetFastPathTests(TurnPipelineTestCase):
    def test_bare_greetings_take_the_fast_path(self):
        for query in ("你好", "嗨", "hello", "Lulu", "你好啊！"):
            with self.subTest(query=query):
                res = self.turn(query)
                self.assertEqual(res.route, "greet")
                self.assertEqual(res.reply, GREET_REPLY)
                self.assertEqual(res.draft_state, "skipped")

    def test_a_greeting_with_a_request_is_not_a_fast_path(self):
        res = self.turn("你好，帮我唱首歌")
        self.assertEqual(res.route, "agents")


class SafetyPathTests(TurnPipelineTestCase):
    def test_crisis_input_short_circuits_before_any_agent(self):
        res = self.turn("我不想活了，想结束生命。")
        self.assertTrue(res.safety_blocked)
        self.assertEqual(res.route, "safety")
        self.assertEqual(res.draft_state, "skipped")
        self.assertTrue(res.reply.strip())
        self.assertEqual(res.steps, [])
        self.assertIsNone(res.play_song_path)

    def test_safety_reply_leaks_no_backend_metadata(self):
        res = self.turn("我想自杀")
        for token in ("风险等级", "HIGH_RISK", "emotionScore", "report_id"):
            self.assertNotIn(token, res.reply)


class ChatPathTests(TurnPipelineTestCase):
    def test_small_talk_answers_from_the_draft_lane(self):
        res = self.turn("今天心情一般")
        self.assertEqual(res.route, "chat")
        self.assertEqual(res.draft_state, "used")
        self.assertTrue(res.reply.strip())
        self.assertEqual(res.steps, [])

    def test_character_card_is_resolved_for_the_owner(self):
        res = self.turn("今天心情一般")
        self.assertTrue(res.character_card_id)

    def test_tts_is_not_synthesised_when_the_client_opts_out(self):
        self.assertIsNone(self.turn("今天心情一般").tts_audio_base64)


class AgentPathTests(TurnPipelineTestCase):
    def test_sing_resolves_a_local_audio_file(self):
        res = self.turn("唱一首 One Last Time")
        self.assertEqual(res.route, "agents")
        self.assertIn("PlaySong", _tool_names(res))
        self.assertTrue(res.play_song_path)
        self.assertTrue(res.reply.strip())

    def test_reminder_is_persisted(self):
        before = self.db.query(ReminderItem).count()
        res = self.turn("提醒我明天上午九点半开会")
        self.assertEqual(res.route, "agents")
        self.assertIn("FlexibleScheduleReminder", _tool_names(res))
        self.assertEqual(self.db.query(ReminderItem).count(), before + 1)

    def test_dependent_intents_announce_their_order(self):
        res = self.turn("唱完再提醒我吃药")
        self.assertEqual(res.route, "agents")
        self.assertEqual((res.trace or {}).get("execution"), "sequential")
        self.assertTrue(((res.trace or {}).get("coord_line") or "").strip())

    def test_skill_turns_discard_the_draft(self):
        self.assertEqual(self.turn("唱一首歌").draft_state, "discarded")


class SessionPersistenceTests(TurnPipelineTestCase):
    def _messages(self, session_id: str) -> list[ChatMessage]:
        return (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id)
            .all()
        )

    def test_each_turn_stores_the_user_and_assistant_message(self):
        first = self.turn("今天心情一般")
        rows = self._messages(first.session_id)
        self.assertEqual([row.role for row in rows], ["user", "assistant"])
        self.assertEqual(rows[0].content, "今天心情一般")
        self.assertEqual(rows[1].content, first.reply)

    def test_passing_a_session_id_continues_the_same_conversation(self):
        first = self.turn("今天心情一般")
        second = self.turn("那明天呢", session_id=first.session_id)
        self.assertEqual(second.session_id, first.session_id)
        self.assertEqual(len(self._messages(first.session_id)), 4)

    def test_omitting_a_session_id_starts_a_new_conversation(self):
        first = self.turn("今天心情一般")
        second = self.turn("今天心情一般")
        self.assertNotEqual(first.session_id, second.session_id)

    def test_turn_ids_are_unique(self):
        ids = {self.turn("今天心情一般").turn_id for _ in range(3)}
        self.assertEqual(len(ids), 3)


if __name__ == "__main__":
    unittest.main()
