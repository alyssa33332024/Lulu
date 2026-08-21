"""AI_PROVIDER=mock 的确定性回复——所有离线端到端测试都建立在它之上。"""

import json
import unittest

from app.services.ai_mock import mock_chat, mock_chat_stream

ROUTE_SYSTEM = {"role": "system", "content": "你是意图路由。只输出一个 JSON。"}
SING_TOOLS = [
    {"type": "function", "function": {"name": "SearchSongCatalog"}},
    {"type": "function", "function": {"name": "PlaySong"}},
]
REMINDER_TOOLS = [
    {"type": "function", "function": {"name": "ParseDateTool"}},
    {"type": "function", "function": {"name": "FlexibleScheduleReminder"}},
]


def _route(query: str, hits: list[dict] | None = None) -> dict:
    payload = json.dumps({"query": query, "hits": hits or []}, ensure_ascii=False)
    reply = mock_chat([ROUTE_SYSTEM, {"role": "user", "content": payload}])
    return json.loads(reply["content"])


def _assistant_called(name: str) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name}}]}


class RoutePlanTests(unittest.TestCase):
    def test_small_talk_routes_to_chat(self):
        self.assertEqual(_route("今天心情一般")["route"], "chat")

    def test_single_intent_has_no_coord_line(self):
        plan = _route("唱一首晴天")
        self.assertEqual(plan["route"], "agents")
        self.assertEqual([s["intent_id"] for s in plan["steps"]], ["sing"])
        self.assertIsNone(plan.get("coord_line"))

    def test_independent_intents_run_in_parallel(self):
        plan = _route("唱首歌同时提醒我喝水")
        self.assertEqual(plan["execution"], "parallel")
        self.assertEqual({s["intent_id"] for s in plan["steps"]}, {"sing", "reminder"})
        self.assertTrue(plan["coord_line"])

    def test_dependent_intents_run_sequentially(self):
        plan = _route("唱完再提醒我吃药")
        self.assertEqual(plan["execution"], "sequential")
        self.assertEqual([s["intent_id"] for s in plan["steps"]], ["sing", "reminder"])
        self.assertEqual([s["order"] for s in plan["steps"]], [1, 2])

    def test_rag_hits_recover_intents_the_keywords_miss(self):
        """“放首曲子”不含唱/歌/音乐，只能靠检索证据判成 sing。"""
        self.assertEqual(_route("放首曲子")["route"], "chat")
        plan = _route("放首曲子", hits=[{"intent_id": "sing", "score": 0.9}])
        self.assertEqual([s["intent_id"] for s in plan["steps"]], ["sing"])


class MemoryPromptTests(unittest.TestCase):
    def test_extraction_returns_history_and_pending(self):
        reply = mock_chat([{"role": "system", "content": "你是记忆提取代理"}])
        payload = json.loads(reply["content"])
        self.assertTrue(payload["history_entries"])
        self.assertTrue(payload["pending_items"])
        self.assertEqual(payload["pending_items"][0]["tag"], "preference")

    def test_long_term_extraction_returns_profile_buckets(self):
        reply = mock_chat([{"role": "system", "content": "你是长期记忆提取专家"}])
        payload = json.loads(reply["content"])
        self.assertEqual(set(payload), {"profile", "preference", "procedure"})
        self.assertTrue(payload["profile"])

    def test_summarisation_returns_plain_text(self):
        reply = mock_chat([{"role": "system", "content": "把以下对话压缩成连贯中文摘要"}])
        self.assertTrue(reply["content"].strip())
        self.assertEqual(reply["tool_calls"], [])


class ToolLoopTests(unittest.TestCase):
    def test_sing_walks_search_then_play_then_speaks(self):
        history = [{"role": "user", "content": "唱一首 One Last Time"}]

        first = mock_chat(history, tools=SING_TOOLS)
        self.assertEqual([tc["name"] for tc in first["tool_calls"]], ["SearchSongCatalog"])

        history += [
            _assistant_called("SearchSongCatalog"),
            {"role": "tool", "content": json.dumps({"matches": [{"id": "one_last_time"}]})},
        ]
        second = mock_chat(history, tools=SING_TOOLS)
        self.assertEqual([tc["name"] for tc in second["tool_calls"]], ["PlaySong"])
        self.assertEqual(
            json.loads(second["tool_calls"][0]["arguments"])["song_id"], "one_last_time"
        )

        history += [_assistant_called("PlaySong"), {"role": "tool", "content": "{}"}]
        final = mock_chat(history, tools=SING_TOOLS)
        self.assertEqual(final["tool_calls"], [])
        self.assertTrue(final["content"].strip())

    def test_reminder_parses_date_before_scheduling(self):
        history = [{"role": "user", "content": "提醒我明天上午九点半开会"}]

        first = mock_chat(history, tools=REMINDER_TOOLS)
        self.assertEqual([tc["name"] for tc in first["tool_calls"]], ["ParseDateTool"])

        history += [
            _assistant_called("ParseDateTool"),
            {"role": "tool", "content": json.dumps({"date_str": "2026-08-22"})},
        ]
        second = mock_chat(history, tools=REMINDER_TOOLS)
        self.assertEqual([tc["name"] for tc in second["tool_calls"]], ["FlexibleScheduleReminder"])
        args = json.loads(second["tool_calls"][0]["arguments"])
        self.assertEqual(args["date_str"], "2026-08-22")
        self.assertEqual(args["time_str"], "09:30")

    def test_a_tool_is_never_called_twice(self):
        history = [
            {"role": "user", "content": "唱一首歌"},
            _assistant_called("SearchSongCatalog"),
            {"role": "tool", "content": "{}"},
            _assistant_called("PlaySong"),
            {"role": "tool", "content": "{}"},
        ]
        self.assertEqual(mock_chat(history, tools=SING_TOOLS)["tool_calls"], [])

    def test_tool_call_ids_are_unique(self):
        a = mock_chat([{"role": "user", "content": "唱歌"}], tools=SING_TOOLS)
        b = mock_chat([{"role": "user", "content": "唱歌"}], tools=SING_TOOLS)
        self.assertNotEqual(a["tool_calls"][0]["id"], b["tool_calls"][0]["id"])


class StreamTests(unittest.TestCase):
    def test_stream_chunks_reassemble_into_the_full_reply(self):
        messages = [{"role": "user", "content": "今天心情一般"}]
        chunks = list(mock_chat_stream(messages))
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), mock_chat(messages)["content"])

    def test_stream_always_ends_on_a_sentence_boundary(self):
        chunks = list(mock_chat_stream([{"role": "system", "content": "把以下对话压缩成连贯中文摘要"}]))
        self.assertTrue("".join(chunks).endswith("。"))


if __name__ == "__main__":
    unittest.main()
