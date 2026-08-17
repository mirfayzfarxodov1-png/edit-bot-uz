"""
Video yuklash moduli - yt-dlp yordamida turli platformalardan video yuklash
Qo'llab-quvvatlanadigan: YouTube, Instagram, TikTok, Twitter/X, Facebook,
Reddit, Vimeo, Dailymotion, Twitch, Pinterest, Telegram public
"""
import os
import asyncio
import logging
import subprocess
import json
import time
from typing import Optional, Dict, Callable

from config import DOWNLOADS_DIR, MAX_FILE_SIZE
from utils import generate_unique_filename, logger, format_file_size


SUPPORTED_PLATFORMS = {
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "instagram.com": "Instagram", "tiktok.com": "TikTok",
    "twitter.com": "Twitter/X", "x.com": "Twitter/X",
    "facebook.com": "Facebook", "fb.watch": "Facebook",
    "reddit.com": "Reddit", "vimeo.com": "Vimeo",
    "dailymotion.com": "Dailymotion", "twitch.tv": "Twitch",
    "pinterest.com": "Pinterest", "t.me": "Telegram",
}


def detect_platform(url: str) -> Optional[str]:
    """URL dan platforma nomini aniqlash"""
    url_lower = url.lower()
    for domain, platform in SUPPORTED_PLATFORMS.items():
        if domain in url_lower:
            return platform
    return None


def is_supported_url(url: str) -> bool:
    """URL qo'llab-quvvatlanadigan platformadanmi?"""
    return detect_platform(url) is not None


async def get_video_info_ytdlp(url: str) -> Optional[Dict]:
    """yt-dlp bilan video haqida ma'lumot olish (yuklamasdan)"""
    try:
        cmd = ["yt-dlp", "--dump-json", "--no-playlist", "--no-download", url]
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30))

        if result.returncode != 0:
            logger.warning(f"yt-dlp info xatolik: {result.stderr}")
            return None

        data = json.loads(result.stdout)
        return {
            "title": data.get("title", "Video"),
            "duration": data.get("duration", 0),
            "thumbnail": data.get("thumbnail", ""),
            "platform": detect_platform(url) or "Unknown",
            "uploader": data.get("uploader", "Unknown"),
            "view_count": data.get("view_count", 0),
            "description": (data.get("description", "") or "")[:200],
            "formats": len(data.get("formats", [])),
        }
    except Exception as e:
        logger.error(f"Video info olishda xatolik: {e}")
        return None


async def download_video(url, quality="best", audio_only=False, subtitle=False,
                         progress_callback=None):
    """URL dan video yuklash"""
    try:
        if progress_callback:
            await progress_callback(10, f"Platform: {detect_platform(url) or 'Unknown'}")

        timestamp = int(time.time())
        output_template = os.path.join(DOWNLOADS_DIR, f"dl_{timestamp}_%(title)s.%(ext)s")

        cmd = ["yt-dlp"]

        if audio_only:
            cmd += ["-f", "bestaudio/best", "--extract-audio",
                    "--audio-format", "mp3", "--audio-quality", "192K"]
        elif quality == "best":
            cmd += ["-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best"]
        elif quality == "720p":
            cmd += ["-f", "bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720]"]
        elif quality == "480p":
            cmd += ["-f", "bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480]"]
        elif quality == "360p":
            cmd += ["-f", "bestvideo[height<=360][ext=mp4]+bestaudio/best[height<=360]"]

        if subtitle:
            cmd += ["--write-sub", "--write-auto-sub", "--sub-lang", "en,uz,ru"]

        cmd += ["--max-filesize", "50M", "--merge-output-format", "mp4",
                "--no-playlist", "--restrict-filenames", "-o", output_template,
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "--add-header", "Accept-Language:uz-UZ,uz;q=0.9,en;q=0.8",
                url]

        if progress_callback:
            await progress_callback(20, "Yuklanmoqda...")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=300))

        if result.returncode != 0:
            logger.error(f"yt-dlp xatolik: {result.stderr}")
            return await download_video_simple(url, progress_callback)

        if progress_callback:
            await progress_callback(80, "Fayl topilmoqda...")

        downloaded_file = find_downloaded_file(DOWNLOADS_DIR, timestamp)

        if not downloaded_file:
            logger.error("Yuklangan fayl topilmadi")
            return None

        file_size = os.path.getsize(downloaded_file)
        if file_size > MAX_FILE_SIZE:
            logger.warning(f"Fayl hajmi katta: {format_file_size(file_size)}")
            os.remove(downloaded_file)
            return None

        if progress_callback:
            await progress_callback(95, f"Yuklandi: {format_file_size(file_size)}")

        logger.info(f"Video yuklandi: {downloaded_file} ({format_file_size(file_size)})")
        return downloaded_file
    except Exception as e:
        logger.error(f"Video yuklab olishda xatolik: {e}")
        return None


async def download_video_simple(url, progress_callback=None):
    """Soddalashtirilgan yuklash (fallback)"""
    try:
        timestamp = int(time.time())
        output_path = os.path.join(DOWNLOADS_DIR, f"dl_{timestamp}_video.mp4")

        cmd = ["yt-dlp", "-f", "best[ext=mp4]/best", "--no-playlist",
               "--max-filesize", "50M", "-o", output_path, url]

        if progress_callback:
            await progress_callback(30, "Sodda usul bilan yuklanmoqda...")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=300))

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        return None
    except Exception as e:
        logger.error(f"Sodda yuklashda xatolik: {e}")
        return None


async def download_audio_only(url, progress_callback=None):
    """URL dan faqat audio yuklash"""
    try:
        timestamp = int(time.time())
        output_template = os.path.join(DOWNLOADS_DIR, f"audio_{timestamp}_%(title)s.%(ext)s")

        cmd = ["yt-dlp", "-f", "bestaudio/best", "--extract-audio",
               "--audio-format", "mp3", "--audio-quality", "192K",
               "--no-playlist", "--restrict-filenames", "-o", output_template, url]

        if progress_callback:
            await progress_callback(20, "Audio yuklanmoqda...")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=180))

        if result.returncode != 0:
            logger.error(f"Audio yuklab olishda xatolik: {result.stderr}")
            return None

        if progress_callback:
            await progress_callback(80, "Audio fayl topilmoqda...")

        downloaded_file = find_downloaded_file(DOWNLOADS_DIR, timestamp)
        if downloaded_file:
            if progress_callback:
                await progress_callback(95, "Audio yuklandi!")
            return downloaded_file
        return None
    except Exception as e:
        logger.error(f"Audio yuklab olishda xatolik: {e}")
        return None


def find_downloaded_file(directory, timestamp):
    """Timestamp bo'yicha yuklangan faylni topish"""
    try:
        if not os.path.exists(directory):
            return None

        found_files = []
        for filename in os.listdir(directory):
            if str(timestamp) in filename:
                filepath = os.path.join(directory, filename)
                found_files.append((filepath, os.path.getmtime(filepath)))

        if found_files:
            found_files.sort(key=lambda x: x[1], reverse=True)
            return found_files[0][0]

        video_extensions = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".mp3", ".m4a"}
        all_files = []
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if any(filename.endswith(ext) for ext in video_extensions):
                mtime = os.path.getmtime(filepath)
                if mtime >= timestamp - 5:
                    all_files.append((filepath, mtime))

        if all_files:
            all_files.sort(key=lambda x: x[1], reverse=True)
            return all_files[0][0]
        return None
    except Exception as e:
        logger.error(f"Fayl qidirishda xatolik: {e}")
        return None


def get_supported_platforms_text():
    """Qo'llab-quvvatlanadigan platformalar ro'yxati"""
    platforms = [
        "🎬 YouTube (video, shorts, playlist)",
        "📸 Instagram (reels, posts, stories)",
        "🎵 TikTok",
        "🐦 Twitter/X",
        "👥 Facebook",
        "💬 Reddit",
        "🎞 Vimeo",
        "📺 Dailymotion",
        "🎮 Twitch (clip, vod)",
        "📌 Pinterest",
        "✈️ Telegram (public link)",
    ]
    return "\n".join(platforms)


async def check_ytdlp_installed():
    """yt-dlp o'rnatilganligini tekshirish"""
    try:
        result = subprocess.run(["yt-dlp", "--version"],
                                capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False
