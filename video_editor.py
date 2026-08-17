"""
Video tahrirlash funksiyalari - barcha real video edit operatsiyalari
FFmpeg va MoviePy yordamida amalga oshiriladi
"""
import os
import logging
import subprocess
import asyncio
import time
import numpy as np
from pathlib import Path
from typing import Optional, Callable, Tuple

import cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeVideoClip,
    concatenate_videoclips, ImageClip, TextClip, CompositeAudioClip
)

from config import TEMP_DIR, OUTPUTS_DIR, TEXT_SIZES, TEXT_COLORS, TEXT_POSITIONS
from utils import generate_unique_filename, logger, safe_delete_file


def check_ffmpeg():
    """FFmpeg o'rnatilganligini tekshirish"""
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def run_ffmpeg(cmd: list, timeout: int = 300) -> Tuple[bool, str]:
    """FFmpeg buyrug'ini ishga tushirish"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            logger.error(f"FFmpeg xatolik: {result.stderr}")
            return False, result.stderr
        return True, result.stdout
    except subprocess.TimeoutExpired:
        return False, "Vaqt tugadi"
    except Exception as e:
        return False, str(e)


# ============================================================
# TRIM - Video kesish
# ============================================================

async def trim_video(input_path, start_time, end_time, progress_callback=None):
    """Videoni kesish - start va end vaqt bo'yicha"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("trim"))
    try:
        if progress_callback:
            await progress_callback(20, "Video kesish boshlandi...")

        cmd = ["ffmpeg", "-y", "-i", input_path,
               "-ss", str(start_time), "-to", str(end_time),
               "-c", "copy", output_path]

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            if progress_callback:
                await progress_callback(40, "Alternativ usul...")
            clip = VideoFileClip(input_path).subclip(start_time, end_time)
            clip.write_videofile(output_path, codec="libx264", audio_codec="aac",
                                 verbose=False, logger=None)
            clip.close()

        if progress_callback:
            await progress_callback(90, "Fayl saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Video kesishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# WATERMARK - Matn qo'shish
# ============================================================

async def add_watermark(input_path, text, position="bottom-right",
                        font_size="orta", color="oq", progress_callback=None):
    """Videoga matn (watermark) qo'shish"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("watermark"))
    try:
        if progress_callback:
            await progress_callback(20, "Matn qo'shish boshlandi...")

        size = TEXT_SIZES.get(font_size, 36)
        hex_color = color_to_hex(color)

        pos_map = {
            "top-left": "10:10",
            "top-right": "main_w-text_w-10:10",
            "bottom-left": "10:main_h-text_h-10",
            "bottom-right": "main_w-text_w-10:main_h-text_h-10",
            "center": "(main_w-text_w)/2:(main_h-text_h)/2",
        }
        pos = pos_map.get(position, pos_map["bottom-right"])

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"drawtext=text='{text}':fontsize={size}:fontcolor={hex_color}"
                   f":x={pos.split(':')[0]}:y={pos.split(':')[1]}"
                   f":box=1:boxcolor=black@0.4:boxborderw=5",
            "-codec:a", "copy", output_path
        ]

        if progress_callback:
            await progress_callback(50, "Matn qo'yilmoqda...")

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            # Fallback - OpenCV
            if progress_callback:
                await progress_callback(60, "OpenCV usuli...")
            result = await _add_watermark_opencv(input_path, text, position, size, color, output_path)
            if not result:
                return None

        if progress_callback:
            await progress_callback(90, "Fayl saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Watermark qo'shishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


async def _add_watermark_opencv(input_path, text, position, font_size, color, output_path):
    """OpenCV yordamida watermark qo'shish (fallback)"""
    try:
        cap = cv2.VideoCapture(input_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        temp_video = os.path.join(TEMP_DIR, generate_unique_filename("temp_wm"))
        out = cv2.VideoWriter(temp_video, fourcc, fps, (width, height))

        color_bgr = color_to_bgr(color)
        font_scale = font_size / 30
        thickness = max(1, int(font_scale * 2))

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)[0]
            x, y = calculate_text_position(position, width, height, text_size)
            cv2.putText(frame, text, (x+2, y+2), cv2.FONT_HERSHEY_SIMPLEX,
                        font_scale, (0, 0, 0), thickness+1)
            cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                        font_scale, color_bgr, thickness)
            out.write(frame)

        cap.release()
        out.release()

        cmd = ["ffmpeg", "-y", "-i", temp_video, "-i", input_path,
               "-map", "0:v", "-map", "1:a?", "-c", "copy", output_path]
        run_ffmpeg(cmd)
        await safe_delete_file(temp_video)
        return True
    except Exception as e:
        logger.error(f"OpenCV watermark xatolik: {e}")
        return False


# ============================================================
# MUSIC - Musiqa qo'shish
# ============================================================

async def add_music(video_path, audio_path, volume=1.0, keep_original=True, progress_callback=None):
    """Videoga musiqa qo'shish"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("music"))
    try:
        if progress_callback:
            await progress_callback(20, "Musiqa qo'shish boshlandi...")

        if keep_original:
            cmd = ["ffmpeg", "-y", "-i", video_path, "-i", audio_path,
                   "-filter_complex",
                   f"[1:a]volume={volume}[music];[0:a][music]amix=inputs=2:duration=first[aout]",
                   "-map", "0:v", "-map", "[aout]",
                   "-c:v", "copy", "-c:a", "aac", "-shortest", output_path]
        else:
            cmd = ["ffmpeg", "-y", "-i", video_path, "-i", audio_path,
                   "-map", "0:v", "-map", "1:a",
                   "-c:v", "copy", "-c:a", "aac",
                   f"-af", f"volume={volume}", "-shortest", output_path]

        if progress_callback:
            await progress_callback(60, "Audio qo'yilmoqda...")

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            # MoviePy fallback
            video_clip = VideoFileClip(video_path)
            audio_clip = AudioFileClip(audio_path).volumex(volume)
            if keep_original and video_clip.audio:
                final_audio = CompositeAudioClip([video_clip.audio, audio_clip])
                video_clip = video_clip.set_audio(final_audio)
            else:
                video_clip = video_clip.set_audio(audio_clip)
            video_clip = video_clip.subclip(0, video_clip.duration)
            video_clip.write_videofile(output_path, codec="libx264", audio_codec="aac",
                                       verbose=False, logger=None)
            video_clip.close()

        if progress_callback:
            await progress_callback(90, "Fayl saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Musiqa qo'shishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# SPEED - Tezlikni o'zgartirish
# ============================================================

async def change_speed(input_path, speed=2.0, progress_callback=None):
    """Video tezligini o'zgartirish"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("speed"))
    try:
        if progress_callback:
            await progress_callback(20, f"Tezlik {speed}x ga o'zgartirilmoqda...")

        vpts = 1.0 / speed
        if speed > 2.0:
            audio_filter = f"atempo=2.0,atempo={speed/2.0}"
        elif speed < 0.5:
            audio_filter = f"atempo=0.5,atempo={speed/0.5}"
        else:
            audio_filter = f"atempo={speed}"

        cmd = ["ffmpeg", "-y", "-i", input_path,
               "-filter_complex",
               f"[0:v]setpts={vpts}*PTS[v];[0:a]{audio_filter}[a]",
               "-map", "[v]", "-map", "[a]", output_path]

        if progress_callback:
            await progress_callback(60, "Tezlik o'zgartirilmoqda...")

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            clip = VideoFileClip(input_path)
            new_clip = clip.speedx(factor=speed)
            new_clip.write_videofile(output_path, codec="libx264", audio_codec="aac",
                                     verbose=False, logger=None)
            clip.close()
            new_clip.close()

        if progress_callback:
            await progress_callback(90, "Fayl saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Tezlik o'zgartirishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# FILTER - Filter qo'shish
# ============================================================

async def apply_filter(input_path, filter_type, intensity=1.0, progress_callback=None):
    """Videoga filter qo'shish"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename(f"filter_{filter_type}"))
    try:
        if progress_callback:
            await progress_callback(20, f"{filter_type} filter qo'yilmoqda...")

        vf_filter = get_ffmpeg_filter(filter_type, intensity)
        cmd = ["ffmpeg", "-y", "-i", input_path, "-vf", vf_filter,
               "-codec:a", "copy", output_path]

        if progress_callback:
            await progress_callback(50, "Filter ishlanmoqda...")

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            if progress_callback:
                await progress_callback(60, "Alternativ usul...")
            result = await apply_filter_opencv(input_path, filter_type, intensity, output_path)
            if not result:
                return None

        if progress_callback:
            await progress_callback(90, "Fayl saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Filter qo'shishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


def get_ffmpeg_filter(filter_type, intensity=1.0):
    """Filter turiga mos FFmpeg filter qatori"""
    filters = {
        "grayscale": "colorchannelmixer=.3:.4:.3:0:.3:.4:.3:0:.3:.4:.3",
        "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
        "blur_light": "boxblur=2:1",
        "blur_medium": "boxblur=5:2",
        "blur_heavy": "boxblur=10:3",
        "negative": "negate",
        "brightness": f"eq=brightness={0.3 * intensity}",
        "contrast": f"eq=contrast={1 + intensity}",
        "saturation": f"eq=saturation={1 + intensity}",
        "vignette": f"vignette=PI/4*{intensity}",
        "pixelate": f"scale=iw/{int(10*intensity+5)}:ih/{int(10*intensity+5)},scale=iw*{int(10*intensity+5)}:ih*{int(10*intensity+5)}:flags=neighbor",
        "oil_painting": "edgedetect=low=0.1:high=0.4",
    }
    return filters.get(filter_type, "null")


async def apply_filter_opencv(input_path, filter_type, intensity, output_path):
    """OpenCV bilan filter qo'shish (fallback)"""
    try:
        cap = cv2.VideoCapture(input_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        temp_video = os.path.join(TEMP_DIR, generate_unique_filename("temp_filter"))
        out = cv2.VideoWriter(temp_video, fourcc, fps, (width, height))

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame = apply_frame_filter(frame, filter_type, intensity)
            out.write(frame)

        cap.release()
        out.release()

        cmd = ["ffmpeg", "-y", "-i", temp_video, "-i", input_path,
               "-map", "0:v", "-map", "1:a?", "-c:v", "libx264",
               "-c:a", "copy", output_path]
        run_ffmpeg(cmd)
        await safe_delete_file(temp_video)
        return True
    except Exception as e:
        logger.error(f"OpenCV filter xatolik: {e}")
        return False


def apply_frame_filter(frame, filter_type, intensity=1.0):
    """Bitta kadrga filter qo'shish"""
    if filter_type == "grayscale":
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    elif filter_type == "sepia":
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sepia = np.zeros_like(frame)
        sepia[:, :, 0] = np.clip(gray * 0.272 + gray * 0.534 + gray * 0.131, 0, 255)
        sepia[:, :, 1] = np.clip(gray * 0.349 + gray * 0.686 + gray * 0.168, 0, 255)
        sepia[:, :, 2] = np.clip(gray * 0.393 + gray * 0.769 + gray * 0.189, 0, 255)
        return sepia.astype(np.uint8)
    elif filter_type in ["blur_light", "blur_medium", "blur_heavy"]:
        blur_map = {"blur_light": 3, "blur_medium": 9, "blur_heavy": 21}
        k = blur_map[filter_type]
        return cv2.GaussianBlur(frame, (k, k), 0)
    elif filter_type == "negative":
        return cv2.bitwise_not(frame)
    elif filter_type == "brightness":
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * (1 + intensity * 0.5), 0, 255)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    elif filter_type == "vignette":
        rows, cols = frame.shape[:2]
        kernel_x = cv2.getGaussianKernel(cols, cols * 0.5)
        kernel_y = cv2.getGaussianKernel(rows, rows * 0.5)
        kernel = kernel_y * kernel_x.T
        mask = kernel / kernel.max()
        vignette = np.copy(frame)
        for i in range(3):
            vignette[:, :, i] = (vignette[:, :, i] * mask).astype(np.uint8)
        return vignette
    elif filter_type == "pixelate":
        pixel_size = max(5, int(20 * intensity))
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (w // pixel_size, h // pixel_size), interpolation=cv2.INTER_LINEAR)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    return frame


# ============================================================
# ROUND VIDEO - Aylana video
# ============================================================

async def make_round_video(input_path, progress_callback=None):
    """Videoni aylana shaklida (round video/video note) tayyorlash"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("round", ".mp4"))
    try:
        if progress_callback:
            await progress_callback(20, "Aylana video tayyorlanmoqda...")

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", ("scale=480:480:force_original_aspect_ratio=increase,"
                    "crop=480:480,format=yuva420p,"
                    "geq=lum='p(X,Y)':a='if(gt(pow(X-240,2)+pow(Y-240,2),pow(240,2)),0,255)'"),
            "-t", "60", "-c:v", "libx264", "-c:a", "aac",
            "-pix_fmt", "yuv420p", output_path
        ]

        if progress_callback:
            await progress_callback(50, "Doira shakllantirilmoqda...")

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            cmd2 = ["ffmpeg", "-y", "-i", input_path,
                    "-vf", "scale=480:480:force_original_aspect_ratio=increase,crop=480:480",
                    "-t", "60", "-c:v", "libx264", "-c:a", "aac", output_path]
            success2, _ = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd2))
            if not success2:
                return None

        if progress_callback:
            await progress_callback(90, "Aylana video tayyor...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Aylana video yaratishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# MERGE - Videolarni birlashtirish
# ============================================================

async def merge_videos(video_paths, transition="none", progress_callback=None):
    """Ikki yoki undan ortiq videoni birlashtirish"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("merge"))
    temp_list = os.path.join(TEMP_DIR, "merge_list.txt")
    try:
        if progress_callback:
            await progress_callback(20, "Videolar birlashtirilmoqda...")

        normalized_paths = []
        for i, vp in enumerate(video_paths):
            norm_path = os.path.join(TEMP_DIR, f"norm_{i}_{int(time.time())}.mp4")
            cmd = ["ffmpeg", "-y", "-i", vp,
                   "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                   "-c:v", "libx264", "-c:a", "aac", "-r", "30", norm_path]
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda c=cmd: run_ffmpeg(c))
            normalized_paths.append(norm_path)

        if progress_callback:
            await progress_callback(50, "Qo'shish amalga oshirilmoqda...")

        with open(temp_list, "w") as f:
            for p in normalized_paths:
                f.write(f"file '{p}'\n")

        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
               "-i", temp_list, "-c", "copy", output_path]
        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            clips = [VideoFileClip(p) for p in video_paths]
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(output_path, codec="libx264", audio_codec="aac",
                                  verbose=False, logger=None)
            for c in clips:
                c.close()

        for p in normalized_paths:
            await safe_delete_file(p)
        await safe_delete_file(temp_list)

        if progress_callback:
            await progress_callback(90, "Fayl saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Video birlashtirishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# COMPRESS - Videoni siqish
# ============================================================

async def compress_video(input_path, quality="orta", progress_callback=None):
    """Videoni siqish"""
    from config import QUALITY_OPTIONS
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("compress"))
    try:
        if progress_callback:
            await progress_callback(20, "Video siqilmoqda...")

        q_settings = QUALITY_OPTIONS.get(quality, QUALITY_OPTIONS["orta"])
        crf = q_settings["crf"]
        bitrate = q_settings["bitrate"]

        if quality == "juda_yuqori":
            scale_filter = ""
        else:
            res_map = {"past": "854:480", "orta": "1280:720", "yuqori": "1920:1080"}
            target_res = res_map.get(quality, "1280:720")
            scale_filter = f"scale={target_res}:force_original_aspect_ratio=decrease"

        cmd = ["ffmpeg", "-y", "-i", input_path]
        if scale_filter:
            cmd += ["-vf", scale_filter]
        cmd += ["-c:v", "libx264", "-crf", str(crf), "-b:v", bitrate,
                "-c:a", "aac", "-b:a", "128k", output_path]

        if progress_callback:
            await progress_callback(60, "Siqish amalga oshirilmoqda...")

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            return None

        if progress_callback:
            await progress_callback(90, "Fayl saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Video siqishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# CROP - Videoni kesib olish
# ============================================================

async def crop_video(input_path, ratio="16:9", x=None, y=None,
                     width=None, height=None, progress_callback=None):
    """Videoni kesib olish (crop)"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("crop"))
    try:
        if progress_callback:
            await progress_callback(20, "Video kesib olinmoqda...")

        if ratio and ratio != "custom":
            ratio_filters = {
                "16:9": "crop=iw:iw*9/16",
                "9:16": "crop=ih*9/16:ih",
                "4:3": "crop=ih*4/3:ih",
                "1:1": "crop=min(iw\\,ih):min(iw\\,ih)",
            }
            crop_filter = ratio_filters.get(ratio, ratio_filters["16:9"])
        elif all(v is not None for v in [x, y, width, height]):
            crop_filter = f"crop={width}:{height}:{x}:{y}"
        else:
            crop_filter = "crop=iw:ih"

        cmd = ["ffmpeg", "-y", "-i", input_path, "-vf", crop_filter,
               "-codec:a", "copy", output_path]

        if progress_callback:
            await progress_callback(60, "Kesib olish amalga oshirilmoqda...")

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            return None

        if progress_callback:
            await progress_callback(90, "Fayl saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Video kesib olishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# ROTATE - Videoni aylantirish
# ============================================================

async def rotate_video(input_path, angle=90, flip=None, progress_callback=None):
    """Videoni aylantirish"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("rotate"))
    try:
        if progress_callback:
            await progress_callback(20, "Video aylantirilmoqda...")

        transpose_map = {90: "transpose=1", 180: "transpose=2,transpose=2", 270: "transpose=2"}

        if flip == "horizontal":
            vf = "hflip"
        elif flip == "vertical":
            vf = "vflip"
        elif angle in transpose_map:
            vf = transpose_map[angle]
        else:
            vf = "null"

        cmd = ["ffmpeg", "-y", "-i", input_path, "-vf", vf,
               "-codec:a", "copy", output_path]

        if progress_callback:
            await progress_callback(60, "Aylantirish amalga oshirilmoqda...")

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            return None

        if progress_callback:
            await progress_callback(90, "Fayl saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Video aylantishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# REVERSE - Teskari video
# ============================================================

async def reverse_video(input_path, reverse_audio=False, progress_callback=None):
    """Videoni teskari aylantirish"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("reverse"))
    try:
        if progress_callback:
            await progress_callback(20, "Video teskari aylantirilmoqda...")

        if reverse_audio:
            cmd = ["ffmpeg", "-y", "-i", input_path,
                   "-vf", "reverse", "-af", "areverse", output_path]
        else:
            cmd = ["ffmpeg", "-y", "-i", input_path,
                   "-vf", "reverse", "-an", output_path]

        if progress_callback:
            await progress_callback(60, "Teskari aylantirish...")

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd, timeout=600))

        if not success:
            clip = VideoFileClip(input_path)
            reversed_clip = clip.fx(lambda c: c.fl_time(lambda t: c.duration - t))
            reversed_clip.write_videofile(output_path, codec="libx264",
                                          verbose=False, logger=None)
            clip.close()

        if progress_callback:
            await progress_callback(90, "Fayl saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Video teskari aylantirishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# GIF - Videodan GIF yaratish
# ============================================================

async def video_to_gif(input_path, start_time=0, end_time=5, fps=10,
                       width=480, progress_callback=None):
    """Videodan GIF yaratish"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("gif", ".gif"))
    palette_path = os.path.join(TEMP_DIR, generate_unique_filename("palette", ".png"))
    try:
        if progress_callback:
            await progress_callback(20, "GIF yaratilmoqda...")

        duration = min(end_time - start_time, 10)

        cmd_palette = ["ffmpeg", "-y", "-ss", str(start_time), "-t", str(duration),
                       "-i", input_path,
                       "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen",
                       palette_path]
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: run_ffmpeg(cmd_palette))

        if progress_callback:
            await progress_callback(50, "GIF palitra tayyorlanmoqda...")

        cmd_gif = ["ffmpeg", "-y", "-ss", str(start_time), "-t", str(duration),
                   "-i", input_path, "-i", palette_path,
                   "-lavfi", f"fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse",
                   output_path]
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd_gif))

        if not success:
            cmd_simple = ["ffmpeg", "-y", "-ss", str(start_time), "-t", str(duration),
                          "-i", input_path, "-vf", f"fps={fps},scale={width}:-1", output_path]
            await loop.run_in_executor(None, lambda: run_ffmpeg(cmd_simple))

        await safe_delete_file(palette_path)

        if progress_callback:
            await progress_callback(90, "GIF saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"GIF yaratishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# STICKER - Videodan sticker yaratish
# ============================================================

async def video_to_sticker(input_path, progress_callback=None):
    """Videodan Telegram sticker yaratish (WebM)"""
    output_path = os.path.join(OUTPUTS_DIR, generate_unique_filename("sticker", ".webm"))
    try:
        if progress_callback:
            await progress_callback(20, "Sticker yaratilmoqda...")

        cmd = ["ffmpeg", "-y", "-i", input_path,
               "-vf", "scale=512:512:force_original_aspect_ratio=decrease,"
                      "pad=512:512:(ow-iw)/2:(oh-ih)/2:0x00000000,setsar=1",
               "-t", "3", "-c:v", "libvpx-vp9", "-b:v", "400k",
               "-an", "-pix_fmt", "yuva420p", output_path]

        if progress_callback:
            await progress_callback(60, "Sticker shakllantirilmoqda...")

        loop = asyncio.get_event_loop()
        success, error = await loop.run_in_executor(None, lambda: run_ffmpeg(cmd))

        if not success:
            return None

        if progress_callback:
            await progress_callback(90, "Sticker saqlanmoqda...")

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None
    except Exception as e:
        logger.error(f"Sticker yaratishda xatolik: {e}")
        await safe_delete_file(output_path)
        return None


# ============================================================
# VIDEO INFO - Video ma'lumoti
# ============================================================

async def get_video_info(input_path):
    """Video haqida batafsil ma'lumot olish"""
    try:
        import json
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", "-show_streams", input_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            cap = cv2.VideoCapture(input_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            info = {
                "duration": cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(1, fps),
                "fps": fps,
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "size": os.path.getsize(input_path),
                "has_audio": False,
                "bitrate": "N/A",
            }
            cap.release()
            return info

        data = json.loads(result.stdout)
        duration = 0
        width = height = fps = 0
        has_audio = False
        bitrate = "N/A"

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width", 0)
                height = stream.get("height", 0)
                fps_str = stream.get("r_frame_rate", "0/1")
                if "/" in fps_str:
                    num, den = fps_str.split("/")
                    fps = round(float(num) / float(den), 2) if float(den) != 0 else 0
                duration = float(stream.get("duration", 0))
            elif stream.get("codec_type") == "audio":
                has_audio = True

        fmt = data.get("format", {})
        if not duration:
            duration = float(fmt.get("duration", 0))
        if fmt.get("bit_rate"):
            bitrate = f"{int(fmt['bit_rate']) // 1000}k"

        return {
            "duration": duration, "fps": fps,
            "width": width, "height": height,
            "size": os.path.getsize(input_path),
            "has_audio": has_audio, "bitrate": bitrate,
        }
    except Exception as e:
        logger.error(f"Video ma'lumot olishda xatolik: {e}")
        return None


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================

def color_to_hex(color_name):
    """Rang nomini hex formatiga o'girish"""
    color_map = {
        "oq": "white", "qora": "black", "qizil": "red",
        "ko'k": "blue", "yashil": "green", "sariq": "yellow",
    }
    return color_map.get(color_name, "white")


def color_to_bgr(color_name):
    """Rang nomini BGR formatiga o'girish"""
    color_bgr_map = {
        "oq": (255, 255, 255), "qora": (0, 0, 0),
        "qizil": (0, 0, 255), "ko'k": (255, 0, 0),
        "yashil": (0, 255, 0), "sariq": (0, 255, 255),
    }
    return color_bgr_map.get(color_name, (255, 255, 255))


def calculate_text_position(position, width, height, text_size, margin=20):
    """Matn joylashuvini hisoblash"""
    tw, th = text_size
    positions = {
        "top-left": (margin, th + margin),
        "top-right": (width - tw - margin, th + margin),
        "bottom-left": (margin, height - margin),
        "bottom-right": (width - tw - margin, height - margin),
        "center": ((width - tw) // 2, (height + th) // 2),
    }
    return positions.get(position, positions["bottom-right"])
