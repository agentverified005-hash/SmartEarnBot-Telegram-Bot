import os, threading, time, sqlite3, re
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
TOKEN=(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_ID=int(os.getenv("ADMIN_ID") or "7077093393")
RAW=os.getenv("REQUIRED_CHANNEL_1","@verifiedearners11,@videoeditingclass11,@jambextensivestudies1,@payout112")
def clean(c):
    return c.replace("https://t.me/","").replace("t.me/","").replace("@","").split("/")[0].strip()
CHS=[clean(c.strip()) for c in re.split(r'[,;\s]+',RAW) if c.strip()]
print(f"TOKEN FOUND len={len(TOKEN)}")
print(f"ADMIN {ADMIN_ID} CHANNELS {CHS}")
DB="bot.db"
def init_db():
    conn=sqlite3.connect(DB)
    cur=conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0, referrals INTEGER DEFAULT 0, referred_by INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, status TEXT DEFAULT 'pending', account TEXT)")
    conn.commit()
    conn.close()
init_db()
def get_user(uid):
    conn=sqlite3.connect(DB)
    cur=conn.cursor()
    cur.execute("SELECT user_id,username,balance,referrals,referred_by FROM users WHERE user_id=?",(uid,))
    r=cur.fetchone()
    conn.close()
    return r
def add_user(uid,uname,ref=None):
    conn=sqlite3.connect(DB)
    cur=conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=?",(uid,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (user_id,username,balance,referrals,referred_by) VALUES (?,?,?,?,?)",(uid,uname,0,0,ref))
        if ref and ref!=uid:
            cur.execute("SELECT user_id FROM users WHERE user_id=?",(ref,))
            if cur.fetchone():
                cur.execute("UPDATE users SET balance=balance+1000,referrals=referrals+1 WHERE user_id=?",(ref,))
        conn.commit()
    conn.close()
async def check_joined(upd,ctx):
    uid=upd.effective_user.id
    nj=[]
    for ch in CHS:
        try:
            m=await ctx.bot.get_chat_member(f"@{ch}",uid)
            if m.status in ['left','kicked']:
                nj.append(ch)
        except:
            nj.append(ch)
    return nj
def join_kb(nj):
    btns=[]
    for ch in nj:
        btns.append([InlineKeyboardButton(f"Join @{ch}",url=f"https://t.me/{ch}")])
    btns.append([InlineKeyboardButton("I Joined Verify",callback_data="verify")])
    return InlineKeyboardMarkup(btns)
def main_kb(is_admin=False):
    kb=[[InlineKeyboardButton("Balance",callback_data="bal"),InlineKeyboardButton("Referrals",callback_data="ref")],[InlineKeyboardButton("Tasks",callback_data="tasks"),InlineKeyboardButton("Withdraw",callback_data="wd")],[InlineKeyboardButton("Support",url="https://t.me/smartearnsupport1")]]
    if is_admin:
        kb.append([InlineKeyboardButton("Admin Panel",callback_data="admin")])
    return InlineKeyboardMarkup(kb)
async def start(upd,ctx):
    u=upd.effective_user
    uname=u.username or u.first_name
    ref=None
    if ctx.args:
        try:
            ref=int(ctx.args[0])
        except:
            pass
    add_user(u.id,uname,ref)
    nj=await check_joined(upd,ctx)
    if nj:
        txt=f"Welcome {u.first_name}!\nEarn N1000 per referral\nMin Withdraw N1000\n\nYou must join:\n"+"\n".join([f"@{c}" for c in nj])
        await upd.message.reply_text(txt,reply_markup=join_kb(nj))
        return
    await upd.message.reply_text(f"Welcome {u.first_name}!\nBalance: Earn N1000 per referral\nChoose:",reply_markup=main_kb(u.id==ADMIN_ID))
async def btn(upd,ctx):
    q=upd.callback_query
    await q.answer()
    uid=q.from_user.id
    data=q.data
    row=get_user(uid)
    if not row:
        await q.message.reply_text("Send /start")
        return
    _,_,bal,refs,_=row
    is_admin=uid==ADMIN_ID
    if data=="verify":
        nj=await check_joined(upd,ctx)
        if nj:
            await q.edit_message_text("Still not joined:\n"+"\n".join([f"@{c}" for c in nj]),reply_markup=join_kb(nj))
        else:
            await q.edit_message_text(f"Verified! Balance N{bal} Refs {refs}",reply_markup=main_kb(is_admin))
    elif data=="bal":
        await q.edit_message_text(f"Balance: N{bal}\nReferrals: {refs}\nMin Withdraw N1000",reply_markup=main_kb(is_admin))
    elif data=="ref":
        bot=(await ctx.bot.get_me()).username
        link=f"https://t.me/{bot}?start={uid}"
        await q.edit_message_text(f"Your link:\n{link}\n\nRefs: {refs}\nEarnings: N{bal}\nN1000 per referral",reply_markup=main_kb(is_admin))
    elif data=="tasks":
        await q.edit_message_text("Tasks:\nJoin channels N500\nInvite 1 friend N1000",reply_markup=main_kb(is_admin))
    elif data=="wd":
        if bal<1000:
            await q.edit_message_text(f"Balance N{bal} too low. Min N1000",reply_markup=main_kb(is_admin))
        else:
            await q.edit_message_text(f"Balance N{bal}\nSend account like:\nOpay 9123456789 John",reply_markup=main_kb(is_admin))
            ctx.user_data['wd']=True
    elif data=="admin" and is_admin:
        conn=sqlite3.connect(DB)
        cur=conn.cursor()
        cur.execute("SELECT COUNT(*),SUM(balance) FROM users")
        c,t=cur.fetchone()
        conn.close()
        await q.edit_message_text(f"Admin\nUsers {c}\nTotal N{t}\n\n/stats /broadcast msg",reply_markup=main_kb(True))
async def msg(upd,ctx):
    if ctx.user_data.get('wd'):
        uid=upd.effective_user.id
        row=get_user(uid)
        if not row:
            return
        _,_,bal,_,_=row
        acc=upd.message.text
        conn=sqlite3.connect(DB)
        cur=conn.cursor()
        cur.execute("INSERT INTO withdrawals (user_id,amount,account) VALUES (?,?,?)",(uid,bal,acc))
        cur.execute("UPDATE users SET balance=0 WHERE user_id=?",(uid,))
        conn.commit()
        conn.close()
        await upd.message.reply_text(f"Withdrawal N{bal} submitted!\n{acc}\nAdmin will pay in 24h")
        try:
            await ctx.bot.send_message(ADMIN_ID,f"NEW WITHDRAWAL\nUser {uid} @{upd.effective_user.username}\nAmount N{bal}\nAccount {acc}")
        except:
            pass
        ctx.user_data['wd']=False
async def stats(upd,ctx):
    if upd.effective_user.id!=ADMIN_ID:
        return
    conn=sqlite3.connect(DB)
    cur=conn.cursor()
    cur.execute("SELECT COUNT(*),SUM(balance),SUM(referrals) FROM users")
    c,t,r=cur.fetchone()
    conn.close()
    await upd.message.reply_text(f"Users {c}\nTotal N{t}\nRefs {r}")
async def broadcast(upd,ctx):
    if upd.effective_user.id!=ADMIN_ID:
        return
    m=" ".join(ctx.args)
    if not m:
        await upd.message.reply_text("Use /broadcast msg")
        return
    conn=sqlite3.connect(DB)
    cur=conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users=cur.fetchall()
    conn.close()
    s=0
    for (uid,) in users:
        try:
            await ctx.bot.send_message(uid,f"Broadcast:\n\n{m}")
            s+=1
        except:
            pass
    await upd.message.reply_text(f"Sent {s}/{len(users)}")
app=Flask(__name__)
@app.route('/')
def home():
    return "Live",200
def run_web():
    app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
def main():
    if not TOKEN:
        print("TOKEN MISSING")
        while True:
            time.sleep(3600)
    threading.Thread(target=run_web,daemon=True).start()
    application=Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start",start))
    application.add_handler(CommandHandler("stats",stats))
    application.add_handler(CommandHandler("broadcast",broadcast))
    application.add_handler(CallbackQueryHandler(btn))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,msg))
    print(f"Polling {CHS}")
    application.run_polling()
if __name__=="__main__":
    main()
