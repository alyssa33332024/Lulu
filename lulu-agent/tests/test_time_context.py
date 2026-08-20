import unittest
from datetime import datetime, timedelta, timezone

from app.services.time_context import build_current_message_time_envelope, stamp_user_message


class TimeContextTests(unittest.TestCase):
    def test_envelope_contains_today_and_tomorrow(self):
        ts = datetime.fromisoformat("2026-04-08T17:57:00+08:00")
        local = ts.astimezone()
        text = build_current_message_time_envelope(message_timestamp=ts)
        self.assertIn(f"当前消息时间: {local:%Y-%m-%d %H:%M}", text)
        self.assertIn(f"今天={local:%Y-%m-%d}", text)
        self.assertIn(f"明天={local + timedelta(days=1):%Y-%m-%d}", text)
        self.assertIn("相对时间以此为准", text)

    def test_stamp_user_message(self):
        ts = datetime(2026, 4, 8, 17, 57, tzinfo=timezone(timedelta(hours=8)))
        out = stamp_user_message("那考试是哪天来着？", message_timestamp=ts)
        self.assertTrue(out.startswith("[当前消息时间:"))
        self.assertTrue(out.endswith("那考试是哪天来着？"))
        self.assertIn("今天=2026-04-08", out)

    def test_stamp_skips_already_stamped(self):
        stamped = "[当前消息时间: x]\nhello"
        self.assertEqual(stamp_user_message(stamped), stamped)


if __name__ == "__main__":
    unittest.main()
