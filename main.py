import logging
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

# ============================================================
# BMAX HELP BOT
# ============================================================

BOT_NAME = "BMAX_HELP_BOT"

# Bot username @ belgisiz yoziladi
BOT_USERNAME = "BMAX_HELP_BOT"

# 2 ta bot egasi
OWNER_IDS = {
    8892671978,
    5940450585,
}

# Render Environment Variable'dan olinadi
import os
BOT_TOKEN = os.getenv("8834635778:AAERGiDkJ8Qa_iiqdTtq_9bXIGcfOQ1p2ds", "")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(
    "bmax_help_bot.db",
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
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    username TEXT,
    first_seen INTEGER
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS group_users (
    chat_id INTEGER,
    user_id INTEGER,
    messages INTEGER DEFAULT 0,
    joined INTEGER DEFAULT 0,
    left_count INTEGER DEFAULT 0,
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
    photo_id TEXT
)
""")

db.commit()

# ============================================================
# XOTIRA
# ============================================================

pending_mutes = {}
ad_waiting = set()

# Flood nazorati
flood_messages = defaultdict(lambda: deque(maxlen=10))

# ============================================================
# SO'KINISH FILTRI
# ============================================================

BAD_WORDS = {
    # O'zbekcha
    "ahmoq",
    "axmoq",
    "tentak",
    "jinni",
    "haromi",
    "yaramas",
    "ablah",
    "iflos",
    "pashol",

    # Ruscha
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
    re.IGNORECASE,
)

# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================

def ensure_group(chat):
    db.execute(
        """
        INSERT OR IGNORE INTO groups(chat_id, title)
        VALUES (?, ?)
        """,
        (chat.id, chat.title or "")
    )

    db.commit()


def ensure_user(user):
    db.execute(
        """
        INSERT OR IGNORE INTO users(
            user_id,
            name,
            username,
            first_seen
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            user.id,
            user.full_name,
            user.username or "",
            int(time.time()),
        )
    )

    db.execute(
        """
        UPDATE users
        SET name=?, username=?
        WHERE user_id=?
        """,
        (
            user.full_name,
            user.username or "",
            user.id,
        )
    )

    db.commit()


def ensure_group_user(chat_id, user_id):
    db.execute(
        """
        INSERT OR IGNORE INTO group_users(
            chat_id,
            user_id
        )
        VALUES (?, ?)
        """,
        (chat_id, user_id)
    )

    db.commit()


def add_message_stat(chat_id, user_id):
    ensure_group_user(chat_id, user_id)

    db.execute(
        """
        UPDATE group_users
        SET messages=messages+1
        WHERE chat_id=?
        AND user_id=?
        """,
        (chat_id, user_id)
    )

    db.commit()


def add_join_stat(chat_id, user_id):
    ensure_group_user(chat_id, user_id)

    db.execute(
        """
        UPDATE group_users
        SET joined=joined+1
        WHERE chat_id=?
        AND user_id=?
        """,
        (chat_id, user_id)
    )

    db.commit()


def add_left_stat(chat_id, user_id):
    ensure_group_user(chat_id, user_id)

    db.execute(
        """
        UPDATE group_users
        SET left_count=left_count+1
        WHERE chat_id=?
        AND user_id=?
        """,
        (chat_id, user_id)
    )

    db.commit()


async def is_admin(update, context, user_id=None):
    chat = update.effective_chat

    if user_id is None:
        user_id = update.effective_user.id

    if chat.type not in ("group", "supergroup"):
        return False

    try:
        member = await context.bot.get_chat_member(
            chat.id,
            user_id
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
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
    old = get_warn(chat_id, user_id)
    new = old + 1

    db.execute(
        """
        INSERT OR REPLACE INTO warns(
            chat_id,
            user_id,
            count
        )
        VALUES (?, ?, ?)
        """,
        (chat_id, user_id, new)
    )

    db.commit()
    return new


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


def normal_permissions():
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )


def muted_permissions():
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
    )

# ============================================================
# START
# ============================================================

async def start(update, context):
    user = update.effective_user

    ensure_user(user)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🆘 Help",
                callback_data="start_help"
            ),
            InlineKeyboardButton(
                "ℹ️ Bot haqida",
                callback_data="start_about"
            ),
        ],
        [
            InlineKeyboardButton(
                "➕ Guruhga qo'shish",
                url=f"https://t.me/{BOT_USERNAME}?startgroup=true"
            ),
        ],
        [
            InlineKeyboardButton(
                "📜 Qoidalar",
                callback_data="start_rules"
            ),
        ],
    ])

    await update.message.reply_text(
        f"👋 Salom, {user.full_name}!\n\n"
        f"🛡️ {BOT_NAME} ga xush kelibsiz!\n\n"
        "Men Telegram guruhlarini boshqarish va "
        "himoya qilish uchun yaratilganman.\n\n"
        "Quyidagi tugmalardan foydalaning:",
        reply_markup=keyboard
    )


# ============================================================
# HELP
# ============================================================

async def show_help(update, context):
    text = (
        "🆘 BMAX HELP BOT — YORDAM\n\n"

        "👤 FOYDALANUVCHI BUYRUQLARI:\n"
        "/start — Bosh menyu\n"
        "/help — Yordam\n"
        "/id — ID ma'lumotlari\n"
        "/info — Foydalanuvchi ma'lumoti\n"
        "/rules — Guruh qoidalari\n"
        "/stats — Guruh statistikasi\n\n"

        "👮 ADMIN BUYRUQLARI:\n"
        "/panel — Admin panel\n"
        "/ban — Ban qilish\n"
        "/kick — Guruhdan chiqarish\n"
        "/warn — Ogohlantirish\n"
        "/unwarn — Warnni tozalash\n"
        ".mute 2min sabab — Mute qilish\n\n"

        "🛡️ HIMOYA:\n"
        "• Spam nazorati\n"
        "• Reklama va havolalarni bloklash\n"
        "• So'kinish filtri\n"
        "• Flood nazorati\n"
        "• CAPTCHA\n"
        "• Warn tizimi\n"
        "• Mute / Ban / Kick\n"
        "• Statistika\n\n"

        "👑 OWNER:\n"
        "/reklama — Reklama yuborish"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)


# ============================================================
# ABOUT
# ============================================================

async def show_about(update, context):
    text = (
        "ℹ️ BMAX HELP BOT HAQIDA\n\n"

        "🤖 Nomi: BMAX HELP BOT\n"
        "🐍 Platforma: Python\n"
        "📦 Kutubxona: python-telegram-bot\n"
        "💾 Database: SQLite\n\n"

        "🛡️ ASOSIY FUNKSIYALAR:\n"
        "✅ Guruh himoyasi\n"
        "✅ Spam nazorati\n"
        "✅ Reklama va linklarni bloklash\n"
        "✅ So'kinish filtri\n"
        "✅ Flood nazorati\n"
        "✅ CAPTCHA tekshiruvi\n"
        "✅ Warn tizimi\n"
        "✅ Ban\n"
        "✅ Kick\n"
        "✅ Mute\n"
        "✅ Mutedan chiqarish\n"
        "✅ Guruh statistikasi\n"
        "✅ A'zolarni kuzatish\n"
        "✅ Qoidalar\n"
        "✅ Admin panel\n"
        "✅ Xush kelibsiz tizimi\n"
        "✅ Owner reklama tizimi\n\n"

        "📢 Reklama avtomatik ravishda har 60 soniyada "
        "yuborilmaydi. Owner o'zi yuborishni boshlaydi.\n\n"

        "🔐 Botni guruhga administrator qilib qo'yish "
        "kerak bo'ladi."
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)


# ============================================================
# CALLBACK START
# ============================================================

async def start_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "start_help":
        await show_help(update, context)

    elif query.data == "start_about":
        await show_about(update, context)

    elif query.data == "start_rules":
        await query.edit_message_text(
            "📜 GURUH QOIDALARI\n\n"
            "Har bir guruhning qoidalari alohida bo'ladi.\n\n"
            "Guruhga botni qo'shib /rules buyrug'idan foydalaning."
        )


# ============================================================
# NEW MEMBER
# ============================================================

async def new_members(update, context):
    message = update.message

    if not message:
        return

    chat = message.chat
    ensure_group(chat)

    for user in message.new_chat_members:
        if user.is_bot:
            continue

        ensure_user(user)
        ensure_group_user(chat.id, user.id)
        add_join_stat(chat.id, user.id)

        try:
            await context.bot.restrict_chat_member(
                chat.id,
                user.id,
                permissions=muted_permissions()
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
                    InlineKeyboardButton(
                        "✅ Men bot emasman",
                        callback_data=f"captcha:{chat.id}:{user.id}"
                    )
                ]
            ])

            await message.reply_text(
                f"👋 Salom, {user.full_name}!\n\n"
                "🔒 Guruhga yozish uchun "
                "bot emasligingizni tasdiqlang.",
                reply_markup=keyboard
            )

        except Exception as e:
            logging.error(
                "CAPTCHA xatosi: %s",
                e
            )


# ============================================================
# CAPTCHA
# ============================================================

async def captcha_button(update, context):
    query = update.callback_query

    parts = query.data.split(":")

    if len(parts) != 3:
        await query.answer()
        return

    chat_id = int(parts[1])
    user_id = int(parts[2])

    if query.from_user.id != user_id:
        await query.answer(
            "❌ Bu tugma siz uchun emas.",
            show_alert=True
        )
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=normal_permissions()
        )

        db.execute(
            """
            DELETE FROM captcha
            WHERE chat_id=?
            AND user_id=?
            """,
            (chat_id, user_id)
        )

        db.commit()

        await query.edit_message_text(
            f"✅ {query.from_user.full_name} tasdiqlandi!\n\n"
            "Endi guruhda yozishingiz mumkin."
        )

        await query.answer("✅ Tasdiqlandi!")

    except Exception as e:
        logging.error("CAPTCHA: %s", e)

        await query.answer(
            "❌ Botga kerakli admin huquqlari berilmagan.",
            show_alert=True
        )


# ============================================================
# CHAT MEMBER
# ============================================================

async def chat_member_update(update, context):
    cm = update.chat_member

    if not cm:
        return

    chat = cm.chat
    user = cm.new_chat_member.user

    ensure_group(chat)
    ensure_user(user)

    if cm.new_chat_member.status in (
        ChatMemberStatus.LEFT,
        ChatMemberStatus.BANNED
    ):
        add_left_stat(chat.id, user.id)


# ============================================================
# MODERATION
# ============================================================

async def moderate(update, context):
    message = update.message

    if not message:
        return

    chat = message.chat
    user = message.from_user

    if chat.type not in ("group", "supergroup"):
        return

    if not user:
        return

    ensure_group(chat)
    ensure_user(user)
    add_message_stat(chat.id, user.id)

    if await is_admin(update, context):
        return

    # CAPTCHA
    pending = db.execute(
        """
        SELECT 1 FROM captcha
        WHERE chat_id=?
        AND user_id=?
        """,
        (chat.id, user.id)
    ).fetchone()

    if pending:
        try:
            await message.delete()
        except Exception:
            pass
        return

    if not message.text:
        return

    text = message.text

    # ========================================================
    # FLOOD
    # ========================================================

    now = time.time()
    key = (chat.id, user.id)

    flood_messages[key].append(now)

    recent = [
        x for x in flood_messages[key]
        if now - x <= 5
    ]

    if len(recent) >= 6:
        try:
            await message.delete()

            await context.bot.restrict_chat_member(
                chat.id,
                user.id,
                permissions=muted_permissions(),
                until_date=int(time.time() + 30)
            )

            await context.bot.send_message(
                chat.id,
                f"🔇 {user.full_name} flood sababli "
                "30 soniyaga mute qilindi."
            )

        except Exception:
            pass

        return

    # ========================================================
    # LINK
    # ========================================================

    if URL_RE.search(text.lower()):
        try:
            await message.delete()

            await context.bot.send_message(
                chat.id,
                f"🔗 {user.full_name}, "
                "guruhda havola va reklama taqiqlangan!"
            )
        except Exception:
            pass

        return

    # ========================================================
    # PROFANITY
    # ========================================================

    if contains_bad_word(text):
        try:
            await message.delete()

            count = add_warn(
                chat.id,
                user.id
            )

            await context.bot.send_message(
                chat.id,
                f"⚠️ {user.full_name}\n\n"
                "🚫 So'kinish taqiqlangan.\n"
                f"Warn: {count}/3"
            )

            if count >= 3:
                await context.bot.restrict_chat_member(
                    chat.id,
                    user.id,
                    permissions=muted_permissions(),
                    until_date=int(time.time() + 600)
                )

                clear_warn(
                    chat.id,
                    user.id
                )

                await context.bot.send_message(
                    chat.id,
                    f"🔇 {user.full_name} 3 ta warn sababli "
                    "10 daqiqaga mute qilindi."
                )

        except Exception as e:
            logging.error(
                "Moderatsiya: %s",
                e
            )


# ============================================================
# /ID
# ============================================================

async def cmd_id(update, context):
    await update.message.reply_text(
        f"👤 Sizning ID: {update.effective_user.id}\n"
        f"👥 Guruh ID: {update.effective_chat.id}"
    )


# ============================================================
# /INFO
# ============================================================

async def cmd_info(update, context):
    message = update.message

    if message.reply_to_message:
        user = message.reply_to_message.from_user
    else:
        user = update.effective_user

    ensure_user(user)

    warn = get_warn(
        message.chat.id,
        user.id
    )

    await message.reply_text(
        f"👤 Ism: {user.full_name}\n"
        f"🆔 ID: {user.id}\n"
        f"🔗 Username: @{user.username or 'yoq'}\n"
        f"⚠️ Warn: {warn}"
    )


# ============================================================
# /BAN
# ============================================================

async def cmd_ban(update, context):
    message = update.message

    if not await is_admin(update, context):
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❗ Foydalanuvchi xabariga reply qilib /ban yozing."
        )
        return

    user = message.reply_to_message.from_user

    if await is_admin(update, context, user.id):
        await message.reply_text(
            "❌ Adminni ban qilib bo'lmaydi."
        )
        return

    try:
        await context.bot.ban_chat_member(
            message.chat.id,
            user.id
        )

        await message.reply_text(
            f"🔨 {user.full_name} ban qilindi."
        )

    except Exception as e:
        logging.error("BAN: %s", e)
        await message.reply_text(
            "❌ Ban qilishda xatolik."
        )


# ============================================================
# /KICK
# ============================================================

async def cmd_kick(update, context):
    message = update.message

    if not await is_admin(update, context):
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❗ Xabarga reply qilib /kick yozing."
        )
        return

    user = message.reply_to_message.from_user

    if await is_admin(update, context, user.id):
        await message.reply_text(
            "❌ Adminni kick qilib bo'lmaydi."
        )
        return

    try:
        await context.bot.ban_chat_member(
            message.chat.id,
            user.id
        )

        await context.bot.unban_chat_member(
            message.chat.id,
            user.id
        )

        await message.reply_text(
            f"👢 {user.full_name} guruhdan chiqarildi."
        )

    except Exception as e:
        logging.error("KICK: %s", e)


# ============================================================
# /WARN
# ============================================================

async def cmd_warn(update, context):
    message = update.message

    if not await is_admin(update, context):
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❗ Xabarga reply qilib /warn yozing."
        )
        return

    user = message.reply_to_message.from_user

    if await is_admin(update, context, user.id):
        await message.reply_text(
            "❌ Adminga warn berib bo'lmaydi."
        )
        return

    count = add_warn(
        message.chat.id,
        user.id
    )

    await message.reply_text(
        f"⚠️ {user.full_name} ogohlantirildi.\n"
        f"Warn: {count}/3"
    )

    if count >= 3:
        try:
            await context.bot.restrict_chat_member(
                message.chat.id,
                user.id,
                permissions=muted_permissions(),
                until_date=int(time.time() + 600)
            )

            clear_warn(
                message.chat.id,
                user.id
            )

            await message.reply_text(
                f"🔇 {user.full_name} 10 daqiqaga mute qilindi."
            )

        except Exception as e:
            logging.error("WARN MUTE: %s", e)


# ============================================================
# /UNWARN
# ============================================================

async def cmd_unwarn(update, context):
    message = update.message

    if not await is_admin(update, context):
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❗ Xabarga reply qilib /unwarn yozing."
        )
        return

    user = message.reply_to_message.from_user

    clear_warn(
        message.chat.id,
        user.id
    )

    await message.reply_text(
        f"✅ {user.full_name} warnlari tozalandi."
    )


# ============================================================
# .MUTE
# ============================================================

async def mute_command(update, context):
    message = update.message

    if not await is_admin(update, context):
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❗ Foydalanuvchi xabariga reply qiling.\n\n"
            "Misol:\n"
            ".mute 2min sabab"
        )
        return

    parts = message.text.split(maxsplit=2)

    if len(parts) < 2:
        await message.reply_text(
            "Misol:\n"
            ".mute 2min sabab"
        )
        return

    seconds = parse_duration(parts[1])

    if seconds is None:
        await message.reply_text(
            "❌ Vaqt noto'g'ri.\n\n"
            ".mute 2min sabab\n"
            ".mute 30min sabab\n"
            ".mute 1h sabab\n"
            ".mute 2d sabab"
        )
        return

    reason = (
        parts[2]
        if len(parts) >= 3
        else "Sabab ko'rsatilmagan"
    )

    user = message.reply_to_message.from_user

    if await is_admin(update, context, user.id):
        await message.reply_text(
            "❌ Adminni mute qilib bo'lmaydi."
        )
        return

    request_id = str(time.time_ns())

    pending_mutes[request_id] = {
        "chat_id": message.chat.id,
        "user_id": user.id,
        "name": user.full_name,
        "seconds": seconds,
        "reason": reason,
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Tasdiqlash",
                callback_data=f"mute_yes:{request_id}"
            ),
            InlineKeyboardButton(
                "❌ Bekor qilish",
                callback_data=f"mute_no:{request_id}"
            ),
        ]
    ])

    await message.reply_text(
        "🔇 MUTE SO'ROVI\n\n"
        f"👤 Ism: {user.full_name}\n"
        f"⏱ Muddati: {duration_text(seconds)}\n"
        f"📝 Sababi: {reason}\n\n"
        "👮 Admin tasdiqlasinmi?",
        reply_markup=keyboard
    )


# ============================================================
# MUTE CALLBACK
# ============================================================

async def mute_callback(update, context):
    query = update.callback_query

    parts = query.data.split(":")

    if len(parts) != 2:
        await query.answer()
        return

    action = parts[0]
    request_id = parts[1]

    data = pending_mutes.get(request_id)

    if not data:
        await query.answer(
            "❌ So'rov eskirgan.",
            show_alert=True
        )
        return

    if not await is_admin(
        update,
        context,
        query.from_user.id
    ):
        await query.answer(
            "❌ Faqat admin tasdiqlashi mumkin.",
            show_alert=True
        )
        return

    if action == "mute_no":
        pending_mutes.pop(
            request_id,
            None
        )

        await query.edit_message_text(
            "❌ Mute bekor qilindi."
        )

        await query.answer()
        return

    chat_id = data["chat_id"]
    user_id = data["user_id"]
    seconds = data["seconds"]
    reason = data["reason"]
    name = data["name"]

    try:
        until_time = int(
            time.time() + seconds
        )

        await context.bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=muted_permissions(),
            until_date=until_time
        )

        db.execute(
            """
            INSERT OR REPLACE INTO muted(
                chat_id,
                user_id,
                until_time,
                reason
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                chat_id,
                user_id,
                until_time,
                reason
            )
        )

        db.commit()

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔊 Mutedan chiqarish",
                    callback_data=f"unmute:{chat_id}:{user_id}"
                )
            ]
        ])

        await query.edit_message_text(
            "🔇 MUTE\n\n"
            f"👤 Ism: {name}\n"
            f"⏱ Muddati: {duration_text(seconds)}\n"
            f"📝 Sababi: {reason}",
            reply_markup=keyboard
        )

        pending_mutes.pop(
            request_id,
            None
        )

        await query.answer(
            "✅ Mute qilindi."
        )

    except Exception as e:
        logging.error("MUTE: %s", e)

        await query.answer(
            "❌ Mute qilishda xatolik.",
            show_alert=True
        )


# ============================================================
# UNMUTE
# ============================================================

async def unmute_callback(update, context):
    query = update.callback_query

    parts = query.data.split(":")

    if len(parts) != 3:
        await query.answer()
        return

    chat_id = int(parts[1])
    user_id = int(parts[2])

    if not await is_admin(
        update,
        context,
        query.from_user.id
    ):
        await query.answer(
            "❌ Faqat admin.",
            show_alert=True
        )
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=normal_permissions()
        )

        db.execute(
            """
            DELETE FROM muted
            WHERE chat_id=?
            AND user_id=?
            """,
            (chat_id, user_id)
        )

        db.commit()

        await query.edit_message_text(
            "🔊 Foydalanuvchi mutedan chiqarildi."
        )

        await query.answer(
            "✅ Tayyor."
        )

    except Exception as e:
        logging.error("UNMUTE: %s", e)

        await query.answer(
            "❌ Xatolik.",
            show_alert=True
        )


# ============================================================
# /RULES
# ============================================================

async def cmd_rules(update, context):
    chat = update.effective_chat

    ensure_group(chat)

    row = db.execute(
        """
        SELECT rules
        FROM groups
        WHERE chat_id=?
        """,
        (chat.id,)
    ).fetchone()

    rules = (
        row[0]
        if row and row[0]
        else "Guruh qoidalari belgilanmagan."
    )

    await update.message.reply_text(
        "📜 GURUH QOIDALARI\n\n" + rules
    )


# ============================================================
# /STATS
# ============================================================

async def cmd_stats(update, context):
    chat_id = update.effective_chat.id

    try:
        members = await context.bot.get_chat_member_count(
            chat_id
        )
    except Exception:
        members = "Noma'lum"

    row = db.execute(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(messages), 0),
            COALESCE(SUM(joined), 0),
            COALESCE(SUM(left_count), 0)
        FROM group_users
        WHERE chat_id=?
        """,
        (chat_id,)
    ).fetchone()

    users = row[0]
    messages = row[1]
    joined = row[2]
    left_count = row[3]

    await update.message.reply_text(
        "📊 GURUH STATISTIKASI\n\n"
        f"👥 A'zolar: {members}\n"
        f"👤 Kuzatilganlar: {users}\n"
        f"💬 Xabarlar: {messages}\n"
        f"🟢 Kirganlar: {joined}\n"
        f"🔴 Chiqib ketganlar: {left_count}"
    )


# ============================================================
# /PANEL
# ============================================================

async def cmd_panel(update, context):
    if not await is_admin(update, context):
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛡️ Himoya",
                callback_data="panel_security"
            )
        ],
        [
            InlineKeyboardButton(
                "📜 Qoidalar",
                callback_data="panel_rules"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Statistika",
                callback_data="panel_stats"
            )
        ],
    ])

    await update.message.reply_text(
        "⚙️ ADMIN PANEL\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=keyboard
    )


async def panel_callback(update, context):
    query = update.callback_query

    if not await is_admin(
        update,
        context,
        query.from_user.id
    ):
        await query.answer(
            "❌ Faqat admin.",
            show_alert=True
        )
        return

    await query.answer()

    if query.data == "panel_security":
        await query.edit_message_text(
            "🛡️ HIMOYA\n\n"
            "✅ So'kinish filtri\n"
            "✅ Reklama va havola bloklash\n"
            "✅ Flood nazorati\n"
            "✅ CAPTCHA\n"
            "✅ Warn\n"
            "✅ Ban\n"
            "✅ Kick\n"
            "✅ Mute"
        )

    elif query.data == "panel_rules":
        row = db.execute(
            """
            SELECT rules
            FROM groups
            WHERE chat_id=?
            """,
            (query.message.chat.id,)
        ).fetchone()

        rules = (
            row[0]
            if row and row[0]
            else "Qoidalar belgilanmagan."
        )

        await query.edit_message_text(
            "📜 QOIDALAR\n\n" + rules
        )

    elif query.data == "panel_stats":
        await query.edit_message_text(
            "📊 Statistikani ko'rish uchun:\n"
            "/stats"
        )


# ============================================================
# REKLAMA — OWNER
# ============================================================

async def cmd_reklama(update, context):
    user_id = update.effective_user.id

    if user_id not in OWNER_IDS:
        await update.message.reply_text(
            "❌ Bu buyruq faqat bot egalari uchun."
        )
        return

    ad_waiting.add(user_id)

    await update.message.reply_text(
        "📢 Reklama matnini yoki rasmini yuboring.\n\n"
        "Rasm yuborsangiz caption ham yozishingiz mumkin."
    )


async def receive_ad(update, context):
    user_id = update.effective_user.id

    if user_id not in OWNER_IDS:
        return

    if update.effective_chat.type != "private":
        return

    if user_id not in ad_waiting:
        return

    message = update.message

    if not message:
        return

    if not message.text and not message.photo:
        return

    ad_waiting.remove(user_id)

    text = (
        message.text
        or message.caption
        or ""
    )

    photo_id = None

    if message.photo:
        photo_id = message.photo[-1].file_id

    db.execute(
        """
        INSERT OR REPLACE INTO advertisements(
            id,
            text,
            photo_id
        )
        VALUES (1, ?, ?)
        """,
        (text, photo_id)
    )

    db.commit()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Bekor qilish",
                callback_data="ad_no"
            ),
            InlineKeyboardButton(
                "📢 Yuborish",
                callback_data="ad_yes"
            ),
        ]
    ])

    await message.reply_text(
        "📣 Reklama tayyor.\n\n"
        "Uni botdan foydalanayotgan guruhlarga "
        "hozir bir marta yuboraymi?",
        reply_markup=keyboard
    )


# ============================================================
# REKLAMA YUBORISH — FAQAT TUGMA BOSILGANDA
# ============================================================

async def ad_callback(update, context):
    query = update.callback_query

    if query.from_user.id not in OWNER_IDS:
        await query.answer(
            "❌ Faqat bot egalari.",
            show_alert=True
        )
        return

    if query.data == "ad_no":
        await query.edit_message_text(
            "❌ Reklama yuborish bekor qilindi."
        )

        await query.answer()
        return

    row = db.execute(
        """
        SELECT text, photo_id
        FROM advertisements
        WHERE id=1
        """
    ).fetchone()

    if not row:
        await query.answer(
            "❌ Reklama topilmadi.",
            show_alert=True
        )
        return

    text, photo_id = row

    # Bot ishlatilgan guruhlar
    groups = db.execute(
        """
        SELECT chat_id
        FROM groups
        """
    ).fetchall()

    sent = 0
    failed = 0

    await query.edit_message_text(
        "📢 Reklama yuborilmoqda..."
    )

    for (chat_id,) in groups:
        try:
            if photo_id:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_id,
                    caption=text or ""
                )
            elif text:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text
                )
            else:
                continue

            sent += 1

        except Exception as e:
            failed += 1
            logging.warning(
                "Reklama %s ga yuborilmadi: %s",
                chat_id,
                e
            )

    # Botni /start qilgan foydalanuvchilar
    users = db.execute(
        """
        SELECT user_id
        FROM users
        """
    ).fetchall()

    user_sent = 0
    user_failed = 0

    for (user_id,) in users:
        try:
            if photo_id:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo_id,
                    caption=text or ""
                )
            elif text:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text
                )
            else:
                continue

            user_sent += 1

        except Exception as e:
            user_failed += 1
            logging.warning(
                "User reklama %s ga yuborilmadi: %s",
                user_id,
                e
            )

    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=(
            "✅ REKLAMA YUBORILDI\n\n"
            f"👥 Guruhlarga: {sent}\n"
            f"❌ Guruh xatolari: {failed}\n\n"
            f"👤 Foydalanuvchilarga: {user_sent}\n"
            f"❌ User xatolari: {user_failed}\n\n"
            "📌 Bu reklama faqat bir marta yuborildi."
        )
    )

    await query.answer(
        "✅ Yuborildi!"
    )


# ============================================================
# PRIVATE MESSAGE HANDLER
# ============================================================

async def private_handler(update, context):
    user = update.effective_user

    if user:
        ensure_user(user)

    await receive_ad(update, context)


# ============================================================
# GROUP MESSAGE HANDLER
# ============================================================

async def group_message_handler(update, context):
    message = update.message

    if not message:
        return

    if message.text:
        # .mute alohida handler orqali ishlaydi
        if message.text.lower().startswith(".mute"):
            return

    await moderate(update, context)


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:
        print(
            "❌ BOT_TOKEN topilmadi!\n"
            "Render Environment Variables ichiga "
            "BOT_TOKEN qo'ying."
        )
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # START / HELP
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("help", show_help)
    )

    # COMMANDLAR
    app.add_handler(
        CommandHandler("id", cmd_id)
    )

    app.add_handler(
        CommandHandler("info", cmd_info)
    )

    app.add_handler(
        CommandHandler("ban", cmd_ban)
    )

    app.add_handler(
        CommandHandler("kick", cmd_kick)
    )

    app.add_handler(
        CommandHandler("warn", cmd_warn)
    )

    app.add_handler(
        CommandHandler("unwarn", cmd_unwarn)
    )

    app.add_handler(
        CommandHandler("rules", cmd_rules)
    )

    app.add_handler(
        CommandHandler("stats", cmd_stats)
    )

    app.add_handler(
        CommandHandler("panel", cmd_panel)
    )

    app.add_handler(
        CommandHandler("reklama", cmd_reklama)
    )

    # YANGI A'ZO
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            new_members
        )
    )

    # CHAT MEMBER
    app.add_handler(
        ChatMemberHandler(
            chat_member_update,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    # .MUTE
    app.add_handler(
        MessageHandler(
            filters.Regex(r"^\.mute(\s|$)"),
            mute_command
        )
    )

    # CAPTCHA
    app.add_handler(
        CallbackQueryHandler(
            captcha_button,
            pattern=r"^captcha:"
        )
    )

    # MUTE
    app.add_handler(
        CallbackQueryHandler(
            mute_callback,
            pattern=r"^mute_(yes|no):"
        )
    )

    # UNMUTE
    app.add_handler(
        CallbackQueryHandler(
            unmute_callback,
            pattern=r"^unmute:"
        )
    )

    # START BUTTONLARI
    app.add_handler(
        CallbackQueryHandler(
            start_callback,
            pattern=r"^start_"
        )
    )

    # PANEL
    app.add_handler(
        CallbackQueryHandler(
            panel_callback,
            pattern=r"^panel_"
        )
    )

    # REKLAMA
    app.add_handler(
        CallbackQueryHandler(
            ad_callback,
            pattern=r"^ad_(yes|no)$"
        )
    )

    # PRIVATE
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & ~filters.COMMAND,
            private_handler
        )
    )

    # GROUP
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS,
            group_message_handler
        )
    )

    print()
    print("=" * 40)
    print("🤖 BMAX HELP BOT")
    print("🐍 Python Telegram Bot")
    print("✅ Bot ishga tushdi!")
    print("=" * 40)
    print()

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
