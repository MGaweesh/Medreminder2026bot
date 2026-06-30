import threading

from bot import run_bot
from scheduler import ReminderScheduler
from storage import ReminderStorage


def main() -> None:
    storage = ReminderStorage()
    scheduler = ReminderScheduler(storage, interval_seconds=30)

    scheduler_thread = threading.Thread(target=scheduler.run_loop, daemon=True)
    scheduler_thread.start()

    run_bot()


if __name__ == "__main__":
    main()
