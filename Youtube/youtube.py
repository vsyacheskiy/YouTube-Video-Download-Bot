# LISA-KOREA | @LISA_FAN_LK | NT_BOT_CHANNEL | LISA-KOREA/YouTube-Video-Download-Bot
#
# [Do not change this repo link] :- https://github.com/LISA-KOREA/YouTube-Video-Download-Bot

import os
import glob
import yt_dlp
import logging
import uuid
import aiohttp
import aiofiles
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from Youtube.config import Config
from Youtube.fix_thumb import fix_thumb
from Youtube.forcesub import handle_force_subscribe, humanbytes


# Cache keeps url and picked formats per message
YT_CACHE = {}


def human_megabits(size: int) -> str:
    """Render bytes as megabits (Mb) with one decimal."""
    if not size:
        return "Unknown"
    return f"{(size * 8) / 1_000_000:.1f} Mb"


def human_rate(size_per_sec: int) -> str:
    if not size_per_sec:
        return ""
    return f"{(size_per_sec * 8) / 1_000_000:.2f} Mb/s"


@Client.on_message(filters.regex(r"^(http(s)?://)?(www\.)?(youtube\.com|youtu\.be)/.+"))
async def youtube_downloader(client, message):
    if Config.CHANNEL:
        fsub = await handle_force_subscribe(client, message)
        if fsub == 400:
            return

    url = message.text.strip()
    processing_msg = await message.reply_text("🔍 **Fetching available formats...**")

    ydl_opts = {"quiet": True}
    if os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 0:
        ydl_opts["cookiefile"] = "cookies.txt"
    buttons = []

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])
            duration = info.get("duration")
            title = info.get("title", "YouTube Video")

            vid_key = str(uuid.uuid4())[:8]
            YT_CACHE[vid_key] = {"url": url, "formats": {}, "audio": None}

            target_heights = [480, 720, 1080]
            best_by_height = {}
            best_audio = None

            for f in formats:
                fmt_id = f.get("format_id")
                note = f.get("format_note") or f.get("format") or ""
                note_lower = str(note).lower()
                ext = f.get("ext") or ""
                vcodec = (f.get("vcodec") or "").lower()
                acodec = (f.get("acodec") or "").lower()
                is_storyboard = ext == "mhtml" or "storyboard" in note_lower or vcodec == "images"
                if not f.get("url"):
                    continue
                size = f.get("filesize") or f.get("filesize_approx")
                height = f.get("height")

                if not fmt_id or "audio" in note_lower or is_storyboard:
                    continue

                if vcodec in ("none", ""):
                    # pure audio candidate
                    if best_audio is None:
                        best_audio = f
                    else:
                        existing_size = best_audio.get("filesize") or best_audio.get("filesize_approx") or 0
                        current_size = size or 0
                        if current_size > existing_size:
                            best_audio = f
                    continue

                if height in target_heights:
                    existing = best_by_height.get(height)
                    if existing:
                        existing_size = existing.get("filesize") or existing.get("filesize_approx") or 0
                        current_size = size or 0
                        if current_size <= existing_size:
                            continue
                    best_by_height[height] = f

            for height in target_heights:
                f = best_by_height.get(height)
                if not f:
                    continue
                fmt_id = f.get("format_id")
                ext = f.get("ext") or ""
                size = f.get("filesize") or f.get("filesize_approx")
                size_text = human_megabits(size)
                text = f"🎬 {height}p - {size_text}"
                cb = f"ytdl|{vid_key}|{fmt_id}|{ext}|video"

                YT_CACHE[vid_key]["formats"][fmt_id] = {
                    "ext": ext,
                    "size": size,
                    "height": height,
                }

                if len(cb.encode()) <= 64:
                    buttons.append([InlineKeyboardButton(text, callback_data=cb)])

            if best_audio:
                audio_fmt_id = best_audio.get("format_id")
                audio_ext = best_audio.get("ext") or "mp3"
                audio_size = best_audio.get("filesize") or best_audio.get("filesize_approx")
                YT_CACHE[vid_key]["audio"] = {"fmt_id": audio_fmt_id, "ext": audio_ext, "size": audio_size}

            if duration and best_audio:
                audio_size_text = human_megabits(audio_size)
                buttons.append(
                    [InlineKeyboardButton(f"🎧 Audio - {audio_size_text}", callback_data=f"ytdl|{vid_key}|{audio_fmt_id}|{audio_ext}|audio")]
                )

            await message.reply_text(
                f"**✅ Available formats for:**\n`{title}`",
                reply_markup=InlineKeyboardMarkup(buttons),
            )

            await processing_msg.delete()

    except Exception as e:
        logging.exception("Error fetching formats:")
        await processing_msg.edit_text(f"⚠️ Error: `{e}`")


@Client.on_callback_query(filters.regex(r"^ytdl\|"))
async def handle_download(client, cq):
    try:
        _, vid_key, fmt_id, ext, mode = cq.data.split("|")
        cache_entry = YT_CACHE.get(vid_key)
        if not cache_entry:
            await cq.message.edit_text("⌛ Session expired. Please resend link.")
            return
        url = cache_entry.get("url")

        await cq.message.edit_text("⏬ **Downloading...**")

        os.makedirs("downloads", exist_ok=True)
        output = f"downloads/{vid_key}.%(ext)s"

        last_progress = {"p": -1}
        spinner = ["⏬", "⬇️", "📥", "📡"]

        def progress_hook(d):
            try:
                status = d.get("status")
                if status == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    downloaded = d.get("downloaded_bytes") or 0
                    percent = (downloaded * 100 / total) if total else 0
                    if percent - last_progress["p"] >= 3:
                        last_progress["p"] = percent
                        speed = human_rate(d.get("speed"))
                        frame = spinner[int(percent / 5) % len(spinner)]
                        tail = f" {speed}" if speed else ""
                        client.loop.create_task(
                            cq.message.edit_text(f"{frame} Downloading... {percent:.1f}%{tail}")
                        )
                elif status == "finished":
                    client.loop.create_task(cq.message.edit_text("🔄 Merging..."))
            except Exception:
                pass

        if mode == "audio":
            audio_entry = cache_entry.get("audio") or {}
            fmt_id = audio_entry.get("fmt_id") or fmt_id or "bestaudio/best"
            ydl_opts = {
                "format": fmt_id,
                "outtmpl": output,
                "quiet": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                "progress_hooks": [progress_hook],
            }
            if os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 0:
                ydl_opts["cookiefile"] = "cookies.txt"
        else:
            fmt_entry = cache_entry["formats"].get(fmt_id) or {}
            ext = fmt_entry.get("ext") or ext
            ydl_opts = {
                "format": f"({fmt_id}+bestaudio/best)/{fmt_id}",
                "outtmpl": output,
                "quiet": True,
                "merge_output_format": "mp4",
                "progress_hooks": [progress_hook],
            }
            if os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 0:
                ydl_opts["cookiefile"] = "cookies.txt"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.ExtractorError as e:
            if "Requested format is not available" in str(e):
                # Fallback to best mp4 + best audio when the chosen format disappears
                fallback_opts = ydl_opts.copy()
                fallback_opts["format"] = "bv*[ext=mp4]+ba/best/best"
                print(f"fallback ydl_opts: {fallback_opts}")
                with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
            else:
                raise

        title = info.get("title", "YouTube Video")
        duration = info.get("duration", 0)
        width = info.get("width")
        height = info.get("height")
        thumb_url = info.get("thumbnail")
        if not thumb_url:
            thumbs = info.get("thumbnails") or []
            if thumbs:
                thumb_url = sorted(thumbs, key=lambda t: (t.get("height") or 0, t.get("width") or 0))[-1].get("url")
        filesize = info.get("filesize") or info.get("filesize_approx")
        file_size_text = human_megabits(filesize)

        if mode == "audio":
            expected_ext = "mp3"
            file_path = f"downloads/{vid_key}.{expected_ext}"
        else:
            final_ext = info.get("ext") or ext or "mp4"
            file_path = f"downloads/{vid_key}.{final_ext}"

        if not os.path.exists(file_path):
            # Try to locate the downloaded file if ext changed after postprocessing/merge
            candidates = sorted(
                [p for p in glob.glob(f"downloads/{vid_key}.*") if os.path.isfile(p)],
                key=os.path.getmtime,
                reverse=True,
            )
            if candidates:
                file_path = candidates[0]

        thumb_path = None
        if thumb_url:
            async with aiohttp.ClientSession() as s:
                async with s.get(thumb_url) as r:
                    if r.status == 200:
                        thumb_path = f"{vid_key}.jpg"
                        async with aiofiles.open(thumb_path, "wb") as f:
                            await f.write(await r.read())

        width, height, thumb_path = await fix_thumb(thumb_path)

        await cq.message.edit_text("⏫ **Uploading...**")

        if mode == "audio":
            await client.send_audio(
                chat_id=cq.message.chat.id,
                audio=file_path,
                caption=f"🎵 **{title}**\n📦 Size: `{file_size_text}`",
                duration=duration,
                thumb=thumb_path if thumb_path and os.path.exists(thumb_path) else None,
            )
        else:
            await client.send_video(
                chat_id=cq.message.chat.id,
                video=file_path,
                caption=f"🎬 **{title}**\n📦 Size: `{file_size_text}`",
                width=width,
                height=height,
                duration=duration,
                thumb=thumb_path if thumb_path and os.path.exists(thumb_path) else None,
                supports_streaming=True,
            )

        await cq.message.edit_text("✅ **Successfully Uploaded!**")

        if os.path.exists(file_path):
            os.remove(file_path)
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)

    except Exception as e:
        logging.exception("Download error:")
        await cq.message.edit_text(f"⚠️ Error: `{e}`")
