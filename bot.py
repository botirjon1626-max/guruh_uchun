import logging
import os
import re
import sqlite3
import time
from collections import defaultdict, deque

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# =========================================================
# BMAX HELP BOT
# =========================================================

BOT_TOKEN = os.getenv("8834635778:AAERGiDkJ8Qa_iiqdTtq_9bXIGcfOQ1p2ds", "").strip()

# Oldingi bergan IDlaringiz
OWNER_IDS = {
    8892671978,
    5940450585,
}

# Bot username'ini @ belgisiz yozing.
# Render Environment Variables'da BOT_USERNAME qo'yishingiz mumkin.
BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "BMAX_HELP_BOT"
).replace("@", "").strip()

DB_FILE = "bmax_help_bot.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.execute("""
CREATE TABLE IF NOT EXISTS groups (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    welcome INTEGER DEFAULT 1,
    links INTEGER DEFAULT 1,
    profanity INTEGER DEFAULT 1,
    flood INTEGER DEFAULT 1,
    captcha INTEGER DEFAULT 1,
    rules TEXT DEFAULT 'Guruh qoidalariga rioya qiling.'
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER,
    user_id INTEGER,
    name TEXT,
    username TEXT,
    messages INTEGER DEFAULT 0,
    joined INTEGER DEFAULT 0,
    left INTEGER DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS warns (
    chat_id INTEGER,
    user_id INTEGER,
    count INTEGER DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS captcha (
    chat_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY(chat_id, user_id)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS muted (
    chat_id INTEGER,
    user_id INTEGER,
    until_time INTEGER,
    reason TEXT,
    PRIMARY KEY(chat_id, user_id)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS advertisements (
    id INTEGER PRIMARY KEY,
    text TEXT,
    photo_id TEXT,
    enabled INTEGER DEFAULT 0
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS used_groups (
    chat_id INTEGER PRIMARY KEY
)
""")

# Botga /start qilgan foydalanuvchilar
db.execute("""
CREATE TABLE IF NOT EXISTS bot_users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    username TEXT,
    started_at INTEGER
)
""")

db.commit()

# =========================================================
# BAD WORDS / LINKS
# =========================================================

BAD_WORDS = {
    "ahmoq",
    "axmoq",
    "tentak",
    "jinni",
    "haromi",
    "yaramas",
    "ablah",
    "iflos",
    "pashol",

    "дурак",
    "дура",
    "идиот",
    "идиотка",
    "дебил",
    "дебилка",
    "тупой",
    "тупая",
    "кретин",
    "козел",
    "козёл",
    "сволочь",
    "пошел",
    "пошёл",
    "пошла",
    "пошли",
}

URL_RE = re.compile(
    r"(https?://\S+|www\.\S+|t\.me/\S+)",
    re.IGNORECASE
)

# =========================================================
# MEMORY
# =========================================================

pending_mutes = {}
ad_waiting = set()

# Flood:
# user -> oxirgi xabar vaqtlari
flood_data = defaultdict(deque)

# =========================================================
# HELPERS
# =========================================================

def ensure_group(chat):
    if not chat or chat.type not in ("group", "supergroup"):
        return

    db.execute(
        """
        INSERT OR IGNORE INTO groups(chat_id, title)
        VALUES (?, ?)
        """,
        (chat.id, chat.title or "")
    )

    db.execute(
        """
        UPDATE groups
        SET title=?
        WHERE chat_id=?
        """,
        (chat.title or "", chat.id)
    )

    db.execute(
        """
        INSERT OR IGNORE INTO used_groups(chat_id)
        VALUES (?)
        """,
        (chat.id,)
    )

    db.commit()


def ensure_user(chat, user, increment=True):
    if not chat or not user:
        return

    db.execute(
        """
        INSERT OR IGNORE INTO users(
            chat_id,
            user_id,
            name,
            username,
            messages,
            joined,
            left
        )
        VALUES (?, ?, ?, ?, 0, 0, 0)
        """,
        (
            chat.id,
            user.id,
            user.full_name,
            user.username or ""
        )
    )

    if increment:
        db.execute(
            """
            UPDATE users
            SET name=?,
                username=?,
                messages=messages+1
            WHERE chat_id=?
            AND user_id=?
            """,
            (
                user.full_name,
                user.username or "",
                chat.id,
                user.id
            )
        )
    else:
        db.execute(
            """
            UPDATE users
            SET name=?,
                username=?
            WHERE chat_id=?
            AND user_id=?
            """,
            (
                user.full_name,
                user.username or "",
                chat.id,
                user.id
            )
        )

    db.commit()


def save_bot_user(user):
    db.execute(
        """
        INSERT OR REPLACE INTO bot_users(
            user_id,
            name,
            username,
            started_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            user.id,
            user.full_name,
            user.username or "",
            int(time.time())
        )
    )
    db.commit()


async def check_admin(update, context, user_id=None):
    chat = update.effective_chat

    if not chat:
        return False

    if user_id is None:
        user_id = update.effective_user.id

    try:
        member = await context.bot.get_chat_member(
            chat.id,
            user_id
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        )

    except Exception:
        return False


def get_warn(chat_id, user_id):
    row = db.execute(
        """
        SELECT count
        FROM warns
        WHERE chat_id=?
        AND user_id=?
        """,
        (chat_id, user_id)
    ).fetchone()

    return row[0] if row else 0


def add_warn(chat_id, user_id):
    count = get_warn(chat_id, user_id) + 1

    db.execute(
        """
        INSERT OR REPLACE INTO warns(
            chat_id,
            user_id,
            count
        )
        VALUES (?, ?, ?)
        """,
        (chat_id, user_id, count)
    )

    db.commit()

    return count


def clear_warn(chat_id, user_id):
    db.execute(
        """
        DELETE FROM warns
        WHERE chat_id=?
        AND user_id=?
        """,
        (chat_id, user_id)
    )
    db.commit()


def contains_bad_word(text):
    words = re.findall(
        r"[a-zA-Zа-яА-ЯёЁўқғҳʻʼ']+",
        text.lower()
    )

    return any(word in BAD_WORDS for word in words)


def parse_duration(value):
    match = re.match(
        r"^(\d+)(min|m|h|d)$",
        value.lower()
    )

    if not match:
        return None

    number = int(match.group(1))
    unit = match.group(2)

    if unit in ("min", "m"):
        return number * 60

    if unit == "h":
        return number * 3600

    if unit == "d":
        return number * 86400

    return None


def duration_text(seconds):
    if seconds < 3600:
        return f"{seconds // 60} daqiqa"

    if seconds < 86400:
        return f"{seconds // 3600} soat"

    return f"{seconds // 86400} kun"


def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📚 HELP",
                callback_data="help"
            ),
            InlineKeyboardButton(
                "🛡 Himoya",
                callback_data="security"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ Guruhga qo'shish",
                url=f"https://t.me/{BOT_USERNAME}?startgroup=true"
            )
        ],
        [
            InlineKeyboardButton(
                "📜 Qoidalar",
                callback_data="help_rules"
            )
        ]
    ])


# =========================================================
# /START
# =========================================================

async def start(update, context):
    if not update.message:
        return

    user = update.effective_user

    save_bot_user(user)

    await update.message.reply_text(
        "🤖 BMAX HELP BOT\n\n"
        "🛡 Guruhingizni himoya qilishga yordam beraman.\n\n"
        "📚 HELP — bot buyruqlari\n"
        "🛡 Himoya — guruh himoyasi\n"
        "➕ Guruhga qo'shish — botni guruhga qo'shing\n\n"
        "Botni guruhga qo'shib ADMIN qiling.",
        reply_markup=main_keyboard()
    )


# =========================================================
# /HELP
# =========================================================

async def help_command(update, context):
    await update.message.reply_text(
        "📚 BMAX HELP BOT — YORDAM\n\n"
        "👤 Foydalanuvchi:\n"
        "/start — botni boshlash\n"
        "/help — yordam\n"
        "/id — ID ko'rish\n"
        "/info — ma'lumot\n\n"
        "👮 Admin:\n"
        "/panel — admin panel\n"
        "/ban — ban\n"
        "/kick — chiqarish\n"
        "/warn — ogohlantirish\n"
        "/unwarn — warnni tozalash\n"
        ".mute 10min sabab — mute\n"
        "/rules — qoidalar\n"
        "/stats — statistika\n\n"
        "🛡 Himoya:\n"
        "• CAPTCHA\n"
        "• Link/reklama bloklash\n"
        "• So'kinish filtri\n"
        "• Flood nazorati\n"
        "• Warn tizimi\n"
        "• Mute / Ban / Kick"
    )


# =========================================================
# CALLBACK HELP
# =========================================================

async def general_callback(update, context):
    query = update.callback_query

    if query.data == "help":
        await query.answer()

        await query.edit_message_text(
            "📚 BMAX HELP BOT\n\n"
            "/start — boshlash\n"
            "/help — yordam\n"
            "/id — ID\n"
            "/info — foydalanuvchi info\n"
            "/panel — admin panel\n"
            "/rules — qoidalar\n"
            "/stats — statistika\n\n"
            "👮 Admin:\n"
            "/ban /kick /warn /unwarn\n"
            ".mute 10min sabab",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Bosh menyu",
                        callback_data="home"
                    )
                ]
            ])
        )

    elif query.data == "security":
        await query.answer()

        await query.edit_message_text(
            "🛡 BMAX HIMOYA\n\n"
            "✅ CAPTCHA\n"
            "✅ Link bloklash\n"
            "✅ Reklama bloklash\n"
            "✅ So'kinish filtri\n"
            "✅ Flood nazorati\n"
            "✅ Warn\n"
            "✅ Ban\n"
            "✅ Kick\n"
            "✅ Mute",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Bosh menyu",
                        callback_data="home"
                    )
                ]
            ])
        )

    elif query.data == "home":
        await query.answer()

        await query.edit_message_text(
            "🤖 BMAX HELP BOT\n\n"
            "Kerakli bo'limni tanlang:",
            reply_markup=main_keyboard()
        )

    elif query.data == "help_rules":
        await query.answer()

        await query.edit_message_text(
            "📜 GURUH QOIDALARI\n\n"
            "Har bir guruh administratori o'z qoidalarini "
            "o'rnatishi mumkin.\n\n"
            "Standart:\n"
            "• Hurmat bilan yozing\n"
            "• Spam qilmang\n"
            "• Reklama/havola yubormang\n"
            "• So'kinmang",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Bosh menyu",
                        callback_data="home"
                    )
                ]
            ])
        )


# =========================================================
# NEW MEMBERS + CAPTCHA
# =========================================================

async def new_members(update, context):
    message = update.message

    if not message:
        return

    chat = message.chat
    ensure_group(chat)

    for user in message.new_chat_members:

        if user.is_bot:
            continue

        try:
            row = db.execute(
                """
                SELECT captcha
                FROM groups
                WHERE chat_id=?
                """,
                (chat.id,)
            ).fetchone()

            captcha_enabled = row[0] if row else 1

            ensure_user(
                chat,
                user,
                increment=False
            )

            db.execute(
                """
                UPDATE users
                SET joined=joined+1
                WHERE chat_id=?
                AND user_id=?
                """,
                (chat.id, user.id)
            )
            db.commit()

            if not captcha_enabled:
                continue

            await context.bot.restrict_chat_member(
                chat.id,
                user.id,
                permissions=ChatPermissions(
                    can_send_messages=False
                )
            )

            db.execute(
                """
                INSERT OR IGNORE INTO captcha(
                    chat_id,
                    user_id
                )
                VALUES (?, ?)
                """,
                (chat.id, user.id)
            )
            db.commit()

            keyboard = InlineKeyboardMarkup([
                [
                    