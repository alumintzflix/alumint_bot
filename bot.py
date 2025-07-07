
import logging
import os
from aiogram import Bot, Dispatcher, types, executor
from dotenv import load_dotenv

# Load .env
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")

# Bot Initialization
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

# In-memory database (for demo)
admin_id = 1784602112  # <-- এখানে আপনার Telegram ID বসান
employees = set()
tasks = {}
click_logs = {}

# /start command
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply("👋 স্বাগতম! আপনি যদি এমপ্লয়ি হন, /get_task লিখুন।")

# /add_employee @username (admin only)
@dp.message_handler(commands=['add_employee'])
async def add_employee(message: types.Message):
    if message.from_user.id != admin_id:
        return await message.reply("❌ আপনি অ্যাডমিন না!")
    try:
        username = message.text.split()[1].replace('@', '')
        employees.add(username)
        await message.reply(f"✅ @{username} কে এমপ্লয়ি হিসেবে যুক্ত করা হলো!")
    except:
        await message.reply("⚠️ সঠিকভাবে লিখুন: /add_employee @username")

# /get_task (employee only)
@dp.message_handler(commands=['get_task'])
async def get_task(message: types.Message):
    username = message.from_user.username
    if username not in employees:
        return await message.reply("❌ আপনি এমপ্লয়ি তালিকায় নেই!")
    link = f"https://example.com/movie123?ref={username}"
    tasks[username] = link
    await message.reply(f"🎯 আজকের টাস্ক লিংক:\n{link}")

# /click <username> (simulate click)
@dp.message_handler(commands=['click'])
async def simulate_click(message: types.Message):
    try:
        parts = message.text.split()
        ref_by = parts[1]
        viewer = message.from_user.username or f"id_{message.from_user.id}"
        click_logs.setdefault(ref_by, []).append(viewer)
        await message.reply(f"✅ @{ref_by} এর লিংকে ক্লিক রেকর্ড হলো!")
    except:
        await message.reply("⚠️ লিখুন: /click <username>")

# /report (admin only)
@dp.message_handler(commands=['report'])
async def get_report(message: types.Message):
    if message.from_user.id != admin_id:
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    if not tasks:
        return await message.reply("📊 কোনো টাস্ক নেই।")
    report = "📋 Task Report:\n\n"
    for emp, link in tasks.items():
        views = click_logs.get(emp, [])
        report += f"👨‍💼 @{emp}\n🔗 Link: {link}\n👁️ Views: {len(views)}\n👤 Users: {', '.join(views) if views else 'None'}\n\n"
    await message.reply(report)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
