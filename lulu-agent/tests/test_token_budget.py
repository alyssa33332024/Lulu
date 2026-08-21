import unittest

from app.memory.token_budget import (
    estimate_context_tokens,
    estimate_message_tokens,
    hard_input_limit,
    soft_input_limit,
    split_keep_recent_by_tokens,
)


class InputLimitTests(unittest.TestCase):
    def test_soft_limit_is_74_percent_of_window(self):
        self.assertEqual(soft_input_limit(100_000), 74_000)

    def test_soft_limit_of_empty_window(self):
        self.assertEqual(soft_input_limit(0), 0)

    def test_hard_limit_reserves_output_budget(self):
        self.assertEqual(hard_input_limit(100_000, 4_096), 95_904)

    def test_output_budget_must_fit_inside_window(self):
        """压缩配置踩过的坑：context_window 调小后 max_output_tokens 反而更大。"""
        with self.assertRaises(ValueError):
            hard_input_limit(80, 4_096)

    def test_bool_is_not_accepted_as_token_count(self):
        with self.assertRaises(ValueError):
            hard_input_limit(1_000, True)

    def test_non_positive_window_rejected(self):
        with self.assertRaises(ValueError):
            hard_input_limit(0, 10)


class EstimateTests(unittest.TestCase):
    def test_empty_history_costs_nothing(self):
        self.assertEqual(estimate_message_tokens([]), 0)

    def test_longer_content_costs_more(self):
        short = estimate_message_tokens([{"role": "user", "content": "你好"}])
        long = estimate_message_tokens([{"role": "user", "content": "你好" * 200}])
        self.assertGreater(long, short)

    def test_low_detail_image_block_priced_at_1024(self):
        tokens = estimate_message_tokens(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"detail": "low"}},
                    ],
                }
            ]
        )
        self.assertGreaterEqual(tokens, 1024)
        self.assertLess(tokens, 8192)

    def test_tool_schemas_count_towards_context(self):
        messages = [{"role": "user", "content": "唱一首歌"}]
        tools = [
            {
                "type": "function",
                "function": {"name": "PlaySong", "parameters": {"song_id": "string"}},
            }
        ]
        self.assertGreater(
            estimate_context_tokens(messages, tools=tools),
            estimate_context_tokens(messages),
        )

    def test_system_prompt_prepended_only_when_absent(self):
        messages = [{"role": "system", "content": "你是 LuLu。"}]
        self.assertEqual(
            estimate_context_tokens(messages, system_prompt="你是 LuLu。"),
            estimate_context_tokens(messages),
        )


class SplitKeepRecentTests(unittest.TestCase):
    def _messages(self, count: int) -> list[dict]:
        return [{"role": "user", "content": f"{i}" + "闲" * 300} for i in range(count)]

    def test_empty_history_splits_to_nothing(self):
        self.assertEqual(split_keep_recent_by_tokens([]), ([], []))

    def test_generous_budget_keeps_everything(self):
        messages = self._messages(4)
        prefix, retained = split_keep_recent_by_tokens(messages, keep_recent_tokens=1_000_000)
        self.assertEqual(prefix, [])
        self.assertEqual(retained, messages)

    def test_tight_budget_splits_without_losing_messages(self):
        messages = self._messages(6)
        prefix, retained = split_keep_recent_by_tokens(messages, keep_recent_tokens=150)
        self.assertTrue(prefix)
        self.assertTrue(retained)
        self.assertEqual(prefix + retained, messages)

    def test_always_retains_at_least_one_message(self):
        messages = self._messages(3)
        _prefix, retained = split_keep_recent_by_tokens(messages, keep_recent_tokens=1)
        self.assertTrue(retained)


if __name__ == "__main__":
    unittest.main()
