import os, threading, time, sqlite3, re
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode

# --- ENV ---
TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID") or "7077093393")
# Supports multiple channels separated by comma
RAW_CHANNELS = os.getenv("REQUIRED_CHANNEL_1", "@verifiedearners11,@videoeditingclass11,@jambextensivestudies1,@payout112")
CHANNELS = [c.strip() for c in re.split(r'[,;\s]+', RAW_CHANNELS) if c.strip()]
# Clean @ and https
def clean_channel(c):
    c = c.replace("https://t.me/", "").replace("t.me/", "").replace("@", "").split("/")[0].strip()
    return c
CHANNELS = [clean_channel(c) for c in CHANNELS]

print(f"TOKEN CHECK: {'FOUND len='+str(len(TOKEN)) if TOKEN else 'MISSING'}")
print(f"ADMIN_ID: {ADMIN_ID}")
print(f"CHANNELS: {CHANNELS}")

# --- DB ---
DB = "bot.db"
def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0, referrals INTEGER DEFAULT 0, referred_by INTEGER, joined INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, status TEXT DEFAULT 'pending', account TEXT)")
    conn.commit()
    conn.close()
init_db()

def get_user(user_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, balance, referrals, referred_by, joined FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row

def add_user(user_id, username, referred_by=None):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (user_id, username, balance, referrals, referred_by) VALUES (?,?,?,?,?)", (user_id, username, 0, 0, referred_by))
        if referred_by and referred_by!= user_id:
            cur.execute("SELECT user_id FROM users WHERE user_id=?", (referred_by,))
            if cur.fetchone():
                cur.execute("UPDATE users SET balance = balance + 1000, referrals = referrals + 1 WHERE user_id=?", (referred_by,))
                print(f"Referral bonus: {referred_by} +1000 for {user_id}")
        conn.commit()
    conn.close()

async def check_joined(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    not_joined = []
    for ch in CHANNELS:
        try:
            member = await context.bot.get_chat_member(f"@{ch}", user_id)
            if member.status in ['left', 'kicked']:
                not_joined.append(ch)
        except Exception as e:
            print(f"Check @{ch} failed: {e}")
            not_joined.append(ch)
    return not_joined

def join_keyboard(not_joined):
    buttons = []
    for ch in not_joined:
        buttons.append([InlineKeyboardButton(f"📢 Join @{ch}", url=f"https://t.me/{ch}")])
    buttons.append([InlineKeyboardButton("✅ I Joined, Verify", callback_data="verify_join")])
    return InlineKeyboardMarkup(buttons)

def main_keyboard(is_admin=False):
