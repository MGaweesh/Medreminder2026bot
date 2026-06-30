import datetime
import os
import time
from typing import Dict, List

from storage import ReminderStorage
from bot import send_message

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

_TZ_NAME = os.environ.get("TZ", "Africa/Cairo")


def _now() -> datetime.datetime:
    """الوقت الحالي بتوقيت المستخدم (من TZ env var)."""
    return datetime.datetime.now(tz=ZoneInfo(_TZ_NAME)).replace(tzinfo=None)


def parse_time_string(time_str: str) -> datetime.time:
    hour_text, minute_text = time_str.split(":", 1)
    return datetime.time(hour=int(hour_text), minute=int(minute_text))


def is_due(reminder: Dict[str, str], now: datetime.datetime) -> bool:
    repeat_rule = reminder.get("repeat_rule", "daily")
    scheduled_time = parse_time_string(reminder["time"])

    if repeat_rule == "daily":
        return _is_daily_due(reminder, now, scheduled_time)

    if repeat_rule == "interval":
        return _is_interval_due(reminder, now)

    return False


def _is_daily_due(reminder: Dict[str, str], now: datetime.datetime, scheduled_time: datetime.time) -> bool:
    if now.time().hour != scheduled_time.hour or now.time().minute != scheduled_time.minute:
        return False
    last_sent_at = reminder.get("last_sent_at")
    today = now.strftime("%Y-%m-%d")
    if not last_sent_at:
        return True
    return not last_sent_at.startswith(today)


def _is_interval_due(reminder: Dict[str, str], now: datetime.datetime) -> bool:
    repeat_value = reminder.get("repeat_value") or 0
    if repeat_value <= 0:
        return False

    last_sent_at = reminder.get("last_sent_at")
    if not last_sent_at:
        scheduled_time = parse_time_string(reminder["time"])
        scheduled_datetime = datetime.datetime.combine(now.date(), scheduled_time)
        if now >= scheduled_datetime and now < scheduled_datetime + datetime.timedelta(minutes=1):
            return True
        return False

    last_sent = datetime.datetime.fromisoformat(last_sent_at)
    return now >= last_sent + datetime.timedelta(hours=repeat_value)


class ReminderScheduler:
    def __init__(self, storage: ReminderStorage, interval_seconds: int = 30):
        self.storage = storage
        self.interval_seconds = interval_seconds

    def run_once(self) -> None:
        now = _now()
        reminders = self.storage.list_all_active()
        for reminder in reminders:
            if is_due(reminder, now):
                send_message(
                    int(reminder["chat_id"]),
                    f"⏰ تذكير مهم: حان الآن موعد الجرعة ({reminder['medication_name']}).",
                )
                self.storage.mark_sent(reminder["id"])

    def run_loop(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception as exc:
                print(f"خطأ في جدولة التذكيرات: {exc}")
            time.sleep(self.interval_seconds)
