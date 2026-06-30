import datetime
import os
import time
import uuid
from typing import Dict, List

from storage import ReminderStorage
from bot import confirm_dose_keyboard, display_time, send_message

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

_TZ_NAME = os.environ.get("TZ", "Africa/Cairo")
# مدة الانتظار قبل إبلاغ الـ caregiver (بالدقائق)
CONFIRM_TIMEOUT_MINUTES = int(os.environ.get("CONFIRM_TIMEOUT_MINUTES", "30"))


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=ZoneInfo(_TZ_NAME)).replace(tzinfo=None)


def parse_time_string(time_str: str) -> datetime.time:
    h, m = time_str.split(":", 1)
    return datetime.time(hour=int(h), minute=int(m))


def is_due(reminder: Dict, now: datetime.datetime) -> bool:
    rule = reminder.get("repeat_rule", "daily")
    if rule == "daily":
        return _is_daily_due(reminder, now)
    if rule == "interval":
        return _is_interval_due(reminder, now)
    return False


def _is_daily_due(reminder: Dict, now: datetime.datetime) -> bool:
    scheduled = parse_time_string(reminder["time"])
    dt = datetime.datetime.combine(now.date(), scheduled)
    if now < dt:
        return False
    created_at_str = reminder.get("created_at")
    if created_at_str:
        try:
            created_at = datetime.datetime.fromisoformat(created_at_str)
            if created_at > dt:
                return False
        except ValueError:
            pass
    last = reminder.get("last_sent_at")
    today = now.strftime("%Y-%m-%d")
    return not last or not last.startswith(today)


def _is_interval_due(reminder: Dict, now: datetime.datetime) -> bool:
    repeat_value = reminder.get("repeat_value") or 0
    if repeat_value <= 0:
        return False
    last = reminder.get("last_sent_at")
    if not last:
        scheduled = parse_time_string(reminder["time"])
        dt = datetime.datetime.combine(now.date(), scheduled)
        created_at_str = reminder.get("created_at")
        if created_at_str:
            try:
                created_at = datetime.datetime.fromisoformat(created_at_str)
                while dt < created_at:
                    dt += datetime.timedelta(hours=repeat_value)
            except ValueError:
                pass
        return now >= dt
    return now >= datetime.datetime.fromisoformat(last) + datetime.timedelta(hours=repeat_value)


class ReminderScheduler:
    def __init__(self, storage: ReminderStorage, interval_seconds: int = 30):
        self.storage = storage
        self.interval_seconds = interval_seconds

    def run_once(self) -> None:
        now = _now()
        self._send_due_reminders(now)
        self._check_unconfirmed()

    def _send_due_reminders(self, now: datetime.datetime) -> None:
        for reminder in self.storage.list_all_active():
            if not is_due(reminder, now):
                continue

            chat_id = int(reminder["chat_id"])
            med_name = reminder["medication_name"]
            time_str = display_time(reminder["time"])

            # إنشاء confirmation record
            confirmation_id = str(uuid.uuid4())
            self.storage.add_pending(confirmation_id, reminder["id"], chat_id)
            self.storage.mark_sent(reminder["id"])

            # إرسال التذكير مع زر التأكيد
            send_message(
                chat_id,
                f"⏰ <b>تذكير الدواء</b>\n\n💊 {med_name}\n🕐 {time_str}\n\nاضغط بعد ما تاخد الدواء 👇",
                reply_markup=confirm_dose_keyboard(confirmation_id),
            )

    def _check_unconfirmed(self) -> None:
        """يبلّغ المتابعين لو المريض ما أكدش أخذ الدواء بعد X دقيقة."""
        unconfirmed = self.storage.get_unconfirmed_pending(
            older_than_minutes=CONFIRM_TIMEOUT_MINUTES
        )
        for pending in unconfirmed:
            chat_id = int(pending["chat_id"])
            caregivers = self.storage.get_caregivers(chat_id)
            if not caregivers:
                # مفيش متابع، نعلّم فقط عشان ما نبعتش تاني
                self.storage.mark_caregiver_notified(pending["id"])
                continue

            reminder = self.storage.get_reminder(pending["reminder_id"])
            med_name = reminder["medication_name"] if reminder else "دواء"
            time_str = display_time(reminder["time"]) if reminder else ""

            for cg_id in caregivers:
                send_message(
                    cg_id,
                    f"⚠️ <b>تنبيه متابعة</b>\n\n"
                    f"الشخص اللي بتتابعه <b>لم يؤكد</b> أخذ دواؤه:\n"
                    f"💊 {med_name}\n🕐 {time_str}\n\n"
                    f"مر أكثر من {CONFIRM_TIMEOUT_MINUTES} دقيقة على موعد الجرعة.",
                )

            self.storage.mark_caregiver_notified(pending["id"])

    def run_loop(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception as exc:
                print(f"Scheduler error: {exc}")
            time.sleep(self.interval_seconds)
