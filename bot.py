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

# 1. خادم مصغر لمنع Render من الدخول في وضع الخمول
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

# 3. إعدادات تلجرام
apihelper.CONNECT_TIMEOUT = 120
apihelper.READ_TIMEOUT = 600

BOT_TOKEN = "9265561235:AAFyaR6rCz1xnZYHxTOP7eI5gOuDO5IVz9k"
bot = telebot.TeleBot(BOT_TOKEN)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

USER_DATA = {}
MAX_CHUNK_BYTES = 45 * 1024 * 1024  # 45 ميغابايت لكل جزء عند التقطيع

def format_count(count):
    """تنسيق أرقام المشاهدات بشكل احترافي"""
    if not count:
        return "غير متوفر"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)

def split_and_send_video(chat_id, file_path, title, total_duration, status_msg_id):
    """تقطيع الفيديو تلقائياً باستخدام FFmpeg إذا تجاوز 48MB بدون فقدان الجودة"""
    file_size = os.path.getsize(file_path)

    if file_size <= 48 * 1024 * 1024:
        bot.edit_message_text("⚡ جاري الرفع لتلجرام بأقصى سرعة...", chat_id=chat_id, message_id=status_msg_id)
        with open(file_path, 'rb') as v:
            bot.send_video(
                chat_id, v, 
                caption=f"🎬 **{title[:140]}**\n\n🤖 بواسطة: @raad_downloader_bot", 
                duration=int(total_duration) if total_duration else None, 
                supports_streaming=True,
                parse_mode="Markdown"
            )
        bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
        return

    num_parts = math.ceil(file_size / MAX_CHUNK_BYTES)
    chunk_duration = math.ceil(total_duration / num_parts) if total_duration else 300

    bot.edit_message_text(f"✂️ حجم المقطع كبير ({file_size / (1024*1024):.1f}MB)\nجاري تقطيعه إلى {num_parts} أجزاء ورفعها...", chat_id=chat_id, message_id=status_msg_id)

    part_files = []
    try:
        for i in range(num_parts):
            start_sec = i * chunk_duration
            part_path = os.path.join(DOWNLOAD_DIR, f"part_{i+1}_{os.path.basename(file_path)}")
            part_files.append(part_path)

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_sec),
                "-i", file_path,
                "-t", str(chunk_duration),
                "-c", "copy",
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
        "🌟 **مرحباً بك في أسرع محمل وسائط سحابي!** 🚀\n\n"
        "أرسل لي أي رابط من المنصات المدعومة:\n"
        "• YouTube • TikTok • Instagram • Facebook • X (Twitter)\n\n"
        "✨ **المميزات:**\n"
        "├ جودات متعددة تصل إلى Full HD 1080p\n"
        "├ استخراج الصوت بجودة صوتية نقية MP3\n"
        "└ تقطيع تلقائي للمقاطع الضخمة لتناسب تلجرام\n\n"
        "👇 **أرسل الرابط الآن للبدء!**"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_link_request(message):
    url = message.text.strip()

    if not url.startswith(("http://", "https://")):
        bot.reply_to(message, "⚠️ يرجى إرسال رابط صحيح يبدأ بـ http أو https")
        return

    wait_msg = bot.reply_to(message, "🔍 جاري فحص الرابط وجلب بيانات المقطع...")

    try:
        ydl_info_opts = {
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
        }
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
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

        # بناء الأزرار بتصميم أيقونات حديث
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
            f"👇 **اختر الصيغة والجودة المطلوبة للتحميل:**"
        )

        bot.delete_message(chat_id=message.chat.id, message_id=wait_msg.message_id)

        # إرسال الغلاف مع البطاقة التفاعلية إن توفر، وإلا إرسال رسالة نصية
        if thumb:
            bot.send_photo(message.chat.id, thumb, caption=caption, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ تعذر تحليل الرابط، تأكد من أن الحساب عام: {str(e)[:120]}", chat_id=message.chat.id, message_id=wait_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_"))
def handle_download_option(call):
    chat_id = call.message.chat.id
    choice = call.data

    if choice == "dl_close":
        bot.delete_message(chat_id, call.message.message_id)
        return

    if chat_id not in USER_DATA:
        bot.answer_callback_query(call.id, "⚠️ انتهت صلاحية هذا الطلب، أرسل الرابط مجدداً.", show_alert=True)
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
        if choice == "dl_mp3":
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
            }
        elif choice == "dl_1080":
            ydl_opts = {
                'format': 'bestvideo+bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
            }
        elif choice == "dl_720":
            ydl_opts = {
                'format': 'best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
            }
        else: # dl_480
            ydl_opts = {
                'format': 'best[height<=480][ext=mp4]/bestvideo[height<=480]+bestaudio/best[height<=480]/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        matching = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*"))
        if not matching:
            raise FileNotFoundError("لم يتم العثور على الملف بعد التنزيل.")
        downloaded_file = matching[0]

        if choice == "dl_mp3":
            bot.edit_message_text("🎧 جاري رفع الملف الصوتي النقي...", chat_id=chat_id, message_id=status_msg.message_id)
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
            split_and_send_video(chat_id, downloaded_file, title, duration, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ حدث خطأ أثناء المعالجة: {str(e)[:120]}", chat_id=chat_id, message_id=status_msg.message_id)
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try: os.remove(downloaded_file)
            except OSError: pass

if __name__ == "__main__":
    print("البوت السينمائي الأنيق يعمل الآن...")
    bot.infinity_polling()
