import datetime
import os
import sqlite3
from typing import Any, Dict, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "med_reminder.db")


class ReminderStorage:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
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
            conn.commit()
        finally:
            conn.close()

    def add_reminder(
        self,
        reminder_id: str,
        chat_id: int,
        medication_name: str,
        time_str: str,
        repeat_rule: str = "daily",
        repeat_value: Optional[int] = None,
    ) -> Dict[str, Any]:
        created_at = datetime.datetime.now().isoformat(timespec="seconds")
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
        sent_at = datetime.datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE reminders SET last_sent_at = ? WHERE id = ?", (sent_at, reminder_id)
            )
            conn.commit()
        finally:
            conn.close()

    def deactivate_reminder(self, reminder_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("UPDATE reminders SET active = 0 WHERE id = ?", (reminder_id,))
            conn.commit()
        finally:
            conn.close()
