import os, asyncio, threading
from flask import Flask
from pymongo import MongoClient
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler

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
WITHDRAWAL_LIMIT = 50000

WITHDRAWAL_NOTICE = f"""
⚠️ WITHDRAWAL NOTICE ⚠️
Withdrawal will ONLY be successful once you reach N{WITHDRAWAL_LIMIT:,}.
If your balance is less than N{WITHDRAWAL_LIMIT:,}, you cannot withdraw.
"""

ADMIN_IDS = [8480726493]
BANK_NAME, ACCOUNT_NUMBER, ACCOUNT_NAME = range(3)

def get_user(uid):
    user = users_col.find_one({"user_id": uid})
    if not user:
        new_user = {
            "user_id": uid, 
            "balance": 0, 
            "referrals": 0, 
            "task_done": 0,
            "bank_name": None,
            "account_number": None,
            "account_name": None,
            "pending_amount": 0,
            "is_pending": 0
        }
        users_col.insert_one(new_user)
        return new_user
    if "bank_name" not in user:
        users_col.update_one({"user_id": uid}, {"$set": {
            "bank_name": None, "account_number": None, "account_name": None,
            "pending_amount": 0, "is_pending": 0
        }})
        return get_user(uid)
    return user

def is_admin(uid):
    return uid in ADMIN_IDS

main_keyboard = ReplyKeyboardMarkup([
    ["🔴 Balance", "🟢 Tasks"],
    ["🟣 Referrals", "🟠 Withdraw"],
    ["🏦 Set Bank"]
], resize_keyboard=True)

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

# --- Admin commands (same as yours) ---
async def count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    total_users = users_col.count_documents({})
    total_balance = sum([u.get('balance',0) for u in users_col.find({}, {"balance":1})])
    total_refs = sum([u.get('referrals',0) for u in users_col.find({}, {"referrals":1})])
    task_done = users_col.count_documents({"task_done": 1})
    pending = users_col.count_documents({"is_pending": 1})
    text = (
        "SmartEarnBot Stats\n\n"
        f"Total Users: {total_users:,}\n"
        f"Task Done: {task_done:,}\n"
        f"Pending Withdrawals: {pending:,}\n"
        f"Total Balance Owed: N{total_balance:,}\n"
        f"Total Referrals: {total_refs:,}\n\n"
        "Use /users to see list\n"
        "Use /paid <user_id> to mark as paid"
    )
    await update.message.reply_text(text)

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if context.args:
        try:
            search_id = int(context.args[0])
            user = users_col.find_one({"user_id": search_id})
            if not user:
                await update.message.reply_text(f"User {search_id} not found")
                return
            await update.message.reply_text(
                f"User: {user['user_id']}\n"
                f"Balance: N{user.get('balance',0):,}\n"
                f"Refs: {user.get('referrals',0)}\n"
                f"Task: {user.get('task_done',0)}\n"
                f"Bank: {user.get('bank_name')} - {user.get('account_number')}\n"
                f"Name: {user.get('account_name')}\n"
                f"Pending: {user.get('pending_amount',0)} - is_pending:{user.get('is_pending',0)}"
            )
            return
        except: pass
    users = list(users_col.find().sort("_id", -1).limit(20))
    total = users_col.count_documents({})
    text = f"Last 20 Users (Total: {total})\n\n"
    for i, u in enumerate(users, 1):
        text += f"{i}. {u['user_id']} - N{u.get('balance',0):,} - Refs:{u.get('referrals',0)} - Pending:{u.get('is_pending',0)}\n"
    text += "\nSend /users <user_id> to search"
    await update.message.reply_text(text)

async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text("Generating file...")
    users = list(users_col.find())
    csv_text = "user_id,balance,referrals,task_done,bank_name,account_number,account_name,pending_amount,is_pending\n"
    for u in users:
        csv_text += f"{u['user_id']},{u.get('balance',0)},{u.get('referrals',0)},{u.get('task_done',0)},{u.get('bank_name','')},{u.get('account_number','')},{u.get('account_name','')},{u.get('pending_amount',0)},{u.get('is_pending',0)}\n"
    with open("/tmp/users.csv", "w") as f:
        f.write(csv_text)
    await update.message.reply_document(document=open("/tmp/users.csv", "rb"), filename="SmartEarnBot_users.csv", caption=f"Total users: {len(users)}")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    reply_msg = update.message.reply_to_message
    args_text = " ".join(context.args) if context.args else ""
    if not reply_msg and not args_text:
        await update.message.reply_text("Usage:\n/broadcast Your message here\n\nOr reply to ANY message with /broadcast")
        return
    users = list(users_col.find({}, {"user_id": 1}))
    await update.message.reply_text(f"Broadcasting to {len(users)} users...")
    success = 0; failed = 0
    for u in users:
        try:
            if reply_msg:
                if reply_msg.photo:
                    cap = args_text or reply_msg.caption or ""
                    await context.bot.send_photo(chat_id=u["user_id"], photo=reply_msg.photo[-1].file_id, caption=cap)
                elif reply_msg.document:
                    cap = args_text or reply_msg.caption
