"""
Edit Bot.uz - Asosiy bot fayli
Barcha handlerlar va buyruqlar shu yerda
"""
import os
import sys
import asyncio
import logging
import time
import json
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode, ChatAction
from telegram.error import BadRequest, Forbidden, TimedOut

from config import (
    BOT_TOKEN, ADMIN_IDS, OWNER_ID,
    MAX_FILE_SIZE, MAX_ROUND_DURATION,
    DOWNLOADS_DIR, OUTPUTS_DIR, TEMP_DIR, MUSIC_DIR, ADMIN_VIDEOS_DIR,
    SPEED_OPTIONS, MUSIC_LIBRARY, FILTER_OPTIONS,
    TEXT_POSITIONS, TEXT_SIZES, TEXT_COLORS, CROP_RATIOS,
    QUALITY_OPTIONS, PROGRESS_UPDATE_INTERVAL,
)
from states import state_manager, UserState
from utils import (
    setup_directories, register_user, get_user, increment_user_edits,
    check_daily_limit, is_user_blocked, is_admin, is_premium,
    parse_time_to_seconds, seconds_to_time_str, format_file_size,
    generate_progress_bar, calculate_remaining_time,
    generate_unique_filename, get_admin_video, get_users, get_stats,
    safe_delete_file, cleanup_temp_files, get_bot_settings,
    save_users, validate_link, logger,
)
from video_editor import (
    check_ffmpeg, trim_video, add_watermark, add_music, change_speed,
    apply_filter, make_round_video, merge_videos, compress_video,
    crop_video, rotate_video, reverse_video, video_to_gif,
    video_to_sticker, get_video_info,
)
from downloader import (
    download_video, download_audio_only, get_video_info_ytdlp,
    detect_platform, is_supported_url, get_supported_platforms_text,
    check_ytdlp_installed,
)
from admin import (
    admin_command, admin_callback, send_broadcast,
    handle_admin_video_upload, is_admin as check_is_admin,
    handle_user_management,
)

# ============================================================
# GLOBAL O'ZGARUVCHILAR
# ============================================================

# Video yuklab olish holati - foydalanuvchi yuborgan videoni saqlash
user_videos = {}  # {user_id: filepath}
# Merge uchun videolar
merge_videos = {}  # {user_id: [filepath1, filepath2, ...]}
# Musiqa holati
user_music_choice = {}  # {user_id: audio_path}
# Generatsiya holati
generation_status = {}  # {user_id: {"active": bool, "type": str, "start_time": float}}


# ============================================================
# PROGRESS BAR FUNKSIYASI
# ============================================================

async def update_progress(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    user_id: int, start_time: float, message_text: str = None
):
    """
    Progress bar yangilash - har 18 sekundda
    
    Args:
        update: Telegram update
        context: Bot context
        user_id: Foydalanuvchi ID
        start_time: Boshlanish vaqti
        message_text: Progress xabar matni
    """
    percent = 10
    msg = None
    
    try:
        if message_text:
            msg = await context.bot.send_message(
                chat_id=user_id,
                text=f"🔄 Generatsiya boshlandi... (3 daqiqa)\n{generate_progress_bar(percent)}\nTaxminan 180 soniya qoldi"
            )
        else:
            return
        
        while percent < 100:
            # Bekor qilish tekshirish
            if state_manager.should_cancel(user_id):
                await msg.edit_text("❌ Generatsiya bekor qilindi!")
                return
            
            await asyncio.sleep(PROGRESS_UPDATE_INTERVAL)
            
            percent = min(90, percent + 15)
            remaining = calculate_remaining_time(start_time, percent)
            
            try:
                await msg.edit_text(
                    f"🔄 Generatsiya davom etmoqda...\n"
                    f"{generate_progress_bar(percent)}\n"
                    f"Taxminan {remaining} qoldi"
                )
            except BadRequest:
                pass  # Xabar o'zgarmagan - o'tkazib yuboramiz
        
        # 100% ga yetganda
        try:
            await msg.edit_text("✅ Edit tayyor! Yuklanmoqda...")
        except BadRequest:
            pass
            
    except Exception as e:
        logger.error(f"Progress yangilashda xatolik: {e}")


# ============================================================
# ASOSIY BUYRUQLAR
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start - Botni ishga tushirish
    Yangi foydalanuvchiga admin videosi va salom yuboriladi
    """
    user = update.effective_user
    user_id = user.id
    
    # Foydalanuvchini ro'yxatdan o'tkazish
    register_user(user_id, user.username, user.first_name, user.last_name)
    
    # Bloklangan foydalanuvchi tekshirish
    if is_user_blocked(user_id):
        await update.message.reply_text(
            "🚫 Siz bloklangansiz. Botdan foydalanish mumkin emas."
        )
        return
    
    # Texnik xizmat rejimi tekshirish
    settings = get_bot_settings()
    if settings.get("maintenance_mode") and not is_admin(user_id):
        await update.message.reply_text(
            "🔧 Bot hozirda texnik xizmat rejimida. Keyinroq urinib ko'ring."
        )
        return
    
    # Salom xabar
    first_name = user.first_name or "Foydalanuvchi"
    welcome_text = (
        f"👋 Salom, {first_name}!\n\n"
        f"🎬 **Edit Bot.uz** - Video edit botiga xush kelibsiz!\n\n"
        f"📌 Bu bot orqali siz:\n"
        f"• Videoni kesishing mumkin (/trim)\n"
        f"• Videoga matn qo'shishing mumkin (/watermark)\n"
        f"• Videoga musiqa qo'shishing mumkin (/music)\n"
        f"• Tezlikni o'zgartirishing mumkin (/speed)\n"
        f"• Filter qo'shishing mumkin (/filter)\n"
        f"• Aylana video yuborishing mumkin (/round)\n"
        f"• Videolarni birlashtirishing mumkin (/merge)\n"
        f"• Va boshqalar...\n\n"
        f"📝 Batafsil: /help\n"
        f"🔗 Linkdan video yuklash ham mumkin!"
    )
    
    # Admin videosini yuborish
    admin_video = get_admin_video()
    if admin_video and os.path.exists(admin_video):
        try:
            await context.bot.send_video(
                chat_id=user_id,
                video=InputFile(admin_video),
                caption=welcome_text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Admin video yuborishda xatolik: {e}")
            await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)
    
    # 1 minutdan keyin tushuntirish xabari
    async def send_explanation():
        await asyncio.sleep(60)
        try:
            explanation = (
                "📝 **Botdan foydalanish bo'yicha qo'llanma:**\n\n"
                "1️⃣ Video yuboring yoki link jo'nating\n"
                "2️⃣ Edit turini tanlang (trim, music, filter, va h.k.)\n"
                "3️⃣ Kerakli parametrlarni kiriting\n"
                "4️⃣ Natijani kuting (taxminan 3 daqiqa)\n\n"
                "🔗 Linkdan yuklash uchun YouTube, Instagram, TikTok, "
                "Twitter, Facebook, Reddit, Vimeo va boshqalardan "
                "link jo'nating.\n\n"
                "❓ Yordam: /help"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=explanation,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Tushuntirish xabari xatolik: {e}")
    
    asyncio.create_task(send_explanation())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /help - Yordam menyusi
    Barcha buyruqlar ro'yxati
    """
    user_id = update.effective_user.id
    if is_user_blocked(user_id):
        return
    
    # Kunlik limit tekshirish
    can_edit, remaining = check_daily_limit(user_id)
    
    help_text = (
        "📋 **Edit Bot.uz - Yordam menyusi**\n\n"
        "🎬 **Video Edit Buyruqlari:**\n"
        "/trim - Video kesish\n"
        "/watermark - Matn qo'shish\n"
        "/music - Musiqa qo'shish\n"
        "/speed - Tezlikni o'zgartirish\n"
        "/filter - Filter qo'shish\n"
        "/round - Aylana video (video note)\n"
        "/merge - Videolarni birlashtirish\n"
        "/compress - Videoni siqish\n"
        "/crop - Kesib olish\n"
        "/rotate - Aylantirish\n"
        "/reverse - Teskari video\n"
        "/gif - GIF yaratish\n"
        "/sticker - Sticker yaratish\n"
        "/info - Video ma'lumoti\n\n"
        "🔧 **Boshqa buyruqlar:**\n"
        "/cancel - Jarayonni bekor qilish\n"
        "/status - Generatsiya holati\n\n"
        f"📊 **Sizning holatingiz:**\n"
        f"Kunlik qolgan editlar: `{remaining}`{' (cheksiz)' if remaining >= 9999 else ''}\n"
        f"⭐ Premium: {'Ha' if is_premium(user_id) else 'Yoq'}\n\n"
        "🔗 **Link yuklash:** YouTube, Instagram, TikTok, "
        "Twitter, Facebook, Reddit, Vimeo, Twitch, Pinterest, Telegram\n\n"
        f"📥 Qo'llab-quvvatlanadigan platformalar:\n{get_supported_platforms_text()}"
    )
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /cancel - Joriy jarayonni bekor qilish
    """
    user_id = update.effective_user.id
    
    # Generatsiyani bekor qilish
    if state_manager.is_generating(user_id):
        if state_manager.cancel_task(user_id):
            generation_status.pop(user_id, None)
            await update.message.reply_text("✅ Generatsiya bekor qilindi!")
        else:
            await update.message.reply_text("⚠️ Generatsiyani bekor qilib bo'lmadi.")
    else:
        # Boshqa holatlarni tozalash
        state_manager.reset_state(user_id)
        user_videos.pop(user_id, None)
        merge_videos.pop(user_id, None)
        user_music_choice.pop(user_id, None)
        await update.message.reply_text(
            "✅ Jarayon bekor qilindi.\n"
            "Yangi buyruq bering yoki video/link yuboring.",
            reply_markup=ReplyKeyboardRemove()
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /status - Generatsiya holatini ko'rish
    """
    user_id = update.effective_user.id
    
    if state_manager.is_generating(user_id):
        gen_info = generation_status.get(user_id, {})
        start_time = gen_info.get("start_time", time.time())
        gen_type = gen_info.get("type", "noma'lum")
        elapsed = time.time() - start_time
        remaining = max(0, 180 - elapsed)
        
        text = (
            f"🔄 **Generatsiya davom etmoqda...**\n\n"
            f"📝 Tur: {gen_type}\n"
            f"⏱ O'tgan: {int(elapsed)} soniya\n"
            f"⏳ Qolgan: ~{int(remaining)} soniya\n"
            f"{generate_progress_bar(min(90, int(elapsed * 100 / 180)))}"
        )
    else:
        state = state_manager.get_state(user_id)
        can_edit, remaining_edits = check_daily_limit(user_id)
        user_data = get_user(user_id) or {}
        
        text = (
            f"📊 **Holatingiz**\n\n"
            f"🔧 Joriy holat: {state.value}\n"
            f"🎬 Jami editlar: {user_data.get('total_edits', 0)}\n"
            f"📆 Bugungi editlar: {user_data.get('daily_edits', 0)}\n"
            f"📊 Qolgan kunlik: {remaining_edits}{' (cheksiz)' if remaining_edits >= 9999 else ''}\n"
            f"⭐ Premium: {'Ha' if is_premium(user_id) else 'Yoq'}"
        )
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ============================================================
# VIDEO EDIT BUYRUQLARI
# ============================================================

async def trim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /trim - Video kesish
    Foydalanuvchidan video, start va end vaqt so'raydi
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text(
            f"⚠️ Kunlik bepul editlar soni tugadi! ({remaining} qoldi)\n"
            "Ertaga qaytadan urinib ko'ring yoki premium oling."
        )
        return
    
    # Reply qilingan video yoki avval yuborilgan videoni tekshirish
    video_path = await get_reply_video_path(update, context)
    
    if not video_path and user_id not in user_videos:
        # Video yuborishni so'rash
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "trim")
        await update.message.reply_text(
            "🎬 **Video kesish**\n\n"
            "Avval video yuboring.\n\n"
            "📝 Format: video yuboring, so'ng start va end vaqtni kiriting.\n"
            "Misol: `00:00 - 00:30`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    # Start vaqtni so'rash
    state_manager.set_state(user_id, UserState.WAITING_TRIM_START)
    state_manager.set_data(user_id, "edit_type", "trim")
    await update.message.reply_text(
        "✂️ Videoni kesish\n\n"
        "Boshlanish vaqtini kiriting (mm:ss yoki soniya):\n"
        "Misol: `00:10` yoki `10`",
        parse_mode=ParseMode.MARKDOWN
    )


async def watermark_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /watermark - Videoga matn qo'shish
    Matn, joylashuv, o'lcham, rang so'raydi
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text(
            f"⚠️ Kunlik limit tugadi! Ertaga qaytadan urinib ko'ring."
        )
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "watermark")
        await update.message.reply_text(
            "📝 **Matn qo'shish**\n\n"
            "Avval video yuboring, so'ng matnni kiriting."
        )
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    state_manager.set_state(user_id, UserState.WAITING_TEXT)
    state_manager.set_data(user_id, "edit_type", "watermark")
    await update.message.reply_text(
        "📝 **Matn qo'shish**\n\n"
        "Videoga qo'shiladigan matnni kiriting:"
    )


async def music_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /music - Videoga musiqa qo'shish
    Audio fayl yoki kutubxonadan tanlash
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "music")
        await update.message.reply_text(
            "🎵 **Musiqa qo'shish**\n\n"
            "Avval video yuboring."
        )
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    # Musiqa tanlash klaviaturasi
    keyboard = []
    row = []
    for i, track in enumerate(MUSIC_LIBRARY):
        row.append(InlineKeyboardButton(
            f"{track['id']}. {track['name'][:20]}",
            callback_data=f"music_{track['id']}"
        ))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(
        "📁 O'z audiomni yuborish", callback_data="music_custom"
    )])
    
    music_list = "\n".join([
        f"{t['id']}. {t['name']} ({t['duration']})"
        for t in MUSIC_LIBRARY
    ])
    
    state_manager.set_state(user_id, UserState.WAITING_MUSIC)
    state_manager.set_data(user_id, "edit_type", "music")
    await update.message.reply_text(
        f"🎵 **Musiqa tanlang:**\n\n{music_list}\n\n"
        "Yoki o'z audio faylingizni yuboring:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def speed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /speed - Video tezligini o'zgartirish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "speed")
        await update.message.reply_text("🎬 Avval video yuboring.")
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    # Tezlik variantlari klaviaturasi
    keyboard = []
    row = []
    for speed in SPEED_OPTIONS:
        label = f"Slow {speed}x" if speed < 1 else f"Fast {speed}x" if speed > 1 else "1x (normal)"
        row.append(InlineKeyboardButton(label, callback_data=f"speed_{speed}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    state_manager.set_state(user_id, UserState.WAITING_SPEED)
    state_manager.set_data(user_id, "edit_type", "speed")
    await update.message.reply_text(
        "⚡ **Tezlik tanlang:**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /filter - Videoga filter qo'shish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "filter")
        await update.message.reply_text("🎬 Avval video yuboring.")
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    # Filter variantlari klaviaturasi
    filter_names = {
        "grayscale": "⚫ Oq-qora",
        "sepia": "🟤 Sepia",
        "blur_light": "💨 Blur (engil)",
        "blur_medium": "💨 Blur (o'rta)",
        "blur_heavy": "💨 Blur (kuchli)",
        "negative": "🔄 Negativ",
        "brightness": "☀️ Yorqinlik",
        "contrast": "🎨 Kontrast",
        "saturation": "🌈 To'yin.",
        "vignette": "🌑 Vignette",
        "pixelate": "🟫 Pixelate",
        "oil_painting": "🖼 Oil Paint",
    }
    
    keyboard = []
    row = []
    for f in FILTER_OPTIONS:
        name = filter_names.get(f, f)
        row.append(InlineKeyboardButton(name, callback_data=f"filter_{f}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    state_manager.set_state(user_id, UserState.WAITING_FILTER)
    state_manager.set_data(user_id, "edit_type", "filter")
    await update.message.reply_text(
        "🎨 **Filter tanlang:**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def round_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /round - Reply qilingan videoni aylana shaklida yuborish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    # Reply qilingan videoni olish
    video_path = await get_reply_video_path(update, context)
    if not video_path:
        await update.message.reply_text(
            "❌ /round buyrug'ini ishlatish uchun videoga reply qiling "
            "yoki avval video yuboring."
        )
        return
    
    # Generatsiyani boshlash
    await start_generation(update, context, user_id, "round", video_path, make_round_video, [])


async def merge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /merge - Ikki videoni birlashtirish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "merge")
        await update.message.reply_text(
            "🔗 **Videolarni birlashtirish**\n\n"
            "Avval birinchi videoni yuboring."
        )
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    merge_videos[user_id] = [video_path] if video_path else [user_videos[user_id]]
    state_manager.set_state(user_id, UserState.WAITING_MERGE_SECOND)
    state_manager.set_data(user_id, "edit_type", "merge")
    
    await update.message.reply_text(
        f"✅ Birinchi video qabul qilindi!\n"
        f"Endi ikkinchi videoni yuboring.\n\n"
        f"📦 Jami: 1/2 video"
    )


async def compress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /compress - Videoni siqish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "compress")
        await update.message.reply_text("🎬 Avval video yuboring.")
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    # Sifat darajalari klaviaturasi
    keyboard = [
        [InlineKeyboardButton("📉 Past (480p)", callback_data="compress_past")],
        [InlineKeyboardButton("📊 O'rta (720p)", callback_data="compress_orta")],
        [InlineKeyboardButton("📈 Yuqori (1080p)", callback_data="compress_yuqori")],
        [InlineKeyboardButton("🔝 Juda yuqori (original)", callback_data="compress_juda_yuqori")],
    ]
    
    state_manager.set_state(user_id, UserState.WAITING_COMPRESS)
    state_manager.set_data(user_id, "edit_type", "compress")
    await update.message.reply_text(
        "🗜 **Sifat darajasini tanlang:**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def crop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /crop - Videoni kesib olish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "crop")
        await update.message.reply_text("🎬 Avval video yuboring.")
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    # Nisbat variantlari
    keyboard = [
        [InlineKeyboardButton("16:9 (YouTube)", callback_data="crop_16:9")],
        [InlineKeyboardButton("9:16 (TikTok/Reels)", callback_data="crop_9:16")],
        [InlineKeyboardButton("4:3 (Klassik)", callback_data="crop_4:3")],
        [InlineKeyboardButton("1:1 (Kvadrat)", callback_data="crop_1:1")],
    ]
    
    state_manager.set_state(user_id, UserState.WAITING_CROP_RATIO)
    state_manager.set_data(user_id, "edit_type", "crop")
    await update.message.reply_text(
        "📐 **Kesib olish nisbatini tanlang:**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def rotate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rotate - Videoni aylantirish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "rotate")
        await update.message.reply_text("🎬 Avval video yuboring.")
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    keyboard = [
        [
            InlineKeyboardButton("↩️ 90°", callback_data="rotate_90"),
            InlineKeyboardButton("↺ 180°", callback_data="rotate_180"),
        ],
        [
            InlineKeyboardButton("↪️ 270°", callback_data="rotate_270"),
            InlineKeyboardButton("🔁 Gorizontal", callback_data="rotate_hflip"),
        ],
        [
            InlineKeyboardButton("🙃 Vertikal", callback_data="rotate_vflip"),
        ]
    ]
    
    state_manager.set_state(user_id, UserState.WAITING_ROTATE)
    state_manager.set_data(user_id, "edit_type", "rotate")
    await update.message.reply_text(
        "🔄 **Aylantirish turini tanlang:**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def reverse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /reverse - Videoni teskari aylantirish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "reverse")
        await update.message.reply_text("🎬 Avval video yuboring.")
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    keyboard = [
        [InlineKeyboardButton("🎬 Faqat video teskari", callback_data="reverse_video_only")],
        [InlineKeyboardButton("🎬🎵 Video + audio teskari", callback_data="reverse_both")],
    ]
    
    state_manager.set_state(user_id, UserState.GENERATING)
    await update.message.reply_text(
        "🔄 **Teskari video**\n\n"
        "Turini tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def gif_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /gif - Videodan GIF yaratish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "gif")
        await update.message.reply_text("🎬 Avval video yuboring.")
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    await start_generation(update, context, user_id, "gif", video_path, video_to_gif, [])


async def sticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /sticker - Videodan sticker yaratish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    can_edit, remaining = check_daily_limit(user_id)
    if not can_edit:
        await update.message.reply_text("⚠️ Kunlik limit tugadi!")
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        state_manager.set_state(user_id, UserState.WAITING_VIDEO)
        state_manager.set_data(user_id, "edit_type", "sticker")
        await update.message.reply_text("🎬 Avval video yuboring.")
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    await start_generation(update, context, user_id, "sticker", video_path, video_to_sticker, [])


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /info - Video haqida ma'lumot
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    video_path = await get_reply_video_path(update, context)
    if not video_path and user_id not in user_videos:
        await update.message.reply_text("❌ Video topilmadi. Videoga reply qiling yoki yuboring.")
        return
    
    if video_path:
        user_videos[user_id] = video_path
    
    await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)
    
    info = await get_video_info(video_path)
    if not info:
        await update.message.reply_text("❌ Video ma'lumotini olishda xatolik.")
        return
    
    text = (
        f"📋 **Video ma'lumotlari**\n\n"
        f"⏱ Davomiyligi: `{seconds_to_time_str(info['duration'])}`\n"
        f"📐 O'lcham: `{info['width']}x{info['height']}`\n"
        f"🎬 FPS: `{info['fps']}`\n"
        f"📁 Fayl hajmi: `{format_file_size(info['size'])}`\n"
        f"📊 Bitrate: `{info['bitrate']}`\n"
        f"🎵 Audio: `{'Mavjud' if info['has_audio'] else 'Yoq'}`"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ============================================================
# CALLBACK HANDLER (Inline tugmalar)
# ============================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Barcha inline tugmalar uchun handler
    """
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # Admin callbacklari
    if data.startswith("admin_"):
        await admin_callback(update, context)
        return
    
    # Musiqa tanlash
    if data.startswith("music_"):
        await handle_music_callback(query, context, user_id, data)
        return
    
    # Tezlik tanlash
    if data.startswith("speed_"):
        speed = float(data.split("_")[1])
        video_path = user_videos.get(user_id)
        if not video_path:
            await query.edit_message_text("❌ Video topilmadi. Qaytadan urinib ko'ring.")
            state_manager.reset_state(user_id)
            return
        
        await query.edit_message_text(f"⚡ Tezlik: {speed}x\nGeneratsiya boshlanmoqda...")
        await start_generation(update, context, user_id, f"speed_{speed}x", video_path,
                               change_speed, [speed])
        return
    
    # Filter tanlash
    if data.startswith("filter_"):
        filter_type = data.split("_", 1)[1]
        video_path = user_videos.get(user_id)
        if not video_path:
            await query.edit_message_text("❌ Video topilmadi.")
            state_manager.reset_state(user_id)
            return
        
        # brightness/contrast/saturation uchun darajani so'rash
        if filter_type in ["brightness", "contrast", "saturation"]:
            keyboard = []
            for val in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0]:
                keyboard.append([InlineKeyboardButton(
                    f"Daraja: {val}", callback_data=f"filterintensity_{filter_type}_{val}"
                )])
            await query.edit_message_text(
                f"🎨 **{filter_type} darajasini tanlang:**",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        await query.edit_message_text(f"🎨 Filter: {filter_type}\nGeneratsiya boshlanmoqda...")
        await start_generation(update, context, user_id, f"filter_{filter_type}", video_path,
                               apply_filter, [filter_type])
        return
    
    # Filter intensivlik
    if data.startswith("filterintensity_"):
        parts = data.split("_")
        filter_type = parts[1]
        intensity = float(parts[2])
        video_path = user_videos.get(user_id)
        if not video_path:
            await query.edit_message_text("❌ Video topilmadi.")
            state_manager.reset_state(user_id)
            return
        
        await query.edit_message_text(
            f"🎨 {filter_type} (daraja: {intensity})\nGeneratsiya boshlanmoqda..."
        )
        await start_generation(update, context, user_id, f"filter_{filter_type}",
                               video_path, apply_filter, [filter_type, intensity])
        return
    
    # Siqish tanlash
    if data.startswith("compress_"):
        quality = data.split("_", 1)[1]
        video_path = user_videos.get(user_id)
        if not video_path:
            await query.edit_message_text("❌ Video topilmadi.")
            state_manager.reset_state(user_id)
            return
        
        quality_names = {
            "past": "Past (480p)", "orta": "O'rta (720p)",
            "yuqori": "Yuqori (1080p)", "juda_yuqori": "Original"
        }
        await query.edit_message_text(
            f"🗜 Sifat: {quality_names.get(quality, quality)}\nGeneratsiya boshlanmoqda..."
        )
        await start_generation(update, context, user_id, "compress", video_path,
                               compress_video, [quality])
        return
    
    # Crop tanlash
    if data.startswith("crop_"):
        ratio = data.split("_", 1)[1]
        video_path = user_videos.get(user_id)
        if not video_path:
            await query.edit_message_text("❌ Video topilmadi.")
            state_manager.reset_state(user_id)
            return
        
        await query.edit_message_text(f"📐 Nisbat: {ratio}\nGeneratsiya boshlanmoqda...")
        await start_generation(update, context, user_id, "crop", video_path,
                               crop_video, [ratio])
        return
    
    # Rotate tanlash
    if data.startswith("rotate_"):
        action = data.split("_", 1)[1]
        video_path = user_videos.get(user_id)
        if not video_path:
            await query.edit_message_text("❌ Video topilmadi.")
            state_manager.reset_state(user_id)
            return
        
        angle = 0
        flip = None
        if action == "90":
            angle = 90
        elif action == "180":
            angle = 180
        elif action == "270":
            angle = 270
        elif action == "hflip":
            flip = "horizontal"
        elif action == "vflip":
            flip = "vertical"
        
        action_name = f"Aylantirish: {angle}°" if angle else f"Aks: {flip}"
        await query.edit_message_text(f"🔄 {action_name}\nGeneratsiya boshlanmoqda...")
        await start_generation(update, context, user_id, "rotate", video_path,
                               rotate_video, [angle, flip])
        return
    
    # Reverse tanlash
    if data.startswith("reverse_"):
        action = data.split("_", 1)[1]
        video_path = user_videos.get(user_id)
        if not video_path:
            await query.edit_message_text("❌ Video topilmadi.")
            state_manager.reset_state(user_id)
            return
        
        reverse_audio = action == "both"
        await query.edit_message_text("🔄 Teskari video...\nGeneratsiya boshlanmoqda...")
        await start_generation(update, context, user_id, "reverse", video_path,
                               reverse_video, [reverse_audio])
        return


async def handle_music_callback(query, context, user_id, data):
    """Musiqa tanlash callback"""
    if data == "music_custom":
        await query.edit_message_text(
            "📁 O'z audio faylingizni yuboring (MP3, M4A, WAV, OGG):"
        )
        return
    
    music_id = int(data.split("_")[1])
    track = next((t for t in MUSIC_LIBRARY if t["id"] == music_id), None)
    
    if not track:
        await query.edit_message_text("❌ Musiqa topilmadi.")
        return
    
    music_path = os.path.join(MUSIC_DIR, track["file"])
    
    if not os.path.exists(music_path):
        # Musiqa fayli yo'q - xabar
        await query.edit_message_text(
            f"⚠️ `{track['file']}` fayli topilmadi.\n"
            "Iltimos, music/ papkasiga musiqa fayllarini joylang yoki "
            "o'z audioningizni yuboring.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    user_music_choice[user_id] = music_path
    
    # Ovoz balandligini so'rash
    keyboard = [
        [
            InlineKeyboardButton("🔇 0.5x", callback_data="musicvol_0.5"),
            InlineKeyboardButton("🔉 1x", callback_data="musicvol_1.0"),
            InlineKeyboardButton("🔊 1.5x", callback_data="musicvol_1.5"),
            InlineKeyboardButton("📢 2x", callback_data="musicvol_2.0"),
        ]
    ]
    
    await query.edit_message_text(
        f"🎵 Tanlandi: {track['name']}\n\n"
        "Ovoz balandligini tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# VIDEO QABUL QILISH HANDLER
# ============================================================

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Foydalanuvchi video yuborganida ishlaydi
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    # Admin video yuklash
    state = state_manager.get_state(user_id)
    if state == UserState.WAITING_ADMIN_VIDEO:
        await handle_admin_video_upload(update, context)
        return
    
    # Merge ikkinchi video
    if state == UserState.WAITING_MERGE_SECOND:
        await handle_merge_second_video(update, context)
        return
    
    # Video yuklab olish
    msg = await update.message.reply_text("⏳ Video yuklab olinmoqda...")
    
    try:
        # Video faylini olish
        video = update.message.video or update.message.document
        if not video:
            await msg.edit_text("❌ Video topilmadi!")
            return
        
        # Fayl hajmi tekshirish
        if video.file_size and video.file_size > MAX_FILE_SIZE:
            await msg.edit_text(
                f"⚠️ Video hajmi {format_file_size(video.file_size)}. "
                f"50MB dan oshmasligi kerak!"
            )
            return
        
        # Video yuklab olish
        file = await video.get_file()
        filename = generate_unique_filename("input", ".mp4")
        filepath = os.path.join(DOWNLOADS_DIR, filename)
        await file.download_to_drive(filepath)
        
        user_videos[user_id] = filepath
        
        await msg.edit_text("✅ Video qabul qilindi!")
        
        # Edit turini aniqlash
        edit_type = state_manager.get_data_value(user_id, "edit_type")
        
        if edit_type == "trim":
            state_manager.set_state(user_id, UserState.WAITING_TRIM_START)
            await update.message.reply_text(
                "✂️ Boshlanish vaqtini kiriting (mm:ss yoki soniya):\n"
                "Misol: `00:10` yoki `10`",
                parse_mode=ParseMode.MARKDOWN
            )
        elif edit_type == "watermark":
            state_manager.set_state(user_id, UserState.WAITING_TEXT)
            await update.message.reply_text("📝 Qo'shiladigan matnni kiriting:")
        elif edit_type == "music":
            # Musiqa kutubxonasini ko'rsatish
            await music_command(update, context)
        elif edit_type == "speed":
            await speed_command(update, context)
        elif edit_type == "filter":
            await filter_command(update, context)
        elif edit_type == "merge":
            merge_videos[user_id] = [filepath]
            state_manager.set_state(user_id, UserState.WAITING_MERGE_SECOND)
            await update.message.reply_text(
                "✅ Birinchi video qabul qilindi!\n"
                "Endi ikkinchi videoni yuboring.\n\n"
                "📦 Jami: 1/2 video"
            )
        elif edit_type == "compress":
            await compress_command(update, context)
        elif edit_type == "crop":
            await crop_command(update, context)
        elif edit_type == "rotate":
            await rotate_command(update, context)
        elif edit_type == "reverse":
            await reverse_command(update, context)
        elif edit_type == "gif":
            await start_generation(update, context, user_id, "gif", filepath, video_to_gif, [])
        elif edit_type == "sticker":
            await start_generation(update, context, user_id, "sticker", filepath, video_to_sticker, [])
        else:
            # Default - edit menyusi
            await show_edit_menu(update, context)
        
    except Exception as e:
        logger.error(f"Video yuklab olishda xatolik: {e}")
        await msg.edit_text(f"❌ Video yuklab olinmadi. Xatolik: {e}")


async def handle_merge_second_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Merge uchun ikkinchi videoni qabul qilish"""
    user_id = update.effective_user.id
    
    msg = await update.message.reply_text("⏳ Ikkinchi video yuklanmoqda...")
    
    try:
        video = update.message.video or update.message.document
        if not video:
            await msg.edit_text("❌ Video topilmadi!")
            return
        
        if video.file_size and video.file_size > MAX_FILE_SIZE:
            await msg.edit_text("⚠️ Video hajmi 50MB dan oshmasligi kerak!")
            return
        
        file = await video.get_file()
        filename = generate_unique_filename("input2", ".mp4")
        filepath = os.path.join(DOWNLOADS_DIR, filename)
        await file.download_to_drive(filepath)
        
        merge_videos[user_id].append(filepath)
        
        await msg.edit_text("✅ Ikkinchi video qabul qilindi!")
        
        # Yana video qo'shishni so'rash
        keyboard = [
            [
                InlineKeyboardButton("✅ Birlashtirish", callback_data="merge_start"),
                InlineKeyboardButton("➕ Yana video", callback_data="merge_more"),
            ]
        ]
        count = len(merge_videos.get(user_id, []))
        await update.message.reply_text(
            f"📦 Jami: {count} ta video qabul qilindi.\n"
            "Birlashtirishni boshlashni xohlaysizmi?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # Merge start callback uchun holat saqlash
        state_manager.set_state(user_id, UserState.IDLE)
        
    except Exception as e:
        logger.error(f"Ikkinchi video yuklashda xatolik: {e}")
        await msg.edit_text(f"❌ Xatolik: {e}")


async def show_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit menyusini ko'rsatish"""
    keyboard = [
        [InlineKeyboardButton("✂️ Trim", callback_data="cmd_trim"),
         InlineKeyboardButton("📝 Watermark", callback_data="cmd_watermark")],
        [InlineKeyboardButton("🎵 Musiqa", callback_data="cmd_music"),
         InlineKeyboardButton("⚡ Tezlik", callback_data="cmd_speed")],
        [InlineKeyboardButton("🎨 Filter", callback_data="cmd_filter"),
         InlineKeyboardButton("🔄 Aylantirish", callback_data="cmd_rotate")],
        [InlineKeyboardButton("📐 Crop", callback_data="cmd_crop"),
         InlineKeyboardButton("🗜 Siqish", callback_data="cmd_compress")],
        [InlineKeyboardButton("↩️ Teskari", callback_data="cmd_reverse"),
         InlineKeyboardButton("🎬 GIF", callback_data="cmd_gif")],
        [InlineKeyboardButton("📱 Sticker", callback_data="cmd_sticker"),
         InlineKeyboardButton("📋 Info", callback_data="cmd_info")],
    ]
    
    await update.message.reply_text(
        "🎬 **Video qabul qilindi!**\n\n"
        "Edit turini tanlang:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# LINK HANDLER
# ============================================================

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Foydalanuvchi link yuborganida - yt-dlp bilan yuklab olish
    """
    user_id = update.effective_user.id
    
    if is_user_blocked(user_id):
        return
    
    url = update.message.text.strip()
    
    if not validate_link(url):
        return
    
    if not is_supported_url(url):
        await update.message.reply_text(
            f"❌ Bu platforma qo'llab-quvvatlanmaydi.\n\n"
            f"Qo'llab-quvvatlanadigan platformalar:\n{get_supported_platforms_text()}"
        )
        return
    
    # Yuklash variantlari
    keyboard = [
        [
            InlineKeyboardButton("🎬 Video (720p)", callback_data="dl_video_best"),
            InlineKeyboardButton("🎬 Video (480p)", callback_data="dl_video_480"),
        ],
        [
            InlineKeyboardButton("🎵 Faqat audio", callback_data="dl_audio"),
            InlineKeyboardButton("📝 Subtitle bilan", callback_data="dl_subtitle"),
        ],
    ]
    
    # Video ma'lumotini olish
    info = await get_video_info_ytdlp(url)
    
    if info:
        info_text = (
            f"📋 **Video ma'lumoti:**\n\n"
            f"📌 Platforma: {info.get('platform', 'Nomalum')}\n"
            f"🎬 Sarlavha: {info.get('title', 'Nomalum')}\n"
            f"⏱ Davomiyligi: {seconds_to_time_str(info.get('duration', 0))}\n"
            f"👤 Muallif: {info.get('uploader', 'Nomalum')}\n\n"
            f"Yuklash turini tanlang:"
        )
    else:
        info_text = "🎬 Yuklab olish turini tanlang:"
    
    # URL ni saqlash
    state_manager.set_data(user_id, "download_url", url)
    
    await update.message.reply_text(
        info_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Linkdan yuklash callback"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if not data.startswith("dl_"):
        return
    
    url = state_manager.get_data_value(user_id, "download_url")
    if not url:
        await query.edit_message_text("❌ URL topilmadi. Qaytadan link yuboring.")
        return
    
    download_type = data.split("_", 1)[1]
    
    await query.edit_message_text("⏳ Yuklab olinmoqda...")
    
    progress_msg = await context.bot.send_message(
        chat_id=user_id,
        text="🔄 Yuklash boshlandi...\n[░░░░░░░░░░] 0%"
    )
    
    async def dl_progress(percent, text):
        try:
            bar = generate_progress_bar(percent)
            await progress_msg.edit_text(f"{text}\n{bar}")
        except BadRequest:
            pass
    
    try:
        if download_type == "video_best":
            filepath = await download_video(url, quality="best", progress_callback=dl_progress)
        elif download_type == "video_480":
            filepath = await download_video(url, quality="480p", progress_callback=dl_progress)
        elif download_type == "audio":
            filepath = await download_audio_only(url, progress_callback=dl_progress)
        elif download_type == "subtitle":
            filepath = await download_video(url, quality="best", subtitle=True, progress_callback=dl_progress)
        else:
            filepath = await download_video(url, progress_callback=dl_progress)
        
        if not filepath:
            await progress_msg.edit_text("❌ Video yuklab olinmadi. Linkni tekshiring.")
            return
        
        await progress_msg.edit_text(f"✅ Yuklandi! ({format_file_size(os.path.getsize(filepath))})")
        
        user_videos[user_id] = filepath
        
        # Edit menyusini ko'rsatish
        keyboard = [
            [InlineKeyboardButton("✂️ Trim", callback_data="cmd_trim"),
             InlineKeyboardButton("📝 Watermark", callback_data="cmd_watermark")],
            [InlineKeyboardButton("🎵 Musiqa", callback_data="cmd_music"),
             InlineKeyboardButton("⚡ Tezlik", callback_data="cmd_speed")],
            [InlineKeyboardButton("🎨 Filter", callback_data="cmd_filter"),
             InlineKeyboardButton("🔄 Aylantirish", callback_data="cmd_rotate")],
            [InlineKeyboardButton("📐 Crop", callback_data="cmd_crop"),
             InlineKeyboardButton("🗜 Siqish", callback_data="cmd_compress")],
            [InlineKeyboardButton("↩️ Teskari", callback_data="cmd_reverse"),
             InlineKeyboardButton("🎬 GIF", callback_data="cmd_gif")],
            [InlineKeyboardButton("📱 Sticker", callback_data="cmd_sticker"),
             InlineKeyboardButton("📋 Info", callback_data="cmd_info")],
        ]
        
        await context.bot.send_message(
            chat_id=user_id,
            text="🎬 Video yuklandi! Edit turini tanlang:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Yuklash callback xatolik: {e}")
        await progress_msg.edit_text(f"❌ Yuklashda xatolik: {e}")


async def handle_cmd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit menyusi tugmalari callback"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    cmd_map = {
        "cmd_trim": trim_command,
        "cmd_watermark": watermark_command,
        "cmd_music": music_command,
        "cmd_speed": speed_command,
        "cmd_filter": filter_command,
        "cmd_rotate": rotate_command,
        "cmd_crop": crop_command,
        "cmd_compress": compress_command,
        "cmd_reverse": reverse_command,
        "cmd_gif": gif_command,
        "cmd_sticker": sticker_command,
        "cmd_info": info_command,
    }
    
    cmd = data.split("_", 1)[1] if data.startswith("cmd_") else None
    
    if data == "merge_start":
        videos = merge_videos.get(user_id, [])
        if len(videos) < 2:
            await query.edit_message_text("❌ Kamida 2 ta video kerak!")
            return
        await query.edit_message_text("🔗 Videolar birlashtirilmoqda...")
        await start_generation(update, context, user_id, "merge", videos, merge_videos_func, [videos])
        return
    
    if data == "merge_more":
        state_manager.set_state(user_id, UserState.WAITING_MERGE_SECOND)
        await query.edit_message_text("📁 Yana video yuboring:")
        return
    
    # Musiqa ovoz balandligi
    if data.startswith("musicvol_"):
        volume = float(data.split("_")[1])
        video_path = user_videos.get(user_id)
        music_path = user_music_choice.get(user_id)
        
        if not video_path or not music_path:
            await query.edit_message_text("❌ Video yoki musiqa topilmadi.")
            return
        
        await query.edit_message_text(f"🎵 Ovoz: {volume}x\nGeneratsiya boshlanmoqda...")
        
        # Original audio ni saqlash/o'chirishni so'rash
        keyboard = [
            [InlineKeyboardButton("✅ Original ovozni saqlash", callback_data=f"musickeep_{volume}_1")],
            [InlineKeyboardButton("❌ Faqat musiqa", callback_data=f"musickeep_{volume}_0")],
        ]
        await context.bot.send_message(
            chat_id=user_id,
            text="Original video ovozini saqlashni xohlaysizmi?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if data.startswith("musickeep_"):
        parts = data.split("_")
        volume = float(parts[1])
        keep_original = parts[2] == "1"
        
        video_path = user_videos.get(user_id)
        music_path = user_music_choice.get(user_id)
        
        if not video_path or not music_path:
            await query.edit_message_text("❌ Fayl topilmadi.")
            return
        
        await query.edit_message_text("🎵 Musiqa qo'shilmoqda...\nGeneratsiya boshlanmoqda...")
        await start_generation(update, context, user_id, "music", video_path,
                               add_music, [music_path, volume, keep_original])
        return
    
    if cmd and cmd in cmd_map:
        # Callback ni command ga o'tkazish
        # Video path ni saqlab qo'yish
        if user_id in user_videos:
            video_path = user_videos[user_id]
            # State ni to'g'rilash
            state_manager.set_state(user_id, UserState.IDLE)
        
        # Fake update yaratish o'rniga to'g'ridan-to'g'ri chaqirish
        await query.edit_message_text(f"⏳ {cmd} tayyorlanmoqda...")
        
        # Video path ni tekshirish
        video_path = user_videos.get(user_id)
        if not video_path:
            await context.bot.send_message(
                chat_id=user_id, text="❌ Video topilmadi. Avval video yuboring."
            )
            return
        
        # Edit turiga qarab davom etish
        if cmd == "trim":
            state_manager.set_state(user_id, UserState.WAITING_TRIM_START)
            state_manager.set_data(user_id, "edit_type", "trim")
            await context.bot.send_message(
                chat_id=user_id,
                text="✂️ Boshlanish vaqtini kiriting (mm:ss yoki ss):",
                parse_mode=ParseMode.MARKDOWN
            )
        elif cmd == "watermark":
            state_manager.set_state(user_id, UserState.WAITING_TEXT)
            state_manager.set_data(user_id, "edit_type", "watermark")
            await context.bot.send_message(chat_id=user_id, text="📝 Matnni kiriting:")
        elif cmd == "music":
            # Musiqa menyusi
            keyboard = []
            row = []
            for track in MUSIC_LIBRARY:
                row.append(InlineKeyboardButton(
                    f"{track['id']}. {track['name'][:15]}",
                    callback_data=f"music_{track['id']}"
                ))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("📁 O'z audiom", callback_data="music_custom")])
            
            music_list = "\n".join([f"{t['id']}. {t['name']} ({t['duration']})" for t in MUSIC_LIBRARY])
            state_manager.set_state(user_id, UserState.WAITING_MUSIC)
            state_manager.set_data(user_id, "edit_type", "music")
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎵 Musiqa tanlang:\n\n{music_list}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif cmd == "speed":
            keyboard = []
            row = []
            for speed in SPEED_OPTIONS:
                label = f"Slow {speed}x" if speed < 1 else f"Fast {speed}x" if speed > 1 else "1x"
                row.append(InlineKeyboardButton(label, callback_data=f"speed_{speed}"))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            
            state_manager.set_state(user_id, UserState.WAITING_SPEED)
            state_manager.set_data(user_id, "edit_type", "speed")
            await context.bot.send_message(
                chat_id=user_id,
                text="⚡ Tezlik tanlang:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif cmd == "filter":
            filter_names = {
                "grayscale": "⚫ Oq-qora", "sepia": "🟤 Sepia",
                "blur_light": "💨 Blur (engil)", "blur_medium": "💨 Blur (o'rta)",
                "blur_heavy": "💨 Blur (kuchli)", "negative": "🔄 Negativ",
                "brightness": "☀️ Yorqinlik", "contrast": "🎨 Kontrast",
                "saturation": "🌈 To'yin.", "vignette": "🌑 Vignette",
                "pixelate": "🟫 Pixelate", "oil_painting": "🖼 Oil Paint",
            }
            keyboard = []
            row = []
            for f in FILTER_OPTIONS:
                row.append(InlineKeyboardButton(filter_names.get(f, f), callback_data=f"filter_{f}"))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            
            state_manager.set_state(user_id, UserState.WAITING_FILTER)
            state_manager.set_data(user_id, "edit_type", "filter")
            await context.bot.send_message(
                chat_id=user_id,
                text="🎨 Filter tanlang:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif cmd == "rotate":
            keyboard = [
                [InlineKeyboardButton("↩️ 90°", callback_data="rotate_90"),
                 InlineKeyboardButton("↺ 180°", callback_data="rotate_180")],
                [InlineKeyboardButton("↪️ 270°", callback_data="rotate_270"),
                 InlineKeyboardButton("🔁 Goriz.", callback_data="rotate_hflip")],
                [InlineKeyboardButton("🙃 Vertik.", callback_data="rotate_vflip")]
            ]
            state_manager.set_state(user_id, UserState.WAITING_ROTATE)
            state_manager.set_data(user_id, "edit_type", "rotate")
            await context.bot.send_message(
                chat_id=user_id,
                text="🔄 Aylantirish turini tanlang:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif cmd == "crop":
            keyboard = [
                [InlineKeyboardButton("16:9 (YouTube)", callback_data="crop_16:9")],
                [InlineKeyboardButton("9:16 (TikTok/Reels)", callback_data="crop_9:16")],
                [InlineKeyboardButton("4:3 (Klassik)", callback_data="crop_4:3")],
                [InlineKeyboardButton("1:1 (Kvadrat)", callback_data="crop_1:1")],
            ]
            state_manager.set_state(user_id, UserState.WAITING_CROP_RATIO)
            state_manager.set_data(user_id, "edit_type", "crop")
            await context.bot.send_message(
                chat_id=user_id,
                text="📐 Nisbatni tanlang:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif cmd == "compress":
            keyboard = [
                [InlineKeyboardButton("📉 Past (480p)", callback_data="compress_past")],
                [InlineKeyboardButton("📊 O'rta (720p)", callback_data="compress_orta")],
                [InlineKeyboardButton("📈 Yuqori (1080p)", callback_data="compress_yuqori")],
                [InlineKeyboardButton("🔝 Original", callback_data="compress_juda_yuqori")],
            ]
            state_manager.set_state(user_id, UserState.WAITING_COMPRESS)
            state_manager.set_data(user_id, "edit_type", "compress")
            await context.bot.send_message(
                chat_id=user_id,
                text="🗜 Sifat darajasini tanlang:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif cmd == "reverse":
            keyboard = [
                [InlineKeyboardButton("🎬 Faqat video", callback_data="reverse_video_only")],
                [InlineKeyboardButton("🎬🎵 Video + audio", callback_data="reverse_both")],
            ]
            state_manager.set_state(user_id, UserState.GENERATING)
            await context.bot.send_message(
                chat_id=user_id,
                text="🔄 Turini tanlang:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif cmd == "gif":
            await start_generation(update, context, user_id, "gif", video_path, video_to_gif, [])
        elif cmd == "sticker":
            await start_generation(update, context, user_id, "sticker", video_path, video_to_sticker, [])
        elif cmd == "info":
            info = await get_video_info(video_path)
            if info:
                text = (
                    f"📋 **Video ma'lumotlari**\n\n"
                    f"⏱ Davomiyligi: `{seconds_to_time_str(info['duration'])}`\n"
                    f"📐 O'lcham: `{info['width']}x{info['height']}`\n"
                    f"🎬 FPS: `{info['fps']}`\n"
                    f"📁 Fayl hajmi: `{format_file_size(info['size'])}`\n"
                    f"📊 Bitrate: `{info['bitrate']}`\n"
                    f"🎵 Audio: `{'Mavjud' if info['has_audio'] else 'Yoq'}`"
                )
                await context.bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.MARKDOWN)
            else:
                await context.bot.send_message(chat_id=user_id, text="❌ Ma'lumot olishda xatolik.")


async def merge_videos_func(video_paths):
    """Merge uchun wrapper funksiya"""
    return await merge_videos(video_paths)


# ============================================================
# MATN HANDLER (state-ga qarab)
# ============================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Foydalanuvchi matn yuborganida ishlaydi
    State ga qarab turli jarayonlarni davom ettiradi
    """
    user_id = update.effective_user.id
    text = update.message.text.strip()
    state = state_manager.get_state(user_id)
    
    # Admin broadcast
    if state == UserState.WAITING_BROADCAST:
        await send_broadcast(update, context)
        return
    
    # Trim start vaqt
    if state == UserState.WAITING_TRIM_START:
        start_time = parse_time_to_seconds(text)
        if start_time is None:
            await update.message.reply_text(
                "⚠️ Vaqt formatini to'g'ri kiriting (mm:ss yoki ss)"
            )
            return
        
        video_path = user_videos.get(user_id)
        if not video_path:
            await update.message.reply_text("❌ Video topilmadi. Qaytadan urinib ko'ring.")
            state_manager.reset_state(user_id)
            return
        
        # Video davomiyligini olish
        info = await get_video_info(video_path)
        if info and start_time >= info["duration"]:
            await update.message.reply_text(
                f"⚠️ Boshlanish vaqti video davomiyligidan oshib ketdi! "
                f"({seconds_to_time_str(info['duration'])})"
            )
            return
        
        state_manager.set_data(user_id, "trim_start", start_time)
        state_manager.set_state(user_id, UserState.WAITING_TRIM_END)
        await update.message.reply_text(
            f"✅ Boshlanish: {seconds_to_time_str(start_time)}\n\n"
            "Endi tugash vaqtini kiriting (mm:ss yoki ss):"
        )
        return
    
    # Trim end vaqt
    if state == UserState.WAITING_TRIM_END:
        end_time = parse_time_to_seconds(text)
        if end_time is None:
            await update.message.reply_text("⚠️ Vaqt formatini to'g'ri kiriting (mm:ss yoki ss)")
            return
        
        start_time = state_manager.get_data_value(user_id, "trim_start")
        if start_time is not None and end_time <= start_time:
            await update.message.reply_text("⚠️ Tugash vaqti boshlanish vaqtidan katta bo'lishi kerak!")
            return
        
        video_path = user_videos.get(user_id)
        if not video_path:
            await update.message.reply_text("❌ Video topilmadi.")
            state_manager.reset_state(user_id)
            return
        
        await update.message.reply_text(
            f"✂️ Kesish: {seconds_to_time_str(start_time)} - {seconds_to_time_str(end_time)}\n"
            "Generatsiya boshlanmoqda..."
        )
        
        await start_generation(update, context, user_id, "trim", video_path,
                               trim_video, [start_time, end_time])
        return
    
    # Watermark matn
    if state == UserState.WAITING_TEXT:
        if not text:
            await update.message.reply_text("⚠️ Matn bo'sh bo'lmasin!")
            return
        
        state_manager.set_data(user_id, "watermark_text", text)
        state_manager.set_state(user_id, UserState.WAITING_TEXT_POSITION)
        
        keyboard = [
            [InlineKeyboardButton("↖️ Yuqori chap", callback_data="wpos_top-left"),
             InlineKeyboardButton("↗️ Yuqori o'ng", callback_data="wpos_top-right")],
            [InlineKeyboardButton("↙️ Pastki chap", callback_data="wpos_bottom-left"),
             InlineKeyboardButton("↘️ Pastki o'ng", callback_data="wpos_bottom-right")],
            [InlineKeyboardButton("🎯 Markazda", callback_data="wpos_center")],
        ]
        await update.message.reply_text(
            "📍 Matn joylashuvini tanlang:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Link yuborilgan - yuklash
    if state == UserState.IDLE and validate_link(text):
        await handle_link(update, context)
        return


# ============================================================
# AUDIO HANDLER
# ============================================================

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Foydalanuvchi audio fayl yuborganida
    """
    user_id = update.effective_user.id
    state = state_manager.get_state(user_id)
    
    if is_user_blocked(user_id):
        return
    
    if state == UserState.WAITING_MUSIC:
        msg = await update.message.reply_text("⏳ Audio yuklanmoqda...")
        
        try:
            audio = update.message.audio or update.message.document
            if not audio:
                await msg.edit_text("❌ Audio topilmadi!")
                return
            
            file = await audio.get_file()
            filename = generate_unique_filename("audio", ".mp3")
            filepath = os.path.join(DOWNLOADS_DIR, filename)
            await file.download_to_drive(filepath)
            
            user_music_choice[user_id] = filepath
            await msg.edit_text("✅ Audio qabul qilindi!")
            
            # Ovoz balandligini so'rash
            keyboard = [
                [
                    InlineKeyboardButton("🔇 0.5x", callback_data="musicvol_0.5"),
                    InlineKeyboardButton("🔉 1x", callback_data="musicvol_1.0"),
                    InlineKeyboardButton("🔊 1.5x", callback_data="musicvol_1.5"),
                    InlineKeyboardButton("📢 2x", callback_data="musicvol_2.0"),
                ]
            ]
            await update.message.reply_text(
                "Ovoz balandligini tanlang:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Audio yuklashda xatolik: {e}")
            await msg.edit_text(f"❌ Xatolik: {e}")


# ============================================================
# WATERMARK CALLBACK HANDLER
# ============================================================

async def handle_watermark_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Watermark joylashuv, o'lcham, rang callbacklari"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # Joylashuv
    if data.startswith("wpos_"):
        position = data.split("_", 1)[1]
        state_manager.set_data(user_id, "watermark_position", position)
        state_manager.set_state(user_id, UserState.WAITING_TEXT_SIZE)
        
        keyboard = [
            [InlineKeyboardButton("🔤 Kichik", callback_data="wsize_kichik"),
             InlineKeyboardButton("🔠 O'rta", callback_data="wsize_orta"),
             InlineKeyboardButton("🔠 Katta", callback_data="wsize_katta")]
        ]
        await query.edit_message_text(
            "🔤 Matn o'lchamini tanlang:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # O'lcham
    if data.startswith("wsize_"):
        size = data.split("_", 1)[1]
        state_manager.set_data(user_id, "watermark_size", size)
        state_manager.set_state(user_id, UserState.WAITING_TEXT_COLOR)
        
        keyboard = [
            [InlineKeyboardButton("⬜ Oq", callback_data="wcolor_oq"),
             InlineKeyboardButton("⬛ Qora", callback_data="wcolor_qora")],
            [InlineKeyboardButton("🟥 Qizil", callback_data="wcolor_qizil"),
             InlineKeyboardButton("🟦 Ko'k", callback_data="wcolor_kok")],
            [InlineKeyboardButton("🟩 Yashil", callback_data="wcolor_yashil"),
             InlineKeyboardButton("🟨 Sariq", callback_data="wcolor_sariq")]
        ]
        await query.edit_message_text(
            "🎨 Matn rangini tanlang:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Rang
    if data.startswith("wcolor_"):
        color = data.split("_", 1)[1]
        
        text = state_manager.get_data_value(user_id, "watermark_text")
        position = state_manager.get_data_value(user_id, "watermark_position", "bottom-right")
        size = state_manager.get_data_value(user_id, "watermark_size", "orta")
        
        video_path = user_videos.get(user_id)
        if not video_path:
            await query.edit_message_text("❌ Video topilmadi.")
            state_manager.reset_state(user_id)
            return
        
        await query.edit_message_text(
            f"📝 Matn: {text}\n📍 Joy: {position}\n🔤 O'lcham: {size}\n🎨 Rang: {color}\n\n"
            "Generatsiya boshlanmoqda..."
        )
        
        await start_generation(update, context, user_id, "watermark", video_path,
                               add_watermark, [text, position, size, color])
        return


# ============================================================
# GENERATSIYA BOSHLASH
# ============================================================

async def start_generation(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    user_id: int, gen_type: str, video_path,
    edit_func, args: list
):
    """
    Generatsiyani boshlash - progress bar bilan
    
    Args:
        update: Telegram update
        context: Bot context
        user_id: Foydalanuvchi ID
        gen_type: Generatsiya turi (trim, watermark, music, ...)
        video_path: Kirish video yo'li
        edit_func: Edit funksiyasi
        args: Edit funksiyasi argumentlari
    """
    # Holatni generatsiyaga o'tkazish
    state_manager.set_state(user_id, UserState.GENERATING)
    generation_status[user_id] = {
        "active": True,
        "type": gen_type,
        "start_time": time.time()
    }
    
    # Progress bar boshlash
    progress_msg = await context.bot.send_message(
        chat_id=user_id,
        text=f"🔄 Generatsiya boshlandi... (3 daqiqa)\n{generate_progress_bar(10)}\nTaxminan 180 soniya qoldi"
    )
    
    # Progress yangilash vazifasi
    async def update_progress_task():
        percent = 10
        while percent < 90:
            if state_manager.should_cancel(user_id):
                return
            await asyncio.sleep(PROGRESS_UPDATE_INTERVAL)
            percent = min(90, percent + 15)
            remaining = calculate_remaining_time(generation_status[user_id]["start_time"], percent)
            try:
                await progress_msg.edit_text(
                    f"🔄 Generatsiya davom etmoqda...\n{generate_progress_bar(percent)}\n"
                    f"Taxminan {remaining} qoldi"
                )
            except BadRequest:
                pass
    
    progress_task = asyncio.create_task(update_progress_task())
    state_manager.set_task(user_id, progress_task)
    
    try:
        # Edit funksiyasini chaqirish
        logger.info(f"Generatsiya boshlandi: user={user_id}, type={gen_type}")
        
        # Progress callback
        async def progress_callback(percent, text=""):
            try:
                if percent >= 90:
                    await progress_msg.edit_text("✅ Edit tayyor! Yuklanmoqda...")
            except BadRequest:
                pass
        
        # Edit funksiyasini bajarish
        if isinstance(video_path, list):
            # Merge uchun
            result = await edit_func(video_path, progress_callback=progress_callback)
        else:
            if args:
                result = await edit_func(video_path, *args, progress_callback=progress_callback)
            else:
                result = await edit_func(video_path, progress_callback=progress_callback)
        
        # Progress task ni to'xtatish
        progress_task.cancel()
        
        if result and os.path.exists(result):
            # Natijani yuborish
            await send_result(update, context, user_id, result, gen_type)
            
            # Statistikani yangilash
            increment_user_edits(user_id, gen_type)
        else:
            await progress_msg.edit_text(
                "❌ Edit qilishda xatolik. Qaytadan urinib ko'ring."
            )
            logger.error(f"Edit natijasi topilmadi: user={user_id}, type={gen_type}")
        
    except asyncio.CancelledError:
        logger.info(f"Generatsiya bekor qilindi: user={user_id}")
        try:
            await progress_msg.edit_text("❌ Generatsiya bekor qilindi!")
        except BadRequest:
            pass
    except Exception as e:
        logger.error(f"Generatsiya xatolik: {e}", exc_info=True)
        try:
            await progress_msg.edit_text(
                f"❌ Edit qilishda xatolik. Qaytadan urinib ko'ring.\n"
                f"Xatolik: {str(e)[:100]}"
            )
        except BadRequest:
            pass
        
        # Adminga xabar
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"⚠️ Botda xatolik:\nUser: {user_id}\nType: {gen_type}\nError: {e}"
                )
            except Exception:
                pass
    finally:
        # Tozalash
        state_manager.clear_task(user_id)
        state_manager.reset_state(user_id)
        generation_status.pop(user_id, None)


async def send_result(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      user_id: int, filepath: str, gen_type: str):
    """
    Natija faylini foydalanuvchiga yuborish
    
    Args:
        update: Telegram update
        context: Bot context
        user_id: Foydalanuvchi ID
        filepath: Natija fayli yo'li
        gen_type: Generatsiya turi
    """
    try:
        file_size = os.path.getsize(filepath)
        await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.UPLOAD_VIDEO)
        
        caption = f"✅ Edit tayyor! ({gen_type})\n📦 {format_file_size(file_size)}"
        
        # Fayl turiga qarab yuborish
        if filepath.endswith(".gif"):
            with open(filepath, "rb") as f:
                await context.bot.send_animation(
                    chat_id=user_id,
                    animation=InputFile(f),
                    caption=caption
                )
        elif filepath.endswith(".webm"):
            # Sticker sifatida yuborish
            with open(filepath, "rb") as f:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=InputFile(f),
                    caption=caption + "\n📱 Sticker sifatida saqlang"
                )
        elif gen_type == "round":
            # Video note (round video) sifatida yuborish
            with open(filepath, "rb") as f:
                await context.bot.send_video_note(
                    chat_id=user_id,
                    video_note=InputFile(f),
                    length=480
                )
            await context.bot.send_message(chat_id=user_id, text=caption)
        else:
            with open(filepath, "rb") as f:
                await context.bot.send_video(
                    chat_id=user_id,
                    video=InputFile(f),
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN
                )
        
        logger.info(f"Natija yuborildi: user={user_id}, file={filepath}")
        
    except Exception as e:
        logger.error(f"Natija yuborishda xatolik: {e}")
        
        # Katta fayl bo'lsa document sifatida yuborish
        try:
            with open(filepath, "rb") as f:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=InputFile(f),
                    caption=f"✅ Edit tayyor! ({gen_type})"
                )
        except Exception as e2:
            logger.error(f"Document yuborishda ham xatolik: {e2}")
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Natijani yuborishda xatolik. Iltimos qaytadan urinib ko'ring."
            )


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================

async def get_reply_video_path(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    Reply qilingan videoni yuklab olish
    
    Returns:
        Video fayli yo'li yoki None
    """
    reply = update.message.reply_to_message
    if not reply:
        return None
    
    video = reply.video or reply.document
    if not video:
        return None
    
    try:
        # Fayl hajmi tekshirish
        if video.file_size and video.file_size > MAX_FILE_SIZE:
            return None
        
        file = await video.get_file()
        filename = generate_unique_filename("reply", ".mp4")
        filepath = os.path.join(DOWNLOADS_DIR, filename)
        await file.download_to_drive(filepath)
        return filepath
    except Exception as e:
        logger.error(f"Reply video yuklashda xatolik: {e}")
        return None


async def daily_cleanup(context: ContextTypes.DEFAULT_TYPE):
    """Kunlik avtomatik tozalash - temp fayllarni o'chirish"""
    logger.info("Kunlik tozalash boshlandi...")
    cleaned = await cleanup_temp_files(max_age_hours=24)
    logger.info(f"Kunlik tozalash tugadi: {cleaned} ta fayl o'chirildi")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global xatolik handler"""
    logger.error(f"Xatolik: {context.error}", exc_info=context.error)
    
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Nimadir noto'g'ri ketdi. Qaytadan urinib ko'ring."
            )
        except Exception:
            pass


# ============================================================
# REFERAL TIZIMI
# ============================================================

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /referral - Referal link olish
    """
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Foydalanuvchi topilmadi.")
        return
    
    ref_code = user.get("referral_code", f"ref_{user_id}")
    referrals = user.get("referrals", 0)
    settings = get_bot_settings()
    bonus = settings.get("referral_bonus", 3)
    
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={ref_code}"
    
    text = (
        f"🎁 **Referal tizimi**\n\n"
        f"Do'stingizni taklif qiling va bonus oling!\n\n"
        f"📊 Sizning takliflaringiz: {referrals}\n"
        f"🎁 Har bir taklif uchun: {bonus} bepul edit\n\n"
        f"🔗 Sizning referal link:\n`{ref_link}`"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ============================================================
# ASOSIY FUNKSIYA
# ============================================================

def main():
    """
    Botni ishga tushirish - barcha handlerlarni ro'yxatdan o'tkazish
    """
    # Papkalarni yaratish
    setup_directories()
    
    # FFmpeg tekshirish
    if not check_ffmpeg():
        logger.warning("FFmpeg topilmadi! Ba'zi funksiyalar ishlamasligi mumkin.")
    
    # Application yaratish
    app = Application.builder().token(BOT_TOKEN).build()
    
    # === Command Handlerlar ===
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("round", round_command))
    app.add_handler(CommandHandler("speed", speed_command))
    app.add_handler(CommandHandler("trim", trim_command))
    app.add_handler(CommandHandler("music", music_command))
    app.add_handler(CommandHandler("watermark", watermark_command))
    app.add_handler(CommandHandler("filter", filter_command))
    app.add_handler(CommandHandler("merge", merge_command))
    app.add_handler(CommandHandler("compress", compress_command))
    app.add_handler(CommandHandler("crop", crop_command))
    app.add_handler(CommandHandler("rotate", rotate_command))
    app.add_handler(CommandHandler("reverse", reverse_command))
    app.add_handler(CommandHandler("gif", gif_command))
    app.add_handler(CommandHandler("sticker", sticker_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("referral", referral_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("block", handle_user_management))
    app.add_handler(CommandHandler("unblock", handle_user_management))
    app.add_handler(CommandHandler("premium", handle_user_management))
    app.add_handler(CommandHandler("unpremium", handle_user_management))
    
    # === Callback Query Handlerlar ===
    app.add_handler(CallbackQueryHandler(callback_handler, pattern=r"^(admin_|music_|speed_|filter_|compress_|crop_|rotate_|reverse_|filterintensity_)"))
    app.add_handler(CallbackQueryHandler(handle_download_callback, pattern=r"^dl_"))
    app.add_handler(CallbackQueryHandler(handle_cmd_callback, pattern=r"^(cmd_|merge_|musicvol_|musickeep_)"))
    app.add_handler(CallbackQueryHandler(handle_watermark_callback, pattern=r"^w(pos|size|color)_"))
    
    # === Message Handlerlar ===
    # Video qabul qilish
    app.add_handler(MessageHandler(
        filters.VIDEO | (filters.Document.VIDEO) | (filters.Document.MimeType("video/mp4")),
        handle_video
    ))
    # Audio qabul qilish
    app.add_handler(MessageHandler(
        filters.AUDIO | (filters.Document.AUDIO),
        handle_audio
    ))
    # Matn (state-ga qarab)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # === Xatolik handler ===
    app.add_error_handler(error_handler)
    
    # === Kunlik tozalash ===
    job_queue = app.job_queue
    if job_queue:
        # Har kuni soat 03:00 da tozalash
        job_queue.run_daily(daily_cleanup, time=datetime.strptime("03:00", "%H:%M").time())
    
    # Botni ishga tushirish
    logger.info("=" * 50)
    logger.info("Edit Bot.uz ishga tushmoqda...")
    logger.info(f"Owner ID: {OWNER_ID}")
    logger.info(f"Admin IDs: {ADMIN_IDS}")
    logger.info("=" * 50)
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
