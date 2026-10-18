import os
import asyncio
import threading
from flask import Flask
from pymongo import MongoClient
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler

# --- FLASK KEEP-ALIVE FOR RENDER WEB SERVICE ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): 
    return "Bot running - OK"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

# --- ENV ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")

# --- DB ---
if MONGO_URL:
    client = MongoClient(MONGO_URL)
    db = client["SmartEarnBot"]
    users_col = db["users"]
else:
    users_col = None

BONUS_PER_CHANNEL = 1000
TOTAL_BONUS = 7000
REF_BONUS = 1000
MIN_WITHDRAW = 50000
WITHDRAWAL_LIMIT = 50000

WITHDRAWAL_NOTICE = f"⚠️ WITHDRAWAL NOTICE ⚠️\nWithdrawal will ONLY be successful once you reach N{WITHDRAWAL_LIMIT:,}."

ADMIN_IDS = [8480726493]
BANK_NAME, ACCOUNT_NUMBER, ACCOUNT_NAME = range(3)

KEYBOARD_REGEX = r"^(🔴 Balance|🟢 Tasks|🟣 Referrals|🟠 Withdraw|🏦 Set Bank|/cancel)$"
NOT_KEYBOARD = filters.TEXT & ~filters.COMMAND & ~filters.Regex(KEYBOARD_REGEX)

def get_user(uid):
    user = users_col.find_one({"user_id": uid})
    if not user:
        new_user = {
            "user_id": uid, "balance": 0, "referrals": 0, "task_done": 0,
            "bank_name": None, "account_number": None, "account_name": None,
            "pending_amount": 0, "is_pending": 0
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

def is_admin(uid): return uid in ADMIN_IDS

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

# --- ADMIN ---
async def count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    total_users = users_col.count_documents({})
    total_balance = sum([u.get('balance',0) for u in users_col.find({}, {"balance":1})])
    text = f"Users: {total_users}\nBalance Owed: N{total_balance:,}"
    await update.message.reply_text(text)

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    users = list(users_col.find().sort("_id", -1).limit(20))
    total = users_col.count_documents({})
    text = f"Last 20 Users (Total: {total})\n\n"
    for i, u in enumerate(users, 1):
        text += f"{i}. {u['user_id']} - N{u.get('balance',0):,}\n"
    await update.message.reply_text(text)

async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text("Generating file...")
    users = list(users_col.find())
    csv_text = "user_id,balance,referrals,task_done,bank_name,account_number,account_name,pending_amount,is_pending\n"
    for u in users:
        csv_text += f"{u['user_id']},{u.get('balance',0)},{u.get('referrals',0)},{u.get('task_done',0)},{u.get('bank_name','')},{u.get('account_number','')},{u.get('account_name','')},{u.get('pending_amount',0)},{u.get('is_pending',0)}\n"
    with open("/tmp/users.csv", "w") as f: f.write(csv_text)
    await update.message.reply_document(document=open("/tmp/users.csv", "rb"), filename="users.csv")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    args_text = " ".join(context.args) if context.args else ""
    if not args_text and not update.message.reply_to_message:
        await update.message.reply_text("Usage: /broadcast Your message")
        return
    users = list(users_col.find({}, {"user_id": 1}))
    await update.message.reply_text(f"Broadcasting to {len(users)} users...")
    success=0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u["user_id"], text=args_text)
            success+=1
            await asyncio.sleep(0.05)
        except: pass
    await update.message.reply_text(f"Done. Sent: {success}")

async def paid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args: return
    uid = int(context.args[0])
    users_col.update_one({"user_id": uid}, {"$set": {"is_pending": 0, "pending_amount": 0}})
    await update.message.reply_text(f"User {uid} marked as paid")
    try: await context.bot.send_message(chat_id=uid, text=f"Your withdrawal of N{WITHDRAWAL_LIMIT:,} has been paid!")
    except: pass

# --- USER ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user(uid)
    if context.args:
        try:
            ref_id = int(context.args[0])
            if ref_id != uid and users_col.find_one({"user_id": ref_id}):
                users_col.update_one({"user_id": ref_id}, {"$inc": {"balance": REF_BONUS, "referrals": 1}})
                await context.bot.send_message(chat_id=ref_id, text=f"You got N{REF_BONUS} referral bonus!")
        except: pass
    await update.message.reply_text(
        f"Welcome!\nEarn N{TOTAL_BONUS} for tasks\nMin Withdraw N{MIN_WITHDRAW:,}\n\n{WITHDRAWAL_NOTICE}",
        reply_markup=main_keyboard
    )

async def set_bank_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏦 Set Bank\n\nSend your Bank Name (e.g Opay, Palmpay)\nSend /cancel to cancel")
    return BANK_NAME

async def receive_bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bank_name'] = update.message.text.strip()
    await update.message.reply_text("Now send your 10-digit Account Number (or /cancel):")
    return ACCOUNT_NUMBER

async def receive_account_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acc = update.message.text.strip()
    if not acc.isdigit() or len(acc) != 10:
        await update.message.reply_text("❌ Must be 10 digits. Send again or /cancel:")
        return ACCOUNT_NUMBER
    context.user_data['account_number'] = acc
    await update.message.reply_text("Last step: Send Account Name (or /cancel):")
    return ACCOUNT_NAME

async def receive_account_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bank_name = context.user_data['bank_name']
    acc_num = context.user_data['account_number']
    acc_name = update.message.text.strip()
    users_col.update_one({"user_id": update.effective_user.id}, {"$set": {
        "bank_name": bank_name, "account_number": acc_num, "account_name": acc_name
    }})
    await update.message.reply_text(f"✅ Bank Saved!\n{bank_name} - {acc_num}\n{acc_name}", reply_markup=main_keyboard)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=main_keyboard)
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text or ""
        uid = update.effective_user.id
        user = get_user(uid)

        if "Balance" in text:
            bal = user.get('balance',0)
            need = max(0, WITHDRAWAL_LIMIT - bal)
            msg = f"Your Balance\n\nAvailable: N{bal:,}\nRefs: {user.get('referrals',0)}\nNeed: N{need:,} more\n\n{WITHDRAWAL_NOTICE}"
            await update.message.reply_text(msg, reply_markup=main_keyboard)
            return

        if "Tasks" in text:
            if user.get('task_done'):
                await update.message.reply_text("You already completed tasks ✅", reply_markup=main_keyboard)
                return
            buttons = [[InlineKeyboardButton(f"Join {ch['name']}", url=ch['url'])] for ch in CHANNELS]
            buttons.append([InlineKeyboardButton("✅ I've Joined - Verify", callback_data="verify_join")])
            await update.message.reply_text(
                f"Join all {len(CHANNELS)} channels to earn N{TOTAL_BONUS}. After joining, click Verify.",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return

        if "Referrals" in text:
            bot_username = (await context.bot.get_me()).username
            link = f"https://t.me/{bot_username}?start={uid}"
            await update.message.reply_text(f"Your Referral Link\n{link}\nEarn N{REF_BONUS} per referral\nTotal: {user.get('referrals',0)}", reply_markup=main_keyboard)
            return

        if "Withdraw" in text:
            bal = user.get('balance', 0)
            if user.get('is_pending'):
                await update.message.reply_text(f"Pending withdrawal N{user.get('pending_amount',0):,} - wait for approval.", reply_markup=main_keyboard)
                return
            if bal < WITHDRAWAL_LIMIT:
                await update.message.reply_text(f"You need N{WITHDRAWAL_LIMIT:,} to withdraw. Your balance N{bal:,}", reply_markup=main_keyboard)
                return
            if not user.get('bank_name'):
                await update.message.reply_text("Set bank first: 🏦 Set Bank", reply_markup=main_keyboard)
                return
            users_col.update_one({"user_id": uid}, {"$set": {"is_pending": 1, "pending_amount": bal, "balance": 0}})
            await update.message.reply_text(f"Withdrawal request N{bal:,} submitted!", reply_markup=main_keyboard)
            for admin_id in ADMIN_IDS:
                try: await context.bot.send_message(chat_id=admin_id, text=f"NEW WITHDRAWAL\nUser {uid}\nAmount N{bal:,}\nBank {user.get('bank_name')} {user.get('account_number')}")
                except: pass
            return
    except Exception as e:
        print(f"Error in handle_message: {e}")

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    if user.get('task_done'):
        await query.edit_message_text("You already completed tasks ✅")
        return
    not_joined = await check_joined(uid, context)
    if not_joined:
        await query.edit_message_text(f"Not joined: {', '.join(not_joined)}\nJoin all and try again.")
        return
    users_col.update_one({"user_id": uid}, {"$set": {"task_done": 1}, "$inc": {"balance": TOTAL_BONUS}})
    await query.edit_message_text(f"Congratulations! You earned N{TOTAL_BONUS}")

def main():
    threading.Thread(target=run_web, daemon=True).start()

    # FIX FOR PYTHON 3.14 - This is what was crashing in your screenshot
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if not TOKEN or not MONGO_URL:
        print("FATAL: BOT_TOKEN or MONGO_URL not set in Render Environment Variables!")
        while True:
            import time; time.sleep(3600)

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏦 Set Bank$"), set_bank_start)],
        states={
            BANK_NAME: [MessageHandler(NOT_KEYBOARD, receive_bank_name)],
            ACCOUNT_NUMBER: [MessageHandler(NOT_KEYBOARD, receive_account_number)],
            ACCOUNT_NAME: [MessageHandler(NOT_KEYBOARD, receive_account_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(KEYBOARD_REGEX), cancel)],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("count", count_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("paid", paid_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(verify_callback, pattern="^verify_join$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot polling started - SmartEarnBot is LIVE")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
