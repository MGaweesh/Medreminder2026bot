import datetime
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

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "Mgaweesh")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

# حالة المحادثة لكل مستخدم
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


def answer_callback(callback_id: str, text: str = "") -> None:
    telegram_request("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def edit_message(chat_id: int, message_id: int, text: str, reply_markup: Optional[Dict] = None) -> None:
    params: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    else:
        params["reply_markup"] = json.dumps({"inline_keyboard": []})
    try:
        telegram_request("editMessageText", params)
    except Exception:
        pass


# ─── Keyboards ─────────────────────────────────────────────────────────────────

def main_menu_keyboard() -> Dict:
    return {
        "keyboard": [
            [{"text": "💊 إضافة دواء"}, {"text": "📋 أدويتي"}],
            [{"text": "🗑 حذف دواء"}, {"text": "👥 المتابعة"}],
        ],
        "resize_keyboard": True,
        "persistent": True,
    }


def ampm_keyboard() -> Dict:
    return {
        "inline_keyboard": [[
            {"text": "🌅 صباحاً", "callback_data": "ampm:am"},
            {"text": "🌙 مساءً", "callback_data": "ampm:pm"},
        ]]
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
        label = f"❌ {r['medication_name']} — {display_time(r['time'])}"
        buttons.append([{"text": label, "callback_data": f"del:{r['id']}"}])
    buttons.append([{"text": "↩️ رجوع", "callback_data": "del:cancel"}])
    return {"inline_keyboard": buttons}


def hours_keyboard() -> Dict:
    buttons = []
    for r in range(3):
        row = []
        for c in range(4):
            h = r * 4 + c + 1
            row.append({"text": f"{h}", "callback_data": f"hour:{h}"})
        buttons.append(row)
    return {"inline_keyboard": buttons}


def minutes_keyboard() -> Dict:
    return {
        "inline_keyboard": [
            [
                {"text": ":00", "callback_data": "minute:00"},
                {"text": ":15", "callback_data": "minute:15"},
                {"text": ":30", "callback_data": "minute:30"},
                {"text": ":45", "callback_data": "minute:45"},
            ]
        ]
    }


def confirm_add_keyboard() -> Dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ تأكيد", "callback_data": "confirm_add:yes"},
                {"text": "❌ إلغاء", "callback_data": "confirm_add:no"},
            ]
        ]
    }


def confirm_dose_keyboard(confirmation_id: str) -> Dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ أخدت الدواء", "callback_data": f"confirm:{confirmation_id}"},
        ]]
    }


def caregiver_menu_keyboard() -> Dict:
    return {
        "inline_keyboard": [
            [{"text": "🔗 مشاركة كودي (لشخص يتابعني)", "callback_data": "cg:share"}],
            [{"text": "👁 ربط بشخص أتابعه", "callback_data": "cg:link"}],
            [{"text": "📊 إدارة المتابَعين", "callback_data": "cg:patients"}],
            [{"text": "🔓 إلغاء ربط", "callback_data": "cg:unlink"}],
        ]
    }


def manage_patient_keyboard(patient_id: int) -> Dict:
    """قائمة إدارة مريض معين من طرف المتابع."""
    pid = str(patient_id)
    return {
        "inline_keyboard": [
            [{"text": "📋 عرض أدويته", "callback_data": f"pt:list:{pid}"}],
            [{"text": "➕ إضافة دواء له", "callback_data": f"pt:add:{pid}"}],
            [{"text": "🗑 حذف دواء له", "callback_data": f"pt:del:{pid}"}],
            [{"text": "🔔 تذكير يدوي الآن", "callback_data": f"pt:remind:{pid}"}],
            [{"text": "↩️ رجوع", "callback_data": "cg:patients"}],
        ]
    }


def delete_patient_med_keyboard(reminders: List[Dict[str, Any]], patient_id: int) -> Dict:
    buttons = []
    for r in reminders:
        label = f"❌ {r['medication_name']} — {display_time(r['time'])}"
        buttons.append([{"text": label, "callback_data": f"pt:delmed:{patient_id}:{r['id']}"}])
    buttons.append([{"text": "↩️ رجوع", "callback_data": f"pt:back:{patient_id}"}])
    return {"inline_keyboard": buttons}


def unlink_keyboard(patients: List[Dict[str, Any]]) -> Dict:
    buttons = []
    for p in patients:
        label = f"🔓 إلغاء متابعة {p['patient_chat_id']}"
        buttons.append([{"text": label, "callback_data": f"unlink:{p['patient_chat_id']}"}])
    buttons.append([{"text": "↩️ رجوع", "callback_data": "cg:back"}])
    return {"inline_keyboard": buttons}


# ─── Time Helpers ──────────────────────────────────────────────────────────────

def normalize_time(value: str) -> str:
    value = value.strip().replace(".", ":")
    if ":" not in value:
        raise ValueError("❌ صيغة الوقت غلط. اكتب مثلاً: <b>8:30</b> أو <b>11:00</b>")
    h, m = value.split(":", 1)
    hour, minute = int(h.strip()), int(m.strip())
    if not (1 <= hour <= 12 and 0 <= minute <= 59):
        raise ValueError("❌ اكتب الوقت من 1 لـ 12 والدقائق من 00 لـ 59\nمثال: <b>8:30</b>")
    return f"{hour:02d}:{minute:02d}"


def apply_ampm(time_str: str, period: str) -> str:
    hour, minute = map(int, time_str.split(":"))
    if period == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = hour if hour == 12 else hour + 12
    return f"{hour:02d}:{minute:02d}"


def display_time(time_24: str) -> str:
    hour, minute = map(int, time_24.split(":"))
    period = "🌅 صباحاً" if hour < 12 else "🌙 مساءً"
    display_hour = hour % 12 or 12
    return f"{display_hour:02d}:{minute:02d} {period}"


def get_all_dose_times(time_24: str, rule: str, repeat_value: Optional[int]) -> List[str]:
    if rule == "daily" or not repeat_value or repeat_value <= 0:
        return [time_24]
    times = []
    h, m = map(int, time_24.split(":"))
    start_dt = datetime.datetime(2000, 1, 1, h, m)
    num_doses = 24 // repeat_value
    for i in range(num_doses):
        dt = start_dt + datetime.timedelta(hours=i * repeat_value)
        times.append(f"{dt.hour:02d}:{dt.minute:02d}")
    times.sort()
    return times


def format_reminder(r: Dict[str, Any]) -> str:
    rule = "يومي" if r.get("repeat_rule") == "daily" else f"كل {r.get('repeat_value')} ساعة"
    return f"• <b>{r['medication_name']}</b> — {display_time(r['time'])} ({rule})"


# ─── Add Medicine Flow ─────────────────────────────────────────────────────────

def start_add_flow(chat_id: int) -> None:
    USER_STATE[chat_id] = {"step": "awaiting_name"}
    send_message(chat_id, "💊 اكتب <b>اسم الدواء</b>:")


# ─── Caregiver Flow ────────────────────────────────────────────────────────────

def show_caregiver_menu(chat_id: int) -> None:
    send_message(chat_id, "👥 <b>إعدادات المتابعة</b>\n\nاختار:", reply_markup=caregiver_menu_keyboard())


# ─── Text Handler ──────────────────────────────────────────────────────────────

def handle_text(chat_id: int, text: str, message: Dict[str, Any]) -> None:
    state = USER_STATE.get(chat_id, {})
    step = state.get("step")

    # ─ أمر الإحصائيات (للمدير فقط)
    if text == "/stats":
        sender = message.get("from", {})
        username = sender.get("username")
        sender_id = sender.get("id")
        
        is_admin = False
        if ADMIN_CHAT_ID and str(sender_id) == str(ADMIN_CHAT_ID):
            is_admin = True
        elif username and username.lower() == ADMIN_USERNAME.lower():
            is_admin = True
            
        if is_admin:
            stats = STORAGE.get_stats()
            msg = (
                "📊 <b>إحصائيات البوت للمدير:</b>\n\n"
                f"👥 <b>إجمالي المستخدمين الفريدين:</b> {stats['total_users']}\n"
                f"💊 <b>عدد المرضى النشطين:</b> {stats['active_patients']}\n"
                f"👥 <b>عدد المتابعين النشطين:</b> {stats['active_caregivers']}\n"
                f"⏰ <b>إجمالي التذكيرات النشطة:</b> {stats['total_reminders']}\n"
            )
            send_message(chat_id, msg)
            return

    # ─ خطوة 1: اسم الدواء للمستخدم نفسه
    if step == "awaiting_name":
        USER_STATE[chat_id] = {"step": "awaiting_repeat", "data": {"name": text}}
        send_message(chat_id, f"✅ الدواء: <b>{text}</b>\n\nاختار نوع التكرار:", reply_markup=repeat_keyboard())
        return

    # ─ خطوة: إدخال كود الربط
    if step == "awaiting_link_code":
        code = text.strip().upper()
        patient_id = STORAGE.use_invite_code(code)
        USER_STATE.pop(chat_id, None)
        if not patient_id:
            send_message(chat_id, "❌ الكود غلط أو انتهت صلاحيته (10 دقائق).\nاطلب كود جديد.")
            return
        if patient_id == chat_id:
            send_message(chat_id, "❌ مينفعش تربط حسابك بنفسك.")
            return
        STORAGE.link_accounts(patient_id, chat_id)
        send_message(chat_id, "✅ <b>تم الربط بنجاح!</b>\nهتوصلك إشعار لو الشخص ده ما خدش دواؤه في الموعد.")
        send_message(patient_id, "✅ تم ربط حساب متابع بحسابك. هيوصله إشعار لو ما أكدتش أخد الدواء.")
        return

    # ─ خطوة 1: إضافة دواء لمريض (من طرف المتابع) — اسم الدواء
    if step == "pt_awaiting_name":
        target_id = state["data"]["target_id"]
        USER_STATE[chat_id] = {"step": "pt_awaiting_repeat", "data": {"target_id": target_id, "name": text}}
        send_message(chat_id, f"✅ الدواء: <b>{text}</b>\n\nاختار نوع التكرار:", reply_markup=repeat_keyboard())
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

    # ─ قائمة المتابعة
    if text in ("👥 المتابعة",):
        show_caregiver_menu(chat_id)
        return

    # ─ start / help
    if text in ("/start", "/help"):
        send_message(
            chat_id,
            "أهلاً! 🩺 <b>بوت تذكير الدواء</b>\n\nاستخدم الأزرار أسفل الشاشة 👇",
            reply_markup=main_menu_keyboard(),
        )
        return

    send_message(chat_id, "استخدم الأزرار 👇", reply_markup=main_menu_keyboard())


# ─── Caregiver Authorization ──────────────────────────────────────────────────

def _assert_caregiver(caregiver_id: int, patient_id: int) -> None:
    """يتحقق إن الـ caregiver مرتبط فعلاً بالمريض، لو لأ يرفع exception."""
    patients = STORAGE.get_patients(caregiver_id)
    ids = [p["patient_chat_id"] for p in patients]
    if patient_id not in ids:
        raise PermissionError("غير مصرح")


# ─── Callback Handler ──────────────────────────────────────────────────────────

def handle_callback(chat_id: int, callback_id: str, data: str, message_id: int) -> None:
    answer_callback(callback_id)
    try:
        _handle_callback_inner(chat_id, data, message_id)
    except PermissionError:
        send_message(chat_id, "⛔ غير مصرح لك بهذا الإجراء.")
    except Exception as exc:
        print(f"callback error: {exc}")


def _handle_callback_inner(chat_id: int, data: str, message_id: int) -> None:

    # ─ AM/PM period
    if data.startswith("ampm:"):
        state = USER_STATE.get(chat_id, {})
        if state.get("step") != "awaiting_ampm":
            return
        period = data.split(":")[1]
        USER_STATE[chat_id]["data"]["period"] = period
        USER_STATE[chat_id]["step"] = "awaiting_minute"
        edit_message(
            chat_id, message_id,
            "🕐 اختار <b>الدقائق</b>:",
            reply_markup=minutes_keyboard(),
        )
        return

    # ─ Repeat rule
    if data.startswith("repeat:"):
        state = USER_STATE.get(chat_id, {})
        step = state.get("step")
        if step not in ("awaiting_repeat", "pt_awaiting_repeat"):
            return
        _, rule, value = data.split(":")
        repeat_value = int(value) if rule == "interval" else None
        
        # Save rule and value, preserve target_id and name
        USER_STATE[chat_id]["data"]["rule"] = rule
        USER_STATE[chat_id]["data"]["repeat_value"] = repeat_value
        USER_STATE[chat_id]["step"] = "awaiting_hour"

        # Tip message based on rule
        tip = ""
        if rule == "interval":
            if repeat_value == 6:
                tip = "\n\n💡 <b>نصيحة:</b> أفضل مواعيد هي: 6 و 12 (صباحاً ومساءً)."
            elif repeat_value == 8:
                tip = "\n\n💡 <b>نصيحة:</b> أفضل مواعيد هي: 2 و 10 و 6 صباحاً."
            elif repeat_value == 12:
                tip = "\n\n💡 <b>نصيحة:</b> أفضل مواعيد هي: 8 صباحاً و 8 مساءً."

        edit_message(
            chat_id, message_id,
            f"🕐 اختار <b>ساعة الجرعة الأولى</b> (من 1 لـ 12):{tip}",
            reply_markup=hours_keyboard(),
        )
        return

    # ─ Hour selection
    if data.startswith("hour:"):
        state = USER_STATE.get(chat_id, {})
        if state.get("step") != "awaiting_hour":
            return
        h = int(data.split(":")[1])
        USER_STATE[chat_id]["data"]["hour"] = h
        USER_STATE[chat_id]["step"] = "awaiting_ampm"
        edit_message(
            chat_id, message_id,
            "🌅 صباحاً ولا مساءً؟",
            reply_markup=ampm_keyboard(),
        )
        return

    # ─ Minute selection
    if data.startswith("minute:"):
        state = USER_STATE.get(chat_id, {})
        if state.get("step") != "awaiting_minute":
            return
        m = data.split(":")[1]
        med_data = state.get("data", {})
        time_raw = f"{med_data['hour']}:{m}"
        time_24 = apply_ampm(time_raw, med_data["period"])
        USER_STATE[chat_id]["data"]["time"] = time_24
        USER_STATE[chat_id]["step"] = "awaiting_confirm"

        rule = med_data["rule"]
        repeat_value = med_data["repeat_value"]
        rule_text = "يومي" if rule == "daily" else f"كل {repeat_value} ساعة"

        times = get_all_dose_times(time_24, rule, repeat_value)
        lines = []
        for idx, t in enumerate(times):
            lines.append(f"• الجرعة {idx+1}: <b>{display_time(t)}</b>")
        times_formatted = "\n".join(lines)

        edit_message(
            chat_id, message_id,
            f"💊 <b>تأكيد مواعيد الجرعات ({rule_text}):</b>\n\n"
            f"اسم الدواء: <b>{med_data['name']}</b>\n"
            f"المواعيد المحددة:\n{times_formatted}\n\n"
            f"هل تريد تأكيد هذه المواعيد؟",
            reply_markup=confirm_add_keyboard(),
        )
        return

    # ─ Final confirmation of adding medicine
    if data.startswith("confirm_add:"):
        state = USER_STATE.get(chat_id, {})
        if state.get("step") != "awaiting_confirm":
            return
        choice = data.split(":")[1]
        if choice == "yes":
            med_data = state.get("data", {})
            target_id = med_data.get("target_id")
            chat_to_save = target_id if target_id else chat_id
            
            rule = med_data["rule"]
            repeat_value = med_data["repeat_value"]
            rule_text = "يومي" if rule == "daily" else f"كل {repeat_value} ساعة"
            reminder_id = str(uuid.uuid4())
            
            STORAGE.add_reminder(
                reminder_id,
                chat_to_save,
                med_data["name"],
                med_data["time"],
                rule,
                repeat_value,
            )
            USER_STATE.pop(chat_id, None)

            if target_id:
                # Caregiver flow
                edit_message(
                    chat_id, message_id,
                    f"✅ <b>تمت الإضافة لحساب المتابَع!</b>\n\n"
                    f"💊 {med_data['name']}\n🕐 {display_time(med_data['time'])}\n🔁 {rule_text}",
                )
                send_message(
                    target_id,
                    f"💊 تمت إضافة دواء جديد لك من قِبل المتابع:\n"
                    f"<b>{med_data['name']}</b> — {display_time(med_data['time'])} ({rule_text})",
                )
            else:
                # Patient flow
                edit_message(
                    chat_id, message_id,
                    f"✅ <b>تمت الإضافة!</b>\n\n💊 {med_data['name']}\n🕐 {display_time(med_data['time'])}\n🔁 {rule_text}",
                )
        else:
            USER_STATE.pop(chat_id, None)
            edit_message(chat_id, message_id, "❌ تم إلغاء إضافة الدواء.")
        return

    # ─ Delete medicine
    if data.startswith("del:"):
        reminder_id = data[4:]
        if reminder_id == "cancel":
            edit_message(chat_id, message_id, "↩️ تم الإلغاء.")
            return
        deleted = STORAGE.remove_reminder(chat_id, reminder_id)
        edit_message(chat_id, message_id, "🗑 تم الحذف." if deleted else "❌ مش لاقي الدواء ده.")
        return

    # ─ Confirm dose taken
    if data.startswith("confirm:"):
        confirmation_id = data[8:]
        result = STORAGE.confirm_pending(confirmation_id)
        if not result or result.get("confirmed_at") is None:
            edit_message(chat_id, message_id, "⚠️ انتهت صلاحية هذا التأكيد.")
            return
        # جيب اسم الدواء
        reminder = STORAGE.get_reminder(result["reminder_id"])
        med_name = reminder["medication_name"] if reminder else "الدواء"
        edit_message(chat_id, message_id, f"✅ <b>تم تسجيل أخذ {med_name}</b> 💊")
        # أبلّغ المتابعين
        caregivers = STORAGE.get_caregivers(chat_id)
        for cg_id in caregivers:
            send_message(
                cg_id,
                f"✅ <b>تم أخذ الدواء</b>\n💊 {med_name}\n🕐 {display_time(reminder['time'])}",
            )
        return

    # ─── Caregiver menu ────────────────────────────────────────────────────────

    if data == "cg:share":
        code = STORAGE.create_invite_code(chat_id)
        edit_message(
            chat_id, message_id,
            f"🔗 <b>كود الربط الخاص بك:</b>\n\n<code>{code}</code>\n\n"
            f"ابعت الكود ده لشخص تريده يتابعك.\n"
            f"⏳ الكود صالح <b>10 دقائق</b> فقط.",
        )
        return

    if data == "cg:link":
        USER_STATE[chat_id] = {"step": "awaiting_link_code"}
        edit_message(chat_id, message_id, "👁 اكتب <b>كود الربط</b> بتاع الشخص اللي تريد تتابعه:")
        return

    if data == "cg:patients":
        patients = STORAGE.get_patients(chat_id)
        if not patients:
            edit_message(chat_id, message_id, "📊 مش بتتابع أي شخص دلوقتي.")
            return
        # لو في مريض واحد روح على قائمة إدارته مباشرة
        if len(patients) == 1:
            pid = patients[0]["patient_chat_id"]
            meds = STORAGE.list_reminders(pid)
            med_lines = "\n".join(format_reminder(r) for r in meds) or "لا يوجد أدوية بعد."
            edit_message(
                chat_id, message_id,
                f"👤 <b>المتابَع:</b> <code>{pid}</code>\n\n📋 أدويته:\n{med_lines}",
                reply_markup=manage_patient_keyboard(pid),
            )
        else:
            # لو أكتر من مريض، اعرض قائمة للاختيار
            buttons = []
            for p in patients:
                pid = p["patient_chat_id"]
                meds = STORAGE.list_reminders(pid)
                label = f"👤 {pid} — {len(meds)} أدوية"
                buttons.append([{"text": label, "callback_data": f"pt:open:{pid}"}])
            edit_message(chat_id, message_id, "اختار الشخص:", reply_markup={"inline_keyboard": buttons})
        return

    # ─ فتح قائمة إدارة مريض معين
    if data.startswith("pt:open:"):
        pid = int(data.split(":")[2])
        _assert_caregiver(chat_id, pid)
        meds = STORAGE.list_reminders(pid)
        med_lines = "\n".join(format_reminder(r) for r in meds) or "لا يوجد أدوية بعد."
        edit_message(
            chat_id, message_id,
            f"👤 <b>المتابَع:</b> <code>{pid}</code>\n\n📋 أدويته:\n{med_lines}",
            reply_markup=manage_patient_keyboard(pid),
        )
        return

    # ─ عرض أدوية المريض
    if data.startswith("pt:list:"):
        pid = int(data.split(":")[2])
        _assert_caregiver(chat_id, pid)
        meds = STORAGE.list_reminders(pid)
        med_lines = "\n".join(format_reminder(r) for r in meds) or "لا يوجد أدوية بعد."
        edit_message(
            chat_id, message_id,
            f"📋 <b>أدوية المتابَع:</b>\n\n{med_lines}",
            reply_markup=manage_patient_keyboard(pid),
        )
        return

    # ─ إضافة دواء للمريض
    if data.startswith("pt:add:"):
        pid = int(data.split(":")[2])
        _assert_caregiver(chat_id, pid)
        USER_STATE[chat_id] = {"step": "pt_awaiting_name", "data": {"target_id": pid}}
        edit_message(chat_id, message_id, f"💊 اكتب <b>اسم الدواء</b> اللي تريد تضيفه للمتابَع:")
        return

    # ─ حذف دواء من المريض — عرض القائمة
    if data.startswith("pt:del:") and data.count(":") == 2:
        pid = int(data.split(":")[2])
        _assert_caregiver(chat_id, pid)
        meds = STORAGE.list_reminders(pid)
        if not meds:
            edit_message(chat_id, message_id, "مفيش أدوية للحذف.", reply_markup=manage_patient_keyboard(pid))
            return
        edit_message(
            chat_id, message_id,
            "اختار الدواء اللي تريد تحذفه:",
            reply_markup=delete_patient_med_keyboard(meds, pid),
        )
        return

    # ─ تنفيذ حذف دواء من المريض
    if data.startswith("pt:delmed:"):
        parts = data.split(":")
        pid = int(parts[2])
        reminder_id = parts[3]
        _assert_caregiver(chat_id, pid)
        deleted = STORAGE.remove_reminder(pid, reminder_id)
        if deleted:
            send_message(pid, "🗑 تم حذف أحد أدويتك من قِبل المتابع.")
        edit_message(
            chat_id, message_id,
            "🗑 تم الحذف." if deleted else "❌ مش لاقي الدواء.",
            reply_markup=manage_patient_keyboard(pid),
        )
        return

    # ─ تذكير يدوي فوري للمريض
    if data.startswith("pt:remind:"):
        pid = int(data.split(":")[2])
        _assert_caregiver(chat_id, pid)
        meds = STORAGE.list_reminders(pid)
        if not meds:
            edit_message(chat_id, message_id, "مفيش أدوية مسجلة.", reply_markup=manage_patient_keyboard(pid))
            return
        for med in meds:
            confirmation_id = str(uuid.uuid4())
            STORAGE.add_pending(confirmation_id, med["id"], pid)
            send_message(
                pid,
                f"🔔 <b>تذكير من المتابع</b>\n\n💊 {med['medication_name']}\n🕐 {display_time(med['time'])}\n\nاضغط بعد ما تاخد الدواء 👇",
                reply_markup=confirm_dose_keyboard(confirmation_id),
            )
        edit_message(
            chat_id, message_id,
            f"✅ تم إرسال تذكير يدوي لـ {len(meds)} دواء.",
            reply_markup=manage_patient_keyboard(pid),
        )
        return

    # ─ رجوع لقائمة المريض
    if data.startswith("pt:back:"):
        pid = int(data.split(":")[2])
        meds = STORAGE.list_reminders(pid)
        med_lines = "\n".join(format_reminder(r) for r in meds) or "لا يوجد أدوية بعد."
        edit_message(
            chat_id, message_id,
            f"👤 <b>المتابَع:</b> <code>{pid}</code>\n\n📋 أدويته:\n{med_lines}",
            reply_markup=manage_patient_keyboard(pid),
        )
        return

    if data == "cg:unlink":
        patients = STORAGE.get_patients(chat_id)
        if not patients:
            edit_message(chat_id, message_id, "مش بتتابع أي شخص.")
            return
        edit_message(chat_id, message_id, "اختار الشخص اللي تريد إلغاء متابعته:", reply_markup=unlink_keyboard(patients))
        return

    if data.startswith("unlink:"):
        patient_id = int(data.split(":")[1])
        removed = STORAGE.unlink_accounts(patient_id, chat_id)
        edit_message(chat_id, message_id, "✅ تم إلغاء الربط." if removed else "❌ مش لاقي هذا الربط.")
        return

    if data == "cg:back":
        edit_message(chat_id, message_id, "↩️ تم الإلغاء.")
        return


# ─── List / Delete helpers ─────────────────────────────────────────────────────

def show_list(chat_id: int) -> None:
    reminders = STORAGE.list_reminders(chat_id)
    if not reminders:
        send_message(chat_id, "📋 مفيش أدوية مضافة.\n\nاضغط <b>💊 إضافة دواء</b> للبدء.")
        return
    lines = [format_reminder(r) for r in reminders]
    send_message(chat_id, "📋 <b>أدويتك:</b>\n\n" + "\n".join(lines))


def show_delete_menu(chat_id: int) -> None:
    reminders = STORAGE.list_reminders(chat_id)
    if not reminders:
        send_message(chat_id, "📋 مفيش أدوية عندك.")
        return
    send_message(chat_id, "اختار الدواء اللي تريد تحذفه:", reply_markup=delete_keyboard(reminders))


# ─── Main update handler ────────────────────────────────────────────────────────

def handle_update(update: Dict[str, Any]) -> None:
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]
        handle_callback(chat_id, cq["id"], cq.get("data", ""), message_id)
        return

    message = update.get("message", {})
    if not message:
        return
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    if not chat_id or not text:
        return
    handle_text(chat_id, text, message)


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
