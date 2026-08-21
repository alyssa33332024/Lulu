"""流式一轮：桌宠靠 sentence 事件提前开 TTS，事件顺序与切句规则都不能回退。"""

from tests.harness_env import session  # isort:skip  必须先导入，隔离 DB 与模型调用

import unittest

from app.agents.harness import REMINDER_WAIT_LINE, _pop_speakable
from app.schemas.dtos import TurnRequest
from app.services.voice import GREET_REPLY


class SpeakableSplitTests(unittest.TestCase):
    """纯函数：从流式缓冲里切出可送 TTS 的片段。"""

    def test_complete_sentences_are_emitted_and_the_tail_kept(self):
        pieces, rest = _pop_speakable("好呀。我在听！还有")
        self.assertEqual(pieces, ["好呀。", "我在听！"])
        self.assertEqual(rest, "还有")

    def test_short_unpunctuated_buffer_waits_for_more(self):
        pieces, rest = _pop_speakable("好呀")
        self.assertEqual(pieces, [])
        self.assertEqual(rest, "好呀")

    def test_long_unpunctuated_buffer_flushes_early_to_cut_ttft(self):
        pieces, rest = _pop_speakable("今天天气不错要不要出去走走看看风景呢")
        self.assertTrue(pieces)
        self.assertNotIn("。", pieces[0])
        self.assertTrue(rest)

    def test_force_drains_whatever_is_left(self):
        pieces, rest = _pop_speakable("还没说完", force=True)
        self.assertEqual(pieces, ["还没说完"])
        self.assertEqual(rest, "")

    def test_empty_buffer_yields_nothing(self):
        self.assertEqual(_pop_speakable(""), ([], ""))


class StreamEventTestCase(unittest.TestCase):
    def setUp(self):
        self.db = session()
        self.addCleanup(self.db.close)

    def events(self, query: str) -> list[dict]:
        from app.agents.harness import LuluTurnHarness

        return list(LuluTurnHarness(self.db).iter_events(TurnRequest(query=query, with_tts=False)))


class ChatStreamTests(StreamEventTestCase):
    def test_event_order_is_route_then_sentences_then_done(self):
        types = [event["type"] for event in self.events("今天心情一般")]
        self.assertEqual(types[0], "route")
        self.assertEqual(types[-1], "done")
        self.assertIn("sentence", types)
        self.assertNotIn("error", types)

    def test_sentences_concatenate_into_the_final_reply(self):
        events = self.events("今天心情一般")
        spoken = "".join(e.get("text") or "" for e in events if e["type"] == "sentence")
        done = events[-1]
        self.assertEqual(done["route"], "chat")
        self.assertTrue(spoken.strip())
        self.assertEqual(spoken.replace(" ", ""), (done["reply"] or "").replace(" ", ""))

    def test_done_carries_the_same_fields_as_the_blocking_endpoint(self):
        done = self.events("今天心情一般")[-1]
        for field in ("session_id", "turn_id", "route", "draft_state", "reply", "steps", "trace"):
            self.assertIn(field, done)


class FastPathStreamTests(StreamEventTestCase):
    def test_greeting_emits_only_done(self):
        events = self.events("你好")
        self.assertEqual([e["type"] for e in events], ["done"])
        self.assertEqual(events[0]["route"], "greet")
        self.assertEqual(events[0]["reply"], GREET_REPLY)

    def test_crisis_input_emits_only_done_and_is_flagged(self):
        events = self.events("我不想活了，想结束生命。")
        self.assertEqual([e["type"] for e in events], ["done"])
        self.assertEqual(events[0]["route"], "safety")
        self.assertTrue(events[0]["safety_blocked"])


class ReminderStreamTests(StreamEventTestCase):
    def test_slow_tool_chain_speaks_a_holding_line_first(self):
        events = self.events("提醒我明天上午九点半开会")
        sentences = [e.get("text") or "" for e in events if e["type"] == "sentence"]
        self.assertIn(REMINDER_WAIT_LINE, sentences)
        self.assertEqual(sentences[0], REMINDER_WAIT_LINE)
        self.assertEqual(events[-1]["route"], "agents")


if __name__ == "__main__":
    unittest.main()
