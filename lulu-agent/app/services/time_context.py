from __future__ import annotations

from datetime import datetime, timedelta

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _normalize_timestamp(message_timestamp: datetime | None = None) -> datetime:
    ts = message_timestamp or datetime.now()
    return ts.astimezone() if ts.tzinfo is not None else ts


def _weekday_cn(ts: datetime) -> str:
    return WEEKDAYS[ts.weekday()]


def build_current_message_time_envelope(*, message_timestamp: datetime | None = None) -> str:
    ts = _normalize_timestamp(message_timestamp)
    if ts.tzinfo is None:
        ts = ts.astimezone()
    yesterday = ts - timedelta(days=1)
    tomorrow = ts + timedelta(days=1)
    day_after_tomorrow = ts + timedelta(days=2)
    return (
        f"[当前消息时间: {ts.strftime('%Y-%m-%d %H:%M:%S %Z')} | "
        f"request_time={ts.isoformat()} | "
        f"今天={ts.strftime('%Y-%m-%d')}（{_weekday_cn(ts)}） | "
        f"昨天={yesterday.strftime('%Y-%m-%d')}（{_weekday_cn(yesterday)}） | "
        f"明天={tomorrow.strftime('%Y-%m-%d')}（{_weekday_cn(tomorrow)}） | "
        f"后天={day_after_tomorrow.strftime('%Y-%m-%d')}（{_weekday_cn(day_after_tomorrow)}） | "
        f"weekday={ts.strftime('%A')} | "
        f"相对时间以此为准]"
    )


def stamp_user_message(text: str, *, message_timestamp: datetime | None = None) -> str:
    """给当前轮 user 消息加时间信封（与 akashic-agent 一致）。"""
    stripped = text.lstrip()
    if not stripped:
        return build_current_message_time_envelope(message_timestamp=message_timestamp)
    if stripped.startswith("[当前消息时间:"):
        return text
    stamp = build_current_message_time_envelope(message_timestamp=message_timestamp)
    return f"{stamp}\n{text}"
