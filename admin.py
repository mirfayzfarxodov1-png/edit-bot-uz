"""
Admin panel - faqat ADMIN_IDS uchun
Bot statistikasi, foydalanuvchi boshqaruvi, broadcast, loglar va sozlamalar
"""
import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import ADMIN_IDS, ADMIN_VIDEOS_DIR, LOG_FILE
from utils import (
    get_users, get_stats, get_bot_settings, save_bot_settings,
    block_user, unblock_user, set_premium,
    get_all_users_list, get_recent_logs, logger, safe_delete_file
)
from states import state_manager, UserState


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_admin_keyboard():
    """Admin panel tugmalar klaviaturasi"""
    keyboard = [
        [InlineKeyboardButton("📤 Video joylash", callback_data="admin_upload_video"),
         InlineKeyboardButton("🗑 Video o'chirish", callback_data="admin_delete_video")],
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats"),
         InlineKeyboardButton("📈 Grafika", callback_data="admin_graph")],
        [InlineKeyboardButton("📨 Xabar yuborish", callback_data="admin_broadcast"),
         InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="admin_users")],
        [InlineKeyboardButton("⚙️ Sozlamalar", callback_data="admin_settings"),
         InlineKeyboardButton("📋 Loglar", callback_data="admin_logs")],
        [InlineKeyboardButton("🔄 Qayta ishga tushirish", callback_data="admin_restart"),
         InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/admin buyrug'i - Admin panelni ochish"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Bu buyruq faqat adminlar uchun!")
        return

    stats = get_stats()
    users = get_users()
    text = (
        "🔐 **Admin Panel - Edit Bot.uz**\n\n"
        f"👥 Jami foydalanuvchilar: `{len(users)}`\n"
        f"🎬 Jami generatsiyalar: `{stats.get('total_generations', 0)}`\n"
        f"📅 Bugun: `{stats.get('daily_stats', {}).get(str(datetime.now().date()), 0)}`\n\n"
        "Quyidagi tugmalardan birini tanlang:"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=get_admin_keyboard())


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel callback handler"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.edit_message_text("❌ Ruxsat yo'q!")
        return

    data = query.data

    if data == "admin_stats":
        await show_statistics(query)
    elif data == "admin_graph":
        await show_graph(query)
    elif data == "admin_broadcast":
        await start_broadcast(query, context)
    elif data == "admin_users":
        await show_users_list(query)
    elif data == "admin_upload_video":
        await start_video_upload(query, context)
    elif data == "admin_delete_video":
        await delete_admin_video(query)
    elif data == "admin_settings":
        await show_settings(query, context)
    elif data == "admin_logs":
        await show_logs(query)
    elif data == "admin_restart":
        await restart_bot(query, context)
    elif data == "admin_back":
        stats = get_stats()
        users = get_users()
        text = (
            "🔐 **Admin Panel - Edit Bot.uz**\n\n"
            f"👥 Jami foydalanuvchilar: `{len(users)}`\n"
            f"🎬 Jami generatsiyalar: `{stats.get('total_generations', 0)}`\n"
            f"📅 Bugun: `{stats.get('daily_stats', {}).get(str(datetime.now().date()), 0)}`\n\n"
            "Quyidagi tugmalardan birini tanlang:"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=get_admin_keyboard())
    elif data.startswith("admin_block_"):
        target_id = int(data.split("_")[2])
        if block_user(target_id):
            await query.edit_message_text(f"✅ Foydalanuvchi {target_id} bloklandi!")
        else:
            await query.edit_message_text("❌ Bloklashda xatolik!")
    elif data.startswith("admin_unblock_"):
        target_id = int(data.split("_")[2])
        if unblock_user(target_id):
            await query.edit_message_text(f"✅ Foydalanuvchi {target_id} blokdan chiqarildi!")
        else:
            await query.edit_message_text("❌ Xatolik!")
    elif data.startswith("admin_premium_"):
        target_id = int(data.split("_")[2])
        if set_premium(target_id, True):
            await query.edit_message_text(f"✅ Foydalanuvchi {target_id} ga premium berildi!")
        else:
            await query.edit_message_text("❌ Xatolik!")
    elif data == "admin_settings_maintenance":
        await toggle_maintenance(query)
    elif data == "admin_settings_free_edits":
        await change_free_edits(query, context)
    elif data.startswith("set_edits_"):
        val = int(data.split("_")[2])
        settings = get_bot_settings()
        settings["free_daily_edits"] = val if val < 9999 else 9999
        save_bot_settings(settings)
        await query.edit_message_text(f"✅ Kunlik bepul editlar: {val if val < 9999 else 'Cheksiz'}")
    elif data.startswith("admin_page_"):
        page = int(data.split("_")[2])
        await show_users_list(query, page=page)


async def show_statistics(query):
    """Bot statistikasini ko'rsatish"""
    stats = get_stats()
    users = get_users()

    daily_stats = stats.get("daily_stats", {})
    last_7_days = []
    for i in range(7):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        count = daily_stats.get(day, 0)
        last_7_days.append(f"  {day}: {count} ta edit")

    popular = stats.get("popular_edits", {})
    sorted_popular = sorted(popular.items(), key=lambda x: x[1], reverse=True)[:5]
    popular_text = "\n".join([f"  {k}: {v} ta" for k, v in sorted_popular]) or "Ma'lumot yo'q"

    premium_count = sum(1 for u in users.values() if u.get("is_premium"))
    blocked_count = sum(1 for u in users.values() if u.get("is_blocked"))

    text = (
        "📊 **Bot Statistikasi**\n\n"
        f"👥 Jami foydalanuvchilar: `{len(users)}`\n"
        f"⭐ Premium: `{premium_count}`\n"
        f"🚫 Bloklangan: `{blocked_count}`\n"
        f"🎬 Jami generatsiyalar: `{stats.get('total_generations', 0)}`\n\n"
        f"📅 **So'nggi 7 kun:**\n" + "\n".join(last_7_days) +
        f"\n\n🔥 **Mashhur editlar:**\n{popular_text}"
    )
    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def show_graph(query):
    """Kunlik grafik (text ko'rinishida)"""
    stats = get_stats()
    daily_stats = stats.get("daily_stats", {})

    days_data = []
    max_count = 1
    for i in range(10):
        day = (datetime.now() - timedelta(days=9 - i)).strftime("%Y-%m-%d")
        count = daily_stats.get(day, 0)
        days_data.append((day[-5:], count))
        max_count = max(max_count, count)

    graph_lines = ["📈 **Kunlik generatsiyalar grafigi:**\n"]
    for date_str, count in days_data:
        bar_length = int(15 * count / max_count) if max_count > 0 else 0
        bar = "█" * bar_length + "░" * (15 - bar_length)
        graph_lines.append(f"`{date_str}` [{bar}] {count}")

    text = "\n".join(graph_lines)
    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def start_broadcast(query, context):
    """Broadcast xabar yuborish jarayonini boshlash"""
    user_id = query.from_user.id
    state_manager.set_state(user_id, UserState.WAITING_BROADCAST)
    text = (
        "📨 **Broadcast Xabar**\n\n"
        "Barcha foydalanuvchilarga yuboriladigan xabarni yozing.\n"
        "Matn, rasm, video qabul qilinadi.\n\n"
        "❌ Bekor qilish: /cancel"
    )
    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def send_broadcast(update, context):
    """Barcha foydalanuvchilarga xabar yuborish"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    users = get_users()
    total = len(users)
    sent = 0
    failed = 0

    await update.message.reply_text(f"📨 Broadcast boshlandi... {total} ta foydalanuvchi")

    for uid_str, user_data in users.items():
        uid = int(uid_str)
        if user_data.get("is_blocked"):
            continue
        try:
            if update.message.photo:
                await context.bot.send_photo(chat_id=uid,
                    photo=update.message.photo[-1].file_id,
                    caption=update.message.caption or "")
            elif update.message.video:
                await context.bot.send_video(chat_id=uid,
                    video=update.message.video.file_id,
                    caption=update.message.caption or "")
            elif update.message.text:
                await context.bot.send_message(chat_id=uid, text=update.message.text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.warning(f"Broadcast xatolik {uid}: {e}")

    state_manager.reset_state(user_id)
    await update.message.reply_text(
        f"✅ Broadcast tugadi!\n✅ Yuborildi: {sent}\n❌ Xatolik: {failed}\n📊 Jami: {total}"
    )


async def show_users_list(query, page=0, per_page=5):
    """Foydalanuvchilar ro'yxati (sahifalar bilan)"""
    all_users = get_all_users_list()
    total = len(all_users)
    start = page * per_page
    end = min(start + per_page, total)
    current_users = all_users[start:end]

    lines = [f"👥 **Foydalanuvchilar** ({start+1}-{end} / {total})\n"]
    for user in current_users:
        uid = user.get("user_id", "?")
        name = user.get("first_name", "Nomsiz")
        username = user.get("username", "")
        edits = user.get("total_edits", 0)
        premium = "⭐" if user.get("is_premium") else ""
        blocked = "🚫" if user.get("is_blocked") else ""
        lines.append(f"{premium}{blocked} `{uid}` - {name}"
                     f"{' (@' + username + ')' if username else ''} | Edit: {edits}")

    text = "\n".join(lines)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Oldingi", callback_data=f"admin_page_{page-1}"))
    if end < total:
        nav_buttons.append(InlineKeyboardButton("Keyingi ▶️", callback_data=f"admin_page_{page+1}"))

    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def start_video_upload(query, context):
    """Admin video yuklash jarayonini boshlash"""
    user_id = query.from_user.id
    state_manager.set_state(user_id, UserState.WAITING_ADMIN_VIDEO)
    text = (
        "📤 **Admin Video Yuklash**\n\n"
        "Video yuboring. Bu video /start ga javoban yangi foydalanuvchilarga ko'rsatiladi.\n\n"
        "❌ Bekor qilish: /cancel"
    )
    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_admin_video_upload(update, context):
    """Admin yuborgan videoni saqlash"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    msg = await update.message.reply_text("⏳ Video yuklanmoqda...")
    try:
        video = update.message.video or update.message.document
        if not video:
            await msg.edit_text("❌ Video yuborilmadi!")
            return

        if os.path.exists(ADMIN_VIDEOS_DIR):
            for f in os.listdir(ADMIN_VIDEOS_DIR):
                await safe_delete_file(os.path.join(ADMIN_VIDEOS_DIR, f))

        file = await video.get_file()
        filename = f"admin_video_{int(asyncio.get_event_loop().time())}.mp4"
        filepath = os.path.join(ADMIN_VIDEOS_DIR, filename)
        await file.download_to_drive(filepath)

        state_manager.reset_state(user_id)
        await msg.edit_text(f"✅ Admin video saqlandi!\nFayl: `{filename}`",
                            parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Admin video yuklashda xatolik: {e}")
        await msg.edit_text(f"❌ Xatolik: {e}")
        state_manager.reset_state(user_id)


async def delete_admin_video(query):
    """Admin videoni o'chirish"""
    try:
        deleted = 0
        if os.path.exists(ADMIN_VIDEOS_DIR):
            for f in os.listdir(ADMIN_VIDEOS_DIR):
                await safe_delete_file(os.path.join(ADMIN_VIDEOS_DIR, f))
                deleted += 1
        keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
        await query.edit_message_text(f"🗑 {deleted} ta admin video o'chirildi!",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Admin video o'chirishda xatolik: {e}")


async def show_settings(query, context):
    """Bot sozlamalarini ko'rsatish"""
    settings = get_bot_settings()
    maintenance = "✅ Yoqilgan" if settings.get("maintenance_mode") else "❌ O'chirilgan"
    text = (
        "⚙️ **Bot Sozlamalari**\n\n"
        f"🔧 Texnik xizmat: {maintenance}\n"
        f"📊 Kunlik bepul editlar: `{settings.get('free_daily_edits', 5)}`\n"
        f"📁 Max fayl hajmi: `{settings.get('max_file_size', 50)}MB`\n"
        f"🎁 Referral bonus: `{settings.get('referral_bonus', 3)} edit`\n"
    )
    keyboard = [
        [InlineKeyboardButton("🔧 Texnik xizmat", callback_data="admin_settings_maintenance"),
         InlineKeyboardButton("📊 Editlar soni", callback_data="admin_settings_free_edits")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def toggle_maintenance(query):
    """Texnik xizmat rejimini yoqish/o'chirish"""
    settings = get_bot_settings()
    settings["maintenance_mode"] = not settings.get("maintenance_mode", False)
    save_bot_settings(settings)
    status = "✅ Yoqildi" if settings["maintenance_mode"] else "❌ O'chirildi"
    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_settings")]]
    await query.edit_message_text(f"🔧 Texnik xizmat: {status}",
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def change_free_edits(query, context):
    """Kunlik bepul editlar sonini o'zgartirish"""
    keyboard = [
        [InlineKeyboardButton("3", callback_data="set_edits_3"),
         InlineKeyboardButton("5", callback_data="set_edits_5"),
         InlineKeyboardButton("10", callback_data="set_edits_10")],
        [InlineKeyboardButton("20", callback_data="set_edits_20"),
         InlineKeyboardButton("Cheksiz", callback_data="set_edits_9999")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_settings")],
    ]
    await query.edit_message_text("📊 Kunlik bepul editlar sonini tanlang:",
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def show_logs(query):
    """So'nggi loglarni ko'rsatish"""
    logs = get_recent_logs(30)
    if not logs:
        logs = "Log yozuvlari topilmadi."
    if len(logs) > 3500:
        logs = "...\n" + logs[-3500:]
    text = f"📋 **So'nggi Loglar:**\n\n```\n{logs}\n```"
    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def restart_bot(query, context):
    """Bot holatini qayta ishga tushirish"""
    await query.edit_message_text("🔄 Bot qayta ishga tushirilmoqda...")
    logger.info("Admin tomonidan qayta ishga tushirish buyurildi")
    users = get_users()
    for uid_str in users:
        uid = int(uid_str)
        state_manager.cancel_task(uid)
        state_manager.reset_state(uid)
    await asyncio.sleep(1)
    await query.edit_message_text("✅ Bot qayta ishga tushirildi!\n\n/admin - Panelga qaytish")


async def handle_user_management(update, context):
    """
    Foydalanuvchini boshqarish buyruqlari:
    /block <id>, /unblock <id>, /premium <id>, /unpremium <id>
    """
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("❌ Foydalanuvchi ID si ko'rsatilmagan!")
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ ID raqam bo'lishi kerak!")
        return

    command = update.message.text.split()[0][1:]

    if command == "block":
        if block_user(target_id):
            await update.message.reply_text(f"✅ Foydalanuvchi {target_id} bloklandi!")
        else:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
    elif command == "unblock":
        if unblock_user(target_id):
            await update.message.reply_text(f"✅ Foydalanuvchi {target_id} blokdan chiqarildi!")
        else:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
    elif command == "premium":
        if set_premium(target_id, True):
            await update.message.reply_text(f"✅ Foydalanuvchi {target_id} ga premium berildi!")
        else:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
    elif command == "unpremium":
        if set_premium(target_id, False):
            await update.message.reply_text(f"✅ Foydalanuvchi {target_id} premiumi olindi!")
        else:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
