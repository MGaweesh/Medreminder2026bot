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

    def test_get_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "med_reminder.db")
            storage = ReminderStorage(db_path=db_path)
            
            # Initial stats should be all zeros
            stats = storage.get_stats()
            self.assertEqual(stats["active_patients"], 0)
            self.assertEqual(stats["active_caregivers"], 0)
            self.assertEqual(stats["total_reminders"], 0)
            self.assertEqual(stats["total_users"], 0)
            
            # Add reminder
            storage.add_reminder("r1", 111, "MedA", "08:00")
            stats = storage.get_stats()
            self.assertEqual(stats["active_patients"], 1)
            self.assertEqual(stats["total_reminders"], 1)
            self.assertEqual(stats["total_users"], 1)
            
            # Link account
            storage.link_accounts(111, 222)
            stats = storage.get_stats()
            self.assertEqual(stats["active_caregivers"], 1)
            self.assertEqual(stats["total_users"], 2)


class SchedulerTests(unittest.TestCase):
    def test_parse_time_string(self):
        self.assertEqual(parse_time_string("08:30"), __import__("datetime").time(8, 30))

    def test_is_due_daily(self):
        now = __import__("datetime").datetime(2026, 6, 30, 8, 30)
        reminder = {"time": "08:30", "repeat_rule": "daily", "last_sent_at": None}
        self.assertTrue(is_due(reminder, now))

    def test_is_due_daily_robust(self):
        # 1. Past scheduled time but not sent yet today -> should be due
        now = __import__("datetime").datetime(2026, 6, 30, 8, 35)
        reminder = {"time": "08:30", "repeat_rule": "daily", "last_sent_at": "2026-06-29T08:30:00"}
        self.assertTrue(is_due(reminder, now))

        # 2. Past scheduled time but already sent today -> should NOT be due
        reminder_sent = {"time": "08:30", "repeat_rule": "daily", "last_sent_at": "2026-06-30T08:35:00"}
        self.assertFalse(is_due(reminder_sent, now))

        # 3. Before scheduled time -> should NOT be due
        now_before = __import__("datetime").datetime(2026, 6, 30, 8, 25)
        self.assertFalse(is_due(reminder, now_before))

        # 4. Created after scheduled time today -> should NOT be due today
        reminder_created_late = {
            "time": "08:30",
            "repeat_rule": "daily",
            "last_sent_at": None,
            "created_at": "2026-06-30T08:31:00"
        }
        self.assertFalse(is_due(reminder_created_late, now))

    def test_is_due_interval(self):
        now = __import__("datetime").datetime(2026, 6, 30, 10, 0)
        reminder = {
            "time": "08:00",
            "repeat_rule": "interval",
            "repeat_value": 2,
            "last_sent_at": "2026-06-30T08:00:00",
        }
        self.assertTrue(is_due(reminder, now))

    def test_is_due_interval_robust(self):
        # 1. Created at 10:00 for 08:00 start every 8h. Grid is 08:00, 16:00, 00:00.
        # At 10:00, it should not trigger (since next is 16:00)
        reminder = {
            "time": "08:00",
            "repeat_rule": "interval",
            "repeat_value": 8,
            "last_sent_at": None,
            "created_at": "2026-06-30T10:00:00"
        }
        now_10_05 = __import__("datetime").datetime(2026, 6, 30, 10, 5)
        self.assertFalse(is_due(reminder, now_10_05))

        # At 16:05 (past 16:00 grid), it should trigger
        now_16_05 = __import__("datetime").datetime(2026, 6, 30, 16, 5)
        self.assertTrue(is_due(reminder, now_16_05))

    def test_get_all_dose_times(self):
        from bot import get_all_dose_times
        times_12 = get_all_dose_times("09:00", "interval", 12)
        self.assertEqual(times_12, ["09:00", "21:00"])

        times_8 = get_all_dose_times("02:00", "interval", 8)
        self.assertEqual(times_8, ["02:00", "10:00", "18:00"])

        times_6 = get_all_dose_times("06:00", "interval", 6)
        self.assertEqual(times_6, ["00:00", "06:00", "12:00", "18:00"])

        times_daily = get_all_dose_times("08:30", "daily", None)
        self.assertEqual(times_daily, ["08:30"])


if __name__ == "__main__":
    unittest.main()
