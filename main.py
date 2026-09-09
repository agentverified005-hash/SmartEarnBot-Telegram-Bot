 from __future__ import annotations
"""SmartEarnBot- a small Telegram earning and referral bot.

Install the dependency with:

    pip install python-telegram-bot

Required environment variable:

    TELEGRAM_BOT_TOKEN=your-token

Optional environment variables:

    REQUIRED_CHANNELS=@channel_one,@channel_two,@channel_three
    REQUIRED_CHANNEL_URLS=https://t.me/channel_one,https://t.me/channel_two,https://t.me/channel_three
    ADMIN_IDS=123456789,987654321
    DATABASE_PATH=smartearnbot.db
    MINING_REWARD=500
    MINING_COOLDOWN_SECONDS=3600
    MINIMUM_WITHDRAWAL=5000

The bot uses Telegram long polling and stores all application data in SQLite.
No token or other credential is hard-coded in this file.
"""

from flask import Flask
import threading
import os



import logging

import sqlite3

import time
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or ""
DATABASE_PATH = os.getenv("DATABASE_PATH", "smartearnbot.db").strip()

# REQUIRED_CHANNELS / REQUIRED_CHANNEL_URLS are comma-separated. The older
# singular variables remain supported for simple one-channel deployments.
REQUIRED_CHANNELS = [
    value.strip()
    for value in os.getenv("REQUIRED_CHANNELS", "").split(",")
    if value.strip()
]
if not REQUIRED_CHANNELS:
    legacy_channel = os.getenv("REQUIRED_CHANNEL", "").strip()
    if legacy_channel:
        REQUIRED_CHANNELS = [legacy_channel]

REQUIRED_CHANNEL_URLS = [
    value.strip()
    for value in os.getenv("REQUIRED_CHANNEL_URLS", "").split(",")
    if value.strip()
]
if not REQUIRED_CHANNEL_URLS:
    legacy_channel_url = os.getenv("REQUIRED_CHANNEL_URL", "").strip()
    if legacy_channel_url:
        REQUIRED_CHANNEL_URLS = [legacy_channel_url]

MINING_REWARD = max(1, int(os.getenv("MINING_REWARD", "500")))
MINING_COOLDOWN_SECONDS = max(
    60, int(os.getenv("MINING_COOLDOWN_SECONDS", "3600"))
)
MINIMUM_WITHDRAWAL = max(
    1, int(os.getenv("MINIMUM_WITHDRAWAL", "5000"))
)

ADMIN_IDS: set[int] = set()
for raw_admin_id in os.getenv("ADMIN_IDS", "").split(","):
    raw_admin_id = raw_admin_id.strip()
    if raw_admin_id:
        try:
            ADMIN_IDS.add(int(raw_admin_id))
        except ValueError:
            logging.warning("Ignoring invalid ADMIN_IDS value: %s", raw_admin_id)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("smartearnbot")
# HTTPX logs full request URLs; Telegram bot URLs contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# SQLite connections are protected because Telegram handlers can run in
# different asyncio tasks while sharing one process.
DB = sqlite3.connect(
    DATABASE_PATH,
    check_same_thread=False,
)
DB.row_factory = sqlite3.Row
DB_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def initialize_database() -> None:
    """Create the database schema and a few useful starter tasks."""
    with DB_LOCK:
        DB.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT NOT NULL DEFAULT '',
                referred_by INTEGER,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                last_mined_at INTEGER,
                FOREIGN KEY (referred_by) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS balances (
                user_id INTEGER PRIMARY KEY,
                amount INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (referrer_id) REFERENCES users(user_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (referred_id) REFERENCES users(user_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS mining (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                reward INTEGER NOT NULL,
                mined_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                processed_at INTEGER,
                processed_by INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                reward INTEGER NOT NULL,
                task_type TEXT NOT NULL,
                target INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS task_claims (
                user_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                claimed_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, task_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
                    ON DELETE CASCADE
            );
            """
        )

        starter_tasks = [
            (
                "Join the community channel",
                "Join the required channel and verify your membership.",
                25,
                "channel",
                1,
            ),
            (
                "Invite 3 friends",
                "Invite three friends using your personal referral link.",
                100,
                "referrals",
                3,
            ),
        ]
        for task in starter_tasks:
            DB.execute(
                """
                INSERT INTO tasks (
                    title, description, reward, task_type, target
                )
                SELECT ?, ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM tasks WHERE task_type = ?
                )
                """,
                (*task, task[3]),
            )
        DB.commit()


def ensure_user(user: Any, referrer_id: int | None = None) -> None:
    """Create or refresh a user and optionally record a valid referral."""
    now = int(time.time())
    user_id = int(user.id)

    with DB_LOCK:
        DB.execute(
            """
            INSERT INTO users (
                user_id, username, first_name, created_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_seen_at = excluded.last_seen_at
            """,
            (
                user_id,
                user.username or "",
                user.first_name or "",
                now,
                now,
            ),
        )
        DB.execute(
            "INSERT OR IGNORE INTO balances (user_id, amount) VALUES (?, 0)",
            (user_id,),
        )

        if referrer_id and referrer_id != user_id:
            referrer_exists = DB.execute(
                "SELECT 1 FROM users WHERE user_id = ?",
                (referrer_id,),
            ).fetchone()
            current_referrer = DB.execute(
                "SELECT referred_by FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if referrer_exists and current_referrer["referred_by"] is None:
                DB.execute(
                    "UPDATE users SET referred_by = ? WHERE user_id = ?",
                    (referrer_id, user_id),
                )
                DB.execute(
                    """
                    INSERT OR IGNORE INTO referrals (
                        referrer_id, referred_id, created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (referrer_id, user_id, now),
                )
        DB.commit()


def get_balance(user_id: int) -> int:
    with DB_LOCK:
        row = DB.execute(
            "SELECT amount FROM balances WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return int(row["amount"]) if row else 0


def change_balance(user_id: int, amount: int) -> int | None:
    """Adjust a balance and return the new amount, or None if no user exists."""
    with DB_LOCK:
        row = DB.execute(
            "SELECT amount FROM balances WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        DB.execute(
            "UPDATE balances SET amount = amount + ? WHERE user_id = ?",
            (amount, user_id),
        )
        DB.commit()
        return int(row["amount"]) + amount


def referral_count(user_id: int) -> int:
    with DB_LOCK:
        row = DB.execute(
            "SELECT COUNT(*) AS total FROM referrals WHERE referrer_id = ?",
            (user_id,),
        ).fetchone()
    return int(row["total"])


def mine_for_user(user_id: int) -> tuple[bool, int, int]:
    """Mine once if the cooldown has elapsed.

    Returns (success, reward-or-zero, seconds-remaining).
    """
    now = int(time.time())
    with DB_LOCK:
        row = DB.execute(
            "SELECT last_mined_at FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return False, 0, 0

        last_mined_at = row["last_mined_at"]
        if last_mined_at is not None:
            elapsed = now - int(last_mined_at)
            if elapsed < MINING_COOLDOWN_SECONDS:
                return (
                    False,
                    0,
                    MINING_COOLDOWN_SECONDS - elapsed,
                )

        DB.execute(
            "UPDATE users SET last_mined_at = ? WHERE user_id = ?",
            (now, user_id),
        )
        DB.execute(
            """
            INSERT INTO mining (user_id, reward, mined_at)
            VALUES (?, ?, ?)
            """,
            (user_id, MINING_REWARD, now),
        )
        DB.execute(
            "UPDATE balances SET amount = amount + ? WHERE user_id = ?",
            (MINING_REWARD, user_id),
        )
        DB.commit()
    return True, MINING_REWARD, 0


def get_tasks() -> list[sqlite3.Row]:
    with DB_LOCK:
        return DB.execute(
            "SELECT * FROM tasks WHERE active = 1 ORDER BY id"
        ).fetchall()


def task_is_claimed(user_id: int, task_id: int) -> bool:
    with DB_LOCK:
        row = DB.execute(
            """
            SELECT 1 FROM task_claims
            WHERE user_id = ? AND task_id = ?
            """,
            (user_id, task_id),
        ).fetchone()
    return row is not None


def claim_task(user_id: int, task_id: int) -> bool:
    """Record a claim and pay the task reward exactly once."""
    now = int(time.time())
    with DB_LOCK:
        task = DB.execute(
            "SELECT reward FROM tasks WHERE id = ? AND active = 1",
            (task_id,),
        ).fetchone()
        if task is None:
            return False
        try:
            DB.execute(
                """
                INSERT INTO task_claims (user_id, task_id, claimed_at)
                VALUES (?, ?, ?)
                """,
                (user_id, task_id, now),
            )
        except sqlite3.IntegrityError:
            return False
        DB.execute(
            "UPDATE balances SET amount = amount + ? WHERE user_id = ?",
            (int(task["reward"]), user_id),
        )
        DB.commit()
    return True


def create_withdrawal(user_id: int, amount: int) -> tuple[int | None, str]:
    """Deduct funds and create a pending withdrawal atomically."""
    if amount < MINIMUM_WITHDRAWAL:
        return None, f"The minimum withdrawal is {MINIMUM_WITHDRAWAL:,} coins."

    now = int(time.time())
    with DB_LOCK:
        row = DB.execute(
            "SELECT amount FROM balances WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None, "Your account could not be found."
        if int(row["amount"]) < amount:
            return None, "You do not have enough coins for that withdrawal."

        balance_update = DB.execute(
            """
            UPDATE balances
            SET amount = amount - ?
            WHERE user_id = ? AND amount >= ?
            """,
            (amount, user_id, amount),
        )
        if balance_update.rowcount != 1:
            DB.rollback()
            return None, "Your balance changed. Please try again."

        cursor = DB.execute(
            """
            INSERT INTO withdrawals (user_id, amount, created_at)
            VALUES (?, ?, ?)
            """,
            (user_id, amount, now),
        )
        withdrawal_id = int(cursor.lastrowid)
        DB.commit()
    return withdrawal_id, ""


def pending_withdrawals(limit: int = 10) -> list[sqlite3.Row]:
    with DB_LOCK:
        return DB.execute(
            """
            SELECT w.*, u.username, u.first_name
            FROM withdrawals AS w
            JOIN users AS u ON u.user_id = w.user_id
            WHERE w.status = 'pending'
            ORDER BY w.created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def approve_withdrawal(withdrawal_id: int, admin_id: int) -> sqlite3.Row | None:
    with DB_LOCK:
        row = DB.execute(
            """
            SELECT * FROM withdrawals
            WHERE id = ? AND status = 'pending'
            """,
            (withdrawal_id,),
        ).fetchone()
        if row is None:
            return None
        DB.execute(
            """
            UPDATE withdrawals
            SET status = 'approved', processed_at = ?, processed_by = ?
            WHERE id = ? AND status = 'pending'
            """,
            (int(time.time()), admin_id, withdrawal_id),
        )
        DB.commit()
    return row


def reject_withdrawal(withdrawal_id: int, admin_id: int) -> sqlite3.Row | None:
    """Reject a withdrawal and refund its deducted amount."""
    with DB_LOCK:
        row = DB.execute(
            """
            SELECT * FROM withdrawals
            WHERE id = ? AND status = 'pending'
            """,
            (withdrawal_id,),
        ).fetchone()
        if row is None:
            return None
        DB.execute(
            """
            UPDATE withdrawals
            SET status = 'rejected', processed_at = ?, processed_by = ?
            WHERE id = ? AND status = 'pending'
            """,
            (int(time.time()), admin_id, withdrawal_id),
        )
        DB.execute(
            """
            UPDATE balances SET amount = amount + ? WHERE user_id = ?
            """,
            (int(row["amount"]), int(row["user_id"])),
        )
        DB.commit()
    return row


# ---------------------------------------------------------------------------
# Telegram presentation helpers
# ---------------------------------------------------------------------------

def format_duration(seconds: int) -> str:
    minutes, remaining_seconds = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {remaining_seconds}s"
    return f"{remaining_seconds}s"


def channel_urls() -> list[str]:
    """Return configured URLs, deriving public links where possible."""
    urls: list[str] = []
    for index, channel in enumerate(REQUIRED_CHANNELS):
        if index < len(REQUIRED_CHANNEL_URLS):
            urls.append(REQUIRED_CHANNEL_URLS[index])
        elif channel.startswith("@"):
            urls.append(f"https://t.me/{channel[1:]}")
        else:
            urls.append("")
    return urls


def membership_keyboard() -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for index, url in enumerate(channel_urls(), start=1):
        if url:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"📣 Join channel {index}",
                        url=url,
                    )
                ]
            )
    buttons.append(
        [InlineKeyboardButton("✅ Verify membership", callback_data="verify")]
    )
    return InlineKeyboardMarkup(buttons)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⛏️ Mine", callback_data="mine"),
                InlineKeyboardButton("💰 Balance", callback_data="balance"),
            ],
            [
                InlineKeyboardButton("✅ Tasks", callback_data="tasks"),
                InlineKeyboardButton("👥 Referrals", callback_data="referrals"),
            ],
            [
                InlineKeyboardButton("💸 Withdraw", callback_data="withdraw"),
                InlineKeyboardButton("ℹ️ Help", callback_data="help"),
            ],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Main menu", callback_data="home")]]
    )


def membership_text() -> str:
    if len(REQUIRED_CHANNELS) > 1:
        channel_name = "all required channels"
    elif REQUIRED_CHANNELS:
        channel_name = REQUIRED_CHANNELS[0]
    else:
        channel_name = "the required channel"
    return (
        "🔐 <b>One quick step</b>\n\n"
        f"Join {channel_name}, then tap <b>Verify membership</b> to unlock "
        "SmartEarnBot."
    )


def main_menu_text(user_id: int) -> str:
    return (
        "🏠 <b>SmartEarnBot</b>\n\n"
        "Choose an option below to start earning coins.\n\n"
        f"💰 Balance: <b>{get_balance(user_id):,}</b> coins"
    )


async def is_channel_member(
    bot: Any,
    user_id: int,
) -> bool:
    """Check membership when a channel is configured.

    If REQUIRED_CHANNELS is empty, membership verification is intentionally
    disabled so the bot remains runnable before deployment configuration.
    """
    if not REQUIRED_CHANNELS:
        return True
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(
                chat_id=channel,
                user_id=user_id,
            )
            if member.status not in {"member", "administrator", "creator"}:
                return False
        except TelegramError as error:
            logger.warning(
                "Membership check failed for %s in %s: %s",
                user_id,
                channel,
                error,
            )
            return False
    return True


async def send_membership_gate(
    update: Update,
) -> None:
    text = membership_text()
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=membership_keyboard(),
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text=text,
            parse_mode="HTML",
            reply_markup=membership_keyboard(),
        )


async def send_main_menu(
    update: Update,
    user_id: int,
    edit: bool = False,
) -> None:
    text = main_menu_text(user_id)
    markup = main_menu_keyboard()
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
        )


async def require_membership(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    user = update.effective_user
    if user is None:
        return False
    if await is_channel_member(context.bot, user.id):
        return True
    await send_membership_gate(update)
    return False


# ---------------------------------------------------------------------------
# User commands and menu actions
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return

    referrer_id: int | None = None
    if context.args:
        referral_code = context.args[0].strip()
        if referral_code.startswith("ref_"):
            try:
                referrer_id = int(referral_code.removeprefix("ref_"))
            except ValueError:
                referrer_id = None

    ensure_user(update.effective_user, referrer_id)
    if not await require_membership(update, context):
        return
    await send_main_menu(update, update.effective_user.id)


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_user is None:
        return
    ensure_user(update.effective_user)
    if not await require_membership(update, context):
        return
    await send_help(update, edit=False)


async def send_help(update: Update, edit: bool = True) -> None:
    text = (
        "ℹ️ <b>SmartEarnBot help</b>\n\n"
        "⛏️ <b>Mine</b> — collect coins after the cooldown ends.\n"
        "💰 <b>Balance</b> — view your current balance.\n"
        "✅ <b>Tasks</b> — complete available tasks for extra coins.\n"
        "👥 <b>Referrals</b> — invite friends and earn referral rewards.\n"
        "💸 <b>Withdraw</b> — submit a withdrawal request when you "
        f"reach {MINIMUM_WITHDRAWAL:,} coins.\n\n"
        "Use the buttons below to navigate."
    )
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=back_keyboard(),
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text=text,
            parse_mode="HTML",
            reply_markup=back_keyboard(),
        )


async def handle_mine(update: Update) -> None:
    query = update.callback_query
    user_id = update.effective_user.id  # type: ignore[union-attr]
    success, reward, remaining = mine_for_user(user_id)
    if success:
        text = (
            "⛏️ <b>Mining complete!</b>\n\n"
            f"You earned <b>+{reward:,}</b> coins.\n"
            f"New balance: <b>{get_balance(user_id):,}</b> coins.\n\n"
            f"Come back in {format_duration(MINING_COOLDOWN_SECONDS)}."
        )
    else:
        text = (
            "⏳ <b>Mining is cooling down</b>\n\n"
            f"Try again in <b>{format_duration(remaining)}</b>."
        )
    await query.edit_message_text(  # type: ignore[union-attr]
        text=text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


async def handle_balance(update: Update) -> None:
    query = update.callback_query
    user_id = update.effective_user.id  # type: ignore[union-attr]
    text = (
        "💰 <b>Your balance</b>\n\n"
        f"<b>{get_balance(user_id):,}</b> coins\n\n"
        "Keep mining and completing tasks to grow your balance."
    )
    await query.edit_message_text(  # type: ignore[union-attr]
        text=text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


async def handle_tasks(update: Update) -> None:
    query = update.callback_query
    user_id = update.effective_user.id  # type: ignore[union-attr]
    tasks = get_tasks()
    lines = ["✅ <b>Tasks</b>\n"]
    buttons: list[list[InlineKeyboardButton]] = []

    for task in tasks:
        claimed = task_is_claimed(user_id, int(task["id"]))
        status = "✅ Completed" if claimed else f"🎁 +{task['reward']:,} coins"
        lines.append(
            f"<b>{task['title']}</b>\n"
            f"{task['description']}\n"
            f"{status}\n"
        )
        if not claimed:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"Claim: {task['title']}",
                        callback_data=f"task:{task['id']}",
                    )
                ]
            )

    if not tasks:
        lines.append("There are no active tasks right now.")
    buttons.append(
        [InlineKeyboardButton("⬅️ Main menu", callback_data="home")]
    )
    await query.edit_message_text(  # type: ignore[union-attr]
        text="\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_task_claim(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    task_id: int,
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id  # type: ignore[union-attr]

    with DB_LOCK:
        task = DB.execute(
            "SELECT * FROM tasks WHERE id = ? AND active = 1",
            (task_id,),
        ).fetchone()

    if task is None:
        await query.answer("That task is no longer available.", show_alert=True)
        return
    if task_is_claimed(user_id, task_id):
        await query.answer("You already claimed this task.", show_alert=True)
        return

    eligible = False
    if task["task_type"] == "channel":
        eligible = await is_channel_member(context.bot, user_id)
    elif task["task_type"] == "referrals":
        eligible = referral_count(user_id) >= int(task["target"])

    if not eligible:
        if task["task_type"] == "channel":
            await query.answer(
                "Join the required channel first, then verify.",
                show_alert=True,
            )
        else:
            await query.answer(
                f"You need {task['target']} referrals to claim this task.",
                show_alert=True,
            )
        return

    if not claim_task(user_id, task_id):
        await query.answer("This task was already claimed.", show_alert=True)
        return

    await query.answer("Task reward added!")
    await query.edit_message_text(
        text=(
            "🎉 <b>Task completed!</b>\n\n"
            f"You earned <b>+{task['reward']:,}</b> coins.\n"
            f"New balance: <b>{get_balance(user_id):,}</b> coins."
        ),
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


async def handle_referrals(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    user_id = update.effective_user.id  # type: ignore[union-attr]
    bot_user = await context.bot.get_me()
    referral_link = f"https://t.me/{bot_user.username}?start=ref_{user_id}"
    count = referral_count(user_id)
    text = (
        "👥 <b>Referral program</b>\n\n"
        f"Your referrals: <b>{count}</b>\n"
        "Invite friends with your personal link. They must start the bot "
        "using your link to be counted.\n\n"
        f"<code>{referral_link}</code>\n\n"
        "Share the link and build your network."
    )
    await query.edit_message_text(  # type: ignore[union-attr]
        text=text,
        parse_mode="HTML",
        reply_markup=back_keyboard(),
    )


async def request_withdrawal_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    context.user_data["awaiting_withdrawal"] = True
    text = (
        "💸 <b>Withdrawal request</b>\n\n"
        f"Available: <b>{get_balance(update.effective_user.id):,}</b> coins\n"
        f"Minimum: <b>{MINIMUM_WITHDRAWAL:,}</b> coins\n\n"
        "Send the amount you want to withdraw as a whole number.\n"
        "Send <b>cancel</b> to go back."
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(  # type: ignore[union-attr]
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Cancel", callback_data="cancel_withdraw"
                        )
                    ]
                ]
            ),
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text=text,
            parse_mode="HTML",
        )


async def handle_withdrawal_amount(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_user is None or update.message is None:
        return
    if not context.user_data.get("awaiting_withdrawal"):
        await update.message.reply_text(
            "Use the buttons below to choose an action.",
            reply_markup=main_menu_keyboard(),
        )
        return

    raw_amount = update.message.text.strip().lower()
    if raw_amount == "cancel":
        context.user_data.pop("awaiting_withdrawal", None)
        await send_main_menu(update, update.effective_user.id)
        return

    try:
        amount = int(raw_amount.replace(",", ""))
    except ValueError:
        await update.message.reply_text(
            "Please send a whole number, or send <b>cancel</b>.",
            parse_mode="HTML",
        )
        return

    if amount <= 0:
        await update.message.reply_text("The amount must be greater than zero.")
        return

    withdrawal_id, error = create_withdrawal(update.effective_user.id, amount)
    if withdrawal_id is None:
        await update.message.reply_text(error)
        return

    context.user_data.pop("awaiting_withdrawal", None)
    await update.message.reply_text(
        "✅ <b>Withdrawal submitted</b>\n\n"
        f"Request ID: <code>#{withdrawal_id}</code>\n"
        f"Amount: <b>{amount:,}</b> coins\n\n"
        "Your request is now pending admin review.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await notify_admins(
        context,
        (
            "💸 <b>New withdrawal request</b>\n\n"
            f"Request: <code>#{withdrawal_id}</code>\n"
            f"User: <code>{update.effective_user.id}</code>\n"
            f"Amount: <b>{amount:,}</b> coins\n\n"
            "Review it with /pendingwithdrawals."
        ),
    )


# ---------------------------------------------------------------------------
# Callback router
# ---------------------------------------------------------------------------

async def callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return

    user = update.effective_user
    ensure_user(user)
    action = query.data or ""

    if action == "verify":
        if await is_channel_member(context.bot, user.id):
            await query.answer("Membership verified!")
            await query.edit_message_text(
                "✅ Membership verified. Welcome to SmartEarnBot!",
                reply_markup=main_menu_keyboard(),
            )
        else:
            await query.answer(
                "Membership was not found yet. Join the channel and try again.",
                show_alert=True,
            )
            await send_membership_gate(update)
        return

    if not await is_channel_member(context.bot, user.id):
        await query.answer(
            "Join the required channel to use SmartEarnBot.",
            show_alert=True,
        )
        await send_membership_gate(update)
        return

    if action == "home":
        await query.answer()
        await send_main_menu(update, user.id, edit=True)
    elif action == "help":
        await query.answer()
        await send_help(update)
    elif action == "mine":
        await query.answer()
        await handle_mine(update)
    elif action == "balance":
        await query.answer()
        await handle_balance(update)
    elif action == "tasks":
        await query.answer()
        await handle_tasks(update)
    elif action.startswith("task:"):
        try:
            task_id = int(action.split(":", 1)[1])
        except ValueError:
            await query.answer("Invalid task.", show_alert=True)
            return
        await handle_task_claim(update, context, task_id)
    elif action == "referrals":
        await query.answer()
        await handle_referrals(update, context)
    elif action == "withdraw":
        await query.answer()
        await request_withdrawal_prompt(update, context)
    elif action == "cancel_withdraw":
        await query.answer()
        context.user_data.pop("awaiting_withdrawal", None)
        await query.edit_message_text(
            text=main_menu_text(user.id),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await query.answer("That option is not available.", show_alert=True)


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def admin_only(
    update: Update,
) -> bool:
    user = update.effective_user
    if user is None or not is_admin(user.id):
        if update.effective_message:
            await update.effective_message.reply_text(
                "This command is available to admins only."
            )
        return False
    return True


async def add_balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await admin_only(update):
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "Usage: /addbalance <user_id> <amount>"
        )
        return
    try:
        user_id, amount = int(context.args[0]), int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text(
            "Both user_id and amount must be whole numbers."
        )
        return
    if amount <= 0:
        await update.effective_message.reply_text(
            "The amount must be greater than zero."
        )
        return
    new_balance = change_balance(user_id, amount)
    if new_balance is None:
        await update.effective_message.reply_text("User not found.")
        return
    await update.effective_message.reply_text(
        f"Added {amount:,} coins. New balance: {new_balance:,}."
    )


async def remove_balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await admin_only(update):
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "Usage: /removebalance <user_id> <amount>"
        )
        return
    try:
        user_id, amount = int(context.args[0]), int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text(
            "Both user_id and amount must be whole numbers."
        )
        return
    if amount <= 0:
        await update.effective_message.reply_text(
            "The amount must be greater than zero."
        )
        return
    current_balance = get_balance(user_id)
    if current_balance < amount:
        await update.effective_message.reply_text(
            "The user does not have enough coins."
        )
        return
    new_balance = change_balance(user_id, -amount)
    await update.effective_message.reply_text(
        f"Removed {amount:,} coins. New balance: {new_balance:,}."
    )


async def set_balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await admin_only(update):
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "Usage: /setbalance <user_id> <amount>"
        )
        return
    try:
        user_id, amount = int(context.args[0]), int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text(
            "Both user_id and amount must be whole numbers."
        )
        return
    if amount < 0:
        await update.effective_message.reply_text(
            "The balance cannot be negative."
        )
        return
    current_balance = get_balance(user_id)
    new_balance = change_balance(user_id, amount - current_balance)
    if new_balance is None:
        await update.effective_message.reply_text("User not found.")
        return
    await update.effective_message.reply_text(
        f"Balance set to {new_balance:,} coins."
    )


async def pending_withdrawals_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await admin_only(update):
        return
    rows = pending_withdrawals()
    if not rows:
        await update.effective_message.reply_text(
            "There are no pending withdrawal requests."
        )
        return
    lines = ["💸 <b>Pending withdrawals</b>\n"]
    for row in rows:
        username = f"@{row['username']}" if row["username"] else "no username"
        lines.append(
            f"#{row['id']} — <b>{row['amount']:,}</b> coins\n"
            f"User: <code>{row['user_id']}</code> ({username})\n"
            f"Approve: <code>/approvewithdrawal {row['id']}</code>\n"
            f"Reject: <code>/rejectwithdrawal {row['id']}</code>\n"
        )
    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
    )


async def approve_withdrawal_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await admin_only(update):
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text(
            "Usage: /approvewithdrawal <request_id>"
        )
        return
    try:
        withdrawal_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("Request ID must be a number.")
        return
    row = approve_withdrawal(withdrawal_id, update.effective_user.id)
    if row is None:
        await update.effective_message.reply_text(
            "Pending withdrawal not found."
        )
        return
    await update.effective_message.reply_text(
        f"Withdrawal #{withdrawal_id} marked as approved."
    )
    try:
        await context.bot.send_message(
            chat_id=int(row["user_id"]),
            text=(
                "✅ <b>Withdrawal approved</b>\n\n"
                f"Request <code>#{withdrawal_id}</code> for "
                f"<b>{row['amount']:,}</b> coins was approved."
            ),
            parse_mode="HTML",
        )
    except TelegramError as error:
        logger.warning("Could not notify user about approval: %s", error)


async def reject_withdrawal_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await admin_only(update):
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text(
            "Usage: /rejectwithdrawal <request_id>"
        )
        return
    try:
        withdrawal_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("Request ID must be a number.")
        return
    row = reject_withdrawal(withdrawal_id, update.effective_user.id)
    if row is None:
        await update.effective_message.reply_text(
            "Pending withdrawal not found."
        )
        return
    await update.effective_message.reply_text(
        f"Withdrawal #{withdrawal_id} rejected and refunded."
    )
    try:
        await context.bot.send_message(
            chat_id=int(row["user_id"]),
            text=(
                "↩️ <b>Withdrawal rejected</b>\n\n"
                f"Request <code>#{withdrawal_id}</code> was rejected. "
                f"<b>{row['amount']:,}</b> coins were returned to your balance."
            ),
            parse_mode="HTML",
        )
    except TelegramError as error:
        logger.warning("Could not notify user about rejection: %s", error)


async def admin_help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await admin_only(update):
        return
    await update.effective_message.reply_text(
        "🔧 <b>Admin commands</b>\n\n"
        "/addbalance user_id amount\n"
        "/removebalance user_id amount\n"
        "/setbalance user_id amount\n"
        "/pendingwithdrawals\n"
        "/approvewithdrawal request_id\n"
        "/rejectwithdrawal request_id",
        parse_mode="HTML",
    )


async def notify_admins(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="HTML",
            )
        except TelegramError as error:
            logger.warning("Could not notify admin %s: %s", admin_id, error)


# ---------------------------------------------------------------------------
# Application entrypoint
# ---------------------------------------------------------------------------

def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Set it in the environment before starting SmartEarnBot."
        )

    initialize_database()
    telegram_request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(telegram_request)
        .get_updates_request(telegram_request)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("withdraw", request_withdrawal_prompt))
    application.add_handler(
        CommandHandler("addbalance", add_balance_command)
    )
    application.add_handler(
        CommandHandler("removebalance", remove_balance_command)
    )
    application.add_handler(CommandHandler("setbalance", set_balance_command))
    application.add_handler(
        CommandHandler("pendingwithdrawals", pending_withdrawals_command)
    )
    application.add_handler(
        CommandHandler("approvewithdrawal", approve_withdrawal_command)
    )
    application.add_handler(
        CommandHandler("rejectwithdrawal", reject_withdrawal_command)
    )
    application.add_handler(CommandHandler("adminhelp", admin_help_command))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdrawal_amount)
    )

    return application


def main() -> None:
    application = build_application()
    logger.info("SmartEarnBot is starting with long polling.")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=-1,
    )


if __name__ == "__main__":
    main()
from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "SmartEarnBot is Alive! Bot is running on Telegram."

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # Start web server in background so Render sees a port
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    # Start your Telegram bot
    main()
