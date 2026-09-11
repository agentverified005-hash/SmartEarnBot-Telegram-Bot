import os
import threading
import time
from flask import Flask
from pymongo import MongoClient
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- WEB SERVER FOR RENDER HEALTH CHECK ---
web_app = Flask(__name__)
@web_app.route('/')
def home():
    return "Bot running with 7 channels - OK"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    # use_reloader=False is CRITICAL or it crashes on Render
    web_app.run(host='0.0.0.0', port=port, use_reloader=False)

# --- SETTINGS ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")

if not TOKEN:
    print("FATAL: BOT_TOKEN not set in Render Env Vars")
    exit(1)
if not MONGO_URL:
    print("FATAL: MONGO_URL not set in Render Env Vars")
    exit(1)

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

# --- DATABASE ---
client = MongoClient(MONGO_URL)
db = client["SmartEarnBot"]
users_col = db["users"]

def get_user(uid):
    user = users_col.find_one({"user_id": uid})
    if not user:
        new_user = {"user_id": uid, "balance": 0, "referrals": 0, "task_done": 0}
        users_col.insert_one(new_user)
        return new_user
    return user

def update_balance(uid, amount):
    users_col.update_one({"user_id": uid}, {"$inc": {"balance": amount}}, upsert=True)

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
        except Exception:
            not_joined.append(ch)
    return not_joined

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if context.args:
        try:
            ref_id = int(context.args[0])
            if ref_id != uid and users_col.find_one({"user_id": ref_id}):
                update_balance(ref_id, REF_BONUS)
                users_col.update_one({"user_id": ref_id}, {"$inc": {"referrals": 1}})
        except:
            pass
    not_joined = await check_joined(uid, context)
    if not_joined:
        buttons = [[InlineKeyboardButton(f"Join {c}", url=f"https://t.me/{c.replace('@','')}")] for c in not_joined]
        buttons.append([InlineKeyboardButton("✅ I Have Joined", callback_data="check_join")])
        await update.message.reply_text(f"⚠️ You must join all channels to use this bot.\n\nYou haven't joined: {', '.join(not_joined)}", reply_markup=InlineKeyboardMarkup(buttons))
        return
    await update.message.reply_text(f"👋 Welcome to SmartEarn!\n\n💰 Balance: ₦{user.get('balance',0)}\n👥 Referrals: {user.get('referrals',0)}\n\nUse the menu below:", reply_markup=main_keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    user = get_user(uid)
    if text == "🔴 Balance":
        await update.message.reply_text(f"💰 Your Balance: ₦{user.get('balance',0)}\n\nMinimum withdrawal: ₦{MIN_WITHDRAWAL}")
    elif text == "🟢 Tasks":
        buttons = [[InlineKeyboardButton(ch['name'], url=ch['url'])] for ch in CHANNELS]
        buttons.append([InlineKeyboardButton("✅ Claim Task Bonus", callback_data="claim_task")])
        await update.message.reply_text(f"📢 Join all {len(CHANNELS)} channels and claim ₦{TASK_BONUS_PER_CHANNEL * len(CHECK_CHANNELS)}", reply_markup=InlineKeyboardMarkup(buttons))
    elif text == "🟣 Referrals":
        bot_user = await context.bot.get_me()
        link = f"https://t.me/{bot_user.username}?start={uid}"
        await update.message.reply_text(f"👥 Your Referral Link:\n{link}\n\nYou get ₦{REF_BONUS} per referral!\nTotal referrals: {user.get('referrals',0)}")
    elif text == "🟠 Withdraw":
        if user.get('balance',0) < MIN_WITHDRAWAL:
            await update.message.reply_text(f"❌ Minimum withdrawal is ₦{MIN_WITHDRAWAL}\nYour balance: ₦{user.get('balance',0)}")
        else:
            await update.message.reply_text(f"💸 Withdrawal request for ₦{user.get('balance',0)} received!\nContact admin.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if query.data == "check_join":
        not_joined = await check_joined(uid, context)
        if not_joined:
            await query.edit_message_text(f"❌ Still not joined: {', '.join(not_joined)}\nPlease join and click again.")
        else:
            user = get_user(uid)
            await query.edit_message_text(f"✅ All joined! Welcome.\nBalance: ₦{user.get('balance',0)}")
    elif query.data == "claim_task":
        not_joined = await check_joined(uid, context)
        if not_joined:
            await query.answer(f"You must join: {', '.join(not_joined)}", show_alert=True)
            return
        user = get_user(uid)
        if user.get('task_done',0) == 1:
            await query.answer("You already claimed this task!", show_alert=True)
            return
        bonus = TASK_BONUS_PER_CHANNEL * len(CHECK_CHANNELS)
        users_col.update_one({"user_id": uid}, {"$set": {"task_done": 1}, "$inc": {"balance": bonus}})
        await query.edit_message_text(f"🎉 Task completed! You received ₦{bonus}")

def main():
    # 1. Start Flask web server in background for Render health check
    threading.Thread(target=run_web, daemon=True).start()
    time.sleep(2) # give Flask time to bind port

    # 2. Start Telegram Bot in MAIN thread
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot is running with polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
