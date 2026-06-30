import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

from storage import ReminderStorage

TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("BOT_TOKEN") or ""
API_URL = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else None
STORAGE = ReminderStorage()

# حالة المحادثة لكل مستخدم: {chat_id: {"step": ..., "data": {...}}}
USER_STATE: Dict[int, Dict[str, Any]] = {}


# ─── Telegram API ──────────────────────────────────────────────────────────────

def telegram_request(method: str, params: Optional[Dict[str, Any]] = None, timeout: int = 35) -> Dict[str, Any]:
    if not API_URL:
        raise RuntimeError("لم يتم تعيين TELEGRAM_TOKEN.")
    body = urllib.parse.urlencode(params or {}).encode("utf-8")
    req = urllib.request.Request(f"{API_URL}/{method}", data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            raise RuntimeError("Conflict: terminated by other getUpdates request") from exc
        raise


def get_updates(offset: Optional[int] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        params["offset"] = offset
    for attempt in range(3):
        try:
            return telegram_request("getUpdates", params, timeout=35).get("result", [])
        except RuntimeError as exc:
            if "Conflict" in str(exc):
                wait = 5 * (attempt + 1)
                print(f"Conflict (attempt {attempt+1}), waiting {wait}s...")
                delete_webhook()
                time.sleep(wait)
                continue
            raise
        except Exception as exc:
            print(f"getUpdates error: {exc}")
            time.sleep(3)
    return []


def delete_webhook() -> None:
    try:
        telegram_request("deleteWebhook", {"drop_pending_updates": True}, timeout=10)
        print("Webhook deleted.")
    except Exception as exc:
        print(f"delete_webhook warning: {exc}")


def kick_other_instances() -> None:
    print("Kicking other instances...")
    for _ in range(3):
        try:
            telegram_request("getUpdates", {"timeout": 0, "limit": 1}, timeout=10)
        except Exception:
            pass
        time.sleep(2)
    print("Done. Starting polling.")


def send_message(chat_id: int, text: str, reply_markup: Optional[Dict] = None) -> None:
    params: Dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    telegram_request("sendMessage", params)


def answer_callback(callback_id: str) -> None:
    telegram_request("answerCallbackQuery", {"callback_query_id": callback_id})


def edit_message(chat_id: int, message_id: int, text: str, reply_markup: Optional[Dict] = None) -> None:
    params: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    try:
        telegram_request("editMessageText", params)
    except Exception:
        pass


# ─── Keyboards ─────────────────────────────────────────────────────────────────

def main_menu_keyboard() -> Dict:
    return {
        "keyboard": [
            [{"text": "💊 إضافة دواء"}, {"text": "📋 أدويتي"}],
            [{"text": "🗑 حذف دواء"}],
        ],
        "resize_keyboard": True,
        "persistent": True,
    }


def repeat_keyboard() -> Dict:
    return {
        "inline_keyboard": [
            [
                {"text": "يومي 🔁", "callback_data": "repeat:daily:0"},
                {"text": "كل 6 ساعات", "callback_data": "repeat:interval:6"},
            ],
            [
                {"text": "كل 8 ساعات", "callback_data": "repeat:interval:8"},
                {"text": "كل 12 ساعة", "callback_data": "repeat:interval:12"},
            ],
        ]
    }


def delete_keyboard(reminders: List[Dict[str, Any]]) -> Dict:
    buttons = []
    for r in reminders:
        label = f"❌ {r['medication_name']} — {r['time']}"
        buttons.append([{"text": label, "callback_data": f"del:{r['id']}"}])
    buttons.append([{"text": "↩️ رجوع", "callback_data": "del:cancel"}])
    return {"inline_keyboard": buttons}


# ─── Helpers ───────────────────────────────────────────────────────────────────

def normalize_time(value: str) -> str:
    value = value.strip()
    if ":" not in value:
        raise ValueError("❌ صيغة الوقت غلط. اكتب مثلاً: <b>08:30</b>")
    h, m = value.split(":", 1)
    hour, minute = int(h), int(m)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("❌ الوقت غير صالح. الساعة بين 00-23 والدقائق بين 00-59")
    return f"{hour:02d}:{minute:02d}"


def format_reminder(r: Dict[str, Any]) -> str:
    rule = "يومي" if r.get("repeat_rule") == "daily" else f"كل {r.get('repeat_value')} ساعة"
    return f"• <b>{r['medication_name']}</b> — {r['time']} ({rule})"


# ─── Flow handlers ─────────────────────────────────────────────────────────────

def start_add_flow(chat_id: int) -> None:
    USER_STATE[chat_id] = {"step": "awaiting_name"}
    send_message(chat_id, "💊 اكتب <b>اسم الدواء</b>:")


def handle_text(chat_id: int, text: str) -> None:
    state = USER_STATE.get(chat_id, {})
    step = state.get("step")

    # ─ إضافة دواء: خطوة 1 — اسم الدواء
    if step == "awaiting_name":
        USER_STATE[chat_id] = {"step": "awaiting_time", "data": {"name": text}}
        send_message(chat_id, f"✅ الدواء: <b>{text}</b>\n\nدلوقتي اكتب <b>وقت الجرعة</b> (مثال: <b>08:30</b>):")
        return

    # ─ إضافة دواء: خطوة 2 — الوقت
    if step == "awaiting_time":
        try:
            time_str = normalize_time(text)
        except ValueError as exc:
            send_message(chat_id, str(exc))
            return
        USER_STATE[chat_id]["data"]["time"] = time_str
        USER_STATE[chat_id]["step"] = "awaiting_repeat"
        send_message(
            chat_id,
            f"✅ الوقت: <b>{time_str}</b>\n\nاختار نوع التكرار:",
            reply_markup=repeat_keyboard(),
        )
        return

    # ─ قائمة الأدوية
    if text in ("📋 أدويتي", "/list"):
        show_list(chat_id)
        return

    # ─ إضافة دواء
    if text in ("💊 إضافة دواء", "/addmed"):
        start_add_flow(chat_id)
        return

    # ─ حذف دواء
    if text in ("🗑 حذف دواء", "/remove"):
        show_delete_menu(chat_id)
        return

    # ─ start / help
    if text in ("/start", "/help"):
        send_message(
            chat_id,
            "أهلاً! 🩺 أنا بوت تذكير الدواء.\nاستخدم الأزرار أسفل الشاشة 👇",
            reply_markup=main_menu_keyboard(),
        )
        return

    # رسالة مش معروفة
    send_message(chat_id, "استخدم الأزرار 👇", reply_markup=main_menu_keyboard())


def handle_callback(chat_id: int, callback_id: str, data: str, message_id: int) -> None:
    answer_callback(callback_id)

    # ─ اختيار التكرار
    if data.startswith("repeat:"):
        state = USER_STATE.get(chat_id, {})
        if state.get("step") != "awaiting_repeat":
            return
        _, rule, value = data.split(":")
        med_data = state.get("data", {})
        repeat_value = int(value) if rule == "interval" else None
        reminder_id = str(uuid.uuid4())
        STORAGE.add_reminder(reminder_id, chat_id, med_data["name"], med_data["time"], rule, repeat_value)
        USER_STATE.pop(chat_id, None)
        rule_text = "يومي" if rule == "daily" else f"كل {repeat_value} ساعة"
        edit_message(
            chat_id, message_id,
            f"✅ <b>تمت الإضافة!</b>\n\n💊 {med_data['name']}\n🕐 {med_data['time']}\n🔁 {rule_text}",
        )
        return

    # ─ حذف دواء
    if data.startswith("del:"):
        reminder_id = data[4:]
        if reminder_id == "cancel":
            edit_message(chat_id, message_id, "↩️ تم الإلغاء.")
            return
        deleted = STORAGE.remove_reminder(chat_id, reminder_id)
        if deleted:
            edit_message(chat_id, message_id, "🗑 تم حذف الدواء بنجاح.")
        else:
            edit_message(chat_id, message_id, "❌ مش لاقي الدواء ده.")
        return


def show_list(chat_id: int) -> None:
    reminders = STORAGE.list_reminders(chat_id)
    if not reminders:
        send_message(chat_id, "📋 مفيش أدوية مضافة لحد دلوقتي.\n\nاضغط <b>💊 إضافة دواء</b> للبدء.")
        return
    lines = [format_reminder(r) for r in reminders]
    send_message(chat_id, "📋 <b>أدويتك:</b>\n\n" + "\n".join(lines))


def show_delete_menu(chat_id: int) -> None:
    reminders = STORAGE.list_reminders(chat_id)
    if not reminders:
        send_message(chat_id, "📋 مفيش أدوية عندك دلوقتي.")
        return
    send_message(chat_id, "اختار الدواء اللي تريد تحذفه:", reply_markup=delete_keyboard(reminders))


# ─── Main update handler ────────────────────────────────────────────────────────

def handle_update(update: Dict[str, Any]) -> None:
    # Callback query (button press)
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]
        handle_callback(chat_id, cq["id"], cq.get("data", ""), message_id)
        return

    # Regular message
    message = update.get("message", {})
    if not message:
        return
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    if not chat_id or not text:
        return

    handle_text(chat_id, text)


# ─── Bot loop ───────────────────────────────────────────────────────────────────

def run_bot() -> None:
    if not TOKEN:
        print("Set TELEGRAM_TOKEN env var and restart.")
        return

    print("Bot is running...")
    offset: Optional[int] = None
    while True:
        try:
            updates = get_updates(offset=offset)
            for update in updates:
                update_id = update.get("update_id")
                if update_id is not None:
                    offset = update_id + 1
                try:
                    handle_update(update)
                except Exception as exc:
                    print(f"handle_update error: {exc}")
        except RuntimeError as exc:
            if "Conflict" in str(exc):
                print(f"Fatal conflict: {exc}")
                raise
            print(f"Polling error: {exc}")
            time.sleep(5)
        except Exception as exc:
            print(f"Unexpected polling error: {exc}")
            time.sleep(5)
