import logging
import os
import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.utils.markdown import hbold
from aiogram.client.default import DefaultBotProperties # এই লাইনটি নতুন!
from dotenv import load_dotenv
from aiohttp import web

# Load .env variables (for local development)
load_dotenv()

# --- Configuration from Environment Variables ---
API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# --- Bot Initialization ---
# DefaultBotProperties ব্যবহার করে parse_mode সেট করা হয়েছে (aiogram 3.7.0+ এর জন্য)
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) # এখানে পরিবর্তন করা হয়েছে!
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
    viewer_info TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# --- Telegram Bot Command Handlers ---

@dp.message(Command("add_employee"))
async def add_employee(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        parts = message.text.split()
        if len(parts) < 2:
            return await message.reply("⚠️ সঠিকভাবে লিখুন: /add_employee @username <Telegram_ID>")
        
        username = parts[1].replace('@', '')
        telegram_id = int(parts[2]) if len(parts) > 2 else None

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
    
    movie_site_base_url = "https://yourmoviesite.com/movie/"
    task_identifier = "some_movie_id_or_slug"
    
    link = f"{movie_site_base_url}{task_identifier}?ref={username}" 
    
    cur.execute("INSERT OR REPLACE INTO tasks (username, task_link) VALUES (?, ?)", (username, link))
    conn.commit()
    await message.reply(f"🎯 আজকের টাস্ক লিংক:\n{link}")

@dp.message(Command("report"))
async def get_report(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
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
    try:
        data = await request.json()
        ref = data.get('ref')
        viewer_info = data.get('user_agent', 'Unknown User')
        
        if ref:
            cur.execute("INSERT INTO clicks (ref, viewer_info) VALUES (?, ?)", (ref, viewer_info))
            conn.commit()
            logging.info(f"Tracked click for ref: {ref}, viewer: {viewer_info}")

            if ADMIN_CHAT_ID:
                try:
                    await bot.send_message(
                        chat_id=int(ADMIN_CHAT_ID),
                        text=f"✅ নতুন ভিউ রেকর্ড করা হয়েছে!\nReferral: `{ref}`\nViewer Info: `{viewer_info}`",
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                except Exception as e:
                    logging.error(f"Failed to send admin notification: {e}")
            
            return web.json_response({"status": "success", "message": "Click tracked successfully"})
        else:
            return web.json_response({"status": "error", "message": "Missing 'ref' parameter"}, status=400)
    except Exception as e:
        logging.error(f"Error in track_click_handler: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# --- Main function to run both polling and web server ---
async def main() -> None:
    polling_task = asyncio.create_task(dp.start_polling(bot))

    app = web.Application()
    app.router.add_post('/track-click', track_click_handler)

    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Web server started on port {port}")

    await asyncio.gather(polling_task, site._server.wait_closed())

if __name__ == '__main__':
    asyncio.run(main())
