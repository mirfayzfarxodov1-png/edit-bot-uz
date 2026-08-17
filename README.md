# Edit Bot.uz - Telegram Video Edit Bot

## O'rnatish

```bash
cd telegram_bot
pip install -r requirements.txt

# .env faylini yarating
cp .env.example .env
# .env faylga BOT_TOKEN ni yozing

# Papkalarni yarating (avtomatik yaratiladi)
# downloads/, outputs/, temp/, music/, admin_videos/

# FFmpeg ni o'rnatish (majburiy)
# Ubuntu/Debian: sudo apt install ffmpeg
# macOS: brew install ffmpeg
# Windows: https://ffmpeg.org/download.html

# yt-dlp ni o'rnatish (linkdan yuklash uchun)
pip install yt-dlp

# Botni ishga tushirish
python bot.py
```

## Fayllar tuzilishi

```
telegram_bot/
├── bot.py            # Asosiy bot - handlerlar va buyruqlar
├── video_editor.py   # Barcha video edit funksiyalari (FFmpeg + MoviePy)
├── downloader.py     # Linkdan video yuklash (yt-dlp)
├── admin.py          # Admin panel
├── states.py         # State management
├── utils.py          # Yordamchi funksiyalar
├── config.py         # Sozlamalar va konstantalar
├── requirements.txt  # Kutubxonalar
├── .env.example      # Environment o'zgaruvchilar namunasi
├── downloads/        # Yuklangan videolar
├── outputs/          # Tayyor editlar
├── temp/             # Vaqtinchalik fayllar
├── music/            # Musiqa kutubxonasi
└── admin_videos/     # Admin videolari
```

## Buyruqlar

| Buyruq | Tavsif |
|--------|--------|
| /start | Botni ishga tushirish |
| /help | Yordam menyusi |
| /trim | Video kesish |
| /watermark | Matn qo'shish |
| /music | Musiqa qo'shish |
| /speed | Tezlikni o'zgartirish |
| /filter | Filter qo'shish |
| /round | Aylana video |
| /merge | Videolarni birlashtirish |
| /compress | Videoni siqish |
| /crop | Kesib olish |
| /rotate | Aylantirish |
| /reverse | Teskari video |
| /gif | GIF yaratish |
| /sticker | Sticker yaratish |
| /info | Video ma'lumoti |
| /admin | Admin panel |
| /cancel | Bekor qilish |
| /status | Holatni ko'rish |

## Admin buyruqlari

- `/block <user_id>` - Foydalanuvchini bloklash
- `/unblock <user_id>` - Blokdan chiqarish
- `/premium <user_id>` - Premium berish
- `/unpremium <user_id>` - Premiumni olish
- `/admin` - Admin panel (statistika, broadcast, loglar, sozlamalar)

## Musiqa kutubxonasi

`music/` papkasiga quyidagi nomlar bilan MP3 fayllarni joylang:
- epic_cinematic.mp3
- sad_piano.mp3
- happy_ukulele.mp3
- romantic_love.mp3
- action_rock.mp3
- funny_comedy.mp3
- dark_horror.mp3
- calm_nature.mp3
- retro_synthwave.mp3
- party_edm.mp3

## Texnik talablar

- Python 3.10+
- FFmpeg (video edit uchun)
- yt-dlp (linkdan yuklash uchun)
- 50MB gacha video fayllar
