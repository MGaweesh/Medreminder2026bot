import os
import sys
import threading

from bot import delete_webhook, run_bot
from scheduler import ReminderScheduler
from storage import ReminderStorage

LOCK_FILE = "/tmp/medreminder.lock"


def acquire_lock() -> None:
    """منع تشغيل أكثر من instance واحد في نفس الوقت."""
    import fcntl
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("يوجد instance آخر من البوت يعمل بالفعل. جارٍ الإنهاء...")
        sys.exit(1)
    # نحتفظ بالـ fd مفتوحاً طوال عمر البروسيس
    return lock_fd  # type: ignore[return-value]


def main() -> None:
    # على Windows لا يوجد fcntl، لذا نتخطى القفل
    if sys.platform != "win32":
        acquire_lock()

    delete_webhook()
    storage = ReminderStorage()
    scheduler = ReminderScheduler(storage, interval_seconds=30)

    scheduler_thread = threading.Thread(target=scheduler.run_loop, daemon=True)
    scheduler_thread.start()

    run_bot()


if __name__ == "__main__":
    main()
