import os
import sqlite3
import tempfile
import unittest

from storage import ReminderStorage
from scheduler import parse_time_string, is_due


class ReminderStorageTests(unittest.TestCase):
    def test_add_list_remove_reminder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "med_reminder.db")
            storage = ReminderStorage(db_path=db_path)

            reminder = storage.add_reminder(
                reminder_id="test-id",
                chat_id=123,
                medication_name="Insulin",
                time_str="09:00",
                repeat_rule="daily",
            )

            self.assertEqual(reminder["medication_name"], "Insulin")
            self.assertEqual(reminder["time"], "09:00")

            reminders = storage.list_reminders(123)
            self.assertEqual(len(reminders), 1)
            self.assertEqual(reminders[0]["id"], "test-id")

            deleted = storage.remove_reminder(123, "test-id")
            self.assertTrue(deleted)
            self.assertEqual(storage.list_reminders(123), [])

    def test_database_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "med_reminder.db")
            ReminderStorage(db_path=db_path)
            self.assertTrue(os.path.exists(db_path))


class SchedulerTests(unittest.TestCase):
    def test_parse_time_string(self):
        self.assertEqual(parse_time_string("08:30"), __import__("datetime").time(8, 30))

    def test_is_due_daily(self):
        now = __import__("datetime").datetime(2026, 6, 30, 8, 30)
        reminder = {"time": "08:30", "repeat_rule": "daily", "last_sent_at": None}
        self.assertTrue(is_due(reminder, now))

    def test_is_due_interval(self):
        now = __import__("datetime").datetime(2026, 6, 30, 10, 0)
        reminder = {
            "time": "08:00",
            "repeat_rule": "interval",
            "repeat_value": 2,
            "last_sent_at": "2026-06-30T08:00:00",
        }
        self.assertTrue(is_due(reminder, now))


if __name__ == "__main__":
    unittest.main()
