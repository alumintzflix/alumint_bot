import logging
import os
from aiogram import Bot, Dispatcher, types, executor
from dotenv import load_dotenv

# Load .env
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")

# Initialize bot
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

# List of employees (for demo)
employees = []

# Handle /start
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply("👋 স্বাগতম! আপনি যদি এমপ্লয়ি হন, /get_task টাইপ করুন।")

# Admin adds employee
@dp.message_handler(commands=['add_employee'])
async def add_employee(message: types.Message):
    if message.from_user.id != 123456789:  # <-- আপনার Telegram ID বসান
        return await message.reply("❌ আপনি অ্যাডমিন না!")

    try:
        username = message.text.split()[1]
        if username not in employees:
            employees.append(username)
            await message.reply(f"✅ এমপ্লয়ি @{username} যুক্ত হয়েছে!")
        else:
            await message.reply("⚠️ এই ইউজার ইতিমধ্যে এমপ্লয়ি।")
    except:
        await message.reply("⚠️ কমান্ড ভুল। ব্যবহার করুন: /add_employee @username")

# Employee gets a task
@dp.message_handler(commands=['get_task'])
async def get_task(message: types.Message):
    if message.from_user.username not in employees:
        return await message.reply("❌ আপনি এমপ্লয়ি তালিকায় নেই!")
    
    # Demo task link
    task_link = "https://example.com/movie123?ref=" + message.from_user.username
    await message.reply(f"🎯 আজকের টাস্ক:\n\nশেয়ার করুন এই লিংকটি:\n{task_link}")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
