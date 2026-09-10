import logging
import sqlite3
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# --- CONFIG ---
TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"
ADMIN_ID = 7077093393 # Your ID - Paschal

CHANNELS = [
    "@verifiedearners11",
    "@videoeditingclass11",
    "@jambextensivestudies1",
    "@payout112",
    "https://t.me/+_2kUihmFJcFjNzBk",
    "https://t.me/+hbE8ioZLCHc2OGRk",
    "https://t.me/+wGwfkO0m-fVjYjc0",
]

MIN_WITHDRAWAL = 50000
REF_BONUS = 1000
TASK_BONUS_PER_CHANNEL = 200

logging.basicConfig(level=logging.INFO)
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, referrals INTEGER DEFAULT 0, referred_by INTEGER DEFAULT NULL)")
conn.commit()

def get_user(user_id):
    cur.execute("SELECT balance, referrals FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row: return row[0], row[1]
    else:
        cur.execute("INSERT INTO users (user_id, balance, referrals) VALUES (?,?,?)", (user_id, 0, 0))
        conn.commit()
        return 0, 0

def add_referral(referrer_id):
    cur.execute("UPDATE users SET referrals = referrals + 1 WHERE user_id=?", (referrer_id,))
    cur.execute("UPDATE users SET balance = balance +? WHERE user_id=?", (REF_BONUS, referrer_id))
    conn.commit()

main_keyboard = ReplyKeyboardMarkup([["💰 Balance", "🏦 Withdraw"], ["👥 Referrals", "📝 Tasks"], ["📊 My Stats"]], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    exists = cur.fetchone()
    if not exists:
        referred_by = None
        if args and args[0].isdigit():
            referred_by = int(args[0])
            if referred_by!= user_id:
                cur.execute("SELECT user_id FROM users WHERE user_id=?", (referred_by,))
                if cur.fetchone():
                    add_referral(referred_by)
        cur.execute("INSERT INTO users (user_id, balance, referrals, referred_by) VALUES (?,?,?,?)", (user_id, 0, 0, referred_by))
        conn.commit()
    balance, referrals = get_user(user_id)
    await update.message.reply_text(f"👋 <b>Welcome!</b>\n\n<b>YOUR STATS:</b>\n• Balance: N{balance:,}\n• Referrals: {referrals}\n\n👇 Use menu.", parse_mode="HTML", reply_markup=main_keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    balance, referrals = get_user(user_id)

    if "Stats" in text:
        await update.message.reply_text(f"<b>YOUR STATS:</b>\n• Balance: N{balance:,}\n• Referrals: {referrals}", parse_mode="HTML", reply_markup=main_keyboard)

    elif "Balance" in text:
        status = "✅ <b>You can withdraw now!</b>" if balance >= MIN_WITHDRAWAL else f"❌ You need <b>N{MIN_WITHDRAWAL - balance:,.0f}</b> more."
        await update.message.reply_text(f"💰 <b>Your Balance</b>\n\n💵 Available: <b>N{balance:,.0f}</b>\n👥 Referrals: {referrals}\nMin: <b>N{MIN_WITHDRAWAL:,.0f}</b>\n\n{status}", parse_mode="HTML", reply_markup=main_keyboard)

    elif "Withdraw" in text:
        if balance >= MIN_WITHDRAWAL:
            await update.message.reply_text(f"🏦 <b>Withdrawal Request</b>\n\nBalance: <b>N{balance:,.0f}</b>\n✅ Eligible: YES\n\nSend bank details:\n<code>Bank - Account Number - Account Name</code>", parse_mode="HTML", reply_markup=main_keyboard)
        else:
            await update.message.reply_text(f"🔒 <b>Locked</b>\nBalance: N{balance:,.0f}\nMin: N{MIN_WITHDRAWAL:,.0f}\nNeed: N{MIN_WITHDRAWAL - balance:,.0f}\n\nDo Referrals (N1,000 each) and Tasks (N1,400)!", parse_mode="HTML", reply_markup=main_keyboard)

    elif "Referrals" in text:
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={user_id}"
        await update.message.reply_text(f"👥 <b>Referral - Earn N1,000!</b>\n\nYou will gain <b>N{REF_BONUS:,.0f}</b> instantly when anyone registers through you!\n\nReferrals: {referrals}\nEarned: N{referrals * REF_BONUS:,.0f}\n\nLink:\n<code>{link}</code>", parse_mode="HTML", reply_markup=main_keyboard)

    elif "Tasks" in text:
        total_bonus = len(CHANNELS) * TASK_BONUS_PER_CHANNEL
        await update.message.reply_text(f"📝 <b>Daily Tasks - Earn N{total_bonus:,.0f}</b>\n\nWe have {len(CHANNELS)} groups.\n💰 Bonus: N{TASK_BONUS_PER_CHANNEL} per group\n🎁 Total: N{total_bonus:,.0f} for all 7\n\n<b>Groups:</b>\n1. @verifiedearners11\n2. @videoeditingclass11\n3. @jambextensivestudies1\n4. @payout112\n5. https://t.me/+_2kUihmFJcFjNzBk\n6. https://t.me/+hbE8ioZLCHc2OGRk\n7. https://t.me/+wGwfkO0m-fVjYjc0\n\n1. Join all\n2. Click ✅ Verify", parse_mode="HTML", reply_markup=main_keyboard)
    else:
        if "-" in text and any(c.isdigit() for c in text):
            await update.message.reply_text(f"✅ Received! Amount N{balance:,} Details: {text}", parse_mode="HTML", reply_markup=main_keyboard)
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"💸 NEW WITHDRAWAL\nUser: {user_id}\nName: {update.effective_user.full_name}\nBalance: N{balance}\nDetails: {text}", parse_mode="HTML")
            except: pass

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
