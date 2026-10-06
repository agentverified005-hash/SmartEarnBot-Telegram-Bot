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

ADMIN_IDS = [8480726493]

def get_user(uid):
    user = users_col.find_one({"user_id": uid})
    if not user:
        new_user = {"user_id": uid, "balance": 0, "referrals": 0, "task_done": 0}
        users_col.insert_one(new_user)
        return new_user
    return user

def is_admin(uid):
    return uid in ADMIN_IDS

main_keyboard = ReplyKeyboardMarkup([["\U0001f534 Balance", "\U0001f7e2 Tasks"],["\U0001f7e3 Referrals", "\U0001f7e0 Withdraw"]], resize_keyboard=True)

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
        "SmartEarnBot Stats\n\n"
        f"Total Users: {total_users:,}\n"
        f"Task Done: {task_done:,}\n"
        f"Total Balance Owed: N{total_balance:,}\n"
        f"Total Referrals: {total_refs:,}\n\n"
        "Use /users to see list\n"
        "Use /export to download CSV"
    )
    await update.message.reply_text(text)

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
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
                f"Task: {user.get('task_done',0)}"
            )
            return
        except:
            pass
    users = list(users_col.find().sort("_id", -1).limit(20))
    total = users_col.count_documents({})
    text = f"Last 20 Users (Total: {total})\n\n"
    for i, u in enumerate(users, 1):
        text += f"{i}. {u['user_id']} - N{u.get('balance',0):,} - Refs:{u.get('referrals',0)}\n"
    text += "\nSend /users <user_id> to search"
    await update.message.reply_text(text)

async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("Generating file...")
    users = list(users_col.find())
    csv_text = "user_id,balance,referrals,task_done\n"
    for u in users:
        csv_text += f"{u['user_id']},{u.get('balance',0)},{u.get('referrals',0)},{u.get('task_done',0)}\n"
    with open("/tmp/users.csv", "w") as f:
        f.write(csv_text)
    await update.message.reply_document(
        document=open("/tmp/users.csv", "rb"),
        filename="SmartEarnBot_users.csv",
        caption=f"Total users: {len(users)}"
    )

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    reply_msg = update.message.reply_to_message
    args_text = " ".join(context.args) if context.args else ""

    if not reply_msg and not args_text:
        await update.message.reply_text(
            "Usage:\n"
            "/broadcast Your message here\n\n"
            "Or reply to ANY message (photo, video, file, text) with /broadcast\n"
            "You can also do: Reply to photo with /broadcast Your caption"
        )
        return

    users = list(users_col.find({}, {"user_id": 1}))
    await update.message.reply_text(f"Broadcasting to {len(users)} users...")

    success = 0
    failed = 0

    for u in users:
        try:
            if reply_msg:
                if reply_msg.photo:
                    cap = args_text or reply_msg.caption or ""
                    await context.bot.send_photo(
                        chat_id=u["user_id"],
                        photo=reply_msg.photo[-1].file_id,
                        caption=cap
                    )
                elif reply_msg.document:
                    cap = args_text or reply_msg.caption or ""
                    await context.bot.send_document(
                        chat_id=u["user_id"],
                        document=reply_msg.document.file_id,
                        caption=cap
                    )
                elif reply_msg.video:
                    cap = args_text or reply_msg.caption or ""
                    await context.bot.send_video(
                        chat_id=u["user_id"],
                        video=reply_msg.video.file_id,
                        caption=cap
                    )
                elif reply_msg.text:
                    txt = args_text or reply_msg.text
                    await context.bot.send_message(chat_id=u["user_id"], text=txt)
                else:
                    await context.bot.copy_message(
                        chat_id=u["user_id"],
                        from_chat_id=update.effective_chat.id,
                        message_id=reply_msg.message_id
                    )
            else:
                await context.bot.send_message(chat_id=u["user_id"], text=args_text)

            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1

    await update.message.reply_text(f"Broadcast done\n\nSent: {success}\nFailed: {failed}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user(uid)
    if context.args:
        try:
            ref_id = int(context.args[0])
            if ref_id!= uid and users_col.find_one({"user_id": ref_id}):
                users_col.update_one({"user_id": ref_id}, {"$inc": {"balance": REF_BONUS, "referrals": 1}})
                await context.bot.send_message(chat_id=ref_id, text=f"You got N{REF_BONUS} referral bonus!")
        except: pass

    welcome_text = (
        f"Welcome!\n\n"
        f"Earn N{BONUS_PER_CHANNEL} per channel = N{TOTAL_BONUS} for all 7 channels\n"
        f"Referrals = N{REF_BONUS} per person\n"
        f"Min Withdraw = N{MIN_WITHDRAW:,}"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    user = get_user(uid)

    if text == "\U0001f534 Balance":
        bal = user.get('balance',0)
        need = MIN_WITHDRAW - bal
        if need < 0: need = 0
        msg = (
            f"Your Balance\n\n"
            f"Available: N{bal:,}\n"
            f"Refs: {user.get('referrals',0)}\n"
            f"Min: N{MIN_WITHDRAW:,}\n\n"
        )
        if bal < MIN_WITHDRAW:
            msg += f"You need N{need:,} more"
        else:
            msg += f"You can withdraw now!"
        await update.message.reply_text(msg)

    elif text == "\U0001f7e2 Tasks":
        task_text = (
            f"Daily Tasks - Earn N{TOTAL_BONUS:,}\n\n"
            f"We have 7 groups\n"
            f"Bonus: N{BONUS_PER_CHANNEL} per group\n"
            f"Total: N{TOTAL_BONUS:,}\n\n"
            f"How to claim:\n"
            f"1. Join all 7 channels below\n"
            f"2. Click Verify\n\n"
            f"Leave = bonus removed"
        )
        buttons = [[InlineKeyboardButton(f"Join {ch['name']} - N{BONUS_PER_CHANNEL}", url=ch['url'])] for ch in CHANNELS]
        buttons.append([InlineKeyboardButton(f"Verify & Claim N{TOTAL_BONUS}", callback_data="claim_task")])
        await update.message.reply_text(task_text, reply_markup=InlineKeyboardMarkup(buttons))

    elif text == "\U0001f7e3 Referrals":
        bot_user = await context.bot.get_me()
        link = f"https://t.me/{bot_user.username}?start={uid}"
        await update.message.reply_text(f"Referrals = N{REF_BONUS} per person\n\nYour link:\n{link}\n\nTotal Refs: {user.get('referrals',0)}")

    elif text == "\U0001f7e0 Withdraw":
        if user.get('balance',0) < MIN_WITHDRAW:
            await update.message.reply_text(f"Min Withdraw = N{MIN_WITHDRAW:,}. You have N{user.get('balance',0):,}")
        else:
            await update.message.reply_text(f"Withdrawal request of N{user.get('balance',0):,} received! Admin will pay soon.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)

    if query.data == "check_join" or query.data == "claim_task":
        not_joined = await check_joined(uid, context)
        if not_joined:
            await query.answer(f"Still not joined: {', '.join(not_joined)}", show_alert=True)
            return
        if user.get('task_done',0) == 1:
            await query.edit_message_text("Already claimed! You joined all channels before.")
            return

        users_col.update_one({"user_id": uid}, {"$set": {"task_done": 1}, "$inc": {"balance": TOTAL_BONUS}})
        await query.edit_message_text(
            f"Success! You joined all channels.\n\n"
            f"N{TOTAL_BONUS:,} (N{BONUS_PER_CHANNEL} x 7) added to your balance!"
        )

def main():
    threading.Thread(target=run_web, daemon=True).start()
    try: asyncio.get_event_loop()
    except RuntimeError: asyncio.set_event_loop(asyncio.new_event_loop())
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("count", count_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("subs", users_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
