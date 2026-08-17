"""
Yordamchi funksiyalar - umumiy ishlatilinadigan funksiyalar to'plami
"""
import os
import json
import logging
import asyncio
import time
import re
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from pathlib import Path

from config import (
    USERS_DB, STATS_DB, BOT_SETTINGS_DB, ADMIN_IDS,
    DOWNLOADS_DIR, OUTPUTS_DIR, TEMP_DIR, MUSIC_DIR, ADMIN_VIDEOS_DIR,
    FREE_DAILY_EDITS, LOG_FILE
)

# Logging sozlash
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def setup_directories():
    """Kerakli papkalarni yaratish"""
    dirs = [DOWNLOADS_DIR, OUTPUTS_DIR, TEMP_DIR, MUSIC_DIR, ADMIN_VIDEOS_DIR]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
    logger.info("Barcha papkalar yaratildi")


def load_json(filepath: str, default: dict = None) -> dict:
    """JSON fayldan ma'lumot o'qish"""
    if default is None:
        default = {}
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"JSON o'qishda xatolik {filepath}: {e}")
    return default


def save_json(filepath: str, data: dict) -> bool:
    """JSON faylga ma'lumot saqlash"""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"JSON saqlashda xatolik {filepath}: {e}")
        return False


def get_users() -> dict:
    return load_json(USERS_DB, {})


def save_users(users: dict) -> bool:
    return save_json(USERS_DB, users)


def get_stats() -> dict:
    default_stats = {
        "total_users": 0, "total_generations": 0,
        "daily_stats": {},
        "popular_edits": {
            "trim": 0, "music": 0, "filter": 0, "speed": 0,
            "watermark": 0, "merge": 0, "compress": 0, "crop": 0,
            "rotate": 0, "reverse": 0, "gif": 0, "sticker": 0, "round": 0,
        },
    }
    return load_json(STATS_DB, default_stats)


def save_stats(stats: dict) -> bool:
    return save_json(STATS_DB, stats)


def get_bot_settings() -> dict:
    default_settings = {
        "maintenance_mode": False,
        "max_file_size": 50,
        "free_daily_edits": FREE_DAILY_EDITS,
        "welcome_message": "Xush kelibsiz! Edit Bot.uz ga!",
        "blocked_users": [],
        "premium_users": [],
        "referral_bonus": 3,
    }
    return load_json(BOT_SETTINGS_DB, default_settings)


def save_bot_settings(settings: dict) -> bool:
    return save_json(BOT_SETTINGS_DB, settings)


def register_user(user_id: int, username: str, first_name: str, last_name: str = "") -> dict:
    """Yangi foydalanuvchini ro'yxatdan o'tkazish yoki yangilash"""
    users = get_users()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if str(user_id) not in users:
        users[str(user_id)] = {
            "user_id": user_id,
            "username": username or "",
            "first_name": first_name or "",
            "last_name": last_name or "",
            "joined_date": now,
            "total_edits": 0,
            "daily_edits": 0,
            "daily_reset": str(date.today()),
            "last_activity": now,
            "is_premium": False,
            "is_blocked": False,
            "referral_code": f"ref_{user_id}",
            "referrals": 0,
            "templates": [],
        }
        stats = get_stats()
        stats["total_users"] = len(users)
        save_stats(stats)
        logger.info(f"Yangi foydalanuvchi: {user_id} ({first_name})")
    else:
        users[str(user_id)]["last_activity"] = now
        users[str(user_id)]["username"] = username or users[str(user_id)].get("username", "")

    save_users(users)
    return users[str(user_id)]


def get_user(user_id: int) -> Optional[dict]:
    users = get_users()
    return users.get(str(user_id))


def increment_user_edits(user_id: int, edit_type: str = "general") -> bool:
    """Foydalanuvchi editlar sonini oshirish"""
    users = get_users()
    key = str(user_id)
    if key not in users:
        return False

    today = str(date.today())
    if users[key].get("daily_reset") != today:
        users[key]["daily_edits"] = 0
        users[key]["daily_reset"] = today

    users[key]["total_edits"] = users[key].get("total_edits", 0) + 1
    users[key]["daily_edits"] = users[key].get("daily_edits", 0) + 1
    users[key]["last_activity"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_users(users)

    stats = get_stats()
    stats["total_generations"] = stats.get("total_generations", 0) + 1
    today_key = str(date.today())
    if "daily_stats" not in stats:
        stats["daily_stats"] = {}
    stats["daily_stats"][today_key] = stats["daily_stats"].get(today_key, 0) + 1
    if "popular_edits" not in stats:
        stats["popular_edits"] = {}
    stats["popular_edits"][edit_type] = stats["popular_edits"].get(edit_type, 0) + 1
    save_stats(stats)
    return True


def check_daily_limit(user_id: int) -> tuple:
    """Kunlik limit tekshirish. (can_edit, remaining) qaytaradi"""
    settings = get_bot_settings()
    users = get_users()
    key = str(user_id)

    if key not in users:
        return True, settings.get("free_daily_edits", FREE_DAILY_EDITS)

    user = users[key]
    if user.get("is_premium", False):
        return True, 9999
    if user_id in ADMIN_IDS:
        return True, 9999

    today = str(date.today())
    if user.get("daily_reset") != today:
        return True, settings.get("free_daily_edits", FREE_DAILY_EDITS)

    daily_edits = user.get("daily_edits", 0)
    max_daily = settings.get("free_daily_edits", FREE_DAILY_EDITS)
    remaining = max(0, max_daily - daily_edits)
    return remaining > 0, remaining


def is_user_blocked(user_id: int) -> bool:
    users = get_users()
    user = users.get(str(user_id), {})
    return user.get("is_blocked", False)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_premium(user_id: int) -> bool:
    users = get_users()
    user = users.get(str(user_id), {})
    return user.get("is_premium", False)


def parse_time_to_seconds(time_str: str) -> Optional[float]:
    """Vaqt formatini sekundga o'girish (mm:ss, ss, hh:mm:ss)"""
    try:
        time_str = time_str.strip()
        if re.match(r"^\d+(\.\d+)?$", time_str):
            return float(time_str)
        if re.match(r"^\d{1,2}:\d{2}(\.\d+)?$", time_str):
            parts = time_str.split(":")
            return int(parts[0]) * 60 + float(parts[1])
        if re.match(r"^\d{1,2}:\d{2}:\d{2}(\.\d+)?$", time_str):
            parts = time_str.split(":")
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except Exception:
        pass
    return None


def seconds_to_time_str(seconds: float) -> str:
    """Sekundni vaqt formatiga o'girish (mm:ss)"""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def format_file_size(size_bytes: int) -> str:
    """Fayl hajmini o'qilishi qulay formatga o'girish"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def generate_progress_bar(percent: int, length: int = 10) -> str:
    """Progress bar yaratish: [████████░░] 80%"""
    filled = int(length * percent / 100)
    empty = length - filled
    bar = "█" * filled + "░" * empty
    return f"[{bar}] {percent}%"


def calculate_remaining_time(start_time: float, percent: int, total_estimate: int = 180) -> str:
    """Qolgan vaqtni hisoblash"""
    if percent <= 0:
        return f"~{total_estimate} soniya"
    elapsed = time.time() - start_time
    estimated_total = elapsed / (percent / 100)
    remaining = max(0, estimated_total - elapsed)
    if remaining < 60:
        return f"~{int(remaining)} soniya"
    else:
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        return f"~{mins} daqiqa {secs} soniya"


def get_file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def generate_unique_filename(prefix: str = "edit", extension: str = ".mp4") -> str:
    """Noyob fayl nomi yaratish"""
    timestamp = int(time.time())
    return f"{prefix}_{timestamp}{extension}"


async def cleanup_temp_files(max_age_hours: int = 24):
    """Eski vaqtinchalik fayllarni tozalash"""
    now = time.time()
    max_age = max_age_hours * 3600
    cleaned = 0
    for directory in [DOWNLOADS_DIR, OUTPUTS_DIR, TEMP_DIR]:
        if not os.path.exists(directory):
            continue
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            try:
                if os.path.isfile(filepath):
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > max_age:
                        os.remove(filepath)
                        cleaned += 1
            except Exception as e:
                logger.error(f"Faylni o'chirishda xatolik {filepath}: {e}")
    logger.info(f"Tozalash tugadi: {cleaned} ta fayl o'chirildi")
    return cleaned


def get_admin_video() -> Optional[str]:
    """Admin yuklagan videoni olish"""
    if not os.path.exists(ADMIN_VIDEOS_DIR):
        return None
    for f in sorted(os.listdir(ADMIN_VIDEOS_DIR), reverse=True):
        if f.endswith((".mp4", ".mov", ".avi", ".mkv")):
            return os.path.join(ADMIN_VIDEOS_DIR, f)
    return None


def get_all_users_list() -> List[dict]:
    users = get_users()
    return list(users.values())


def block_user(user_id: int) -> bool:
    users = get_users()
    key = str(user_id)
    if key in users:
        users[key]["is_blocked"] = True
        save_users(users)
        return True
    return False


def unblock_user(user_id: int) -> bool:
    users = get_users()
    key = str(user_id)
    if key in users:
        users[key]["is_blocked"] = False
        save_users(users)
        return True
    return False


def set_premium(user_id: int, status: bool = True) -> bool:
    users = get_users()
    key = str(user_id)
    if key in users:
        users[key]["is_premium"] = status
        save_users(users)
        return True
    return False


def get_recent_logs(lines: int = 50) -> str:
    """So'nggi log yozuvlarini olish"""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
                return "".join(all_lines[-lines:])
    except Exception as e:
        return f"Loglarni o'qishda xatolik: {e}"
    return "Log fayli topilmadi"


def validate_link(url: str) -> bool:
    """URL to'g'riligini tekshirish"""
    pattern = re.compile(
        r"^(https?://)?"
        r"((([a-z\d]([a-z\d-]*[a-z\d])*)\.)+[a-z]{2,}|"
        r"((\d{1,3}\.){3}\d{1,3}))"
        r"(\:\d+)?(\/[-a-z\d%_.~+]*)*"
        r"(\?[;&a-z\d%_.~+=-]*)?"
        r"(\#[-a-z\d_]*)?$",
        re.IGNORECASE,
    )
    return bool(pattern.match(url))


def format_user_info(user: dict) -> str:
    """Foydalanuvchi ma'lumotlarini formatlash"""
    lines = [
        f"ID: {user.get('user_id', 'N/A')}",
        f"Ism: {user.get('first_name', '')} {user.get('last_name', '')}".strip(),
        f"Username: @{user.get('username', 'N/A')}",
        f"Qo'shildi: {user.get('joined_date', 'N/A')}",
        f"Jami editlar: {user.get('total_edits', 0)}",
        f"Bugungi editlar: {user.get('daily_edits', 0)}",
        f"Premium: {'Ha' if user.get('is_premium') else 'Yoq'}",
        f"Bloklangan: {'Ha' if user.get('is_blocked') else 'Yoq'}",
    ]
    return "\n".join(lines)


async def safe_delete_file(filepath: str):
    """Faylni xavfsiz o'chirish"""
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
            logger.debug(f"Fayl o'chirildi: {filepath}")
    except Exception as e:
        logger.error(f"Faylni o'chirishda xatolik: {e}")
