
import logging
import os
import sqlite3
from aiogram import Bot, Dispatcher, types, executor
from dotenv import load_dotenv

# Load .env
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")

# Bot Initialization
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

# Admin ID
admin_id = 1784602112  # <-- এখানে আপনার Telegram ID বসান

# SQLite setup
conn = sqlite3.connect("bot.db")
cur = conn.cursor()

# Create necessary tables
cur.execute("""
CREATE TABLE IF NOT EXISTS employees (
    username TEXT PRIMARY KEY
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    username TEXT PRIMARY KEY,
    task_link TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS clicks (
    ref TEXT,
    viewer TEXT
)
""")
conn.commit()

# Add employee
@dp.message_handler(commands=['add_employee'])
async def add_employee(message: types.Message):
    if message.from_user.id != admin_id:
        return await message.reply("❌ আপনি অ্যাডমিন না!")
    try:
        username = message.text.split()[1].replace('@', '')
        cur.execute("INSERT OR IGNORE INTO employees (username) VALUES (?)", (username,))
        conn.commit()
        await message.reply(f"✅ @{username} কে এমপ্লয়ি হিসেবে যুক্ত করা হলো!")
    except:
        await message.reply("⚠️ সঠিকভাবে লিখুন: /add_employee @username")

# Get task
@dp.message_handler(commands=['get_task'])
async def get_task(message: types.Message):
    username = message.from_user.username
    cur.execute("SELECT username FROM employees WHERE username = ?", (username,))
    if not cur.fetchone():
        return await message.reply("❌ আপনি এমপ্লয়ি তালিকায় নেই!")
    link = f"https://example.com/movie123?ref={username}"
    cur.execute("INSERT OR REPLACE INTO tasks (username, task_link) VALUES (?, ?)", (username, link))
    conn.commit()
    await message.reply(f"🎯 আজকের টাস্ক লিংক:\n{link}")

# Simulate click
@dp.message_handler(commands=['click'])
async def simulate_click(message: types.Message):
    try:
        parts = message.text.split()
        ref_by = parts[1]
        viewer = message.from_user.username or f"id_{message.from_user.id}"
        cur.execute("INSERT INTO clicks (ref, viewer) VALUES (?, ?)", (ref_by, viewer))
        conn.commit()
        await message.reply(f"✅ @{ref_by} এর লিংকে ক্লিক রেকর্ড হলো!")
    except:
        await message.reply("⚠️ লিখুন: /click <username>")

# Report
@dp.message_handler(commands=['report'])
async def get_report(message: types.Message):
    if message.from_user.id != admin_id:
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    report = "📋 Task Report:\n\n"
    cur.execute("SELECT * FROM tasks")
    for emp, link in cur.fetchall():
        cur.execute("SELECT viewer FROM clicks WHERE ref = ?", (emp,))
        viewers = [row[0] for row in cur.fetchall()]
        report += f"👨‍💼 @{emp}\n🔗 Link: {link}\n👁️ Views: {len(viewers)}\n👤 Users: {', '.join(viewers) if viewers else 'None'}\n\n"
    await message.reply(report)

# Start command
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply("👋 স্বাগতম! আপনি যদি এমপ্লয়ি হন, /get_task লিখুন।")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
