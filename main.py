import os
import threading
from flask import Flask
from pymongo import MongoClient
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- FIX FOR RENDER WEB SERVICE HANG ---
web_app = Flask(__name__)
@web_app.route('/')
def home():
    return "Bot running with 7 channels - OK"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()
# --- END FIX ---

# --- SETTINGS ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
MIN_WITHDRAWAL = 50000
REF_BONUS = 1000
TASK_BONUS_PER_CHANNEL = 750

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

# --- DATABASE - PERMANENT MONGODB ---
client = MongoClient(MONGO_URL)
db = client["SmartEarnBot"]
users_col = db["users"]

def get_user(uid):
    user = users_col.find_one({"user_id": uid})
    if not user:
        new_user = {"user_id": uid, "balance": 0, "referrals": 0, "task_done": 0}
        users_col.insert_one(new_user)
        return 0, 0, 0
    return user.get("balance", 0), user.get("referrals", 0), user.get("task_done", 0)

main_keyboard = ReplyKeyboardMarkup([
    ["🔴 Balance", "🟢 Tasks"],
    ["🟣 Referrals", "🟠 Withdraw"]
], resize_keyboard=True)

async def check_joined(uid, context):
    not_joined = []
    for ch in CHECK_CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=ch, user_id=uid)
            if member.status in ['left', 'kicked']:
                not_joined.append(ch)
        except
