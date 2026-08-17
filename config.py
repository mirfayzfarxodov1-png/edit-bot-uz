"""
Konfiguratsiya fayli - bot sozlamalari va konstantalar
"""
import os
from dotenv import load_dotenv

# .env fayldan o'qish - aniq yo'lni ko'rsatish
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)

# Bot asosiy sozlamalari - BOT_TOKEN ni birinchi navbatda TELEGRAM_BOT_TOKEN dan o'qiymiz
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

# Agar token bo'sh bo'lsa, xatolik chiqaramiz
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi! Iltimos, .env faylini tekshiring.")

OWNER_ID = int(os.getenv("OWNER_ID", "8404514882"))
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "5675087151,8404514882").split(",") if x.strip()]

# Fayl o'lcham chegaralari
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_VIDEO_DURATION = 600  # 10 daqiqa (sekund)
MAX_ROUND_DURATION = 60   # Aylana video 60 sekund

# Papkalar
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
MUSIC_DIR = os.path.join(BASE_DIR, "music")
ADMIN_VIDEOS_DIR = os.path.join(BASE_DIR, "admin_videos")

# Ma'lumotlar bazasi fayllari
USERS_DB = os.path.join(BASE_DIR, "users.json")
STATS_DB = os.path.join(BASE_DIR, "stats.json")
BOT_SETTINGS_DB = os.path.join(BASE_DIR, "bot_settings.json")

# Progress yangilanish vaqti (sekund)
PROGRESS_UPDATE_INTERVAL = 18

# Kunlik bepul editlar soni
FREE_DAILY_EDITS = 5

# Tezlik variantlari
SPEED_OPTIONS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 3.0, 4.0]

# Video sifat darajalari
QUALITY_OPTIONS = {
    "past": {"resolution": "480p", "bitrate": "800k", "crf": 28},
    "orta": {"resolution": "720p", "bitrate": "1500k", "crf": 23},
    "yuqori": {"resolution": "1080p", "bitrate": "3000k", "crf": 18},
    "juda_yuqori": {"resolution": "original", "bitrate": "5000k", "crf": 15},
}

# Musiqa kutubxonasi
MUSIC_LIBRARY = [
    {"id": 1, "name": "Epic - Dramatic Cinematic", "duration": "00:30", "file": "epic_cinematic.mp3"},
    {"id": 2, "name": "Sad - Emotional Piano", "duration": "00:45", "file": "sad_piano.mp3"},
    {"id": 3, "name": "Happy - Upbeat Ukulele", "duration": "00:35", "file": "happy_ukulele.mp3"},
    {"id": 4, "name": "Romantic - Love Theme", "duration": "01:00", "file": "romantic_love.mp3"},
    {"id": 5, "name": "Action - Fast Rock", "duration": "00:40", "file": "action_rock.mp3"},
    {"id": 6, "name": "Funny - Comedy Sound", "duration": "00:25", "file": "funny_comedy.mp3"},
    {"id": 7, "name": "Dark - Horror Ambient", "duration": "00:50", "file": "dark_horror.mp3"},
    {"id": 8, "name": "Calm - Nature Relax", "duration": "01:15", "file": "calm_nature.mp3"},
    {"id": 9, "name": "Retro - 80s Synthwave", "duration": "00:55", "file": "retro_synthwave.mp3"},
    {"id": 10, "name": "Party - EDM Dance", "duration": "01:00", "file": "party_edm.mp3"},
]

# Filterlar
FILTER_OPTIONS = [
    "grayscale", "sepia", "blur_light", "blur_medium", "blur_heavy",
    "negative", "brightness", "contrast", "saturation",
    "vignette", "pixelate", "oil_painting",
]

# Matn joylashuvi
TEXT_POSITIONS = ["top-left", "top-right", "bottom-left", "bottom-right", "center"]

# Matn o'lchamlari
TEXT_SIZES = {"kichik": 24, "orta": 36, "katta": 48}

# Matn ranglari
TEXT_COLORS = {
    "oq": "white", "qora": "black", "qizil": "red",
    "ko'k": "blue", "yashil": "green", "sariq": "yellow",
}

# Crop nisbatlari
CROP_RATIOS = ["16:9", "9:16", "4:3", "1:1", "custom"]

# Transition turlari
TRANSITION_TYPES = ["none", "fade_in", "fade_out", "crossfade"]

# Log fayli
LOG_FILE = os.path.join(BASE_DIR, "bot.log")
