import os
import re
import time
import sqlite3
import logging
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

# =========================
# SOZLAMALAR
# =========================

BOT_TOKEN = os.getenv("8834635778:AAERGiDkJ8Qa_iiqdTtq_9bXIGcfOQ1p2ds", "").strip()

# Render Environment:
# OWNER_IDS=8892671978,5940450585
OWNER_IDS = {
    int(x.strip())
    for x in os.getenv("OWNER_IDS", "").split(",")
    if x.strip().isdigit()
}


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# =========================
# DATABASE
# =========================

db = sqlite3.connect(
    "bmax_help_bot.db",
    check_same_thread=False
)

db.execute("PRAGMA journal_mode=WAL")

db.execute("""
CREATE TABLE IF NOT EXISTS groups (
    chat_id INTEGER PRIMARY KEY,
    title TEXT DEFAULT '',
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
    text TEXT DEFAULT '',
    photo_id TEXT,
    enabled INTEGER DEFAULT 0
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS used_groups (
    chat_id INTEGER PRIMARY KEY
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS private_users (
    user_id INTEGER PRIMARY KEY,
    name TEXT DEFAULT '',
    username TEXT DEFAULT '',
    started INTEGER DEFAULT 1
)
""")

db.commit()

# =========================
# FILTRLAR
# =========================

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

# 8 soniyada 6 tadan ko'p xabar = flood
flood_cache = defaultdict(deque)

FLOOD_LIMIT = 6
FLOOD_SECONDS = 8

pending_mutes = {}
ad_waiting = set()

# =========================
# YORDAMCHI FUNKSIYALAR
# =========================

def ensure_group(chat):

    db.execute(
        """
        INSERT OR IGNORE INTO groups(
            chat_id,
            title
        )
        VALUES(?,?)
        """,
        (
            chat.id,
            chat.title or ""
        )
    )

    db.execute(
        """
        UPDATE groups
        SET title=?
        WHERE chat_id=?
        """,
        (
            chat.title or "",
            chat.id
        )
    )

    db.execute(
        """
        INSERT OR IGNORE INTO used_groups(
            chat_id
        )
        VALUES(?)
        """,
        (
            chat.id,
        )
    )

    db.commit()


def ensure_user(
    chat,
    user,
    increment=False,
    joined=0
):

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
        VALUES(?,?,?,?,0,?,0)
        """,
        (
            chat.id,
            user.id,
            user.full_name,
            user.username or "",
            joined
        )
    )

    db.execute(
        """
        UPDATE users
        SET name=?,
            username=?,
            messages=messages+?,
            joined=joined+?
        WHERE chat_id=?
        AND user_id=?
        """,
        (
            user.full_name,
            user.username or "",
            1 if increment else 0,
            joined,
            chat.id,
            user.id
        )
    )

    db.commit()


def ensure_private_user(user):

    db.execute(
        """
        INSERT OR REPLACE INTO private_users(
            user_id,
            name,
            username,
            started
        )
        VALUES(?,?,?,1)
        """,
        (
            user.id,
            user.full_name,
            user.username or ""
        )
    )

    db.commit()


async def is_admin(
    update,
    context,
    user_id=None
):

    chat = update.effective_chat

    if not chat:
        return False

    if user_id is None:

        if update.effective_user:
            user_id = update.effective_user.id

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


def get_warn(
    chat_id,
    user_id
):

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


def add_warn(
    chat_id,
    user_id
):

    count = get_warn(
        chat_id,
        user_id
    ) + 1

    db.execute(
        """
        INSERT OR REPLACE INTO warns(
            chat_id,
            user_id,
            count
        )
        VALUES(?,?,?)
        """,
        (
            chat_id,
            user_id,
            count
        )
    )

    db.commit()

    return count


def clear_warn(
    chat_id,
    user_id
):

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

    words = re.findall(
        r"[a-zA-Zа-яА-ЯёЁўқғҳʻʼ']+",
        text.lower()
    )

    return any(
        word in BAD_WORDS
        for word in words
    )


def parse_duration(value):

    match = re.fullmatch(
        r"(\d+)(min|m|h|d)",
        value.lower()
    )

    if not match:
        return None

    number = int(
        match.group(1)
    )

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


async def mute_user(
    context,
    chat_id,
    user_id,
    seconds
):

    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(
            can_send_messages=False
        ),
        until_date=int(
            time.time() + seconds
        )
    )


async def unmute_user(
    context,
    chat_id,
    user_id
):

    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
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


# =========================
# START
# =========================

async def start(
    update,
    context
):

    user = update.effective_user

    if user:
        ensure_private_user(user)

    bot_username = (
        context.bot.username or ""
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📖 Help",
                callback_data="help"
            ),

            InlineKeyboardButton(
                "🛡 Funksiyalar",
                callback_data="features"
            )
        ],

        [
            InlineKeyboardButton(
                "➕ Guruhga qo'shish",
                url=(
                    f"https://t.me/"
                    f"{bot_username}"
                    f"?startgroup=true"
                )
            )
        ],

        [
            InlineKeyboardButton(
                "📜 Qoidalar",
                callback_data="bot_rules"
            )
        ]

    ])

    await update.message.reply_text(

        "🤖 BMAX HELP BOT\n\n"

        "Guruhingizni himoya qilish va "
        "boshqarish uchun meni guruhga "
        "qo'shing va ADMIN qiling.\n\n"

        "👇 Kerakli bo'limni tanlang:",

        reply_markup=keyboard
    )


async def help_command(
    update,
    context
):

    await update.message.reply_text(

        "📖 BMAX HELP BOT — YORDAM\n\n"

        "👤 Oddiy foydalanuvchi:\n"
        "/start — bosh menyu\n"
        "/help — yordam\n"
        "/id — ID ko'rish\n"
        "/info — profil ma'lumoti\n\n"

        "👮 Admin:\n"
        "/panel — admin panel\n"
        "/rules — guruh qoidalari\n"
        "/stats — statistika\n"
        "/warn — warn\n"
        "/unwarn — warnni tozalash\n"
        "/ban — ban\n"
        "/kick — kick\n"
        ".mute 10min sabab — mute\n\n"

        "🔐 Himoya:\n"
        "CAPTCHA, havola bloklash, "
        "so'kinish filtri va flood nazorati."
    )


# =========================
# YANGI A'ZOLAR / CAPTCHA
# =========================

async def new_members(
    update,
    context
):

    message = update.message

    if not message:
        return

    chat = message.chat

    ensure_group(chat)

    for user in message.new_chat_members:

        if user.is_bot:
            continue

        ensure_user(
            chat,
            user,
            joined=1
        )

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
                VALUES(?,?)
                """,
                (
                    chat.id,
                    user.id
                )
            )

            db.commit()

            keyboard = InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "✅ Men bot emasman",
                        callback_data=(
                            f"captcha:"
                            f"{chat.id}:"
                            f"{user.id}"
                        )
                    )
                ]

            ])

            await message.reply_text(

                f"👋 Salom, "
                f"{user.full_name}!\n\n"

                "🔒 Guruhga yozish uchun "
                "quyidagi tugmani bosing.",

                reply_markup=keyboard
            )

        except Exception as e:

            logger.exception(
                "CAPTCHA error: %s",
                e
            )


async def captcha_button(
    update,
    context
):

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

        await unmute_user(
            context,
            chat_id,
            user_id
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

            f"✅ "
            f"{query.from_user.full_name} "
            "tasdiqlandi!\n"

            "Endi guruhda yozishingiz mumkin."
        )

    except Exception as e:

        logger.exception(
            "Captcha confirm error: %s",
            e
        )

        await query.answer(
            "❌ Botni admin qiling.",
            show_alert=True
        )


# =========================
# CHAT MEMBER
# =========================

async def chat_member_update(
    update,
    context
):

    cm = update.chat_member

    if not cm:
        return

    chat = cm.chat

    user = cm.new_chat_member.user

    ensure_group(chat)

    if cm.new_chat_member.status in (
        ChatMemberStatus.LEFT,
        ChatMemberStatus.BANNED
    ):

        db.execute(
            """
            UPDATE users
            SET left=left+1
            WHERE chat_id=?
            AND user_id=?
            """,
            (
                chat.id,
                user.id
            )
        )

        db.commit()


# =========================
# MODERATSIYA
# =========================

async def moderate(
    update,
    context
):

    message = update.message

    if not message:
        return

    chat = message.chat

    user = message.from_user

    ensure_group(chat)

    ensure_user(
        chat,
        user,
        increment=True
    )

    if await is_admin(
        update,
        context
    ):
        return

    # CAPTCHA

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

    text = message.text or ""

    # FLOOD

    now = time.time()

    queue = flood_cache[
        (chat.id, user.id)
    ]

    while (
        queue
        and
        now - queue[0] > FLOOD_SECONDS
    ):
        queue.popleft()

    queue.append(now)

    if len(queue) > FLOOD_LIMIT:

        try:

            await message.delete()

            await mute_user(
                context,
                chat.id,
                user.id,
                60
            )

            queue.clear()

            await context.bot.send_message(

                chat.id,

                f"🔇 {user.full_name} "
                "flood sababli "
                "1 daqiqaga mute qilindi."
            )

        except Exception as e:

            logger.exception(
                "Flood error: %s",
                e
            )

        return

    # LINK / REKLAMA

    if URL_RE.search(text):

        try:

            await message.delete()

            await context.bot.send_message(

                chat.id,

                f"🔗 {user.full_name}, "
                "guruhda reklama va "
                "havolalar taqiqlangan!"
            )

        except Exception:
            pass

        return

    # SO'KINISH

    if contains_bad_word(text):

        try:

            await message.delete()

            count = add_warn(
                chat.id,
                user.id
            )

            await context.bot.send_message(

                chat.id,

                f"⚠️ {user.full_name}\n"
                "🚫 So'kinish taqiqlangan.\n"
                f"Warn: {count}/3"
            )

            if count >= 3:

                await mute_user(
                    context,
                    chat.id,
                    user.id,
                    600
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

            logger.exception(
                "Bad word error: %s",
                e
            )


# =========================
# ID / INFO
# =========================

async def cmd_id(
    update,
    context
):

    await update.message.reply_text(

        f"👤 Sizning ID: "
        f"{update.effective_user.id}\n"

        f"👥 Chat ID: "
        f"{update.effective_chat.id}"
    )


async def cmd_info(
    update,
    context
):

    message = update.message

    if message.reply_to_message:

        user = (
            message.reply_to_message.from_user
        )

    else:

        user = update.effective_user

    warn = get_warn(
        message.chat.id,
        user.id
    )

    await message.reply_text(

        f"👤 Ism: {user.full_name}\n"
        f"🆔 ID: {user.id}\n"
        f"🔗 Username: "
        f"@{user.username or 'yoq'}\n"
        f"⚠️ Warn: {warn}"
    )


# =========================
# BAN
# =========================

async def cmd_ban(
    update,
    context
):

    message = update.message

    if not await is_admin(
        update,
        context
    ):
        return

    if not message.reply_to_message:

        await message.reply_text(
            "❗ Xabarga reply qilib "
            "/ban yozing."
        )

        return

    user = (
        message.reply_to_message.from_user
    )

    try:

        await context.bot.ban_chat_member(
            message.chat.id,
            user.id
        )

        await message.reply_text(
            f"🔨 {user.full_name} "
            "ban qilindi."
        )

    except Exception as e:

        logger.exception(
            "Ban error: %s",
            e
        )

        await message.reply_text(
            "❌ Ban qilishda xatolik."
        )


# =========================
# KICK
# =========================

async def cmd_kick(
    update,
    context
):

    message = update.message

    if not await is_admin(
        update,
        context
    ):
        return

    if not message.reply_to_message:

        await message.reply_text(
            "❗ Xabarga reply qilib "
            "/kick yozing."
        )

        return

    user = (
        message.reply_to_message.from_user
    )

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
            f"👢 {user.full_name} "
            "guruhdan chiqarildi."
        )

    except Exception as e:

        logger.exception(
            "Kick error: %s",
            e
        )


# =========================
# WARN
# =========================

async def cmd_warn(
    update,
    context
):

    message = update.message

    if not await is_admin(
        update,
        context
    ):
        return

    if not message.reply_to_message:

        await message.reply_text(
            "❗ Xabarga reply qilib "
            "/warn yozing."
        )

        return

    user = (
        message.reply_to_message.from_user
    )

    count = add_warn(
        message.chat.id,
        user.id
    )

    await message.reply_text(

        f"⚠️ {user.full_name} "
        "ogohlantirildi.\n"

        f"Warn: {count}/3"
    )

    if count >= 3:

        try:

            await mute_user(
                context,
                message.chat.id,
                user.id,
                600
            )

            clear_warn(
                message.chat.id,
                user.id
            )

            await message.reply_text(

                f"🔇 {user.full_name} "
                "10 daqiqaga mute qilindi."
            )

        except Exception as e:

            logger.exception(
                "Warn mute error: %s",
                e
            )


# =========================
# UNWARN
# =========================

async def cmd_unwarn(
    update,
    context
):

    message = update.message

    if not await is_admin(
        update,
        context
    ):
        return

    if not message.reply_to_message:

        await message.reply_text(
            "❗ Xabarga reply qilib "
            "/unwarn yozing."
        )

        return

    user = (
        message.reply_to_message.from_user
    )

    clear_warn(
        message.chat.id,
        user.id
    )

    await message.reply_text(

        f"✅ {user.full_name} "
        "warnlari tozalandi."
    )


# =========================
# MUTE
# =========================

async def mute_command(
    update,
    context
):

    message = update.message

    if not await is_admin(
        update,
        context
    ):
        return

    if not message.reply_to_message:

        await message.reply_text(

            "❗ Reply qiling:\n"
            ".mute 10min sabab"
        )

        return

    parts = message.text.split(
        maxsplit=2
    )

    if len(parts) < 2:

        await message.reply_text(

            "Misol:\n"
            ".mute 10min sabab"
        )

        return

    seconds = parse_duration(
        parts[1]
    )

    if seconds is None:

        await message.reply_text(

            "❌ Vaqt noto'g'ri.\n\n"

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
        else "Sabab ko'rsatilmagan"
    )

    user = (
        message.reply_to_message.from_user
    )

    request_id = str(
        time.time_ns()
    )

    pending_mutes[request_id] = {

        "chat_id":
            message.chat.id,

        "user_id":
            user.id,

        "name":
            user.full_name,

        "seconds":
            seconds,

        "reason":
            reason
    }

    keyboard = InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "✅ Tasdiqlash",
                callback_data=(
                    f"mute_yes:"
                    f"{request_id}"
                )
            ),

            InlineKeyboardButton(
                "❌ Bekor qilish",
                callback_data=(
                    f"mute_no:"
                    f"{request_id}"
                )
            )

        ]

    ])

    await message.reply_text(

        f"🔇 MUTE SO'ROVI\n\n"

        f"👤 Ism: {user.full_name}\n"

        f"⏱ Muddati: "
        f"{duration_text(seconds)}\n"

        f"📝 Sababi: {reason}\n\n"

        "👮 Tasdiqlaysizmi?",

        reply_markup=keyboard
    )


async def mute_callback(
    update,
    context
):

    query = update.callback_query

    parts = query.data.split(":")

    action = parts[0]

    request_id = parts[1]

    data = pending_mutes.get(
        request_id
    )

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
            "❌ Faqat admin.",
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

    try:

        chat_id = data["chat_id"]

        user_id = data["user_id"]

        seconds = data["seconds"]

        reason = data["reason"]

        await mute_user(
            context,
            chat_id,
            user_id,
            seconds
        )

        until_time = int(
            time.time() + seconds
        )

        db.execute(

            """
            INSERT OR REPLACE INTO muted(
                chat_id,
                user_id,
                until_time,
                reason
            )
            VALUES(?,?,?,?)
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
                        f"unmute:"
                        f"{chat_id}:"
                        f"{user_id}"
                    )
                )

            ]

        ])

        await query.edit_message_text(

            f"🔇 MUTE\n\n"

            f"👤 Ism: "
            f"{data['name']}\n"

            f"⏱ Muddati: "
            f"{duration_text(seconds)}\n"

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

        logger.exception(
            "Mute error: %s",
            e
        )

        await query.answer(
            "❌ Mute qilishda xatolik.",
            show_alert=True
        )


async def unmute_callback(
    update,
    context
):

    query = update.callback_query

    parts = query.data.split(":")

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

        await unmute_user(
            context,
            chat_id,
            user_id
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
            "🔊 Foydalanuvchi "
            "mutedan chiqarildi."
        )

        await query.answer(
            "✅ Tayyor."
        )

    except Exception as e:

        logger.exception(
            "Unmute error: %s",
            e
        )

        await query.answer(
            "❌ Xatolik.",
            show_alert=True
        )


# =========================
# RULES
# =========================

async def cmd_rules(
    update,
    context
):

    chat_id = (
        update.effective_chat.id
    )

    ensure_group(
        update.effective_chat
    )

    row = db.execute(

        """
        SELECT rules
        FROM groups
        WHERE chat_id=?
        """,

        (
            chat_id,
        )
    ).fetchone()

    rules = (
        row[0]
        if row
        else "Qoidalar yo'q."
    )

    await update.message.reply_text(

        "📜 GURUH QOIDALARI\n\n"
        + rules
    )


# =========================
# STATS
# =========================

async def cmd_stats(
    update,
    context
):

    chat_id = (
        update.effective_chat.id
    )

    try:

        members = (
            await context.bot
            .get_chat_member_count(
                chat_id
            )
        )

    except Exception:

        members = "Noma'lum"

    row = db.execute(

        """
        SELECT COUNT(*),
               COALESCE(
                   SUM(messages),0
               ),
               COALESCE(
                   SUM(joined),0
               ),
               COALESCE(
                   SUM(left),0
               )
        FROM users
        WHERE chat_id=?
        """,

        (
            chat_id,
        )
    ).fetchone()

    await update.message.reply_text(

        "📊 GURUH STATISTIKASI\n\n"

        f"👥 A'zolar: {members}\n"

        f"👤 Kuzatilganlar: "
        f"{row[0]}\n"

        f"💬 Xabarlar: "
        f"{row[1]}\n"

        f"🟢 Kirganlar: "
        f"{row[2]}\n"

        f"🔴 Chiqib ketganlar: "
        f"{row[3]}"
    )


# =========================
# PANEL
# =========================

async def cmd_panel(
    update,
    context
):

    if not await is_admin(
        update,
        context
    ):
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

        "⚙️ BMAX HELP BOT — "
        "ADMIN PANEL\n\n"

        "Bo'limni tanlang:",

        reply_markup=keyboard
    )


async def panel_callback(
    update,
    context
):

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

            "🛡 HIMOYA\n\n"

            "✅ CAPTCHA\n"
            "✅ So'kinish filtri\n"
            "✅ Reklama/havola bloklash\n"
            "✅ Flood nazorati\n"
            "✅ Warn / Ban / Kick / Mute"
        )

    elif query.data == "panel_rules":

        row = db.execute(

            """
            SELECT rules
            FROM groups
            WHERE chat_id=?
            """,

            (
                query.message.chat.id,
            )
        ).fetchone()

        await query.edit_message_text(

            "📜 QOIDALAR\n\n"

            + (
                row[0]
                if row
                else "Qoidalar yo'q."
            )
        )

    elif query.data == "panel_stats":

        await query.edit_message_text(

            "📊 Statistikani ko'rish uchun:\n"
            "/stats"
        )


# =========================
# START TUGMALARI
# =========================

async def general_callback(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    if query.data == "help":

        await query.edit_message_text(

            "📖 YORDAM\n\n"

            "/start — bosh menyu\n"
            "/help — yordam\n"
            "/id — ID\n"
            "/info — ma'lumot\n"
            "/panel — admin panel\n"
            "/rules — qoidalar\n"
            "/stats — statistika"
        )

    elif query.data == "features":

        await query.edit_message_text(

            "🛡 BMAX HELP BOT\n\n"

            "• CAPTCHA\n"
            "• Havola/reklama bloklash\n"
            "• So'kinish filtri\n"
            "• Flood himoyasi\n"
            "• Warn 3/3 → mute\n"
            "• Ban / Kick\n"
            "• Mute / Unmute\n"
            "• Statistika"
        )

    elif query.data == "bot_rules":

        await query.edit_message_text(

            "📜 BOT QOIDASI\n\n"

            "Botni guruhga qo'shgach "
            "ADMIN qiling.\n\n"

            "Shunda moderatsiya va "
            "CAPTCHA ishlaydi."
        )


# =========================
# REKLAMA
# =========================

async def cmd_reklama(
    update,
    context
):

    user_id = (
        update.effective_user.id
    )

    if user_id not in OWNER_IDS:

        await update.message.reply_text(
            "❌ Bu buyruq faqat "
            "bot egalari uchun."
        )

        return

    ad_waiting.add(
        user_id
    )

    await update.message.reply_text(

        "📢 Reklama yuboring.\n\n"

        "Matn yoki rasm+caption.\n\n"

        "Tasdiqlasangiz "
        "BIR MARTA yuboriladi."
    )


async def receive_ad(
    update,
    context
):

    user_id = (
        update.effective_user.id
    )

    if user_id not in OWNER_IDS:
        return

    if (
        update.effective_chat.type
        != "private"
    ):
        return

    if user_id not in ad_waiting:
        return

    if (
        not update.message.text
        and not update.message.photo
    ):
        return

    ad_waiting.remove(
        user_id
    )

    text = (

        update.message.text
        or update.message.caption
        or ""
    )

    photo_id = None

    if update.message.photo:

        photo_id = (
            update.message
            .photo[-1]
            .file_id
        )

    db.execute(

        """
        INSERT OR REPLACE INTO advertisements(
            id,
            text,
            photo_id,
            enabled
        )
        VALUES(1,?,?,0)
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
                "❌ Bekor",
                callback_data="ad_no"
            ),

            InlineKeyboardButton(
                "📢 1 MARTA YUBORISH",
                callback_data="ad_yes"
            )

        ]

    ])

    await update.message.reply_text(

        "📣 Reklama tayyor.\n\n"

        "Tasdiqlasangiz barcha "
        "saqlangan guruhlarga va "
        "/start yuborgan "
        "foydalanuvchilarga "
        "BIR MARTA yuboriladi.",

        reply_markup=keyboard
    )


async def ad_callback(
    update,
    context
):

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
            "❌ Reklama bekor qilindi."
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

    await query.edit_message_text(

        "⏳ Reklama yuborilmoqda...\n\n"

        "Bu avtomatik har daqiqada "
        "yuborilmaydi."
    )

    await query.answer()

    groups = [

        r[0]

        for r in db.execute(
            """
            SELECT chat_id
            FROM used_groups
            """
        ).fetchall()

    ]

    users = [

        r[0]

        for r in db.execute(
            """
            SELECT user_id
            FROM private_users
            """
        ).fetchall()

    ]

    sent = 0
    failed = 0

    # GURUHLARGA
    for chat_id in groups:

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

                failed += 1

                continue

            sent += 1

        except Exception as e:

            failed += 1

            logger.warning(
                "Ad group %s failed: %s",
                chat_id,
                e
            )

    # FOYDALANUVCHILARGA
    for user_id in users:

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

                failed += 1

                continue

            sent += 1

        except Exception as e:

            failed += 1

            logger.warning(
                "Ad user %s failed: %s",
                user_id,
                e
            )

    # AVTOMATIK TAKRORLASH YO'Q
    db.execute(

        """
        UPDATE advertisements
        SET enabled=0
        WHERE id=1
        """
    )

    db.commit()

    try:

        await context.bot.send_message(

            query.from_user.id,

            f"✅ Reklama yuborildi!\n\n"

            f"📨 Yetkazildi: {sent}\n"

            f"❌ Yuborilmadi: {failed}\n\n"

            "🔁 Yana yuborish uchun "
            "/reklama ni bosing."
        )

    except Exception:
        pass


# =========================
# MAIN
# =========================

def main():

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # COMMANDLAR

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

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

    app.add_handler(
        CommandHandler(
            "reklama",
            cmd_reklama
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

    # .mute

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

    # START TUGMALARI

    app.add_handler(

        CallbackQueryHandler(

            general_callback,

            pattern=r"^(help|features|bot_rules)$"
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

    # GROUP MODERATION

    app.add_handler(

        MessageHandler(

            filters.ChatType.GROUPS
            & filters.TEXT,

            moderate
        )
    )

    logger.info(
        "BMAX HELP BOT ishga tushdi!"
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()