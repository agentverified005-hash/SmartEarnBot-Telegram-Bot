import os
import sqlite3
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- SETTINGS ---
TOKEN = os.getenv("BOT_TOKEN")
MIN_WITHDRAWAL = 50000
REF_BONUS = 1000
TASK_BONUS_PER_CHANNEL = 200 # 200 x 7 = 1400
ADMIN_ID = 123456789 # Put your own Telegram ID here

# --- YOUR 7 CHANNELS FINAL ---
CHANNELS = [
    {"username": "@verifiedearners11", "url": "https://t.me/verifiedearners11", "name": "Verified Earners"},
    {"username": "@videoeditingclass11", "url": "https://t.me/videoeditingclass11", "name": "Video Editing Class"},
    {"username": "@jambextensivestudies1", "url": "https://t.me/jambextensivestudies1", "name": "JAMB Extensive Studies"},
    {"username": "@payout112", "url": "https://t.me/payout112", "name": "Payout Channel"},
    {"username": "@_2kUihmFJcFjNzBk", "url": "https://t.me/+_2kUihmFJcFjNzBk", "name": "VIP Group 1"},
    {"username": "@hbE8ioZLCHc2OGRk", "url": "https://t.me/+hbE8ioZLCHc2OGRk", "name": "VIP Group 2"},
    {"username": "@wGwfkO0m-fVjYjc0", "url": "https://t.me/+wGwfkO0m-fVjYjc0", "name": "VIP Group 3"},
]

# For checking, use only public usernames - private + links can't be checked by username
CHECK_CHANNELS = ["@verifiedearners11", "@videoeditingclass11", "@jambextensivestudies1", "@payout112"]

# --- DATABASE ---
conn = sqlite3.connect("users.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, referrals INTEGER DEFAULT 0, task_done INTEGER DEFAULT 0)")
conn.commit()

def get_user(uid):
    cur.execute("SELECT balance, referrals, task_done FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    if not r:
        cur.execute("INSERT INTO users (user_id, balance, referrals, task_done) VALUES (?, 0, 0, 0)", (uid,))
        conn.commit()
        return 0, 0, 0
    return r[0], r[1], r[2]

main_keyboard = ReplyKeyboardMarkup([
    ["💰 Balance", "📝 Tasks"],
    ["👥 Referrals", "🏦 Withdraw"]
], resize_keyboard=True)

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
    get_user(uid)
    if context.args and context.args[0].isdigit():
        ref_id = int(context.args[0])
        if ref_id!= uid:
            cur.execute("SELECT user_id FROM users WHERE user_id=?", (ref_id,))
            if cur.fetchone():
                cur.execute("UPDATE users SET balance = balance +?, referrals = referrals + 1 WHERE user_id=?", (REF_BONUS, ref_id))
                conn.commit()
                try:
                    await context.bot.send_message(ref_id, f"🎉 New referral! You gained N{REF_BONUS}!")
                except:
                    pass
    await update.message.reply_text(
        f"👋 Welcome!\n\n💰 Earn N{TASK_BONUS_PER_CHANNEL} per channel = N{len(CHANNELS)*TASK_BONUS_PER_CHANNEL} for all {len(CHANNELS)} channels\n👥 Referrals = N{REF_BONUS} per person\n🏦 Min Withdraw = N{MIN_WITHDRAWAL:,}",
        reply_markup=main_keyboard
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    balance, referrals, task_done = get_user(uid)

    if "Balance" in text:
        status = "✅ <b>You can withdraw now!</b>" if balance >= MIN_WITHDRAWAL else f"❌ You need <b>N{MIN_WITHDRAWAL - balance:,.0f}</b> more"
        await update.message.reply_text(f"💰 <b>Your Balance</b>\n\n💵 Available: <b>N{balance:,.0f}</b>\n👥 Refs: {referrals}\nMin: <b>N{MIN_WITHDRAWAL:,.0f}</b>\n\n{status}", parse_mode="HTML", reply_markup=main_keyboard)

    elif "Withdraw" in text:
        if balance >= MIN_WITHDRAWAL:
            await update.message.reply_text(f"🏦 <b>Withdraw - Eligible</b>\nBalance: <b>N{balance:,.0f}</b>\n\nSend:\n<code>Bank - Account Number - Name</code>\nExample: <code>OPay - 8101234567 - Paschal Obinna</code>", parse_mode="HTML", reply_markup=main_keyboard)
        else:
            await update.message.reply_text(f"🔒 <b>Locked</b>\nBalance N{balance:,.0f} / Min N{MIN_WITHDRAWAL:,}\nYou need N{MIN_WITHDRAWAL - balance:,.0f} more\n\nDo Tasks (N{len(CHANNELS)*TASK_BONUS_PER_CHANNEL}) + Referrals (N{REF_BONUS})", parse_mode="HTML", reply_markup=main_keyboard)

    elif "Referrals" in text:
        botname = (await context.bot.get_me()).username
        link = f"https://t.me/{botname}?start={uid}"
        await update.message.reply_text(f"👥 <b>Referral - You gain N{REF_BONUS}!</b>\n\nYou will gain <b>N{REF_BONUS:,.0f} if users register through you</b>\n\n👤 Your Referrals: <b>{referrals}</b>\n💰 Earned: <b>N{referrals*REF_BONUS:,.0f}</b>\n\n🔗 Your Link:\n<code>{link}</code>\n\n1. Share link\n2. Person starts bot\n3. You get N1000", parse_mode="HTML", reply_markup=main_keyboard)

    elif "Tasks" in text:
        total = len(CHANNELS) * TASK_BONUS_PER_CHANNEL
        buttons = []
        for ch in CHANNELS:
            buttons.append([InlineKeyboardButton(f"Join {ch['name']} - N{TASK_BONUS_PER_CHANNEL}", url=ch['url'])])
        buttons.append([InlineKeyboardButton(f"✅ Verify & Claim N{total}", callback_data="verify")])
        await update.message.reply_text(
            f"📝 <b>Daily Tasks - Earn N{total:,.0f}</b>\n\nWe have <b>{len(CHANNELS)} groups</b>\n💰 Bonus: <b>N{TASK_BONUS_PER_CHANNEL} per group</b>\n🎁 Total: <b>N{total:,.0f}</b>\n\nHow to claim:\n1. Join all {len(CHANNELS)} channels below\n2. Click ✅ Verify\n\n⚠️ Leave = bonus removed",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()
    balance, referrals, task_done = get_user(uid)

    if task_done == 1:
        await query.edit_message_text("✅ You already claimed N1400 task bonus!")
        return

    not_joined = await check_joined(uid, context)
    if not_joined:
        await query.edit_message_text(f"❌ Not completed!\n\nYou haven't joined: {', '.join(not_joined)}\n\nJoin all 4 public channels first then click Verify again.\n\n(Private + links will be added after you make them public or give me their -100 IDs)")
        return

    total = len(CHANNELS) * TASK_BONUS_PER_CHANNEL
    cur.execute("UPDATE users SET balance = balance +?, task_done = 1 WHERE user_id=?", (total, uid))
    conn.commit()
    await query.edit_message_text(f"🎉 Success! You joined all channels.\n\n💰 N{total:,.0f} (N{TASK_BONUS_PER_CHANNEL} x {len(CHANNELS)}) added to your balance!")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(verify_callback, pattern="verify"))
    print("Bot running with 7 channels...")
    app.run_polling()

if __name__ == "__main__":
    main()
