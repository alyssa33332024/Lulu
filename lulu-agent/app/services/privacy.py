from __future__ import annotations

import re


class PrivacySanitizer:
    _phone = re.compile(r"1[3-9]\d{9}")
    _email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

    def sanitize(self, text: str) -> str:
        text = self._phone.sub("[手机号]", text)
        text = self._email.sub("[邮箱]", text)
        return text
