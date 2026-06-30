# Medication Reminder Bot

بوت تليجرام لتذكير بمواعيد الجرعات مع بنية أفضل وتخزين SQLite وجدولة متقدمة.

## الميزات
- تخزين مواعيد الجرعات في قاعدة بيانات `SQLite`
- أوامر لإضافة وعرض وحذف التذكيرات
- دعم تكرار يومي و"كل X ساعات"
- تشغيل دائم مع فحص تذكيرات مستمر

## التشغيل
1. ضع التوكن في متغير بيئة `TELEGRAM_TOKEN`

   - PowerShell:
     ```powershell
     $env:TELEGRAM_TOKEN = "123456789:ABCdef..."
     ```

   - أو عبر `setx` لجعل المتغير دائم:
     ```powershell
     setx TELEGRAM_TOKEN "123456789:ABCdef..."
     ```

2. شغّل بوت Telegram:
   ```powershell
   cd 'd:\Projects\Med Reminder'
   python main.py
   ```

3. استخدم الأوامر داخل Telegram:
   - `/start`
   - `/addmed Paracetamol 08:30`
   - `/addmed Paracetamol 08:30 every8h`
   - `/list`
   - `/remove <id>`

## ملاحظة
قاعدة البيانات `med_reminder.db` تُنشأ تلقائيًا في نفس المجلد.
