#!/usr/bin/env python3
"""
🇲🇲 Burmese Video Dubber - Telegram Bot
=========================================

Setup:
    1. Get Bot Token from @BotFather on Telegram
    2. Get Gemini API Key from aistudio.google.com/app/apikey
    3. Set env vars: TELEGRAM_BOT_TOKEN, GEMINI_API_KEY
    4. pip install python-telegram-bot youtube-transcript-api google-generativeai edge-tts yt-dlp ffmpeg-python
    5. python telegram_bot.py
"""

import os
import sys
import json
import time
import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ─── Logging ───
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Config ───
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OUTPUT_DIR = Path("./bot_output")
OUTPUT_DIR.mkdir(exist_ok=True)

VOICES = {
    "male": "my-MM-ThihaNeural",
    "female": "my-MM-NilarNeural",
}


def extract_video_id(url: str) -> str:
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    raise ValueError("Invalid YouTube URL")


async def send_progress(context, chat_id, text):
    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=text)
        return msg.message_id
    except Exception as e:
        logger.error(f"Failed to send progress: {e}")
        return None


async def edit_progress(context, chat_id, message_id, text):
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text
        )
    except Exception as e:
        logger.error(f"Failed to edit progress: {e}")


# ═══════════════════════════════════════════════════
# COMMAND HANDLERS
# ═══════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "🎬 *Welcome to Burmese Video Dubber!*\n\n"
        "I can turn any YouTube movie recap into a Burmese dubbed video.\n\n"
        "*How to use:*\n"
        "1️⃣ Send me a YouTube video URL\n"
        "2️⃣ Choose Male or Female voice\n"
        "3️⃣ Wait while I process it\n"
        "4️⃣ Download your dubbed video!\n\n"
        "*Commands:*\n"
        "• /start - This message\n"
        "• /help - Detailed help\n"
        "• /voice - Change default voice\n\n"
        "💰 *Totally Free*"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 *How to Use*\n\n"
        "*Step 1:* Send a YouTube URL\n"
        "   Example: `https://youtube.com/watch?v=abc123`\n\n"
        "*Step 2:* Choose voice\n   🇲🇲 Thiha (Male) or 🇲🇲 Nilar (Female)\n\n"
        "*Step 3:* Wait for processing\n   Usually 2-10 minutes\n\n"
        "⚠️ *Limitations:*\n"
        "   • Video must have captions\n"
        "   • Max ~15 minutes\n"
        "   • Telegram file limit: 50MB"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🇲🇲 Thiha (Male)", callback_data="voice_male")],
        [InlineKeyboardButton("🇲🇲 Nilar (Female)", callback_data="voice_female")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🎙️ Choose your default Burmese voice:", reply_markup=reply_markup
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id

    if data.startswith("voice_"):
        voice_choice = data.replace("voice_", "")
        context.chat_data["voice"] = VOICES[voice_choice]
        await query.edit_message_text(
            f"✅ Default voice set to: *{voice_choice.title()}* (🇲🇲)",
            parse_mode="Markdown",
        )

    elif data.startswith("dub_"):
        video_id = data.replace("dub_", "")
        youtube_url = context.chat_data.get(f"url_{video_id}")
        voice = context.chat_data.get("voice", VOICES["male"])

        if not youtube_url:
            await query.edit_message_text("❌ Error: URL not found.")
            return

        await query.edit_message_text("🚀 Starting dubbing process...")
        await process_video(update, context, youtube_url, voice, chat_id)


# ═══════════════════════════════════════════════════
# MAIN PROCESSING PIPELINE
# ═══════════════════════════════════════════════════

async def process_video(update, context, youtube_url: str, voice: str, chat_id: int):
    try:
        video_id = extract_video_id(youtube_url)
    except ValueError:
        await context.bot.send_message(chat_id=chat_id, text="❌ Invalid YouTube URL!")
        return

    output_dir = OUTPUT_DIR / video_id
    output_dir.mkdir(exist_ok=True)

    progress_msg = await send_progress(context, chat_id, "⏳ Starting...")
    start_time = time.time()

    try:
        # ── STEP 1: Extract Transcript ──
        await edit_progress(context, chat_id, progress_msg, "📋 Step 1/5: Extracting transcript...")
        from youtube_transcript_api import YouTubeTranscriptApi

        # ✅ FIX: youtube-transcript-api v1.2.4+ API
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id)

        transcript_list = []
        for snippet in fetched:
            transcript_list.append({
                "text": snippet.text,
                "start": snippet.start,
                "duration": snippet.duration
            })

        full_text = " ".join([seg["text"] for seg in transcript_list])

        # Truncate if too long
        total_duration = transcript_list[-1]["start"] + transcript_list[-1].get("duration", 0)
        if total_duration > 15 * 60:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Video is {total_duration/60:.0f} min. Truncating to 15 min."
            )
            cutoff = 15 * 60
            transcript_list = [seg for seg in transcript_list if seg["start"] < cutoff]
            full_text = " ".join([seg["text"] for seg in transcript_list])

        # Save transcript
        transcript_path = output_dir / f"{video_id}_transcript.json"
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(transcript_list, f, ensure_ascii=False, indent=2)

        await edit_progress(
            context, chat_id, progress_msg,
            f"✅ Step 1/5: Transcript extracted ({len(transcript_list)} segments, {len(full_text)} chars)"
        )

        # ── STEP 2: Translate ──
        await edit_progress(context, chat_id, progress_msg, "🌐 Step 2/5: Translating to Burmese...")
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash-lite")

        words = full_text.split()
        chunks = []
        current_chunk = []
        current_len = 0
        chunk_size = 3000

        for word in words:
            current_chunk.append(word)
            current_len += len(word) + 1
            if current_len >= chunk_size:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_len = 0
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        translated_parts = []
        for i, chunk in enumerate(chunks):
            prompt = f"""Translate the following English text into natural, fluent Burmese (Myanmar language).
Keep the meaning accurate but make it sound natural when spoken aloud.
Do not add explanations, only return the translated text.

Text to translate:
{chunk}"""
            try:
                response = model.generate_content(prompt)
                translated_parts.append(response.text.strip())
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Chunk {i+1} failed: {e}")
                translated_parts.append(chunk)

        burmese_text = " ".join(translated_parts)

        burmese_path = output_dir / f"{video_id}_burmese.txt"
        with open(burmese_path, "w", encoding="utf-8") as f:
            f.write(burmese_text)

        await edit_progress(
            context, chat_id, progress_msg,
            f"✅ Step 2/5: Translated to Burmese ({len(burmese_text)} chars)"
        )

        # ── STEP 3: TTS ──
        await edit_progress(context, chat_id, progress_msg, "🔊 Step 3/5: Generating voice-over...")
        import edge_tts

        audio_path = str(output_dir / f"{video_id}_burmese_audio.mp3")

        communicate = edge_tts.Communicate(burmese_text, voice)
        await communicate.save(audio_path)

        await edit_progress(context, chat_id, progress_msg, "✅ Step 3/5: Voice-over generated!")

        # ── STEP 4: Download Video ──
        await edit_progress(context, chat_id, progress_msg, "📹 Step 4/5: Downloading video...")
        import yt_dlp

        ydl_opts = {
            "format": "bestvideo[ext=mp4][duration<960]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
            "merge_output_format": "mp4",
            "quiet": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            video_path = output_dir / f"{info.get('id', video_id)}.mp4"
            video_title = info.get("title", "Unknown")

        await edit_progress(
            context, chat_id, progress_msg,
            f"✅ Step 4/5: Video downloaded ({video_title})"
        )

        # ── STEP 5: Merge ──
        await edit_progress(context, chat_id, progress_msg, "🎬 Step 5/5: Merging video + audio...")
        import ffmpeg

        final_output = str(output_dir / f"{video_id}_burmese_dubbed.mp4")

        (
            ffmpeg
            .input(str(video_path))
            .input(audio_path)
            .output(
                final_output,
                vcodec="copy",
                acodec="aac",
                shortest=None,
                map=["0:v:0", "1:a:0"]
            )
            .overwrite_output()
            .run(quiet=True)
        )

        elapsed = time.time() - start_time
        await edit_progress(
            context, chat_id, progress_msg,
            f"🎉 Done in {elapsed/60:.1f} minutes! Sending files..."
        )

        # ── Send Results ──
        video_size = os.path.getsize(final_output)

        preview = burmese_text[:400] + "..." if len(burmese_text) > 400 else burmese_text
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🇲🇲 *Burmese Preview:*\n`{preview}`",
            parse_mode="Markdown",
        )

        await context.bot.send_audio(
            chat_id=chat_id,
            audio=open(audio_path, "rb"),
            title=f"{video_title} - Burmese Dub",
            performer="Burmese Dubber",
        )

        if video_size < 50 * 1024 * 1024:
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(final_output, "rb"),
                caption=f"🎬 *{video_title}* — Burmese Dubbed\n⏱️ {elapsed/60:.1f} min",
                parse_mode="Markdown",
                supports_streaming=True,
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Video is {video_size/1024/1024:.1f}MB (over 50MB limit).\n📁 Saved at: `{final_output}`",
                parse_mode="Markdown",
            )

        await context.bot.send_document(
            chat_id=chat_id,
            document=open(burmese_path, "rb"),
            caption="🇲🇲 Burmese text (full)",
        )

        await context.bot.send_document(
            chat_id=chat_id,
            document=open(transcript_path, "rb"),
            caption="📝 Original transcript (JSON)",
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ *All done!*\n\n🎬 {video_title}\n⏱️ {elapsed/60:.1f} min\n📝 {len(transcript_list)} segments\n🇲🇲 {len(burmese_text)} chars\n\nSend another URL!",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.exception("Processing failed")
        await edit_progress(context, chat_id, progress_msg, f"❌ Error: {str(e)}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ *Failed:*\n`{str(e)}`\n\n💡 Tips:\n• Video must have captions\n• Check Gemini API key\n• Try shorter video",
            parse_mode="Markdown",
        )


# ═══════════════════════════════════════════════════
# MESSAGE HANDLER
# ═══════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id

    if "youtube.com" in text or "youtu.be" in text:
        try:
            video_id = extract_video_id(text)
        except ValueError:
            await update.message.reply_text("❌ Invalid YouTube URL.")
            return

        context.chat_data[f"url_{video_id}"] = text

        keyboard = [
            [InlineKeyboardButton("🚀 Start Dubbing", callback_data=f"dub_{video_id}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"📺 *YouTube Video Detected!*\n\nURL: `{text}`\n\nClick below to start.",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
    else:
        await update.message.reply_text(
            "🤔 Send me a YouTube URL!\nExample: `https://youtube.com/watch?v=abc123`",
            parse_mode="Markdown",
        )


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set!")
        print("   1. Message @BotFather on Telegram")
        print("   2. Create a new bot and get the token")
        print("   3. Set: export TELEGRAM_BOT_TOKEN='your-token'")
        sys.exit(1)

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY not set!")
        print("   Get free at: https://aistudio.google.com/app/apikey")
        sys.exit(1)

    print("🤖 Starting Burmese Video Dubber Bot...")
    print(f"   Output dir: {OUTPUT_DIR.absolute()}")

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("voice", voice_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
