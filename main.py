import os, threading, time
from flask import Flask
from telegram.ext import Application, CommandHandler
from telegram import Update
from telegram.ext import ContextTypes

TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_ID = os.getenv("ADMIN_ID")
CH1 = os.getenv("REQUIRED_CHANNEL_1")
CH2 = os.getenv("REQUIRED_CHANNEL_2")

print(f"TOKEN CHECK: {'FOUND len='+str(len(TOKEN)) if TOKEN else 'MISSING'}")
print(f"ADMIN_ID: {ADMIN_ID}")
print(f"CH1: {CH1} | CH2: {CH2}")

app = Flask(__name__)
@app.route('/')
def home(): return "SmartEarnBot Live - Bot polling active", 200

def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

threading.Thread(target=run_web, daemon=True).start()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"✅ SmartEarnBot is ONLINE!\nAdmin: {ADMIN_ID}\nForce Join: {CH1}, {CH2}")

def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN env missing!")
        while True: time.sleep(3600)
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    print("Starting polling... Send /start to your bot now")
    application.run_polling()

if __name__ == "__main__":
    main()
