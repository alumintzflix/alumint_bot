import logging
import os
import sqlite3
import asyncio # New: For running multiple async tasks
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode # For better message formatting
from aiogram.filters import CommandStart, Command # For aiogram 3.x command handling
from aiogram.utils.markdown import hbold # For bold text in messages
from dotenv import load_dotenv
from aiohttp import web # New: For the web server

# Load .env variables from a .env file if it exists locally
load_dotenv()

# --- Configuration from Environment Variables ---
# **এখানে তোমার BOT_TOKEN বা ADMIN_CHAT_ID সরাসরি লিখবে না**
# এগুলো Render ড্যাশবোর্ডে Environment Variables হিসেবে সেট করতে হবে।
API_TOKEN = os.getenv("BOT_TOKEN") # Your Telegram Bot Token
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID") # Your Telegram Admin User ID (for receiving notifications)

# --- Basic Setup ---
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- SQLite Database Setup ---
conn = sqlite3.connect("bot.db")
cur = conn.cursor()

# Create tables if they don't exist
cur.execute("""
CREATE TABLE IF NOT EXISTS employees (
    username TEXT PRIMARY KEY,
    telegram_id INTEGER UNIQUE
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
    viewer_info TEXT, -- Storing user_agent or other relevant info
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# --- Telegram Bot Command Handlers ---

@dp.message(Command("add_employee"))
async def add_employee(message: types.Message):
    # Ensure only the admin can use this command
    if str(message.from_user.id) != ADMIN_CHAT_ID: # Compare as string
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        parts = message.text.split()
        if len(parts) < 2:
            return await message.reply("⚠️ সঠিকভাবে লিখুন: /add_employee @username <Telegram_ID>")
        
        username = parts[1].replace('@', '')
        telegram_id = int(parts[2]) if len(parts) > 2 else None # Optional Telegram ID

        if telegram_id:
            cur.execute("INSERT OR IGNORE INTO employees (username, telegram_id) VALUES (?, ?)", (username, telegram_id))
        else:
            cur.execute("INSERT OR IGNORE INTO employees (username) VALUES (?)", (username,))
        conn.commit()
        await message.reply(f"✅ @{username} (ID: {telegram_id if telegram_id else 'N/A'}) কে এমপ্লয়ি হিসেবে যুক্ত করা হলো!")
    except (IndexError, ValueError):
        await message.reply("⚠️ সঠিকভাবে লিখুন: /add_employee @username <Telegram_ID (ঐচ্ছিক)>")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")

@dp.message(Command("get_task"))
async def get_task(message: types.Message):
    username = message.from_user.username
    if not username:
        return await message.reply("❌ আপনার টেলিগ্রাম ইউজারনেম সেট করা নেই। দয়া করে সেটিংস থেকে সেট করুন।")

    cur.execute("SELECT username FROM employees WHERE username = ?", (username,))
    if not cur.fetchone():
        return await message.reply("❌ আপনি এমপ্লয়ি তালিকায় নেই!")
    
    # --- IMPORTANT: Make this link dynamic based on your movie site and task ---
    # Example: you might fetch this from another database table for assigned tasks
    movie_site_base_url = "https://yourmoviesite.com/movie/" # Replace with your actual movie site base URL
    task_identifier = "some_movie_id_or_slug" # Replace with actual task logic
    
    # The 'ref' parameter should uniquely identify the employee for tracking
    link = f"{movie_site_base_url}{task_identifier}?ref={username}" 
    
    cur.execute("INSERT OR REPLACE INTO tasks (username, task_link) VALUES (?, ?)", (username, link))
    conn.commit()
    await message.reply(f"🎯 আজকের টাস্ক লিংক:\n{link}")

@dp.message(Command("report"))
async def get_report(message: types.Message):
    # Ensure only the admin can use this command
    if str(message.from_user.id) != ADMIN_CHAT_ID: # Compare as string
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    
    report = "📋 Task Report:\n\n"
    cur.execute("SELECT username, task_link FROM tasks")
    tasks = cur.fetchall()

    if not tasks:
        report += "কোনো টাস্ক অ্যাসাইন করা হয়নি।"
    else:
        for emp_username, link in tasks:
            cur.execute("SELECT viewer_info FROM clicks WHERE ref = ?", (emp_username,))
            viewers = [row[0] for row in cur.fetchall()]
            report += f"👨‍💼 @{emp_username}\n🔗 Link: {link}\n👁️ Views: {len(viewers)}\n👤 Users: {', '.join(viewers) if viewers else 'None'}\n\n"
    
    await message.reply(report)

@dp.message(CommandStart())
async def send_welcome(message: types.Message):
    await message.reply(f"👋 স্বাগতম, {hbold(message.from_user.full_name)}! আপনি যদি এমপ্লয়ি হন, /get_task লিখুন।")

# --- Web Server for handling external HTTP requests (from footer.php) ---

async def track_click_handler(request):
    """Handles POST requests from the website for click tracking."""
    try:
        data = await request.json()
        ref = data.get('ref')
        viewer_info = data.get('user_agent', 'Unknown User') # Using user_agent or other info for viewer
        
        if ref:
            # Insert click data into the database
            cur.execute("INSERT INTO clicks (ref, viewer_info) VALUES (?, ?)", (ref, viewer_info))
            conn.commit()
            logging.
