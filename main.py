from __future__ import annotations
import os, logging, sqlite3, time, threading
from typing import Any
from flask import Flask

# --- FLASK FOR RENDER ---
app = Flask(__name__)
@app.route('/')
def home(): return "SmartEarnBot is Live!"
@app.route('/health')
def health(): return "OK", 200
def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
threading.Thread(target=run_web, daemon=True).start()

import logging, sqlite3, time
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
    raw = raw.replace(" ", ",")
    return [u.strip() for u in raw.split(",") if u.strip()]

REQUIRED_CHANNELS = get_channels_from_env()
REQUIRED_CHANNEL_URLS = get_urls_from_env()

MINING_REWARD = max(1, int(os.getenv("MINING_REWARD", "500")))
MINING_COOLDOWN_SECONDS = max(60, int(os.getenv("MINING_COOLDOWN_SECONDS", "3600")))
MINIMUM_WITHDRAWAL = max(1, int(os.getenv("MINIMUM_WITHDRAWAL", "5000")))

ADMIN_IDS: set[int] = set()
for raw_admin_id in os.getenv("ADMIN_IDS", "").split(","):
    raw_admin_id = raw_admin_id.strip()
    if raw_admin_id:
        try: ADMIN_IDS.add(int(raw_admin_id))
        except ValueError: pass

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("smartearnbot")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

DB = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
DB.row_factory = sqlite3.Row
DB_LOCK = threading.RLock()

def initialize_database() -> None:
    with DB_LOCK:
        DB.executescript("""
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT NOT NULL DEFAULT '', referred_by INTEGER, created_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL, last_mined_at INTEGER);
            CREATE TABLE IF NOT EXISTS balances (user_id INTEGER PRIMARY KEY, amount INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL, referred_id INTEGER NOT NULL UNIQUE, created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS mining (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, reward INTEGER NOT NULL, mined_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL, processed_at INTEGER, processed_by INTEGER);
            CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL, reward INTEGER NOT NULL, task_type TEXT NOT NULL, target INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS task_claims (user_id INTEGER NOT NULL, task_id INTEGER NOT NULL, claimed_at INTEGER NOT NULL, PRIMARY KEY (user_id, task_id));
            """)
        starter_tasks = [("Join the community channel","Join the required channel and verify your membership.",25,"channel",1),("Invite 3 friends","Invite three friends using your personal referral link.",100,"referrals",3)]
        for task in starter_tasks:
            DB.execute("INSERT INTO tasks (title, description, reward, task_type, target) SELECT?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE task_type =?)", (*task, task[3]))
        DB.commit()

def ensure_user(user: Any, referrer_id: int | None = None) -> None:
    now = int(time.time()); user_id = int(user.id)
    with DB_LOCK:
        DB.execute("INSERT INTO users (user_id, username, first_name, created_at, last_seen_at) VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_seen_at=excluded.last_seen_at", (user_id, user.username or "", user.first_name or "", now, now))
        DB.execute("INSERT OR IGNORE INTO balances (user_id, amount) VALUES (?, 0)", (user_id,))
        if referrer_id and referrer_id!= user_id:
            referrer_exists = DB.execute("SELECT 1 FROM users WHERE user_id =?", (referrer_id,)).fetchone()
            current_referrer = DB.execute("SELECT referred_by FROM users WHERE user_id =?", (user_id,)).fetchone()
            if referrer_exists and current_referrer and current_referrer["referred_by"] is None:
                DB.execute("UPDATE users SET referred_by =? WHERE user_id =?", (referrer_id, user_id))
                DB.execute("INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at) VALUES (?,?,?)", (referrer_id, user_id, now))
        DB.commit()

def get_balance(user_id: int) -> int:
    with DB_LOCK: row = DB.execute("SELECT amount FROM balances WHERE user_id =?", (user_id,)).fetchone()
    return int(row["amount"]) if row else 0

def change_balance(user_id: int, amount: int) -> int | None:
    with DB_LOCK:
