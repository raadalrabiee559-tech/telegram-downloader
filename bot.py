import os
import glob
import time
import math
import subprocess
import threading
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import apihelper, types
import yt_dlp

# 1. خادم مصغر لمنع Render من الخمول
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is online and running!")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# 2. التنبيه الذاتي كل 10 دقائق لضمان عمل البوت 24 ساعة
def keep_alive_ping():
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen("https://telegram-downloader-0owh.onrender.com", timeout=15)
        except Exception:
            pass

threading.Thread(target=keep_alive_ping, daemon=True).start()

# 3. التحديث التلقائي لـ yt-dlp كل 24 ساعة
def auto_update_ytdlp():
    while True:
        time.sleep(86400) # كل 24 ساعة
        try:
            subprocess.run(["pip", "install", "--upgrade", "yt-dlp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

threading.Thread(target=auto_update_ytdlp, daemon=True).start()

# 4. إعدادات تلجرام
apihelper.CONNECT_TIMEOUT = 30
apihelper.READ_TIMEOUT = 300

BOT_TOKEN = "9265561235:AAFyaR6rCz1xnZYHxTOP7eI5gOuDO5IVz9k"
bot = telebot.TeleBot(BOT_TOKEN)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

USER_DATA = {}
MAX_CHUNK_BYTES = 47 * 1024 * 1024  # حد أقصى 47 ميغابايت لكل جزء لتجنب حظر تلجرام

# قراءة الكوكيز تلقائياً إذا كانت موجودة
COOKIE_PATH = "cookies.txt" if os.path.exists("cookies.txt") else None

def get_base_ydl_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 15, # قطع الاتصال بعد 15 ثانية إذا لم يستجب الموقع
        'retries': 2,
        'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
    }
    if COOKIE_PATH:
        opts['cookiefile'] = COOKIE_PATH
    return opts

def format_count(count):
    if not count:
        return "غير متوفر"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)

def fast_split_and_send(chat_id, file_path, title, total_duration, status_msg_id):
    """تقطيع سريع جداً بتقنية القص المباشر وإرسالها متتالية"""
    file_size = os.path.getsize(file_path)

    # إذا كان الحجم طبيعياً
    if file_size <= 48 * 1024 * 1024:
        bot.edit_message_text("⚡ جاري الرفع لتلجرام...", chat_id=chat_id, message_id=status_msg_id)
        with open(file_path, 'rb') as v:
            bot.send_video(
                chat_id, v, 
                caption=f"🎬 **{title[:140]}**\n\n🤖 @raad_downloader_bot", 
                duration=int(total_duration) if total_duration else None, 
                supports_streaming=True,
                parse_mode="Markdown"
            )
        bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
        return

    # حساب عدد الأجزاء
    num_parts = math.ceil(file_size / MAX_CHUNK_BYTES)
    chunk_duration = math.ceil(total_duration / num_parts) if total_duration else 180

    bot.edit_message_text(f"✂️ حجم الفيديو ({file_size / (1024*1024):.1f}MB) يتجاوز حد تلجرام.\n⚡ جاري التقطيع الفوري إلى {num_parts} أجزاء ورفعها...", chat_id=chat_id, message_id=status_msg_id)

    part_files = []
    try:
        for i in range(num_parts):
            start_sec = i * chunk_duration
            part_path = os.path.join(DOWNLOAD_DIR, f"part_{i+1}_{os.path.basename(file_path)}")
            part_files.append(part_path)

            # أمر التقطيع فائق السرعة
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_sec),
                "-i", file_path,
                "-t", str(chunk_duration),
                "-c", "copy",
                "-avoid_negative_ts", "1",
                part_path
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.exists(part_path) and os.path.getsize(part_path) > 0:
                with open(part_path, 'rb') as part_v:
                    bot.send_video(
                        chat_id, 
                        part_v, 
                        caption=f"🎬 **{title[:100]}**\n📦 **الجزء ({i+1}/{num_parts})**\n\n🤖 @raad_downloader_bot",
                        duration=int(chunk_duration),
                        supports_streaming=True,
                        parse_mode="Markdown"
                    )

        bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
    finally:
        for p in part_files:
            if os.path.exists(p):
                try: os.remove(p)
                except OSError: pass

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "🌟 **أهلاً بك في محمل الوسائط السحابي فائق السرعة!** 🚀\n\n"
        "أرسل لي أي رابط وسأقوم بتحليله فوراً:\n"
        "• YouTube • TikTok • Instagram • Facebook • X\n\n"
        "⚡ **تحديثات النظام:**\n"
        "├ تقطيع فوري فائق السرعة للمقاطع الضخمة\n"
        "├ كشف فوري لأي أخطاء في الروابط\n"
        "└ تحديث يومي تلقائي لمكتبات التنزيل\n\n"
        "👇 **أرسل الرابط الآن لتجربته!**"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['update'])
def manual_update(message):
    status_msg = bot.reply_to(message, "⏳ جاري فحص وتحديث مكتبة التحميل لأحدث إصدار...")
    try:
        res = subprocess.run(["pip", "install", "--upgrade", "yt-dlp"], capture_output=True, text=True)
        bot.edit_message_text("✅ **تم تحديث محرك التحميل بنجاح لأحدث إصدار!**", chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ فشل التحديث: {str(e)}", chat_id=message.chat.id, message_id=status_msg.message_id)

@bot.message_handler(func=lambda message: True)
def handle_link_request(message):
    url = message.text.strip()

    if not url.startswith(("http://", "https://")):
        bot.reply_to(message, "⚠️ يرجى إرسال رابط صحيح يبدأ بـ http أو https")
        return

    wait_msg = bot.reply_to(message, "🔍 جاري فحص الرابط وجلب بيانات المقطع...")

    try:
        ydl_info_opts = get_base_ydl_opts()
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError("تعذر العثور على أي فيديو متاح في هذا الرابط.")
            
            title = info.get('title', 'مقطع فيديو')
            duration = info.get('duration', 0)
            uploader = info.get('uploader') or info.get('channel') or "غير معروف"
            views = info.get('view_count', 0)
            thumb = info.get('thumbnail')

        USER_DATA[message.chat.id] = {
            "url": url, 
            "title": title, 
            "duration": duration,
            "uploader": uploader
        }

        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_1080 = types.InlineKeyboardButton("💎 Full HD 1080p", callback_data="dl_1080")
        btn_720 = types.InlineKeyboardButton("⚡ 720p (موصى به)", callback_data="dl_720")
        btn_480 = types.InlineKeyboardButton("📱 480p (موفر باقة)", callback_data="dl_480")
        btn_mp3 = types.InlineKeyboardButton("🎧 صوت نقي MP3", callback_data="dl_mp3")
        btn_close = types.InlineKeyboardButton("❌ إغلاق", callback_data="dl_close")

        markup.add(btn_1080)
        markup.add(btn_720, btn_480)
        markup.add(btn_mp3)
        markup.add(btn_close)

        dur_text = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "غير محدد"
        caption = (
            f"🎬 **{title[:120]}**\n\n"
            f"👤 **الناشر:** {uploader}\n"
            f"⏱ **المدة:** {dur_text} دقيقة\n"
            f"👁 **المشاهدات:** {format_count(views)}\n\n"
            f"👇 **اختر الصيغة والجودة المطلوبة:**"
        )

        bot.delete_message(chat_id=message.chat.id, message_id=wait_msg.message_id)

        if thumb:
            bot.send_photo(message.chat.id, thumb, caption=caption, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")

    except yt_dlp.utils.DownloadError as de:
        err_text = str(de)
        if "Unsupported URL" in err_text:
            msg = "❌ هذا الرابط من موقع غير مدعوم أو غير صالح."
        elif "Private video" in err_text or "login" in err_text.lower():
            msg = "🔒 هذا المقطع خاص (Private) ولا يمكن تنزيله إلا بتسجيل الدخول."
        elif "Sign in to confirm" in err_text:
            msg = "⚠️ يوتيوب يطلب تأكيد حساب للوصول لهذا المقطع على السيرفر."
        else:
            msg = f"❌ تعذر تنزيل المقطع: {err_text[:120]}"
        bot.edit_message_text(msg, chat_id=message.chat.id, message_id=wait_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"⚠️ حدث خطأ في معالجة الرابط: {str(e)[:120]}", chat_id=message.chat.id, message_id=wait_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_"))
def handle_download_option(call):
    chat_id = call.message.chat.id
    choice = call.data

    if choice == "dl_close":
        bot.delete_message(chat_id, call.message.message_id)
        return

    if chat_id not in USER_DATA:
        bot.answer_callback_query(call.id, "⚠️ انتهت صلاحية الطلب، أرسل الرابط مجدداً.", show_alert=True)
        return

    data = USER_DATA[chat_id]
    url = data["url"]
    title = data["title"]
    duration = data["duration"]
    uploader = data["uploader"]

    bot.answer_callback_query(call.id, "🚀 بدأ التنزيل السحابي الفوري...")
    status_msg = bot.send_message(chat_id, "⚡ **جاري السحب والمعالجة عبر الخادم السحابي...**", parse_mode="Markdown")

    file_prefix = f"{chat_id}_{int(time.time())}"
    downloaded_file = None

    try:
        ydl_opts = get_base_ydl_opts()

        if choice == "dl_mp3":
            ydl_opts.update({
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        elif choice == "dl_1080":
            ydl_opts.update({
                'format': 'bestvideo+bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'merge_output_format': 'mp4',
            })
        elif choice == "dl_720":
            ydl_opts.update({
                'format': 'best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'merge_output_format': 'mp4',
            })
        else: # dl_480
            ydl_opts.update({
                'format': 'best[height<=480][ext=mp4]/bestvideo[height<=480]+bestaudio/best[height<=480]/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'merge_output_format': 'mp4',
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        matching = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*"))
        if not matching:
            raise FileNotFoundError("لم يتم العثور على الملف بعد التنزيل.")
        downloaded_file = matching[0]

        if choice == "dl_mp3":
            bot.edit_message_text("🎧 جاري رفع الملف الصوتي...", chat_id=chat_id, message_id=status_msg.message_id)
            with open(downloaded_file, 'rb') as audio:
                bot.send_audio(
                    chat_id, audio, 
                    title=title[:100], 
                    performer=uploader[:50],
                    duration=int(duration) if duration else None, 
                    caption=f"🎵 **{title[:140]}**\n\n🤖 @raad_downloader_bot",
                    parse_mode="Markdown"
                )
            bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
        else:
            fast_split_and_send(chat_id, downloaded_file, title, duration, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ حدث خطأ أثناء المعالجة: {str(e)[:120]}", chat_id=chat_id, message_id=status_msg.message_id)
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try: os.remove(downloaded_file)
            except OSError: pass

if __name__ == "__main__":
    print("البوت السريع والمحدث يعمل الآن...")
    bot.infinity_polling()
