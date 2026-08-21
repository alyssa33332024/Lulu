"""Akashic 式记忆：MEMORY.md 注入 system、增量事实进 PENDING.md、超窗压缩写回 summary。"""

from tests.harness_env import SETTINGS, session  # isort:skip  必须先导入，隔离 DB 与模型调用

import unittest

from app.memory import AkashicMemoryFacade
from app.memory.md_store import MemoryStore
from app.memory.workspace import ensure_person_workspace, person_workspace
from app.models.entities import ChatMessage, ChatSession
from app.services.context import ContextService

PERSON_ID = "unittest_person"


class WorkspaceTests(unittest.TestCase):
    def test_workspace_is_created_under_the_harness_memory_root(self):
        workspace = ensure_person_workspace(PERSON_ID)
        self.assertTrue(workspace.exists())
        self.assertEqual(workspace, person_workspace(PERSON_ID))
        self.assertIn(
            SETTINGS.akashic_memory_root.resolve(),
            workspace.resolve().parents,
        )

    def test_long_term_memory_round_trips(self):
        store = MemoryStore(ensure_person_workspace(PERSON_ID))
        store.write_long_term("# 长期记忆\n用户喜欢弹钢琴。\n")
        self.assertIn("用户喜欢弹钢琴", store.read_long_term())


class PromptInjectionTests(unittest.TestCase):
    def setUp(self):
        MemoryStore(ensure_person_workspace(PERSON_ID)).write_long_term(
            "# 长期记忆\n用户喜欢弹钢琴。\n"
        )

    def test_memory_md_reaches_the_person_context_field(self):
        fields = AkashicMemoryFacade().render_person_fields(PERSON_ID, query="钢琴")
        self.assertIn("钢琴", fields.user_profile or "")

    def test_top_level_heading_is_stripped_to_avoid_a_double_title(self):
        """外层 person.md 已经有「## 长期记忆」，这里不能再带一层标题。"""
        profile = AkashicMemoryFacade().render_person_fields(PERSON_ID, query="钢琴").user_profile
        self.assertFalse((profile or "").lstrip().startswith("#"))

    def test_unknown_person_yields_no_memory(self):
        fields = AkashicMemoryFacade().render_person_fields("nobody_at_all", query="钢琴")
        self.assertFalse((fields.user_profile or "").strip())


class ConsolidationTests(unittest.TestCase):
    def test_compressed_batch_lands_in_pending(self):
        AkashicMemoryFacade().consolidate_compressed_batch(
            person_id=PERSON_ID,
            session_id="unittest-compact",
            messages=[
                {"role": "user", "content": "我喜欢弹钢琴"},
                {"role": "assistant", "content": "好呀，有空可以一起聊音乐。"},
            ],
        )
        pending = MemoryStore(person_workspace(PERSON_ID)).read_pending()
        self.assertTrue(pending.strip())
        self.assertTrue("钢琴" in pending or "preference" in pending)

    def test_empty_batch_is_a_no_op(self):
        before = MemoryStore(person_workspace(PERSON_ID)).read_pending()
        AkashicMemoryFacade().consolidate_compressed_batch(
            person_id=PERSON_ID, session_id="unittest-empty", messages=[]
        )
        self.assertEqual(MemoryStore(person_workspace(PERSON_ID)).read_pending(), before)

    def test_recall_returns_a_list_and_never_raises(self):
        self.assertIsInstance(AkashicMemoryFacade().recall(PERSON_ID, "钢琴"), list)
        self.assertEqual(AkashicMemoryFacade().recall("nobody_at_all", "钢琴"), [])


class ContextCompressionTests(unittest.TestCase):
    def setUp(self):
        self.db = session()
        self.addCleanup(self.db.close)
        original = SETTINGS.context_keep_recent_tokens
        self.addCleanup(setattr, SETTINGS, "context_keep_recent_tokens", original)
        SETTINGS.context_keep_recent_tokens = 8

    def _session_with_history(self, public_id: str, turns: int = 6) -> ChatSession:
        chat_session = ChatSession(public_id=public_id, title="compress")
        self.db.add(chat_session)
        self.db.commit()
        for i in range(turns):
            self.db.add(
                ChatMessage(
                    session_id=public_id,
                    role="user",
                    content=f"这是第{i}轮很长的闲聊内容，用来触发压缩。",
                )
            )
            self.db.add(ChatMessage(session_id=public_id, role="assistant", content="嗯，我在听。"))
        self.db.commit()
        self.db.refresh(chat_session)
        return chat_session

    def test_forced_compression_summarises_and_returns_the_batch(self):
        chat_session = self._session_with_history("unittest-compress")
        batch = ContextService(self.db).maybe_compress(
            chat_session, system_overhead="你是 LuLu。", force=True
        )
        self.assertTrue(batch)
        self.db.refresh(chat_session)
        self.assertTrue((chat_session.summary or "").strip())

    def test_short_history_is_left_alone(self):
        chat_session = self._session_with_history("unittest-short", turns=1)
        self.assertIsNone(
            ContextService(self.db).maybe_compress(chat_session, system_overhead="你是 LuLu。")
        )


if __name__ == "__main__":
    unittest.main()
