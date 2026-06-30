import os
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

from storage import ReminderStorage

TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("BOT_TOKEN") or ""
API_URL = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else None
STORAGE = ReminderStorage()


def telegram_request(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not API_URL:
        raise RuntimeError("لم يتم تعيين TELEGRAM_TOKEN. عيّن متغير البيئة ثم أعد التشغيل.")
    body = urllib.parse.urlencode(params or {}).encode("utf-8")
    request = urllib.request.Request(f"{API_URL}/{method}", data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise RuntimeError("Conflict: يبدو أنه تم تفعيل webhook للبوت. تأكد من تعطيل webhook قبل استخدام polling.") from exc
        raise


def get_updates(offset: Optional[int] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"timeout": 5}
    if offset is not None:
        params["offset"] = offset

    for attempt in range(2):
        try:
            payload = telegram_request("getUpdates", params)
            return payload.get("result", [])
        except RuntimeError as exc:
            if "Conflict" in str(exc) and attempt == 0:
                print("Conflict detected، أحاول حذف webhook ثم إعادة المحاولة...")
                delete_webhook()
                time.sleep(1)
                continue
            raise

    return []

def delete_webhook() -> None:
    try:
        telegram_request("deleteWebhook")
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            print("Webhook غير مفعّل بالفعل أو تم حذفه.")
            return
        raise
    except RuntimeError as exc:
        print(f"تحذير: {exc}")
    except Exception as exc:
        print(f"فشل حذف webhook: {exc}")


def send_message(chat_id: int, text: str) -> None:
    telegram_request("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def normalize_time_string(value: str) -> str:
    raw_value = value.strip()
    if ":" not in raw_value:
        raise ValueError("استخدم الوقت بصيغة HH:MM")
    hour_text, minute_text = raw_value.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("الوقت غير صالح. استخدم ساعات بين 00 و 23 ودقائق بين 00 و 59")
    return f"{hour:02d}:{minute:02d}"


def parse_addmed_command(text: str) -> Tuple[str, str, str, Optional[int]]:
    parts = text.strip().split()
    if len(parts) < 2:
        raise ValueError("الصيغة: /addmed اسم_الدواء 08:30 [daily|everyXh]")

    if parts[-1].startswith("every"):
        raise ValueError("أضف قاعدة التكرار بعد الوقت، مثل: /addmed دواء 08:30 every8h")

    medication_name = " ".join(parts[:-1])
    time_str = normalize_time_string(parts[-1])
    repeat_rule = "daily"
    repeat_value: Optional[int] = None

    if len(parts) > 2:
        last = parts[-1]
        second_last = parts[-2]
        if second_last.startswith("every"):
            repeat_rule = "interval"
            repeat_value = int(second_last[5:-1]) if second_last.endswith("h") else int(second_last[5:])
            medication_name = " ".join(parts[:-2])
            time_str = normalize_time_string(last)

    return medication_name, time_str, repeat_rule, repeat_value


def format_reminder(reminder: Dict[str, Any]) -> str:
    parts = [f"• {reminder['medication_name']} — {reminder['time']}"]
    rule = reminder.get("repeat_rule", "daily")
    if rule == "interval":
        parts.append(f"كل {reminder.get('repeat_value')} ساعة")
    else:
        parts.append("يومي")
    parts.append(f"المعرف: {reminder['id']}")
    return " — ".join(parts)


def handle_update(update: Dict[str, Any]) -> None:
    message = update.get("message", {})
    if not message:
        return

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    if not chat_id or not text:
        return

    if text.startswith("/start"):
        send_message(
            chat_id,
            "أهلاً بك! 🩺\nأنا بوت تذكير بالجرعات الاحترافي.\n\n"
            "• /addmed اسم_الدواء 08:30\n"
            "• /addmed اسم_الدواء 08:30 every8h\n"
            "• /list\n"
            "• /remove معرف_التذكير\n"
            "• /help",
        )
        return

    if text.startswith("/help"):
        send_message(
            chat_id,
            "استخدم /addmed اسم_الدواء 08:30 لإضافة تذكير يومي، أو /addmed اسم_الدواء 08:30 every8h لتكرار كل 8 ساعات."
        )
        return

    if text.startswith("/addmed"):
        try:
            medication_name, time_str, repeat_rule, repeat_value = parse_addmed_command(text[len("/addmed"):].strip())
        except ValueError as exc:
            send_message(chat_id, str(exc))
            return

        reminder_id = str(uuid.uuid4())
        reminder = STORAGE.add_reminder(chat_id, medication_name, time_str, repeat_rule, repeat_value)
        send_message(
            chat_id,
            f"✅ تمت إضافة تذكير جديد:\n{name_message(reminder)}\n{repeat_message(reminder)}\nالمعرف: {reminder['id']}",
        )
        return

    if text.startswith("/list"):
        reminders = STORAGE.list_reminders(chat_id)
        if not reminders:
            send_message(chat_id, "لا توجد جرعات محفوظة حتى الآن.")
            return
        lines = [format_reminder(reminder) for reminder in reminders]
        send_message(chat_id, "قائمة التذكيرات:\n" + "\n".join(lines))
        return

    if text.startswith("/remove"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send_message(chat_id, "استخدم الصيغة: /remove معرف_التذكير")
            return
        reminder_id = parts[1].strip()
        deleted = STORAGE.remove_reminder(chat_id, reminder_id)
        send_message(chat_id, "✅ تم حذف التذكير." if deleted else "لم أتمكن من حذف هذا التذكير. تأكد من المعرف.")
        return

    send_message(chat_id, "أرسل /help لرؤية الأوامر المتاحة.")


def name_message(reminder: Dict[str, Any]) -> str:
    return f"الدواء: {reminder['medication_name']}\nالوقت: {reminder['time']}"


def repeat_message(reminder: Dict[str, Any]) -> str:
    if reminder.get("repeat_rule") == "interval":
        return f"التكرار: كل {reminder.get('repeat_value')} ساعة"
    return "التكرار: يومي"


def run_bot() -> None:
    if not TOKEN:
        print("أدخل قيمة TELEGRAM_TOKEN في متغيرات البيئة ثم أعد تشغيل البوت.")
        return

    print("البوت يعمل الآن...")
    offset: Optional[int] = None
    while True:
        updates = get_updates(offset=offset)
        for update in updates:
            update_id = update.get("update_id")
            if update_id is not None:
                offset = update_id + 1
            handle_update(update)
