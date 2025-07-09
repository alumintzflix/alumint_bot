import logging
import os
import sqlite3
import asyncio
import datetime
from urllib.parse import urlparse
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.markdown import hbold, hcode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from aiohttp import web

# Load .env variables
load_dotenv()

# --- Configuration from Environment Variables ---
API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEB_SERVER_URL = os.getenv("WEB_SERVER_URL") # Example: https://your-render-app.onrender.com

# --- Bot Initialization ---
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- FSM States for Profile Setup ---
class ProfileSetup(StatesGroup):
    name = State()
    phone = State()
    email = State()
    bkash = State()
    binance_id = State()
    youtube = State()
    facebook = State()
    tiktok = State()
    website = State()
    about_yourself = State()

# --- FSM States for Withdrawal ---
class Withdrawal(StatesGroup):
    amount = State()
    payment_method = State()
    comment = State()

# --- SQLite Database Setup ---
conn = sqlite3.connect("bot.db")
cur = conn.cursor()

# Create/Update tables
# employees table: user details and profile info, now with banned and is_editor flags
cur.execute("""
CREATE TABLE IF NOT EXISTS employees (
    username TEXT PRIMARY KEY,
    telegram_id INTEGER UNIQUE,
    is_admin BOOLEAN DEFAULT 0,
    is_editor BOOLEAN DEFAULT 0,
    profile_set BOOLEAN DEFAULT 0,
    banned BOOLEAN DEFAULT 0,
    full_name TEXT,
    phone_number TEXT,
    email TEXT,
    bkash_number TEXT,
    binance_id TEXT,
    youtube_link TEXT,
    facebook_link TEXT,
    tiktok_link TEXT,
    website_link TEXT,
    about_yourself TEXT,
    total_visits INTEGER DEFAULT 0,
    total_clicks INTEGER DEFAULT 0,
    usdt_balance REAL DEFAULT 0.0
)
""")

# domains table: to store allowed movie site domains (from previous)
cur.execute("""
CREATE TABLE IF NOT EXISTS domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    base_url TEXT
)
""")

# global_tasks table: for a single task assigned to all employees (from previous)
cur.execute("""
CREATE TABLE IF NOT EXISTS global_tasks (
    id INTEGER PRIMARY KEY DEFAULT 1,
    task_identifier TEXT,
    domain_id INTEGER,
    last_set_date TEXT,
    FOREIGN KEY (domain_id) REFERENCES domains(id)
)
""")

# individual_tasks table: for tasks assigned to specific employees (from previous)
cur.execute("""
CREATE TABLE IF NOT EXISTS individual_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_username TEXT,
    task_identifier TEXT,
    domain_id INTEGER,
    assigned_by TEXT,
    assigned_date TEXT DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending',
    FOREIGN KEY (employee_username) REFERENCES employees(username),
    FOREIGN KEY (domain_id) REFERENCES domains(id)
)
""")

# clicks table: to track user clicks and duration, now with more details
cur.execute("""
CREATE TABLE IF NOT EXISTS clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_by_employee TEXT, -- The employee's username
    viewer_telegram_id INTEGER, -- The Telegram ID of the user who clicked
    viewer_username TEXT, -- The Telegram username of the user who clicked
    viewer_full_name TEXT, -- The Telegram full name of the user who clicked
    user_agent TEXT, -- Browser user agent
    page_url TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_visit BOOLEAN DEFAULT 0, -- True if stayed >= 12 seconds
    is_click BOOLEAN DEFAULT 0, -- True if detected, regardless of duration
    is_telegram_browser BOOLEAN DEFAULT 0, -- True if opened in Telegram's internal browser
    unique_daily_key TEXT UNIQUE -- For 20 visits per day limit (username + date + ref_by_employee + page_url)
)
""")

# New tables for public lists
cur.execute("""
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    description TEXT,
    link TEXT UNIQUE
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS earning_bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    description TEXT,
    link TEXT UNIQUE
)
""")

# Global settings for visit to USDT rate
cur.execute("""
CREATE TABLE IF NOT EXISTS global_settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")
# Initialize default USDT rate if not exists
cur.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES (?, ?)", ('usdt_rate_per_1000_visits', '1.00'))

# New table for withdrawal requests
cur.execute("""
CREATE TABLE IF NOT EXISTS withdraw_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_username TEXT,
    usdt_amount REAL,
    payment_method TEXT, -- 'Bkash' or 'Binance'
    payment_detail TEXT, -- The Bkash number or Binance ID from profile
    comment TEXT, -- User's 60 char comment
    request_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
    FOREIGN KEY (employee_username) REFERENCES employees(username)
)
""")

conn.commit()

# --- Helper functions ---
def is_admin(user_id):
    return str(user_id) == ADMIN_CHAT_ID

def is_editor(user_id):
    cur.execute("SELECT is_editor FROM employees WHERE telegram_id = ?", (user_id,))
    result = cur.fetchone()
    return result and result[0] == 1

# Define commands that editors can also use (subset of admin commands)
# These are commands where editor access is granted via the `has_editor_permission` function
EDITOR_ALLOWED_ADMIN_COMMANDS = [
    "list_employees", # Already handled by is_admin or is_editor check directly in handler
    "click_user_list",
    "report", # Adding report for editors
    "list_domains", # Adding list_domains for editors
    "channel_list", # Editors can see public lists
    "earning_bot_list", # Editors can see public lists
    "site_list" # Editors can see public lists
]

def has_editor_permission(user_id, command_name):
    if not is_editor(user_id):
        return False
    # Check if the command (without '/') is in the allowed list
    # The command_name from message.text will be like "click_user_list"
    return command_name in EDITOR_ALLOWED_ADMIN_COMMANDS


# --- Telegram Bot Command Handlers ---

# START Command - Improved Welcome Message & Public Commands
@dp.message(CommandStart())
async def send_welcome(message: types.Message, state: FSMContext):
    user_username = message.from_user.username
    user_id = message.from_user.id

    welcome_message = (
        "👋 <b>স্বাগতম!</b> এই বট আপনাকে অনলাইনে আয় করার চমৎকার সুযোগ করে দেবে। সহজ টাস্ক সম্পূর্ণ করে আপনি সহজেই USDT উপার্জন করতে পারবেন!\n\n"
        "Hello! This bot offers you an excellent opportunity to earn online. Complete simple tasks and easily earn USDT!\n\n"
    )
    
    # Check if user is an employee
    cur.execute("SELECT profile_set, banned FROM employees WHERE username = ? OR telegram_id = ?", (user_username, user_id))
    employee_status = cur.fetchone()

    is_already_employee = False
    profile_is_set = False
    is_banned = False

    if employee_status:
        is_already_employee = True
        profile_is_set = employee_status[0]
        is_banned = employee_status[1]

    if is_banned:
        welcome_message += "🚫 দুঃখিত, আপনি এই বট থেকে নিষিদ্ধ (banned) হয়েছেন। আপনি কোনো কার্যক্রম করতে পারবেন না।"
        await message.reply(welcome_message, parse_mode=ParseMode.HTML)
        return

    if is_already_employee:
        welcome_message += "আপনার বর্তমান স্ট্যাটাস: <b>এমপ্লয়ি</b>\n\n"
        if not profile_is_set:
            welcome_message += "⚠️ আপনার প্রোফাইল সেট করা নেই। দয়া করে `/set_profile` কমান্ড ব্যবহার করে আপনার প্রোফাইল সেট করুন।"
            # Start profile setup FSM if not set
            await state.set_state(ProfileSetup.name)
            await message.answer("আপনার <b>পুরো নাম</b> লিখুন:") # Initial prompt for profile setup
            return # Exit early to proceed with FSM
    else:
        welcome_message += "আপনি কি আমাদের সাথে কাজ করে আয় করতে চান? `/join_employee` কমান্ড ব্যবহার করে একজন এমপ্লয়ি হিসেবে যুক্ত হন!\n\n"
        
    welcome_message += (
        "🌐 <b>সাধারণ কমান্ডসমূহ:</b>\n"
        "/bot_info - এই বট সম্পর্কে জানুন\n"
        "/help_group - সাহায্য পেতে গ্রুপে যোগ দিন\n"
        "/contact - আমাদের সাথে যোগাযোগ করুন\n"
        "/channel_list - আমাদের চ্যানেলগুলো দেখুন\n"
        "/earning_bot_list - আয়ের অন্যান্য বট দেখুন\n"
        "/site_list - আমাদের ওয়েবসাইটগুলো দেখুন\n"
        "/em_cmd - এমপ্লয়ি কমান্ড তালিকা (যদি আপনি এমপ্লয়ি হন)\n"
    )
    await message.reply(welcome_message, parse_mode=ParseMode.HTML)


# --- Public Commands (already has is_editor_permission for list, channel_list, earning_bot_list, site_list) ---
@dp.message(Command("bot_info"))
async def bot_info_handler(message: types.Message):
    info_text = (
        "🤖 <b>আলুমিন্ট টাস্ক বট - আপনার আয়ের সঙ্গী!</b>\n\n"
        "এই বটটি আপনাকে বিভিন্ন অনলাইন টাস্ক (যেমন ওয়েবসাইট ভিজিট, ভিডিও দেখা) সম্পন্ন করার মাধ্যমে সহজ উপায়ে USDT উপার্জন করার সুযোগ দেয়। আমাদের এমপ্লয়ি হিসেবে যোগ দিয়ে আপনি আপনার রেফারেল লিংকের মাধ্যমে ভিজিটর এনে আয় করতে পারবেন। এখানে আপনি আপনার কাজের অগ্রগতি, আয় এবং পেমেন্টের তথ্য ট্র্যাক করতে পারবেন।\n\n"
        "<b>English:</b>\n"
        "🤖 <b>Alumint Task Bot - Your Earning Companion!</b>\n\n"
        "This bot provides you with an easy way to earn USDT by completing various online tasks (like website visits, watching videos). By joining as our employee, you can earn by bringing visitors through your referral links. Here, you can track your work progress, earnings, and payment information."
    )
    await message.reply(info_text, parse_mode=ParseMode.HTML)

@dp.message(Command("help_group"))
async def help_group_handler(message: types.Message):
    await message.reply("Need help? Join our support group here: [ZflixCO Group](https://t.me/zflixcogroup)", parse_mode=ParseMode.HTML)

@dp.message(Command("contact"))
async def contact_handler(message: types.Message):
    await message.reply("For business inquiries or direct support, contact us: @zflix_contract", parse_mode=ParseMode.HTML)

@dp.message(Command("channel_list"))
async def channel_list_handler(message: types.Message):
    # Publicly accessible, but also included in editor permission list for clarity in has_editor_permission
    cur.execute("SELECT name, description, link FROM channels")
    channels = cur.fetchall()
    if not channels:
        return await message.reply("ℹ️ কোনো চ্যানেল যুক্ত করা হয়নি।")
    
    channel_text = "📢 <b>আমাদের চ্যানেলসমূহ:</b>\n\n"
    for name, desc, link in channels:
        channel_text += f"<b>{name}</b>\n{desc}\n[Join Channel]({link})\n\n"
    await message.reply(channel_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

@dp.message(Command("earning_bot_list"))
async def earning_bot_list_handler(message: types.Message):
    # Publicly accessible, but also included in editor permission list for clarity in has_editor_permission
    cur.execute("SELECT name, description, link FROM earning_bots")
    bots = cur.fetchall()
    if not bots:
        return await message.reply("ℹ️ কোনো আয়ের বট যুক্ত করা হয়নি।")
    
    bot_text = "💰 <b>আয়ের অন্যান্য বট:</b>\n\n"
    for name, desc, link in bots:
        bot_text += f"<b>{name}</b>\n{desc}\n[Start Bot]({link})\n\n"
    await message.reply(bot_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

@dp.message(Command("site_list"))
async def site_list_handler(message: types.Message):
    # Publicly accessible, but also included in editor permission list for clarity in has_editor_permission
    cur.execute("SELECT name, base_url FROM domains")
    domains = cur.fetchall()
    if not domains:
        return await message.reply("ℹ️ কোনো ওয়েবসাইট যুক্ত করা হয়নি।")
    
    site_text = "🌐 <b>আমাদের ওয়েবসাইটসমূহ:</b>\n\n"
    for name, url in domains:
        site_text += f"<b>{name}</b>\n[ভিজিট করুন]({url})\n\n"
    await message.reply(site_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# --- Admin Commands for Public Lists ---
@dp.message(Command("add_channel"))
async def add_channel_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        parts = message.text.split(" ", 3) # /add_channel Name: Desc: Link:
        if len(parts) < 4 or not all(p.endswith(":") for p in parts[1:3]):
            return await message.reply("⚠️ সঠিকভাবে লিখুন: /add_channel Channel Name: <name> Channel Description: <desc> Channel Link: <link>")
        
        # Simple parsing for now, could be more robust
        channel_name = parts[1].replace("Name:", "").strip()
        channel_desc = parts[2].replace("Description:", "").strip()
        channel_link = parts[3].replace("Link:", "").strip()

        cur.execute("INSERT INTO channels (name, description, link) VALUES (?, ?, ?)", (channel_name, channel_desc, channel_link))
        conn.commit()
        await message.reply(f"✅ চ্যানেল '{channel_name}' সফলভাবে যুক্ত করা হলো।")
    except sqlite3.IntegrityError:
        await message.reply(f"⚠️ এই চ্যানেলটি ইতিমধ্যেই বিদ্যমান।")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")

@dp.message(Command("add_bot"))
async def add_earning_bot_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        parts = message.text.split(" ", 3) # /add_bot Name: Desc: Link:
        if len(parts) < 4 or not all(p.endswith(":") for p in parts[1:3]):
            return await message.reply("⚠️ সঠিকভাবে লিখুন: /add_bot Bot Name: <name> Bot Description: <desc> Bot Link: <link>")
        
        bot_name = parts[1].replace("Name:", "").strip()
        bot_desc = parts[2].replace("Description:", "").strip()
        bot_link = parts[3].replace("Link:", "").strip()

        cur.execute("INSERT INTO earning_bots (name, description, link) VALUES (?, ?, ?)", (bot_name, bot_desc, bot_link))
        conn.commit()
        await message.reply(f"✅ বট '{bot_name}' সফলভাবে যুক্ত করা হলো।")
    except sqlite3.IntegrityError:
        await message.reply(f"⚠️ এই বটটি ইতিমধ্যেই বিদ্যমান।")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")


# --- Employee Self-Registration: New command `join_employee` ---
@dp.message(Command("join_employee"))
async def self_join_employee_handler(message: types.Message, state: FSMContext):
    username = message.from_user.username
    telegram_id = message.from_user.id
    if not username:
        return await message.reply("❌ আপনার টেলিগ্রাম ইউজারনেম সেট করা নেই। দয়া করে সেটিংস থেকে সেট করুন।")
    
    cur.execute("SELECT username, banned FROM employees WHERE username = ? OR telegram_id = ?", (username, telegram_id))
    employee_data = cur.fetchone()

    if employee_data:
        if employee_data[1]: # Check if banned
            return await message.reply("🚫 দুঃখিত, আপনি এই বট থেকে নিষিদ্ধ (banned) হয়েছেন। আপনি যুক্ত হতে পারবেন না।")
        else:
            return await message.reply("ℹ️ আপনি ইতিমধ্যেই একজন এমপ্লয়ি হিসেবে নিবন্ধিত আছেন।")
    
    # Add to employees table with profile_set = 0 and banned = 0
    cur.execute("INSERT INTO employees (username, telegram_id, profile_set, banned) VALUES (?, ?, ?, ?)", (username, telegram_id, 0, 0))
    conn.commit()
    await message.reply(f"✅ @{username} আপনাকে এমপ্লয়ি হিসেবে যুক্ত করা হলো! এখন আপনার প্রোফাইল সেট করার পালা।")
    
    # Start profile setup FSM
    await state.set_state(ProfileSetup.name)
    await message.answer("আপনার <b>পুরো নাম</b> লিখুন:")


# --- Profile Management (FSM) ---

@dp.message(Command("set_profile", "change_profile"))
async def start_profile_setup(message: types.Message, state: FSMContext):
    username = message.from_user.username
    cur.execute("SELECT username FROM employees WHERE username = ?", (username,))
    if not cur.fetchone():
        return await message.reply("❌ আপনি এমপ্লয়ি নন।`/join_employee` কমান্ড ব্যবহার করে যুক্ত হন।")
    
    await state.set_state(ProfileSetup.name)
    await message.answer("আপনার <b>পুরো নাম</b> লিখুন:")

@dp.message(ProfileSetup.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer("আপনার <b>ফোন নম্বর</b> লিখুন:")
    await state.set_state(ProfileSetup.phone)

@dp.message(ProfileSetup.phone)
async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone_number=message.text)
    await message.answer("আপনার <b>ইমেইল</b> লিখুন:")
    await state.set_state(ProfileSetup.email)

@dp.message(ProfileSetup.email)
async def process_email(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer("আপনার <b>বিকাশ নম্বর</b> লিখুন:")
    await state.set_state(ProfileSetup.bkash)

@dp.message(ProfileSetup.bkash)
async def process_bkash(message: types.Message, state: FSMContext):
    await state.update_data(bkash_number=message.text)
    await message.answer("আপনার <b>Binance ID</b> লিখুন:")
    await state.set_state(ProfileSetup.binance_id)

@dp.message(ProfileSetup.binance_id)
async def process_binance(message: types.Message, state: FSMContext):
    await state.update_data(binance_id=message.text)
    await message.answer("আপনার <b>Youtube Link</b> (যদি থাকে) লিখুন:")
    await state.set_state(ProfileSetup.youtube)

@dp.message(ProfileSetup.youtube)
async def process_youtube(message: types.Message, state: FSMContext):
    await state.update_data(youtube_link=message.text)
    await message.answer("আপনার <b>Facebook Link</b> (যদি থাকে) লিখুন:")
    await state.set_state(ProfileSetup.facebook)

@dp.message(ProfileSetup.facebook)
async def process_facebook(message: types.Message, state: FSMContext):
    await state.update_data(facebook_link=message.text)
    await message.answer("আপনার <b>TikTok Link</b> (যদি থাকে) লিখুন:")
    await state.set_state(ProfileSetup.tiktok)

@dp.message(ProfileSetup.tiktok)
async def process_tiktok(message: types.Message, state: FSMContext):
    await state.update_data(tiktok_link=message.text)
    await message.answer("আপনার <b>Website Link</b> (যদি থাকে) লিখুন:")
    await state.set_state(ProfileSetup.website)

@dp.message(ProfileSetup.website)
async def process_website(message: types.Message, state: FSMContext):
    await state.update_data(website_link=message.text)
    
    user_data = await state.get_data()
    username = message.from_user.username

    cur.execute("""
        UPDATE employees SET
        profile_set = ?, full_name = ?, phone_number = ?, email = ?,
        bkash_number = ?, binance_id = ?, youtube_link = ?,
        facebook_link = ?, tiktok_link = ?, website_link = ?,
        about_yourself = ?
        WHERE username = ?
    """, (
        1, user_data['full_name'], user_data['phone_number'], user_data['email'],
        user_data['bkash_number'], user_data['binance_id'], user_data['youtube_link'],
        user_data['facebook_link'], user_data['tiktok_link'], user_data['website_link'],
        user_data['about_yourself'], username
    ))
    conn.commit()
    
    await message.reply("✅ আপনার প্রোফাইল সফলভাবে সেট/আপডেট করা হয়েছে!")
    await state.clear()

@dp.message(Command("my_profile"))
async def my_profile_handler(message: types.Message):
    username = message.from_user.username
    if not username:
        return await message.reply("❌ আপনার টেলিগ্রাম ইউজারনেম সেট করা নেই।")
    
    cur.execute("""
        SELECT full_name, phone_number, email, bkash_number, binance_id,
               youtube_link, facebook_link, tiktok_link, website_link, about_yourself,
               profile_set
        FROM employees WHERE username = ?
    """, (username,))
    profile_data = cur.fetchone()

    if not profile_data:
        return await message.reply("❌ আপনি একজন নিবন্ধিত কর্মচারী নন। `/join_employee` কমান্ড ব্যবহার করে যুক্ত হন।")
    
    (full_name, phone, email, bkash, binance, youtube, facebook, tiktok, website, about, profile_set) = profile_data

    if not profile_set:
        return await message.reply("⚠️ আপনার প্রোফাইল সেট করা নেই। `/set_profile` কমান্ড ব্যবহার করে আপনার প্রোফাইল সেট করুন।")

    profile_text = (
        f"👤 <b>আপনার প্রোফাইল:</b>\n\n"
        f"<b>নাম:</b> {full_name or 'N/A'}\n"
        f"<b>ফোন:</b> {phone or 'N/A'}\n"
        f"<b>ইমেইল:</b> {email or 'N/A'}\n"
        f"<b>বিকাশ নম্বর:</b> {bkash or 'N/A'}\n"
        f"<b>Binance ID:</b> {binance or 'N/A'}\n"
        f"<b>Youtube:</b> {youtube or 'N/A'}\n"
        f"<b>Facebook:</b> {facebook or 'N/A'}\n"
        f"<b>TikTok:</b> {tiktok or 'N/A'}\n"
        f"<b>Website:</b> {website or 'N/A'}\n"
        f"<b>About:</b> {about or 'N/A'}\n\n"
        "প্রোফাইল পরিবর্তন করতে: `/change_profile`"
    )
    await message.reply(profile_text, parse_mode=ParseMode.HTML)


# --- Employee Commands List (updated) ---
@dp.message(Command("em_cmd", "my_cmd")) # Added my_cmd as an alias
async def employee_command_list(message: types.Message):
    commands_text = (
        "📋 <b>এমপ্লয়ি কমান্ডসমূহ:</b>\n\n"
        "/start - বটের সাথে কথা বলা শুরু করুন\n"
        "/em_cmd (বা /my_cmd) - এই কমান্ড তালিকা দেখুন\n"
        "/get_task - আপনার টাস্ক লিংক পান\n"
        "/my_views - আপনার রেফারেল ভিউ সংখ্যা দেখুন\n"
        "/my_profile - আপনার প্রোফাইল তথ্য দেখুন\n"
        "/set_profile (বা /change_profile) - আপনার প্রোফাইল সেট/পরিবর্তন করুন\n"
        "/my_balance - আপনার USDT ব্যালেন্স দেখুন\n"
        "/claim_usdt - ভিজিট থেকে USDT তে রূপান্তর করুন (নতুন কমান্ড)\n" # <-- নতুন কমান্ড যোগ করা হয়েছে
        "/withdraw_usdt - ব্যালেন্স উত্তোলন করুন\n"
    )
    await message.reply(commands_text, parse_mode=ParseMode.HTML)


# --- Existing Commands (modified) ---

# Admin Commands List (from previous, now with new commands and editor access notes)
@dp.message(Command("ad_cmd"))
async def admin_command_list(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    
    commands_text = (
        "📋 <b>অ্যাডমিন কমান্ডসমূহ:</b>\n\n"
        "/ad_cmd - এই কমান্ড তালিকা দেখুন\n"
        "/em_cmd - এমপ্লয়ি কমান্ড তালিকা দেখুন\n"
        "/add_employee @username <Telegram_ID> - নতুন কর্মচারী যুক্ত করুন (অ্যাডমিন অনুমোদিত)\n"
        "/delete_employee @username - কর্মচারী মুছে ফেলুন\n"
        "/list_employees - সকল কর্মচারীর তালিকা দেখুন (এডিটরদেরও অনুমতি আছে)\n"
        "/click_user_list - রেফারেল লিংক ক্লিক করা ব্যবহারকারীদের তালিকা দেখুন (এডিটরদেরও অনুমতি আছে)\n"
        "/band_employee @username - কর্মচারীকে নিষিদ্ধ করুন\n"
        "/add_editor @username - কর্মচারীকে এডিটর হিসেবে যুক্ত করুন\n"
        "/remove_editor @username - কর্মচারীকে এডিটর থেকে অপসারণ করুন\n"
        "/report - টাস্ক এবং ভিউ রিপোর্ট দেখুন (এডিটরদেরও অনুমতি আছে)\n"
        "/list_domains - সকল ডোমেইন তালিকা দেখুন (এডিটরদেরও অনুমতি আছে)\n"
        "/channel_list - আমাদের চ্যানেলগুলো দেখুন (এডিটরদেরও অনুমতি আছে)\n"
        "/earning_bot_list - আয়ের অন্যান্য বট দেখুন (এডিটরদেরও অনুমতি আছে)\n"
        "/site_list - আমাদের ওয়েবসাইটগুলো দেখুন (এডিটরদেরও অনুমতি আছে)\n"
        "/add_domain <name> <base_url> - নতুন ডোমেইন যোগ করুন\n"
        "/delete_domain <name> - ডোমেইন মুছে ফেলুন\n"
        "/add_channel Channel Name: <name> Channel Description: <desc> Channel Link: <link> - নতুন চ্যানেল যোগ করুন\n"
        "/add_bot Bot Name: <name> Bot Description: <desc> Bot Link: <link> - নতুন আর্নিং বট যোগ করুন\n"
        "/set_global_task <domain_name> <task_identifier> - সকল কর্মচারীর জন্য গ্লোবাল টাস্ক সেট করুন\n"
        "/assign_task @username <domain_name> <task_identifier> - নির্দিষ্ট কর্মচারীকে টাস্ক দিন\n"
        "/post_all <আপনার_মেসেজ> - সকল কর্মচারীকে মেসেজ পাঠান\n"
        "/post_to_employee @username <আপনার_মেসেজ> - নির্দিষ্ট কর্মচারীকে মেসেজ পাঠান\n"
        "/set_usdt <amount> - প্রতি 1000 ভিজিট এর জন্য USDT রেট সেট করুন (যেমন: /set_usdt 1.00)\n"
        "/em_visit_add @username <visits> - কর্মচারীর ভিজিট যোগ করুন (যেমন: /em_visit_add @user 115)\n"
        "/em_visit_minus @username <visits> - কর্মচারীর ভিজিট কাটুন (যেমন: /em_visit_minus @user 115)\n"
        "/convert_visits_to_usdt @username - ভিজিট থেকে USDT তে রূপান্তর করুন (এই কমান্ড অ্যাডমিনদের জন্য থাকবে)\n"
    )
    await message.reply(commands_text, parse_mode=ParseMode.HTML)


# Admin Employee Management (already exists, but updated for 'banned' status)
@dp.message(Command("add_employee"))
async def admin_add_employee_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!") # Only admin can use this form of add_employee
    try:
        parts = message.text.split()
        if len(parts) < 2:
            return await message.reply("⚠️ সঠিকভাবে লিখুন: /add_employee @username <Telegram_ID (ঐচ্ছিক)>")
        
        username = parts[1].replace('@', '')
        telegram_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

        cur.execute("SELECT banned FROM employees WHERE username = ?", (username,))
        existing_employee = cur.fetchone()

        if existing_employee:
            if existing_employee[0]: # If banned, unban them
                cur.execute("UPDATE employees SET banned = 0, telegram_id = ? WHERE username = ?", (telegram_id, username))
                conn.commit()
                await message.reply(f"✅ @{username} (ID: {telegram_id if telegram_id else 'N/A'}) কে সফলভাবে আনব্যান করা হলো এবং এমপ্লয়ি হিসেবে পুনঃযুক্ত করা হলো!")
            else:
                await message.reply(f"ℹ️ @{username} ইতিমধ্যেই একজন এমপ্লয়ি হিসেবে নিবন্ধিত আছেন।")
        else:
            cur.execute("INSERT INTO employees (username, telegram_id, banned) VALUES (?, ?, ?)", (username, telegram_id, 0))
            conn.commit()
            await message.reply(f"✅ @{username} (ID: {telegram_id if telegram_id else 'N/A'}) কে এমপ্লয়ি হিসেবে যুক্ত করা হলো!")
    except (IndexError, ValueError):
        await message.reply("⚠️ সঠিকভাবে লিখুন: /add_employee @username <Telegram_ID (ঐচ্ছিক)>")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")

@dp.message(Command("delete_employee"))
async def delete_employee(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        username = message.text.split()[1].replace('@', '')
        cur.execute("DELETE FROM employees WHERE username = ?", (username,))
        cur.execute("DELETE FROM individual_tasks WHERE employee_username = ?", (username,)) # Delete associated tasks
        conn.commit()
        if cur.rowcount > 0:
            await message.reply(f"✅ @{username} কে এমপ্লয়ি তালিকা থেকে মুছে ফেলা হলো এবং তার টাস্কগুলোও ডিলিট করা হলো।")
        else:
            await message.reply(f"ℹ️ @{username} নামে কোনো এমপ্লয়ি পাওয়া যায়নি।")
    except IndexError:
        await message.reply("⚠️ সঠিকভাবে লিখুন: /delete_employee @username")

@dp.message(Command("band_employee")) # NEW
async def band_employee_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        username = message.text.split()[1].replace('@', '')
        cur.execute("UPDATE employees SET banned = 1 WHERE username = ?", (username,))
        conn.commit()
        if cur.rowcount > 0:
            await message.reply(f"✅ @{username} কে সফলভাবে নিষিদ্ধ (banned) করা হলো। সে আর নিজে থেকে জয়েন করতে পারবে না।")
        else:
            await message.reply(f"ℹ️ @{username} নামে কোনো এমপ্লয়ি পাওয়া যায়নি।")
    except IndexError:
        await message.reply("⚠️ সঠিকভাবে লিখুন: /band_employee @username")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")

@dp.message(Command("add_editor")) # NEW
async def add_editor_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        username = message.text.split()[1].replace('@', '')
        cur.execute("UPDATE employees SET is_editor = 1 WHERE username = ?", (username,))
        conn.commit()
        if cur.rowcount > 0:
            await message.reply(f"✅ @{username} কে সফলভাবে এডিটর হিসেবে যুক্ত করা হলো।")
        else:
            await message.reply(f"ℹ️ @{username} নামে কোনো কর্মচারী পাওয়া যায়নি।")
    except IndexError:
        await message.reply("⚠️ সঠিকভাবে লিখুন: /add_editor @username")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")

@dp.message(Command("remove_editor")) # NEW
async def remove_editor_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        username = message.text.split()[1].replace('@', '')
        cur.execute("UPDATE employees SET is_editor = 0 WHERE username = ?", (username,))
        conn.commit()
        if cur.rowcount > 0:
            await message.reply(f"✅ @{username} কে সফলভাবে এডিটর থেকে অপসারণ করা হলো।")
        else:
            await message.reply(f"ℹ️ @{username} নামে কোনো কর্মচারী পাওয়া যায়নি।")
    except IndexError:
        await message.reply("⚠️ সঠিকভাবে লিখুন: /remove_editor @username")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")

@dp.message(Command("list_employees"))
async def list_employees(message: types.Message):
    # Editors (via has_editor_permission) and Admins can use this
    if not (is_admin(message.from_user.id) or has_editor_permission(message.from_user.id, "list_employees")):
        return await message.reply("❌ আপনার এই কমান্ড ব্যবহারের অনুমতি নেই!")
    
    cur.execute("SELECT username, full_name, total_visits, usdt_balance, banned, is_editor FROM employees")
    employees = cur.fetchall()
    if not employees:
        return await message.reply("ℹ️ কোনো এমপ্লয়ি পাওয়া যায়নি।")
    
    employee_list_text = "👥 <b>এমপ্লয়িদের তালিকা:</b>\n\n"
    for emp_username, emp_full_name, total_visits, usdt_balance, banned_status, is_editor_status in employees:
        status_text = ""
        if banned_status:
            status_text += "🚫 Banned"
        if is_editor_status:
            status_text += " ✨ Editor"
        
        employee_list_text += (
            f"<b>@{emp_username}</b> ({emp_full_name or 'N/A'}) {status_text.strip()}\n"
            f"  👁️ ভিজিট: {total_visits}, 💰 ব্যালেন্স: {usdt_balance:.2f} USDT\n"
        )
    await message.reply(employee_list_text, parse_mode=ParseMode.HTML)

@dp.message(Command("click_user_list")) # NEW - now also for editors
async def click_user_list_handler(message: types.Message):
    # Editors (via has_editor_permission) and Admins can use this
    if not (is_admin(message.from_user.id) or has_editor_permission(message.from_user.id, "click_user_list")):
        return await message.reply("❌ আপনি অ্যাডমিন নন বা এই কমান্ড ব্যবহারের অনুমতি নেই!")
    
    # Select distinct viewer_username and viewer_full_name from clicks
    # Exclude those who are also employees
    cur.execute("""
        SELECT DISTINCT c.viewer_username, c.viewer_full_name, c.viewer_telegram_id
        FROM clicks c
        LEFT JOIN employees e ON c.viewer_username = e.username OR c.viewer_telegram_id = e.telegram_id
        WHERE e.username IS NULL
    """)
    clicked_users = cur.fetchall()

    if not clicked_users:
        return await message.reply("ℹ️ কোনো নন-এমপ্লয়ি ব্যবহারকারী রেফারেল লিংকে ক্লিক করেনি।")
    
    user_list_text = "👤 <b>রেফারেল লিংক ক্লিক করা ব্যবহারকারী (নন-এমপ্লয়ি):</b>\n\n"
    for username, full_name, telegram_id in clicked_users:
        user_list_text += f"• <b>{full_name or 'N/A'}</b> (@{username or 'N/A'}) [ID: {telegram_id or 'N/A'}]\n"
    await message.reply(user_list_text, parse_mode=ParseMode.HTML)

@dp.message(Command("report")) # Now also for editors
async def get_report(message: types.Message):
    if not (is_admin(message.from_user.id) or has_editor_permission(message.from_user.id, "report")):
        return await message.reply("❌ আপনার এই কমান্ড ব্যবহারের অনুমতি নেই!")
    
    report_text = "📋 <b>রিপোর্ট:</b>\n\n"
    
    # Total Clicks and Visits
    cur.execute("SELECT COUNT(*), SUM(CASE WHEN is_visit = 1 THEN 1 ELSE 0 END) FROM clicks")
    total_clicks, total_visits = cur.fetchone()
    report_text += f"🔗 মোট ক্লিক: {total_clicks or 0}\n"
    report_text += f"👁️ মোট ভিজিট (১২+ সেকেন্ড): {total_visits or 0}\n\n"

    # Top Employees by Visits
    cur.execute("SELECT username, total_visits FROM employees ORDER BY total_visits DESC LIMIT 5")
    top_employees = cur.fetchall()
    if top_employees:
        report_text += "📈 <b>শীর্ষ ৫ এমপ্লয়ি (ভিজিট অনুযায়ী):</b>\n"
        for i, (username, visits) in enumerate(top_employees):
            report_text += f"{i+1}. @{username}: {visits} ভিজিট\n"
        report_text += "\n"

    # Recent Withdraw Requests (Pending)
    cur.execute("""
        SELECT employee_username, usdt_amount, payment_method, payment_detail, request_date
        FROM withdraw_requests WHERE status = 'pending' ORDER BY request_date DESC LIMIT 5
    """)
    pending_withdraws = cur.fetchall()
    if pending_withdraws:
        report_text += "⏳ <b>সাম্প্রতিক পেন্ডিং উত্তোলন অনুরোধ:</b>\n"
        for username, amount, method, detail, date in pending_withdraws:
            report_text += f"• @{username}: {amount:.2f} USDT ({method}, {detail}) - {date}\n"
        report_text += "\n"
    else:
        report_text += "ℹ️ কোনো পেন্ডিং উত্তোলন অনুরোধ নেই।\n\n"

    await message.reply(report_text, parse_mode=ParseMode.HTML)


# --- Balance and Visit Adjustment ---

@dp.message(Command("set_usdt"))
async def set_usdt_rate_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        parts = message.text.split()
        if len(parts) < 2:
            return await message.reply("⚠️ সঠিকভাবে লিখুন: /set_usdt <amount> (যেমন: 1.00)")
        
        usdt_amount = float(parts[1])
        if usdt_amount <= 0:
            return await message.reply("❌ USDT রেট অবশ্যই 0 এর বেশি হতে হবে।")
        
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)", ('usdt_rate_per_1000_visits', str(usdt_amount)))
        conn.commit()
        await message.reply(f"✅ সফলভাবে 1000 ভিজিট এর জন্য USDT রেট সেট করা হলো: {usdt_amount:.2f} USDT")
    except ValueError:
        await message.reply("❌ অবৈধ সংখ্যা। সঠিকভাবে লিখুন: /set_usdt <amount>")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")

@dp.message(Command("em_visit_add"))
async def employee_visit_add_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        parts = message.text.split()
        if len(parts) < 3:
            return await message.reply("⚠️ সঠিকভাবে লিখুন: /em_visit_add @username <visits>")
        
        target_username = parts[1].replace('@', '')
        visits_to_add = int(parts[2])
        if visits_to_add <= 0:
            return await message.reply("❌ যোগ করার ভিজিট সংখ্যা অবশ্যই 0 এর বেশি হতে হবে।")
        
        cur.execute("UPDATE employees SET total_visits = total_visits + ? WHERE username = ?", (visits_to_add, target_username))
        conn.commit()
        if cur.rowcount == 0:
            return await message.reply(f"ℹ️ @{target_username} নামে কোনো কর্মচারী পাওয়া যায়নি।")
        
        await message.reply(f"✅ @{target_username} এর ভিজিট সংখ্যায় {visits_to_add} ভিজিট যোগ করা হলো।")
    except ValueError:
        await message.reply("❌ অবৈধ সংখ্যা। সঠিকভাবে লিখুন: /em_visit_add @username <visits>")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")

@dp.message(Command("em_visit_minus"))
async def employee_visit_minus_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        parts = message.text.split()
        if len(parts) < 3:
            return await message.reply("⚠️ সঠিকভাবে লিখুন: /em_visit_minus @username <visits>")
        
        target_username = parts[1].replace('@', '')
        visits_to_minus = int(parts[2])
        if visits_to_minus <= 0:
            return await message.reply("❌ কমানোর ভিজিট সংখ্যা অবশ্যই 0 এর বেশি হতে হবে।")
        
        # Ensure total_visits doesn't go below zero
        cur.execute("UPDATE employees SET total_visits = MAX(0, total_visits - ?) WHERE username = ?", (visits_to_minus, target_username))
        conn.commit()
        if cur.rowcount == 0:
            return await message.reply(f"ℹ️ @{target_username} নামে কোনো কর্মচারী পাওয়া যায়নি।")
        
        await message.reply(f"✅ @{target_username} এর ভিজিট সংখ্যা থেকে {visits_to_minus} ভিজিট কমানো হলো।")
    except ValueError:
        await message.reply("❌ অবৈধ সংখ্যা। সঠিকভাবে লিখুন: /em_visit_minus @username <visits>")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")

# --- ADMIN COMMAND: Convert total_visits to usdt_balance (still admin only for specific employee conversion) ---
@dp.message(Command("convert_visits_to_usdt"))
async def convert_visits_to_usdt_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.reply("❌ আপনি অ্যাডমিন নন!")
    try:
        parts = message.text.split()
        if len(parts) < 2:
            return await message.reply("⚠️ সঠিকভাবে লিখুন: /convert_visits_to_usdt @username")
        
        target_username = parts[1].replace('@', '')

        cur.execute("SELECT total_visits, usdt_balance FROM employees WHERE username = ?", (target_username,))
        employee_data = cur.fetchone()

        if not employee_data:
            return await message.reply(f"ℹ️ @{target_username} নামে কোনো কর্মচারী পাওয়া যায়নি।")
        
        total_visits = employee_data[0]
        current_usdt_balance = employee_data[1]

        if total_visits == 0:
            return await message.reply(f"ℹ️ @{target_username} এর কোনো নতুন ভিজিট নেই যা USDT তে কনভার্ট করা যাবে।")

        cur.execute("SELECT value FROM global_settings WHERE key = 'usdt_rate_per_1000_visits'")
        usdt_rate_str = cur.fetchone()
        usdt_rate = float(usdt_rate_str[0]) if usdt_rate_str else 0.0

        if usdt_rate == 0.0:
            return await message.reply("❌ USDT রেট সেট করা নেই। দয়া করে অ্যাডমিন `/set_usdt` কমান্ড ব্যবহার করে সেট করুন।")

        usdt_to_add = (total_visits / 1000) * usdt_rate

        # Update usdt_balance and reset total_visits
        cur.execute("UPDATE employees SET usdt_balance = ?, total_visits = 0 WHERE username = ?",
                    (current_usdt_balance + usdt_to_add, target_username))
        conn.commit()

        await message.reply(f"✅ @{target_username} এর {total_visits} ভিজিট সফলভাবে {usdt_to_add:.2f} USDT তে কনভার্ট করা হয়েছে। বর্তমান উত্তোলনযোগ্য ব্যালেন্স: {current_usdt_balance + usdt_to_add:.2f} USDT। ভিজিট সংখ্যা ০ তে রিসেট করা হলো।")

    except ValueError:
        await message.reply("❌ অবৈধ ইনপুট।")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")

# --- EMPLOYEE COMMAND: Convert own total_visits to usdt_balance ---
@dp.message(Command("claim_usdt"))
async def claim_usdt_handler(message: types.Message):
    username = message.from_user.username
    if not username:
        return await message.reply("❌ আপনার টেলিগ্রাম ইউজারনেম সেট করা নেই।")

    cur.execute("SELECT total_visits, usdt_balance FROM employees WHERE username = ?", (username,))
    employee_data = cur.fetchone()

    if not employee_data:
        return await message.reply("❌ আপনি একজন নিবন্ধিত কর্মচারী নন। `/join_employee` কমান্ড ব্যবহার করে যুক্ত হন।")
    
    total_visits = employee_data[0]
    current_usdt_balance = employee_data[1]

    if total_visits == 0:
        return await message.reply("ℹ️ আপনার কোনো নতুন ভিজিট নেই যা USDT তে কনভার্ট করা যাবে।")

    cur.execute("SELECT value FROM global_settings WHERE key = 'usdt_rate_per_1000_visits'")
    usdt_rate_str = cur.fetchone()
    usdt_rate = float(usdt_rate_str[0]) if usdt_rate_str else 0.0

    if usdt_rate == 0.0:
        return await message.reply("❌ USDT রেট সেট করা নেই। দয়া করে অ্যাডমিনকে `/set_usdt` কমান্ড ব্যবহার করে সেট করতে বলুন।")

    usdt_to_add = (total_visits / 1000) * usdt_rate

    # Update usdt_balance and reset total_visits
    cur.execute("UPDATE employees SET usdt_balance = ?, total_visits = 0 WHERE username = ?",
                (current_usdt_balance + usdt_to_add, username))
    conn.commit()

    await message.reply(f"✅ আপনার {total_visits} ভিজিট সফলভাবে {usdt_to_add:.2f} USDT তে কনভার্ট করা হয়েছে। আপনার বর্তমান উত্তোলনযোগ্য ব্যালেন্স: {current_usdt_balance + usdt_to_add:.2f} USDT। ভিজিট সংখ্যা ০ তে রিসেট করা হলো।")


@dp.message(Command("my_balance"))
async def my_balance_handler(message: types.Message):
    username = message.from_user.username
    if not username:
        return await message.reply("❌ আপনার টেলিগ্রাম ইউজারনেম সেট করা নেই।")
    
    cur.execute("SELECT total_visits, usdt_balance FROM employees WHERE username = ?", (username,))
    employee_data = cur.fetchone()

    if not employee_data:
        return await message.reply("❌ আপনি একজন নিবন্ধিত কর্মচারী নন। `/join_employee` কমান্ড ব্যবহার করে যুক্ত হন।")
    
    total_visits = employee_data[0]
    current_usdt_balance = employee_data[1] 

    cur.execute("SELECT value FROM global_settings WHERE key = 'usdt_rate_per_1000_visits'")
    usdt_rate_str = cur.fetchone()
    usdt_rate = float(usdt_rate_str[0]) if usdt_rate_str else 0.0 

    calculated_usdt = (total_visits / 1000) * usdt_rate

    # Check for pending withdrawals
    cur.execute("SELECT COUNT(*) FROM withdraw_requests WHERE employee_username = ? AND status = 'pending'", (username,))
    pending_withdrawals = cur.fetchone()[0]

    await message.reply(
        f"💰 <b>আপনার ব্যালেন্স:</b>\n"
        f"👁️ মোট ভিজিট: {total_visits}\n"
        f"💵 আনুমানিক USDT ব্যালেন্স: {calculated_usdt:.2f} USDT\n"
        f"আপনার বর্তমান উত্তোলনযোগ্য ব্যালেন্স: {current_usdt_balance:.2f} USDT\n"
        f"পেন্ডিং উত্তোলন: {pending_withdrawals}টি\n\n"
        f"ভিজিট থেকে USDT তে রূপান্তর করতে: `/claim_usdt`\n" # <--- এই লাইনটি যোগ করা হয়েছে
        f"উত্তোলন করতে: `/withdraw_usdt`"
    , parse_mode=ParseMode.HTML)


# --- Withdrawal System (Employee Side) ---
@dp.message(Command("withdraw_usdt"))
async def start_withdraw(message: types.Message, state: FSMContext):
    username = message.from_user.username
    cur.execute("SELECT usdt_balance, profile_set, bkash_number, binance_id FROM employees WHERE username = ?", (username,))
    employee_data = cur.fetchone()

    if not employee_data:
        return await message.reply("❌ আপনি একজন নিবন্ধিত কর্মচারী নন। `/join_employee` কমান্ড ব্যবহার করে যুক্ত হন।")
    
    usdt_balance = employee_data[0]
    profile_set = employee_data[1]
    bkash_number = employee_data[2]
    binance_id = employee_data[3]

    if not profile_set:
        return await message.reply("⚠️ উত্তোলন করার আগে আপনার প্রোফাইল সেট করুন: `/set_profile`")

    if usdt_balance < 1.00: # Minimum withdrawal amount
        return await message.reply(f"❌ উত্তোলনের জন্য আপনার ব্যালেন্সে কমপক্ষে 1.00 USDT থাকতে হবে। আপনার বর্তমান ব্যালেন্স: {usdt_balance:.2f} USDT")

    amounts = [1.00, 5.00, 10.00, 30.00, 100.00]
    available_amounts = [amt for amt in amounts if usdt_balance >= amt]

    if not available_amounts:
        return await message.reply(f"❌ আপনার বর্তমান ব্যালেন্স {usdt_balance:.2f} USDT দিয়ে কোনো উত্তোলন সম্ভব নয়।")

    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text=f"Withdraw ${amt:.2f}")] for amt in available_amounts
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("আপনি কত USDT উত্তোলন করতে চান? (আপনার বর্তমান ব্যালেন্স: {usdt_balance:.2f} USDT)", reply_markup=keyboard)
    await state.set_state(Withdrawal.amount)

@dp.message(Withdrawal.amount)
async def process_withdraw_amount(message: types.Message, state: FSMContext):
    try:
        text = message.text.replace("Withdraw $", "")
        amount = float(text)
        
        username = message.from_user.username
        cur.execute("SELECT usdt_balance FROM employees WHERE username = ?", (username,))
        current_balance = cur.fetchone()[0]

        if amount <= 0:
            return await message.reply("❌ উত্তোলনের পরিমাণ অবশ্যই 0 এর বেশি হতে হবে।")

        if amount > current_balance:
            return await message.reply(f"❌ আপনার ব্যালেন্স যথেষ্ট নয়। আপনার ব্যালেন্স: {current_balance:.2f} USDT। অনুগ্রহ করে সঠিক পরিমাণ বেছে নিন বা টাইপ করুন।")
        
        await state.update_data(usdt_amount=amount)

        # Ask for payment method
        keyboard = types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="Bkash")],
                [types.KeyboardButton(text="Binance")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await message.answer("কোন মাধ্যমে পেমেন্ট নিতে চান?", reply_markup=keyboard)
        await state.set_state(Withdrawal.payment_method)

    except ValueError:
        await message.reply("❌ অনুগ্রহ করে সঠিক উত্তোলনের পরিমাণ বেছে নিন বা সংখ্যায় টাইপ করুন।")
    except Exception as e:
        await message.reply(f"❌ একটি ত্রুটি হয়েছে: {e}")
        await state.clear()

@dp.message(Withdrawal.payment_method)
async def process_withdraw_payment_method(message: types.Message, state: FSMContext):
    payment_method = message.text
    if payment_method not in ["Bkash", "Binance"]:
        return await message.reply("❌ অনুগ্রহ করে 'Bkash' অথবা 'Binance' বেছে নিন।")
    
    username = message.from_user.username
    cur.execute("SELECT bkash_number, binance_id FROM employees WHERE username = ?", (username,))
    profile_data = cur.fetchone()
    bkash_number = profile_data[0]
    binance_id = profile_data[1]

    if payment_method == "Bkash" and not bkash_number:
        return await message.reply("⚠️ আপনার প্রোফাইলে বিকাশ নম্বর সেট করা নেই। দয়া করে সেট করুন `/set_profile`")
    if payment_method == "Binance" and not binance_id:
        return await message.reply("⚠️ আপনার প্রোফাইলে Binance ID সেট করা নেই। দয়া করে সেট করুন `/set_profile`")

    await state.update_data(payment_method=payment_method)
    await message.answer("উত্তোলন সম্পর্কে আপনার কোনো মন্তব্য থাকলে সর্বোচ্চ ৬০ অক্ষরের মধ্যে লিখুন (ঐচ্ছিক, না থাকলে 'না' লিখুন):")
    await state.set_state(Withdrawal.comment)

@dp.message(Withdrawal.comment)
async def process_withdraw_comment(message: types.Message, state: FSMContext):
    comment = message.text.strip()
    if comment.lower() == 'না':
        comment = ""
    elif len(comment) > 60:
        return await message.reply("❌ মন্তব্য ৬০ অক্ষরের বেশি হতে পারবে না।")
    
    await state.update_data(comment=comment)
    
    data = await state.get_data()
    username = message.from_user.username
    
    amount = data['usdt_amount']
    payment_method = data['payment_method']
    
    # CORRECTED LINE:
    cur.execute("SELECT bkash_number, binance_id FROM employees WHERE username = ?", (username,))
    profile_data = cur.fetchone()
    payment_detail = profile_data[0] if payment_method == "Bkash" else profile_data[1]

    # Save withdrawal request to DB
    cur.execute("""
        INSERT INTO withdraw_requests (employee_username, usdt_amount, payment_method, payment_detail, comment)
        VALUES (?, ?, ?, ?, ?)
    """, (username, amount, payment_method, payment_detail, comment))
    conn.commit()

    # Deduct amount from user's usdt_balance
    cur.execute("UPDATE employees SET usdt_balance = usdt_balance - ? WHERE username = ?", (amount, username))
    conn.commit()

    await message.reply(
        f"✅ আপনার উত্তোলনের অনুরোধ সফলভাবে পাঠানো হয়েছে!\n"
        f"পরিমাণ: {amount:.2f} USDT\n"
        f"পেমেন্ট মাধ্যম: {payment_method}\n"
        f"পেমেন্ট ডিটেইল: {payment_detail}\n"
        f"মন্তব্য: {comment if comment else 'নেই'}\n\n"
        "আমাদের অ্যাডমিন আপনার অনুরোধ পর্যালোচনা করবেন।"
    , parse_mode=ParseMode.HTML, reply_markup=types.ReplyKeyboardRemove())
    await state.clear()

# --- Web Server for handling external HTTP requests (from footer.php) ---

async def track_click_handler(request):
    try:
        data = await request.json()
        ref_by_employee = data.get('ref')
        viewer_username = data.get('viewer_username') # From JS
        viewer_telegram_id = data.get('viewer_telegram_id') # From JS
        viewer_full_name = data.get('viewer_full_name') # From JS
        user_agent = data.get('user_agent', 'Unknown User')
        page_url = data.get('page_url', 'Unknown URL')
        is_visit_flag = data.get('is_visit', False) # True if JS sends after 12s
        is_telegram_browser = data.get('is_telegram_browser', False)

        today_date = datetime.date.today().isoformat()
        # More generalized unique daily key for 20 visits per day for the same viewer on the same page
        # The key should combine viewer, date, and page_url (not ref_by_employee for uniqueness across multiple referrals to the same page)
        unique_daily_key_for_viewer_page = f"{viewer_telegram_id or viewer_username}_{today_date}_{page_url}"

        # Check if this specific page has been visited by this viewer today (to avoid double counting same page visit for the same day)
        cur.execute("SELECT id FROM clicks WHERE unique_daily_key = ? AND is_visit = 1", (unique_daily_key_for_viewer_page,))
        if cur.fetchone():
            logging.info(f"Duplicate visit for {unique_daily_key_for_viewer_page}. Skipping visit count.")
            # Still track the click if it's new, but don't increment visit count again
            # We will still log the click, but only increment total_visits once per page per day per viewer
            # However, the user also needs to prevent general 20 clicks per day.
            # So, we first check the 20 clicks limit, then the unique visit.

            # We need to refine the unique_daily_key to prevent more than 20 TOTAL clicks by the same viewer_telegram_id/viewer_username PER DAY, regardless of referrer or page.
            # The existing unique_daily_key is tied to ref_by_employee and page_url, which is too specific for the 20-visit limit.
            # Let's adjust the 20 visit limit check.

            # Check daily TOTAL click limit for this viewer (max 20 per day per viewer)
            cur.execute("""
                SELECT COUNT(*) FROM clicks 
                WHERE (viewer_telegram_id = ? OR viewer_username = ?) 
                AND STRFTIME('%Y-%m-%d', timestamp) = ?
            """, (viewer_telegram_id, viewer_username, today_date))
            
            total_clicks_today_for_viewer = cur.fetchone()[0]

            if total_clicks_today_for_viewer >= 20:
                logging.info(f"Daily total click limit reached for {viewer_username}.")
                return web.json_response({"status": "limit_reached", "message": "Daily total click limit reached for this user."})
            
            # If it's a duplicate visit for the same page/viewer, we will still record the click, but not increment employee's total_visits
            # The employee's total_visits is only for UNIQUE visits (12+ seconds) based on page_url per viewer per day.
            # If is_visit_flag is True, and it's a duplicate for unique_daily_key_for_viewer_page, we don't increment total_visits for employee.
            # But we still record this click in 'clicks' table as is_click = True.

            # Check if this specific page+employee has already been counted as a visit by this user today
            # This is for the employee's total_visits
            unique_employee_page_visit_key = f"{ref_by_employee}_{viewer_telegram_id or viewer_username}_{today_date}_{page_url}"
            cur.execute("SELECT id FROM clicks WHERE unique_daily_key = ? AND is_visit = 1", (unique_employee_page_visit_key,))
            is_duplicate_employee_page_visit = cur.fetchone() is not None

            # Insert into clicks table
            cur.execute("""
                INSERT INTO clicks (ref_by_employee, viewer_telegram_id, viewer_username, viewer_full_name,
                                    user_agent, page_url, is_visit, is_click, is_telegram_browser, unique_daily_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ref_by_employee, viewer_telegram_id, viewer_username, viewer_full_name,
                user_agent, page_url, is_visit_flag, True, is_telegram_browser, unique_employee_page_visit_key
            ))
            conn.commit()

            # Update employee's total_visits only if it's a new unique visit for them
            if is_visit_flag and not is_duplicate_employee_page_visit:
                cur.execute("UPDATE employees SET total_visits = total_visits + 1 WHERE username = ?", (ref_by_employee,))
                conn.commit()
            
            # Always update total_clicks for the employee for any new click (even if it's a duplicate visit or not a visit)
            cur.execute("UPDATE employees SET total_clicks = total_clicks + 1 WHERE username = ?", (ref_by_employee,))
            conn.commit()
            
            logging.info(f"Tracked click for ref: {ref_by_employee}, viewer: {viewer_username}, URL: {page_url}, Visit: {is_visit_flag}, Duplicate Visit: {is_duplicate_employee_page_visit}")

            if ADMIN_CHAT_ID:
                try:
                    domain_name = urlparse(page_url).netloc
                    status_emoji = "✅ ভিজিট" if is_visit_flag else "🔗 ক্লিক"
                    notification_message = (f"<b>{status_emoji} রেকর্ড করা হয়েছে!</b>\n"
                                          f"<b>রেফারেল:</b> <code>{ref_by_employee}</code>\n"
                                          f"<b>ডোমেইন:</b> {domain_name}\n"
                                          f"<b>পেজ URL:</b> {hcode(page_url)}\n"
                                          f"<b>ভিউয়ার:</b> {hbold(viewer_full_name)} (@{viewer_username})\n"
                                          f"<b>ব্রাউজার:</b> {'Telegram' if is_telegram_browser else 'External'}\n"
                                          f"<b>ইউজার এজেন্ট:</b> <code>{user_agent}</code>")
                    if is_visit_flag and is_duplicate_employee_page_visit:
                        notification_message += "\n\n(ℹ️ এই ভিজিটটি আজ এই পেজের জন্য ইতিমধ্যে গণনা করা হয়েছে, তাই এমপ্লয়ির ভিজিট সংখ্যা বাড়ানো হয়নি।)"

                    await bot.send_message(
                        chat_id=int(ADMIN_CHAT_ID),
                        text=notification_message,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logging.error(f"Failed to send admin notification: {e}")
            
            return web.json_response({"status": "success", "message": "Click tracked successfully"})

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
