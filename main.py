from __future__ import annotations
import os, logging, sqlite3, time, threading
from typing import Any
from flask import Flask

# --- FLASK FOR RENDER (MUST BE AT TOP) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "SmartEarnBot is Live!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()

# --- TELEGRAM BOT IMPORTS ---
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.request import HTTPXRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or ""
DATABASE_PATH = os.getenv("DATABASE_PATH", "smartearnbot.db").strip()

def get_channels_from_env():
    raw = os.getenv("REQUIRED_CHANNELS", "").strip() or os.getenv("REQUIRED_CHANNEL", "").strip()
    if not raw: return []
    raw = raw.replace(" ", ",")
    channels = [c.strip() for c in raw.split(",") if c.strip()]
    fixed = []
    for c in channels:
        if not c.startswith("@") and not c.startswith("https://"): c = "@"+c
        fixed.append(c)
    return fixed

def get_urls_from_env():
    raw = os.getenv("REQUIRED_CHANNEL_URLS", "").strip() or os.getenv("REQUIRED_CHANNEL_URL", "").strip()
    if not raw: return []
    return [u.strip() for u in raw.split(",") if u.strip()]

# --- DATABASE SETUP ---
DB_LOCK = threading.Lock()
DB = sqlite3.connect(DATABASE_PATH, check_same_thread=False, isolation_level=None)
DB.row_factory = sqlite3.Row

with DB_LOCK:
    DB.executescript("""
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_seen INTEGER, referred_by INTEGER);
        CREATE TABLE IF NOT EXISTS balances (user_id INTEGER PRIMARY KEY, amount INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS referrals (referrer_id INTEGER, referred_id INTEGER, UNIQUE(referrer_id, referred_id));
        CREATE TABLE IF NOT EXISTS mining (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, last_claim INTEGER);
        CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, status TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT, reward INTEGER, task_type TEXT, target INTEGER);
        CREATE TABLE IF NOT EXISTS task_claims (user_id INTEGER, task_id INTEGER, claimed_at INTEGER, UNIQUE(user_id, task_id));
    """)
    starter_tasks = [("Join the community channel","Join the required channel and verify your membership.",25,"channel",1),("Invite 3 friends","Invite three friends using your personal referral link.",100,"referrals",3)]
    for task in starter_tasks:
        DB.execute("INSERT INTO tasks (title, description, reward, task_type, target) SELECT?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE task_type =?)", (*task, task[3]))
    DB.commit()

def ensure_user(user: Any, referrer_id: int | None = None) -> None:
    now = int(time.time()); user_id = int(user.id)
    with DB_LOCK:
        DB.execute("INSERT INTO users (user_id, username, first_seen) VALUES (?,?,?) ON CONFLICT(user_id) DO NOTHING", (user_id, user.username, now))
        DB.execute("INSERT OR IGNORE INTO balances (user_id, amount) VALUES (?, 0)", (user_id,))
        if referrer_id and referrer_id!= user_id:
            referrer_exists = DB.execute("SELECT 1 FROM users WHERE user_id =?", (referrer_id,)).fetchone()
            current_referrer = DB.execute("SELECT referred_by FROM users WHERE user_id =?", (user_id,)).fetchone()
            if referrer_exists and current_referrer and current_referrer["referred_by"] is None:
                DB.execute("UPDATE users SET referred_by =? WHERE user_id =?", (referrer_id, user_id))
                DB.execute("INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?,?)", (referrer_id, user_id))
        DB.commit()

def get_balance(user_id: int) -> int:
    with DB_LOCK:
        row = DB.execute("SELECT amount FROM balances WHERE user_id =?", (user_id,)).fetchone()
    return int(row["amount"]) if row else 0

def change_balance(user_id: int, amount: int) -> None:
    with DB_LOCK:
        DB.execute("INSERT OR IGNORE INTO balances (user_id, amount) VALUES (?, 0)", (user_id,))
        DB.execute("UPDATE balances SET amount = amount +? WHERE user_id =?", (amount, user_id))
        DB.commit()

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    ref_id = int(args[0]) if args and args[0].isdigit() else None
    ensure_user(user, ref_id)
    bal = get_balance(user.id)
    await update.message.reply_text(f"Welcome {user.first_name}!\n💰 Balance: {bal}\n\nYour referral link: https://t.me/{context.bot.username}?start={user.id}")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    bal = get_balance(update.effective_user.id)
    await update.message.reply_text(f"💰 Your balance: {bal}")

def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN not set! Set TELEGRAM_BOT_TOKEN in Render Environment")
        while True:
            time.sleep(3600)
    request = HTTPXRequest(connect_timeout=20, read_timeout=20)
    application = Application.builder().token(BOT_TOKEN).request(request).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance_cmd))
    print("Starting Telegram polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
