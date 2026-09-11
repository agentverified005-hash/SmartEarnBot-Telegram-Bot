import os
import asyncio
import threading
from flask import Flask
from pymongo import MongoClient
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- Flask keep-alive for Render ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): 
    return "Bot running - OK"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

# --- Config ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")

if not TOKEN or not MONGO_URL:
    raise ValueError("Set BOT_TOKEN and MONGO_URL in Render Environment")

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

main_keyboard = ReplyKeyboardMarkup([["🔴 Balance", "🟢 Tasks"],["🟣 Referrals", "🟠 Withdraw"]], resize_keyboard=True)
CHANNELS = [{"username": "@verifiedearners11", "url": "https://t.me/verifiedearners11", "name": "Verified Earners"},{"username": "@videoeditingclass11", "url": "https://t.me/videoeditingclass11", "name": "Video Editing Class"},{"username": "@jambextensivestudies1", "url": "https://t.me/jambextensivestudies1", "name": "JAMB Extensive Studies"},{"username": "@payout112", "url": "https://t.me/payout112", "name": "Payout Channel"},{"username": "@_2kUihmFJcFjNzBk", "url": "https://t.me/+_2kUihmFJcFjNzBk", "name": "VIP Group 1"},{"username": "@hbE8ioZLCHc2OGRk", "url": "https://t.me/+hbE8ioZLCHc2OGRk", "name": "VIP Group 2"},{"username": "@wGwfkO0m-fVjYjc0", "url": "https://t.me/+wGwfkO0m-fVjYjc0", "name": "VIP Group 3"}]
CHECK_CHANNELS = ["@verifiedearners11", "@videoeditingclass11", "@jambextensivestudies1", "@payout112"]

async def check_joined(uid, context):
    not_joined = []
    for ch in CHECK_CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=ch, user_id=uid)
            if member.status in ['left', 'kicked']: 
                not_joined.append(ch)
        except: 
            not_joined.append(ch)
    return not_joined

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if context.args:
        try:
            ref_id = int(context.args[0])
            if ref_id != uid and users_col.find_one({"user_id": ref_id}):
                update_balance(ref_id, 1000)
                users_col.update_one({"user_id": ref_id}, {"$inc": {"referrals": 1}})
        except: pass
    not_joined = await check_joined(uid, context)
    if not_joined:
        buttons = [[InlineKeyboardButton(f"Join {c}", url=f"https://t.me/{c.replace('@','')}")] for c in not_joined]
        buttons.append([InlineKeyboardButton("✅ I Have Joined", callback_data="check_join")])
        await update.message.reply_text(f"⚠️ Join all: {', '.join(not_joined)}", reply_markup=InlineKeyboardMarkup(buttons))
        return
    await update.message.reply_text(f"👋 Welcome! Balance: ₦{user.get('balance',0)}", reply_markup=main_keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    user = get_user(uid)
    if text == "🔴 Balance": await update.message.reply_text(f"💰 Balance: ₦{user.get('balance',0)}")
    elif text == "🟢 Tasks":
        buttons = [[InlineKeyboardButton(ch['name'], url=ch['url'])] for ch in CHANNELS]
        buttons.append([InlineKeyboardButton("✅ Claim Task Bonus", callback_data="claim_task")])
        await update.message.reply_text(f"📢 Join {len(CHANNELS)} channels", reply_markup=InlineKeyboardMarkup(buttons))
    elif text == "🟣 Referrals":
        bot_user = await context.bot.get_me()
        await update.message.reply_text(f"Link: https://t.me/{bot_user.username}?start={uid}\nReferrals: {user.get('referrals',0)}")
    elif text == "🟠 Withdraw":
        if user.get('balance',0) < 50000: await update.message.reply_text(f"Min ₦50000. You have ₦{user.get('balance',0)}")
        else: await update.message.reply_text(f"Withdrawal ₦{user.get('balance',0)} received!")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if query.data == "check_join":
        not_joined = await check_joined(uid, context)
        if not_joined: await query.edit_message_text(f"❌ Still not joined: {', '.join(not_joined)}")
        else:
            user = get_user(uid)
            await query.edit_message_text(f"✅ All joined! Balance: ₦{user.get('balance',0)}")
    elif query.data == "claim_task":
        not_joined = await check_joined(uid, context)
        if not_joined:
            await query.answer(f"Join: {', '.join(not_joined)}", show_alert=True)
            return
        user = get_user(uid)
        if user.get('task_done',0) == 1:
            await query.answer("Already claimed!", show_alert=True)
            return
        bonus = 750 * len(CHECK_CHANNELS)
        users_col.update_one({"user_id": uid}, {"$set": {"task_done": 1}, "$inc": {"balance": bonus}})
        await query.edit_message_text(f"🎉 You received ₦{bonus}")

def main():
    # 1. Start Flask in background
    threading.Thread(target=run_web, daemon=True).start()
    
    # 2. FIX for Python 3.14 on Render: create event loop explicitly
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot is running with polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": 
    main()
