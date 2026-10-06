import os, asyncio, threading
from flask import Flask
from pymongo import MongoClient
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Bot running - OK"
def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
client = MongoClient(MONGO_URL)
db = client["SmartEarnBot"]
users_col = db["users"]

BONUS_PER_CHANNEL = 1000
TOTAL_BONUS = 7000
REF_BONUS = 1000
MIN_WITHDRAW = 50000

ADMIN_IDS = [8480726493] # <-- change to your ID from @userinfobot

def get_user(uid):
    user = users_col.find_one({"user_id": uid})
    if not user:
        new_user = {"user_id": uid, "balance": 0, "referrals": 0, "task_done": 0}
        users_col.insert_one(new_user)
        return new_user
    return user

def is_admin(uid):
    return uid in ADMIN_IDS

main_keyboard = ReplyKeyboardMarkup([["🔴 Balance", "🟢 Tasks"],["🟣 Referrals", "🟠 Withdraw"]], resize_keyboard=True)

CHANNELS = [
    {"username": "@verifiedearners11", "url": "https://t.me/verifiedearners11", "name": "Verified Earners"},
    {"username": "@videoeditingclass11", "url": "https://t.me/videoeditingclass11", "name": "Video Editing Class"},
    {"username": "@jambextensivestudies1", "url": "https://t.me/jambextensivestudies1", "name": "JAMB Extensive Studies"},
    {"username": "@payout112", "url": "https://t.me/payout112", "name": "Payout Channel"},
    {"username": "@_2kUihmFJcFjNzBk", "url": "https://t.me/+_2kUihmFJcFjNzBk", "name": "VIP Group 1"},
    {"username": "@hbE8ioZLCHc2OGRk", "url": "https://t.me/+hbE8ioZLCHc2OGRk", "name": "VIP Group 2"},
    {"username": "@wGwfkO0m-fVjYjc0", "url": "https://t.me/+wGwfkO0m-fVjYjc0", "name": "VIP Group 3"},
]
CHECK_CHANNELS = ["@verifiedearners11", "@videoeditingclass11", "@jambextensivestudies1", "@payout112"]

async def check_joined(uid, context):
    not_joined = []
    for ch in CHECK_CHANNELS:
        try:
            m = await context.bot.get_chat_member(chat_id=ch, user_id=uid)
            if m.status in ['left', 'kicked']: not_joined.append(ch)
        except: not_joined.append(ch)
    return not_joined

async def count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    total_users = users_col.count_documents({})
    total_balance = sum([u.get('balance',0) for u in users_col.find({}, {"balance":1})])
    total_refs = sum([u.get('referrals',0) for u in users_col.find({}, {"referrals":1})])
    task_done = users_col.count_documents({"task_done": 1})
    text = (
        f"📊 SmartEarnBot Stats\n\n"
        f"👥 Total Users: {total_users:,}\n"
        f"✅ Task Done: {task_done:,}\n"
        f"💰 Total Balance Owed: N{total_balance:,}\n"
        f"👥 Total Refer
