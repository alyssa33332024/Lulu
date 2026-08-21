"""HTTP 契约：桌宠只认这几个端点的字段名与流格式。"""

from tests.harness_env import CONTEXT  # isort:skip  必须先导入，隔离 DB 与模型调用

import json
import unittest

from fastapi.testclient import TestClient

from app.main import create_app

PERSON_ID = "api_test_person"


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app())

    def stream(self, query: str) -> list[dict]:
        response = self.client.post("/api/turn/stream", json={"query": query, "with_tts": False})
        self.assertEqual(response.status_code, 200)
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]


class HealthTests(ApiTestCase):
    def test_health_reports_the_service_up(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "UP", "service": "lulu-agent"})

    def test_agent_status_exposes_the_framework_and_ready_skills(self):
        payload = self.client.get("/api/agent/status").json()
        self.assertEqual(payload["framework"], "dag_unidirectional")
        skills = payload["skills"]
        self.assertCountEqual([skill["id"] for skill in skills], ["sing", "reminder"])
        for skill in skills:
            self.assertEqual(skill["status"], "READY")
            self.assertTrue(skill["path"].endswith("SKILL.md"))


class TurnEndpointTests(ApiTestCase):
    def test_small_talk_returns_a_chat_reply(self):
        payload = self.client.post(
            "/api/turn", json={"query": "今天心情一般", "with_tts": False}
        ).json()
        self.assertEqual(payload["route"], "chat")
        self.assertTrue(payload["reply"])
        self.assertFalse(payload["safety_blocked"])

    def test_response_carries_the_full_turn_contract(self):
        payload = self.client.post("/api/turn", json={"query": "今天心情一般", "with_tts": False}).json()
        for field in (
            "session_id",
            "turn_id",
            "route",
            "steps",
            "draft_state",
            "reply",
            "filler",
            "safety_blocked",
            "character_card_id",
            "play_song_path",
            "tts_audio_base64",
            "trace",
        ):
            self.assertIn(field, payload)

    def test_session_id_can_be_carried_across_requests(self):
        first = self.client.post("/api/turn", json={"query": "今天心情一般", "with_tts": False}).json()
        second = self.client.post(
            "/api/turn",
            json={"query": "那明天呢", "session_id": first["session_id"], "with_tts": False},
        ).json()
        self.assertEqual(second["session_id"], first["session_id"])

    def test_sing_returns_a_playable_path(self):
        payload = self.client.post(
            "/api/turn", json={"query": "唱一首 One Last Time", "with_tts": False}
        ).json()
        self.assertEqual(payload["route"], "agents")
        self.assertTrue(payload["play_song_path"])

    def test_missing_query_is_rejected(self):
        self.assertEqual(self.client.post("/api/turn", json={}).status_code, 422)


class StreamEndpointTests(ApiTestCase):
    def test_stream_is_ndjson_ordered_route_sentences_done(self):
        events = self.stream("今天心情一般")
        types = [event["type"] for event in events]
        self.assertEqual(types[0], "route")
        self.assertEqual(types[-1], "done")
        self.assertIn("sentence", types)
        self.assertNotIn("error", types)

    def test_done_event_matches_the_blocking_endpoint(self):
        done = self.stream("今天心情一般")[-1]
        self.assertEqual(done["route"], "chat")
        self.assertTrue(done["reply"])
        self.assertIn("trace", done)

    def test_greeting_streams_a_single_done_event(self):
        events = self.stream("你好")
        self.assertEqual([event["type"] for event in events], ["done"])
        self.assertEqual(events[0]["route"], "greet")


class CharacterEndpointTests(ApiTestCase):
    def test_progress_starts_empty_for_a_new_person(self):
        payload = self.client.get("/api/character/progress", params={"person_id": PERSON_ID}).json()
        self.assertEqual(payload["person_id"], PERSON_ID)
        self.assertIn("default", payload["unlocked_ids"])
        self.assertIn("metrics", payload)

    def test_selecting_a_locked_card_is_refused(self):
        response = self.client.post(
            "/api/character/select", json={"person_id": PERSON_ID, "card_id": "playful"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_selecting_the_default_card_succeeds(self):
        response = self.client.post(
            "/api/character/select", json={"person_id": PERSON_ID, "card_id": "default"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])


class EnvironmentTests(unittest.TestCase):
    def test_tests_never_touch_the_real_database(self):
        self.assertIn("harness", CONTEXT.settings.database_url)

    def test_tests_never_call_the_real_model_provider(self):
        self.assertEqual(CONTEXT.settings.ai_provider, "mock")


if __name__ == "__main__":
    unittest.main()
