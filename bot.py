import os
import glob
import time
import threading
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import apihelper, types
import yt_dlp

# 1. خادم مصغر لمنع Render من إيقاف الخدمة
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

# 2. التنبيه الذاتي كل 10 دقائق ليبقى البوت حياً 24 ساعة
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

# ذاكرة مؤقتة لحفظ روابط المستخدمين أثناء الاختيار
USER_URLS = {}

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "أهلاً بك يا بطل! 🚀\n\nأرسل لي أي رابط من (TikTok, Instagram, YouTube, X, Facebook) وستظهر لك خيارات التحميل فوراً (فيديو بجودات مختلفة أو صوت MP3)."
    )

@bot.message_handler(func=lambda message: True)
def handle_link_request(message):
    url = message.text.strip()

    if not url.startswith(("http://", "https://")):
        bot.reply_to(message, "⚠️ يرجى إرسال رابط صحيح يبدأ بـ http أو https")
        return

    wait_msg = bot.reply_to(message, "🔍 جاري فحص الرابط واستخراج خيارات التحميل...")

    try:
        # استخراج معلومات الفيديو بسرعة دون تحميل
        ydl_info_opts = {
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
        }
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'مقطع فيديو')
            duration = info.get('duration', 0)

        # حفظ الرابط في الذاكرة
        USER_URLS[message.chat.id] = {"url": url, "title": title, "duration": duration}

        # بناء الأزرار التفاعلية
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_720 = types.InlineKeyboardButton("🎬 فيديو عالي (720p)", callback_data="dl_720")
        btn_480 = types.InlineKeyboardButton("📱 فيديو سريع (480p)", callback_data="dl_480")
        btn_mp3 = types.InlineKeyboardButton("🎵 صوت فقط (MP3)", callback_data="dl_mp3")
        markup.add(btn_720, btn_480)
        markup.add(btn_mp3)

        duration_text = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "غير محدد"
        caption = f"📌 **{title[:120]}**\n⏱ المدة: {duration_text}\n\n👇 اختر صيغة التحميل المطلوبة:"

        bot.edit_message_text(caption, chat_id=message.chat.id, message_id=wait_msg.message_id, reply_markup=markup, parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ تعذر استخراج بيانات المقطع: {str(e)[:120]}", chat_id=message.chat.id, message_id=wait_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_"))
def handle_download_option(call):
    chat_id = call.message.chat.id
    if chat_id not in USER_URLS:
        bot.answer_callback_query(call.id, "⚠️ انتهت صلاحية هذا الطلب، أرسل الرابط مجدداً.", show_alert=True)
        return

    data = USER_URLS[chat_id]
    url = data["url"]
    title = data["title"]
    duration = data["duration"]
    choice = call.data

    bot.answer_callback_query(call.id, "⏳ جاري بدء التحميل والمعالجة...")
    status_msg = bot.send_message(chat_id, "⏳ جاري التنزيل بالسيرفر السحابي بأقصى سرعة...")

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
                'max_filesize': 50 * 1024 * 1024,
                'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
            }
        elif choice == "dl_720":
            ydl_opts = {
                'format': 'best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,
                'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
            }
        else: # dl_480
            ydl_opts = {
                'format': 'best[height<=480][ext=mp4]/bestvideo[height<=480]+bestaudio/best[height<=480]/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,
                'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # العثور على الملف الناتج
        matching = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_prefix}.*"))
        if not matching:
            raise FileNotFoundError("لم يتم العثور على الملف بعد التنزيل.")
        downloaded_file = matching[0]

        bot.edit_message_text("📤 تم التنزيل بنجاح! جاري الإرسال لتلجرام...", chat_id=chat_id, message_id=status_msg.message_id)

        # الإرسال بناءً على النوع
        if choice == "dl_mp3":
            with open(downloaded_file, 'rb') as audio:
                bot.send_audio(
                    chat_id,
                    audio,
                    title=title[:100],
                    duration=int(duration) if duration else None,
                    caption=f"🎵 {title[:150]}"
                )
        else:
            with open(downloaded_file, 'rb') as video:
                bot.send_video(
                    chat_id,
                    video,
                    caption=f"🎬 {title[:150]}",
                    duration=int(duration) if duration else None,
                    supports_streaming=True
                )

        bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ حدث خطأ أثناء التحميل: {str(e)[:120]}", chat_id=chat_id, message_id=status_msg.message_id)
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except OSError:
                pass

if __name__ == "__main__":
    print("البوت الاحترافي المتقدم يعمل الآن...")
    bot.infinity_polling()
