import datetime
import os
import random
import sqlite3
import string
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

_TZ_NAME = os.environ.get("TZ", "Africa/Cairo")


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=ZoneInfo(_TZ_NAME)).replace(tzinfo=None)

_DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(__file__))
DB_PATH = os.path.join(_DATA_DIR, "med_reminder.db")


class ReminderStorage:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    medication_name TEXT NOT NULL,
                    time TEXT NOT NULL,
                    repeat_rule TEXT NOT NULL,
                    repeat_value INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_sent_at TEXT
                )
                """
            )
            # جدول الـ pending confirmations — لما البوت يبعت تذكير وينتظر تأكيد
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_confirmations (
                    id TEXT PRIMARY KEY,
                    reminder_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    sent_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    caregiver_notified INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            # جدول ربط المستخدمين — patient <-> caregiver
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS linked_accounts (
                    patient_chat_id INTEGER NOT NULL,
                    caregiver_chat_id INTEGER NOT NULL,
                    linked_at TEXT NOT NULL,
                    PRIMARY KEY (patient_chat_id, caregiver_chat_id)
                )
                """
            )
            # جدول أكواد الدعوة المؤقتة
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS invite_codes (
                    code TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    # ─── Reminders ────────────────────────────────────────────────────────────

    def add_reminder(
        self,
        reminder_id: str,
        chat_id: int,
        medication_name: str,
        time_str: str,
        repeat_rule: str = "daily",
        repeat_value: Optional[int] = None,
    ) -> Dict[str, Any]:
        created_at = _now().isoformat(timespec="seconds")
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO reminders (id, chat_id, medication_name, time, repeat_rule, repeat_value, active, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (reminder_id, chat_id, medication_name, time_str, repeat_rule, repeat_value, created_at),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_reminder(reminder_id)

    def get_reminder(self, reminder_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        finally:
            conn.close()
        return dict(row) if row else None

    def remove_reminder(self, chat_id: int, reminder_id: str) -> bool:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM reminders WHERE id = ? AND chat_id = ?", (reminder_id, chat_id)
            )
            conn.commit()
        finally:
            conn.close()
        return cursor.rowcount > 0

    def list_reminders(self, chat_id: int) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE chat_id = ? AND active = 1 ORDER BY time", (chat_id,)
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def list_all_active(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM reminders WHERE active = 1").fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def mark_sent(self, reminder_id: str) -> None:
        sent_at = _now().isoformat(timespec="seconds")
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE reminders SET last_sent_at = ? WHERE id = ?", (sent_at, reminder_id)
            )
            conn.commit()
        finally:
            conn.close()

    # ─── Pending Confirmations ────────────────────────────────────────────────

    def add_pending(self, confirmation_id: str, reminder_id: str, chat_id: int) -> None:
        sent_at = _now().isoformat(timespec="seconds")
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO pending_confirmations (id, reminder_id, chat_id, sent_at)"
                " VALUES (?, ?, ?, ?)",
                (confirmation_id, reminder_id, chat_id, sent_at),
            )
            conn.commit()
        finally:
            conn.close()

    def confirm_pending(self, confirmation_id: str) -> Optional[Dict[str, Any]]:
        """يعلّم الـ confirmation كمؤكد ويرجع بياناته."""
        confirmed_at = _now().isoformat(timespec="seconds")
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE pending_confirmations SET confirmed_at = ? WHERE id = ? AND confirmed_at IS NULL",
                (confirmed_at, confirmation_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM pending_confirmations WHERE id = ?", (confirmation_id,)
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row else None

    def get_unconfirmed_pending(self, older_than_minutes: int = 30) -> List[Dict[str, Any]]:
        """يرجع التذكيرات اللي اتبعتت ولسه مفيش تأكيد عليها وعدى عليها X دقيقة."""
        cutoff = (
            _now() - datetime.timedelta(minutes=older_than_minutes)
        ).isoformat(timespec="seconds")
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM pending_confirmations
                WHERE confirmed_at IS NULL
                  AND caregiver_notified = 0
                  AND sent_at <= ?
                """,
                (cutoff,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def mark_caregiver_notified(self, confirmation_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE pending_confirmations SET caregiver_notified = 1 WHERE id = ?",
                (confirmation_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # ─── Linked Accounts ──────────────────────────────────────────────────────

    def link_accounts(self, patient_chat_id: int, caregiver_chat_id: int) -> None:
        linked_at = _now().isoformat(timespec="seconds")
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO linked_accounts (patient_chat_id, caregiver_chat_id, linked_at)"
                " VALUES (?, ?, ?)",
                (patient_chat_id, caregiver_chat_id, linked_at),
            )
            conn.commit()
        finally:
            conn.close()

    def unlink_accounts(self, patient_chat_id: int, caregiver_chat_id: int) -> bool:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM linked_accounts WHERE patient_chat_id = ? AND caregiver_chat_id = ?",
                (patient_chat_id, caregiver_chat_id),
            )
            conn.commit()
        finally:
            conn.close()
        return cursor.rowcount > 0

    def get_caregivers(self, patient_chat_id: int) -> List[int]:
        """يرجع قائمة الـ chat_ids للمسؤولين عن المريض."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT caregiver_chat_id FROM linked_accounts WHERE patient_chat_id = ?",
                (patient_chat_id,),
            ).fetchall()
        finally:
            conn.close()
        return [row["caregiver_chat_id"] for row in rows]

    def get_patients(self, caregiver_chat_id: int) -> List[Dict[str, Any]]:
        """يرجع قائمة المرضى اللي بيتابعهم الـ caregiver."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM linked_accounts WHERE caregiver_chat_id = ?",
                (caregiver_chat_id,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    # ─── Invite Codes ─────────────────────────────────────────────────────────

    def create_invite_code(self, chat_id: int) -> str:
        """ينشئ كود دعوة مؤقت مكون من 6 أحرف."""
        # امسح الأكواد القديمة لنفس المستخدم أولاً
        conn = self._connect()
        try:
            conn.execute("DELETE FROM invite_codes WHERE chat_id = ? AND used = 0", (chat_id,))
            conn.commit()
        finally:
            conn.close()

        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        created_at = _now().isoformat(timespec="seconds")
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO invite_codes (code, chat_id, created_at) VALUES (?, ?, ?)",
                (code, chat_id, created_at),
            )
            conn.commit()
        finally:
            conn.close()
        return code

    def use_invite_code(self, code: str) -> Optional[int]:
        """يستخدم الكود ويرجع الـ chat_id بتاع المريض، أو None لو الكود غلط/منتهي."""
        # الكود صالح لمدة 10 دقائق
        cutoff = (
            _now() - datetime.timedelta(minutes=10)
        ).isoformat(timespec="seconds")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM invite_codes WHERE code = ? AND used = 0 AND created_at >= ?",
                (code.upper().strip(), cutoff),
            ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE invite_codes SET used = 1 WHERE code = ?", (code,))
            conn.commit()
        finally:
            conn.close()
        return row["chat_id"]
