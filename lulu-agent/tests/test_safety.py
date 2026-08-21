from tests.harness_env import SETTINGS  # isort:skip  必须先导入，隔离 DB 与模型调用

import unittest

from app.services.safety import SafetyService

BACKEND_METADATA = ("风险等级", "HIGH_RISK", "emotionScore", "report_id", "crisis_terms")


class SafetyGateTests(unittest.TestCase):
    def setUp(self):
        self.safety = SafetyService()

    def test_chinese_crisis_phrases_are_blocked(self):
        for text in ("我不想活了，想结束生命。", "我想自杀", "最近一直在自残"):
            with self.subTest(text=text):
                blocked, reply = self.safety.check_input(text)
                self.assertTrue(blocked)
                self.assertTrue((reply or "").strip())

    def test_english_crisis_phrases_are_blocked(self):
        blocked, reply = self.safety.check_input("I want to kill myself tonight.")
        self.assertTrue(blocked)
        self.assertTrue((reply or "").strip())

    def test_matching_is_case_insensitive(self):
        self.assertTrue(self.safety.check_input("I want to KILL MYSELF")[0])

    def test_ordinary_and_skill_queries_pass_through(self):
        for text in ("你好呀，今天怎么样", "帮我唱一首歌吧", "提醒我明天开会", "今天心情一般"):
            with self.subTest(text=text):
                blocked, reply = self.safety.check_input(text)
                self.assertFalse(blocked)
                self.assertIsNone(reply)

    def test_fallback_reply_leaks_no_backend_metadata(self):
        _blocked, reply = self.safety.check_input("我不想活了")
        for token in BACKEND_METADATA:
            self.assertNotIn(token, reply or "")

    def test_fallback_points_at_human_support(self):
        _blocked, reply = self.safety.check_input("我不想活了")
        self.assertTrue(any(k in reply for k in ("热线", "信任", "陪着你")))

    def test_config_defines_crisis_terms(self):
        self.assertTrue(SETTINGS.safety_path.exists())
        self.assertTrue(self.safety.crisis_terms)


if __name__ == "__main__":
    unittest.main()
