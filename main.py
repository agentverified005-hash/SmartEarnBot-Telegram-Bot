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

def get_user(uid):
    user = users_col.find_one({"user_id": uid})
    if not user:
        new_user = {"user_id": uid, "balance": 0, "referrals": 0, "task_done": 0}
        users_col.insert_one(new_user)
        return new_user
    return user

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user(uid)
    if context.args:
        try:
            ref_id = int(context.args[0])
            if ref_id!= uid and users_col.find_one({"user_id": ref_id}):
                users_col.update_one({"user_id": ref_id}, {"$inc": {"balance": REF_BONUS, "referrals": 1}})
                await context.bot.send_message(chat_id=ref_id, text=f"🎉 You got N{REF_BONUS} referral bonus!")
        except: pass

    # THIS IS YOUR OLD WELCOME YOU LIKE
    welcome_text = (
        f"👋 Welcome!\n\n"
        f"💰 Earn N{BONUS_PER_CHANNEL} per channel = N{TOTAL_BONUS} for all 7 channels\n"
        f"👥 Referrals = N{REF_BONUS} per person\n"
        f"🏦 Min Withdraw = N{MIN_WITHDRAW:,}"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    user = get_user(uid)

    if text == "🔴 Balance":
        bal = user.get('balance',0)
        need = MIN_WITHDRAW - bal
        if need < 0: need = 0
        msg = (
            f"💰 Your Balance\n\n"
            f"💵 Available: N{bal:,}\n"
            f"👥 Refs: {user.get('referrals',0)}\n"
            f"Min: N{MIN_WITHDRAW:,}\n\n"
        )
        if bal < MIN_WITHDRAW:
            msg += f"❌ You need N{need:,} more"
        else:
            msg += f"✅ You can withdraw now!"
        await update.message.reply_text(msg)

    elif text == "🟢 Tasks":
        # THIS IS YOUR OLD DAILY TASKS YOU LIKE
        task_text = (
            f"📝 Daily Tasks - Earn N{TOTAL_BONUS:,}\n\n"
            f"We have 7 groups\n"
            f"💰 Bonus: N{BONUS_PER_CHANNEL} per group\n"
            f"🎁 Total: N{TOTAL_BONUS:,}\n\n"
            f"How to claim:\n"
            f"1. Join all 7 channels below\n"
            f"2. Click ✅ Verify\n\n"
            f"⚠️ Leave = bonus removed"
        )
        buttons = [[InlineKeyboardButton(f"Join {ch['name']} - N{BONUS_PER_CHANNEL}", url=ch['url'])] for ch in CHANNELS]
        buttons.append([InlineKeyboardButton(f"✅ Verify & Claim N{TOTAL_BONUS}", callback_data="claim_task")])
        await update.message.reply_text(task_text, reply_markup=InlineKeyboardMarkup(buttons))

    elif text == "🟣 Referrals":
        bot_user = await context.bot.get_me()
        link = f"https://t.me/{bot_user.username}?start={uid}"
        await update.message.reply_text(f"👥 Referrals = N{REF_BONUS} per person\n\nYour link:\n{link}\n\nTotal Refs: {user.get('referrals',0)}")

    elif text == "🟠 Withdraw":
        if user.get('balance',0) < MIN_WITHDRAW:
            await update.message.reply_text(f"Min Withdraw = N{MIN_WITHDRAW:,}. You have N{user.get('balance',0):,}")
        else:
            await update.message.reply_text(f"✅ Withdrawal request of N{user.get('balance',0):,} received! Admin will pay soon.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)

    if query.data == "check_join" or query.data == "claim_task":
        not_joined = await check_joined(uid, context)
        if not_joined:
            await query.answer(f"❌ Still not joined: {', '.join(not_joined)}", show_alert=True)
            return
        if user.get('task_done',0) == 1:
            await query.edit_message_text("⚠️ Already claimed! You joined all channels before.")
            return

        users_col.update_one({"user_id": uid}, {"$set": {"task_done": 1}, "$inc": {"balance": TOTAL_BONUS}})
        # THIS IS YOUR SUCCESS MESSAGE YOU LIKE
        await query.edit_message_text(
            f"🎉 Success! You joined all channels.\n\n"
            f"💰 N{TOTAL_BONUS:,} (N{BONUS_PER_CHANNEL} x 7) added to your balance!"
        )

def main():
    threading.Thread(target=run_web, daemon=True).start()
    try: asyncio.get_event_loop()
    except RuntimeError: asyncio.set_event_loop(asyncio.new_event_loop())
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot running with old settings restored...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
