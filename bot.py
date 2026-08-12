import logging
import re
import sqlite3
import time

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
# 1-QISM
# ============================================================

# TOKENNI SHU YERGA O'Z TOKENINGIZNI YOZING
BOT_TOKEN = "8834635778:AAERGiDkJ8Qa_iiqdTtq_9bXIGcfOQ1p2ds"

# BOT EGALARI ID'LARI
OWNER_IDS = {
    8892671978,
    5940450585,
}

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
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

db.commit()

# ============================================================
# SO'KINISH FILTRI
# ============================================================

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

# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================

def ensure_group(chat):
    db.execute(
        """
        INSERT OR IGNORE INTO groups(chat_id, title)
        VALUES (?, ?)
        """,
        (
            chat.id,
            chat.title or ""
        )
    )

    db.execute(
        """
        INSERT OR IGNORE INTO used_groups(chat_id)
        VALUES (?)
        """,
        (chat.id,)
    )

    db.commit()


def ensure_user(chat, user):
    db.execute(
        """
        INSERT OR IGNORE INTO users(
            chat_id,
            user_id,
            name,
            username,
            messages
        )
        VALUES (?, ?, ?, ?, 0)
        """,
        (
            chat.id,
            user.id,
            user.full_name,
            user.username or ""
        )
    )

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

    db.commit()


async def check_admin(update, context, user_id=None):
    chat = update.effective_chat

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
        (
            chat_id,
            user_id
        )
    ).fetchone()

    return row[0] if row else 0


def add_warn(chat_id, user_id):
    old = get_warn(
        chat_id,
        user_id
    )

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
        (
            chat_id,
            user_id,
            new
        )
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
        (
            chat_id,
            user_id
        )
    )

    db.commit()


def contains_bad_word(text):
    text = text.lower()

    words = re.findall(
        r"[a-zA-Zа-яА-ЯёЁўқғҳʻʼ']+",
        text
    )

    return any(
        word in BAD_WORDS
        for word in words
    )


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


# ============================================================
# /START
# ============================================================

async def start(update, context):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🆘 HELP",
                callback_data="help"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ Guruhga qo'shish",
                url=(
                    "https://t.me/"
                    + context.bot.username
                    + "?startgroup=true"
                )
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ Bot haqida",
                callback_data="about"
            )
        ]
    ])

    await update.message.reply_text(
        "🛡 <b>BMAX HELP BOT</b>\n\n"
        "Assalomu alaykum! 👋\n"
        "Men Telegram guruhlarini boshqarish "
        "va himoya qilish uchun yaratilgan botman.\n\n"
        "🛡 Guruh himoyasi\n"
        "🚫 So'kinish filtri\n"
        "🔗 Havola/reklama nazorati\n"
        "⚠️ Warn tizimi\n"
        "🔇 Mute\n"
        "🔨 Ban\n"
        "👢 Kick\n"
        "🤖 CAPTCHA\n"
        "📊 Statistika\n"
        "📜 Qoidalar\n\n"
        "Quyidagi tugmalardan foydalaning:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ============================================================
# HELP / ABOUT CALLBACK
# ============================================================

async def start_callback(update, context):
    query = update.callback_query

    await query.answer()

    if query.data == "help":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 Orqaga",
                    callback_data="back_start"
                )
            ]
        ])

        await query.edit_message_text(
            "🆘 <b>BMAX HELP BOT — YORDAM</b>\n\n"
            "👮 Admin komandalar:\n"
            "/panel — Admin panel\n"
            "/ban — Ban qilish\n"
            "/kick — Guruhdan chiqarish\n"
            "/warn — Warn berish\n"
            "/unwarn — Warnni tozalash\n"
            ".mute 10min sabab — Mute\n"
            "/info — Foydalanuvchi ma'lumoti\n"
            "/id — ID ko'rish\n"
            "/rules — Guruh qoidalari\n"
            "/stats — Statistika\n\n"
            "📢 Bot egasi:\n"
            "/reklama — Reklama yuborish tizimi",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    elif query.data == "about":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 Orqaga",
                    callback_data="back_start"
                )
            ]
        ])

        await query.edit_message_text(
            "ℹ️ <b>BMAX HELP BOT</b>\n\n"
            "🛡 Guruhlarni himoya qilish va "
            "boshqarish uchun yordamchi bot.\n\n"
            "🐍 Python Telegram Bot\n"
            "🇺🇿 O'zbekcha interfeys\n"
            "🔒 CAPTCHA\n"
            "⚠️ Warn tizimi\n"
            "📊 Statistika\n"
            "📢 Reklama tizimi",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    elif query.data == "back_start":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🆘 HELP",
                    callback_data="help"
                )
            ],
            [
                InlineKeyboardButton(
                    "➕ Guruhga qo'shish",
                    url=(
                        "https://t.me/"
                        + context.bot.username
                        + "?startgroup=true"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "ℹ️ Bot haqida",
                    callback_data="about"
                )
            ]
        ])

        await query.edit_message_text(
            "🛡 <b>BMAX HELP BOT</b>\n\n"
            "Kerakli bo'limni tanlang:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )


# ============================================================
# YANGI A'ZO / CAPTCHA
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

        try:
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
                (
                    chat.id,
                    user.id
                )
            )

            db.execute(
                """
                INSERT OR IGNORE INTO users(
                    chat_id,
                    user_id,
                    name,
                    username,
                    joined
                )
                VALUES (?, ?, ?, ?, 1)
                """,
                (
                    chat.id,
                    user.id,
                    user.full_name,
                    user.username or ""
                )
            )

            db.commit()

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Men bot emasman",
                        callback_data=(
                            f"captcha:{chat.id}:{user.id}"
                        )
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
            logging.error(e)


async def captcha_button(update, context):
    query = update.callback_query

    await query.answer()

    parts = query.data.split(":")

    if len(parts) != 3:
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
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )

        db.execute(
            """
            DELETE FROM captcha
            WHERE chat_id=?
            AND user_id=?
            """,
            (
                chat_id,
                user_id
            )
        )

        db.commit()

        await query.edit_message_text(
            f"✅ {query.from_user.full_name} "
            "tasdiqlandi!\n\n"
            "Endi guruhda yozishingiz mumkin."
        )

    except Exception as e:
        logging.error(e)

        await query.answer(
            "❌ Bot admin ekanligini tekshiring.",
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

    if cm.new_chat_member.status in (
        ChatMemberStatus.LEFT,
        ChatMemberStatus.BANNED
    ):
        db.execute(
            """
            UPDATE users
            SET left=1
            WHERE chat_id=?
            AND user_id=?
            """,
            (
                chat.id,
                user.id
            )
        )

        db.commit()


# ============================================================
# MODERATSIYA
# ============================================================

async def moderate(update, context):
    message = update.message

    if not message:
        return

    chat = message.chat
    user = message.from_user

    if chat.type not in (
        "group",
        "supergroup"
    ):
        return

    ensure_group(chat)
    ensure_user(chat, user)

    if await check_admin(
        update,
        context
    ):
        return

    pending = db.execute(
        """
        SELECT 1
        FROM captcha
        WHERE chat_id=?
        AND user_id=?
        """,
        (
            chat.id,
            user.id
        )
    ).fetchone()

    if pending:
        try:
            await message.delete()
        except Exception:
            pass

        return

    if not message.text:
        return

    text = message.text.lower()

    if URL_RE.search(text):
        try:
            await message.delete()

            await context.bot.send_message(
                chat.id,
                f"🔗 {user.full_name}, "
                "guruhda reklama va havolalar taqiqlangan!"
            )

        except Exception:
            pass

        return

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
                    permissions=ChatPermissions(
                        can_send_messages=False
                    ),
                    until_date=int(
                        time.time() + 600
                    )
                )

                clear_warn(
                    chat.id,
                    user.id
                )

                await context.bot.send_message(
                    chat.id,
                    f"🔇 {user.full_name} "
                    "3 ta warn sababli "
                    "10 daqiqaga mute qilindi."
                )

        except Exception as e:
            logging.error(e)
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

    warn = get_warn(
        message.chat.id,
        user.id
    )

    await message.reply_text(
        f"👤 Ism: {user.full_name}\n"
        f"🆔 ID: {user.id}\n"
        f"🔗 Username: @{user.username or 'yo‘q'}\n"
        f"⚠️ Warn: {warn}"
    )


# ============================================================
# /BAN
# ============================================================

async def cmd_ban(update, context):
    message = update.message

    if not await check_admin(update, context):
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❗ Foydalanuvchi xabariga reply qilib /ban yozing."
        )
        return

    user = message.reply_to_message.from_user

    try:
        await context.bot.ban_chat_member(
            message.chat.id,
            user.id
        )

        await message.reply_text(
            f"🔨 {user.full_name} ban qilindi."
        )

    except Exception as e:
        logging.error(e)
        await message.reply_text(
            "❌ Ban qilishda xatolik."
        )


# ============================================================
# /KICK
# ============================================================

async def cmd_kick(update, context):
    message = update.message

    if not await check_admin(update, context):
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❗ Foydalanuvchi xabariga reply qilib /kick yozing."
        )
        return

    user = message.reply_to_message.from_user

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
        logging.error(e)


# ============================================================
# /WARN
# ============================================================

async def cmd_warn(update, context):
    message = update.message

    if not await check_admin(update, context):
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❗ Foydalanuvchi xabariga reply qilib /warn yozing."
        )
        return

    user = message.reply_to_message.from_user

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
                permissions=ChatPermissions(
                    can_send_messages=False
                ),
                until_date=int(
                    time.time() + 600
                )
            )

            clear_warn(
                message.chat.id,
                user.id
            )

            await message.reply_text(
                f"🔇 {user.full_name} "
                "3 ta warn sababli "
                "10 daqiqaga mute qilindi."
            )

        except Exception as e:
            logging.error(e)


# ============================================================
# /UNWARN
# ============================================================

async def cmd_unwarn(update, context):
    message = update.message

    if not await check_admin(update, context):
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❗ Foydalanuvchi xabariga reply qilib /unwarn yozing."
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
# MUTE
# ============================================================

pending_mutes = {}


async def mute_command(update, context):
    message = update.message

    if not await check_admin(update, context):
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❗ Foydalanuvchi xabariga reply qiling.\n\n"
            "Misol:\n"
            ".mute 10min sabab"
        )
        return

    parts = message.text.split(
        maxsplit=2
    )

    if len(parts) < 2:
        await message.reply_text(
            "❌ Misol:\n"
            ".mute 10min sabab"
        )
        return

    seconds = parse_duration(parts[1])

    if seconds is None:
        await message.reply_text(
            "❌ Vaqt noto‘g‘ri.\n\n"
            "Misollar:\n"
            ".mute 2min sabab\n"
            ".mute 30min sabab\n"
            ".mute 1h sabab\n"
            ".mute 2d sabab"
        )
        return

    reason = (
        parts[2]
        if len(parts) >= 3
        else "Sabab ko‘rsatilmagan"
    )

    user = message.reply_to_message.from_user

    request_id = str(
        time.time_ns()
    )

    pending_mutes[request_id] = {
        "chat_id": message.chat.id,
        "user_id": user.id,
        "name": user.full_name,
        "seconds": seconds,
        "reason": reason
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
            )
        ]
    ])

    await message.reply_text(
        f"🔇 MUTE SO‘ROVI\n\n"
        f"👤 Ism: {user.full_name}\n"
        f"⏱ Muddati: {duration_text(seconds)}\n"
        f"📝 Sababi: {reason}\n\n"
        "👮 Admin tasdiqlasinmi?",
        reply_markup=keyboard
    )


async def mute_callback(update, context):
    query = update.callback_query

    parts = query.data.split(":")

    if len(parts) != 2:
        await query.answer()
        return

    action = parts[0]
    request_id = parts[1]

    data = pending_mutes.get(
        request_id
    )

    if not data:
        await query.answer(
            "❌ So‘rov eskirgan.",
            show_alert=True
        )
        return

    if not await check_admin(
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
            permissions=ChatPermissions(
                can_send_messages=False
            ),
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
                    callback_data=(
                        f"unmute:{chat_id}:{user_id}"
                    )
                )
            ]
        ])

        await query.edit_message_text(
            f"🔇 MUTE\n\n"
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
        logging.error(e)

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

    if not await check_admin(
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
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )

        db.execute(
            """
            DELETE FROM muted
            WHERE chat_id=?
            AND user_id=?
            """,
            (
                chat_id,
                user_id
            )
        )

        db.commit()

        await query.edit_message_text(
            "🔊 Foydalanuvchi mutedan chiqarildi."
        )

        await query.answer(
            "✅ Tayyor."
        )

    except Exception as e:
        logging.error(e)

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
        if row
        else "Qoidalar yo‘q."
    )

    await update.message.reply_text(
        "📜 GURUH QOIDALARI\n\n"
        + rules
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
        members = "Noma’lum"

    row = db.execute(
        """
        SELECT COUNT(*),
               COALESCE(SUM(messages), 0),
               COALESCE(SUM(joined), 0),
               COALESCE(SUM(left), 0)
        FROM users
        WHERE chat_id=?
        """,
        (chat_id,)
    ).fetchone()

    users = row[0]
    messages = row[1]
    joined = row[2]
    left = row[3]

    await update.message.reply_text(
        "📊 GURUH STATISTIKASI\n\n"
        f"👥 A'zolar: {members}\n"
        f"👤 Kuzatilganlar: {users}\n"
        f"💬 Xabarlar: {messages}\n"
        f"🟢 Kirganlar: {joined}\n"
        f"🔴 Chiqib ketganlar: {left}"
    )


# ============================================================
# /PANEL
# ============================================================

async def cmd_panel(update, context):
    if not await check_admin(update, context):
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛡 Himoya",
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
        ]
    ])

    await update.message.reply_text(
        "⚙️ ADMIN PANEL\n\n"
        "Kerakli bo‘limni tanlang:",
        reply_markup=keyboard
    )


async def panel_callback(update, context):
    query = update.callback_query

    await query.answer()

    if query.data == "panel_security":

        await query.edit_message_text(
            "🛡 HIMOYA\n\n"
            "✅ So‘kinish filtri\n"
            "✅ Reklama va havola bloklash\n"
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
            if row
            else "Qoidalar yo‘q."
        )

        await query.edit_message_text(
            "📜 QOIDALAR\n\n"
            + rules
        )

    elif query.data == "panel_stats":

        await query.edit_message_text(
            "📊 Statistikani ko‘rish uchun:\n"
            "/stats"
        )


# ============================================================
# REKLAMA
# ============================================================

ad_waiting = set()


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
        "Keyin men sizdan tasdiqlashni so‘rayman."
    )


async def receive_ad(update, context):
    user_id = update.effective_user.id

    if user_id not in OWNER_IDS:
        return

    if update.effective_chat.type != "private":
        return

    if user_id not in ad_waiting:
        return

    if (
        not update.message.text
        and not update.message.photo
    ):
        return

    ad_waiting.remove(user_id)

    text = (
        update.message.text
        or update.message.caption
        or ""
    )

    photo_id = None

    if update.message.photo:
        photo_id = (
            update.message.photo[-1].file_id
        )

    db.execute(
        """
        INSERT OR REPLACE INTO advertisements(
            id,
            text,
            photo_id,
            enabled
        )
        VALUES (1, ?, ?, 0)
        """,
        (
            text,
            photo_id
        )
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
            )
        ]
    ])

    await update.message.reply_text(
        "📣 Reklama barcha ishlayotgan "
        "guruhlar va foydalanuvchilarga yuborilsinmi?",
        reply_markup=keyboard
    )


async def ad_callback(update, context):
    query = update.callback_query

    if query.from_user.id not in OWNER_IDS:
        await query.answer(
            "❌ Faqat bot egalari.",
            show_alert=True
        )
        return

    if query.data == "ad_no":

        db.execute(
            """
            UPDATE advertisements
            SET enabled=0
            WHERE id=1
            """
        )

        db.commit()

        await query.edit_message_text(
            "❌ Reklama yuborilmadi."
        )

        await query.answer()
        return

    db.execute(
        """
        UPDATE advertisements
        SET enabled=1
        WHERE id=1
        """
    )

    db.commit()

    await query.edit_message_text(
        "✅ Reklama tasdiqlandi.\n\n"
        "📢 Endi yuborish mumkin."
    )

    await query.answer()


# ============================================================
# REKLAMANI QO‘LDA YUBORISH
# ============================================================

async def cmd_yubor(update, context):
    user_id = update.effective_user.id

    if user_id not in OWNER_IDS:
        await update.message.reply_text(
            "❌ Bu buyruq faqat bot egalari uchun."
        )
        return

    row = db.execute(
        """
        SELECT text, photo_id, enabled
        FROM advertisements
        WHERE id=1
        """
    ).fetchone()

    if not row:
        await update.message.reply_text(
            "❌ Hozircha reklama tayyorlanmagan."
        )
        return

    if row[2] != 1:
        await update.message.reply_text(
            "❌ Reklama tasdiqlanmagan.\n"
            "Avval /reklama orqali reklama tayyorlang."
        )
        return

    text = row[0]
    photo_id = row[1]

    groups = db.execute(
        """
        SELECT chat_id
        FROM used_groups
        """
    ).fetchall()

    sent = 0
    failed = 0

    for group in groups:
        chat_id = group[0]

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

            sent += 1

        except Exception as e:
            logging.error(
                "Reklama yuborilmadi %s: %s",
                chat_id,
                e
            )
            failed += 1

    await update.message.reply_text(
        "📢 REKLAMA Yuborish YAKUNLANDI\n\n"
        f"✅ Yuborildi: {sent}\n"
        f"❌ Xatolik: {failed}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if BOT_TOKEN == "BU_YERGA_BOT_TOKENINGIZNI_YOZING":
        print("❌ BOT TOKENINI KIRITING!")
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # START
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # ASOSIY BUYRUQLAR
    app.add_handler(
        CommandHandler(
            "id",
            cmd_id
        )
    )

    app.add_handler(
        CommandHandler(
            "info",
            cmd_info
        )
    )

    app.add_handler(
        CommandHandler(
            "ban",
            cmd_ban
        )
    )

    app.add_handler(
        CommandHandler(
            "kick",
            cmd_kick
        )
    )

    app.add_handler(
        CommandHandler(
            "warn",
            cmd_warn
        )
    )

    app.add_handler(
        CommandHandler(
            "unwarn",
            cmd_unwarn
        )
    )

    app.add_handler(
        CommandHandler(
            "rules",
            cmd_rules
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            cmd_stats
        )
    )

    app.add_handler(
        CommandHandler(
            "panel",
            cmd_panel
        )
    )

    # REKLAMA
    app.add_handler(
        CommandHandler(
            "reklama",
            cmd_reklama
        )
    )

    app.add_handler(
        CommandHandler(
            "yubor",
            cmd_yubor
        )
    )

    # YANGI A'ZOLAR
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

    # MUTE
    app.add_handler(
        MessageHandler(
            filters.Regex(
                r"^\.mute(\s|$)"
            ),
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

    # MUTE CALLBACK
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

    # PANEL
    app.add_handler(
        CallbackQueryHandler(
            panel_callback,
            pattern=r"^panel_"
        )
    )

    # START / HELP / ABOUT
    app.add_handler(
        CallbackQueryHandler(
            start_callback,
            pattern=r"^(help|about|back_start)$"
        )
    )

    # REKLAMA
    app.add_handler(
        CallbackQueryHandler(
            ad_callback,
            pattern=r"^ad_(yes|no)$"
        )
    )

    # PRIVATE REKLAMA
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & (
                filters.TEXT
                | filters.PHOTO
            ),
            receive_ad
        )
    )

    # GURUH MODERATSIYASI
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & filters.TEXT,
            moderate
        )
    )

    print()
    print("==============================")
    print("🛡 BMAX HELP BOT")
    print("🐍 Python Telegram Bot")
    print("✅ Bot ishga tushdi!")
    print("==============================")
    print()

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main() 