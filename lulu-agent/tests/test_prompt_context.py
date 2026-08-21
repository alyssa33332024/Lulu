from tests.harness_env import SETTINGS  # isort:skip  必须先导入，隔离 DB 与模型调用

import unittest

from app.memory.prompting import (
    SYSTEM_CONTEXT_FRAME_END,
    ContextFrameSection,
    build_context_frame_content,
    is_context_frame,
)
from app.services.prompt import PromptService, PromptTemplates


class PersonContextTests(unittest.TestCase):
    def test_long_term_memory_is_injected(self):
        block = PromptTemplates.person_context_block(long_term_memory="用户喜欢弹钢琴")
        self.assertIn("用户喜欢弹钢琴", block)

    def test_empty_memory_injects_nothing(self):
        """只剩标题时整块不进 system，避免白占上下文。"""
        self.assertEqual(PromptTemplates.person_context_block(long_term_memory=None), "")
        self.assertEqual(PromptTemplates.person_context_block(long_term_memory="   "), "")

    def test_user_profile_falls_back_to_long_term_slot(self):
        block = PromptTemplates.person_context_block(user_profile="用户是学生")
        self.assertIn("用户是学生", block)

    def test_retrieved_memory_never_reaches_the_system_block(self):
        block = PromptTemplates.person_context_block(retrieved_memory="上周去了海边")
        self.assertNotIn("海边", block)


class EnvContextTests(unittest.TestCase):
    def test_env_and_document_context_render(self):
        block = PromptTemplates.context_block(
            env_context="客厅，晚上八点",
            document_context="演唱会在周六",
        )
        self.assertIn("客厅，晚上八点", block)
        self.assertIn("演唱会在周六", block)

    def test_missing_fields_drop_their_whole_block(self):
        block = PromptTemplates.context_block(env_context="客厅")
        self.assertIn("客厅", block)
        self.assertNotIn("外部知识", block)

    def test_all_empty_renders_nothing(self):
        self.assertEqual(PromptTemplates.context_block(), "")


class RetrievedMemoryFrameTests(unittest.TestCase):
    def test_empty_recall_produces_no_frame(self):
        self.assertIsNone(PromptTemplates.retrieved_memory_frame(None))
        self.assertIsNone(PromptTemplates.retrieved_memory_frame("  "))

    def test_frame_is_a_user_message_carrying_a_system_reminder(self):
        frame = PromptTemplates.retrieved_memory_frame("用户喜欢弹钢琴")
        self.assertIsNotNone(frame)
        self.assertEqual(frame["role"], "user")
        self.assertTrue(is_context_frame(frame["content"]))
        self.assertIn("retrieved_memory", frame["content"])
        self.assertIn("用户喜欢弹钢琴", frame["content"])
        self.assertTrue(frame["content"].rstrip().endswith(SYSTEM_CONTEXT_FRAME_END))

    def test_frame_disclaims_that_content_is_not_user_speech(self):
        frame = PromptTemplates.retrieved_memory_frame("用户喜欢弹钢琴")
        self.assertIn("不是用户陈述", frame["content"])

    def test_blank_sections_are_dropped(self):
        self.assertEqual(
            build_context_frame_content([ContextFrameSection(name="retrieved_memory", content="  ")]),
            "",
        )

    def test_plain_text_is_not_mistaken_for_a_frame(self):
        self.assertFalse(is_context_frame("我昨天去了海边"))


class DraftGateTests(unittest.TestCase):
    def setUp(self):
        original = SETTINGS.draft_gate_enabled
        self.addCleanup(setattr, SETTINGS, "draft_gate_enabled", original)

    def test_skill_queries_skip_the_draft(self):
        SETTINGS.draft_gate_enabled = True
        prompt = PromptService()
        self.assertTrue(prompt.should_skip_draft("唱一首歌给我听"))
        self.assertTrue(prompt.should_skip_draft("提醒我明天开会"))

    def test_small_talk_still_gets_a_draft(self):
        SETTINGS.draft_gate_enabled = True
        prompt = PromptService()
        self.assertFalse(prompt.should_skip_draft("今天心情一般"))
        self.assertFalse(prompt.should_skip_draft("你好呀"))

    def test_disabled_gate_never_skips(self):
        SETTINGS.draft_gate_enabled = False
        self.assertFalse(PromptService().should_skip_draft("唱一首歌"))


if __name__ == "__main__":
    unittest.main()
