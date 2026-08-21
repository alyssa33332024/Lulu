"""把 `python -m app.harness.runner --suite all` 的 11 个验收 suite 挂进测试集。

单测覆盖单点行为，harness 覆盖跨组件验收（RAG 命中率、角色解锁门槛、技能目录等），
两边都跑才算完整。
"""

from tests.harness_env import CONTEXT  # isort:skip  必须先导入，隔离 DB 与模型调用

import unittest

from app.harness.runner import resolve_suites, run_check

SUITES = resolve_suites(None)


class EngineeringHarnessTests(unittest.TestCase):
    def test_all_suites_are_registered(self):
        self.assertEqual(len(SUITES), 11)

    def test_every_suite_passes(self):
        for name, fn in SUITES:
            with self.subTest(suite=name):
                result = run_check(name, fn, CONTEXT)
                self.assertTrue(result.passed, "\n".join(result.failures))

    def test_intent_routing_stays_above_the_accuracy_floor(self):
        from app.harness.runner import run_rag_harness

        details = run_rag_harness(CONTEXT)
        self.assertGreaterEqual(details["hitRate"], 0.75)
        self.assertEqual(details["total"], details["hit"] + len(
            [row for row in details["details"] if not row["ok"]]
        ))


if __name__ == "__main__":
    unittest.main()
