import os
import glob
import time
import threading
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import apihelper
import yt_dlp

# خادم مصغر ليتعرف Render على أن الخدمة تعمل بنجاح
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

# دالة التنبيه الذاتي كل 10 دقائق ليبقى السيرفر شغالاً 24 ساعة
def keep_alive_ping():
    while True:
        time.sleep(600)  # كل 10 دقائق
        try:
            urllib.request.urlopen("https://telegram-downloader-0owh.onrender.com", timeout=15)
        except Exception:
            pass

threading.Thread(target=keep_alive_ping, daemon=True).start()

# إعدادات البوت
apihelper.CONNECT_TIMEOUT = 120
apihelper.READ_TIMEOUT = 600

BOT_TOKEN = "9265561235:AAFyaR6rCz1xnZYHxTOP7eI5gOuDO5IVz9k"
bot = telebot.TeleBot(BOT_TOKEN)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "أهلاً بك! 🎥\nأرسل لي رابط أي فيديو (TikTok, Instagram, YouTube, X, Facebook) وسأقوم بتحميله بسرعة فوراً عبر السحابة."
    )

@bot.message_handler(func=lambda message: True)
def handle_social_media_link(message):
    url = message.text.strip()

    if not url.startswith(("http://", "https://")):
        bot.reply_to(message, "يرجى إرسال رابط صحيح يبدأ بـ http أو https")
        return

    status_msg = bot.reply_to(message, "⏳ جاري التنزيل بالسيرفر السحابي بأقصى سرعة...")
    file_template = os.path.join(DOWNLOAD_DIR, f"{message.chat.id}_%(id)s.%(ext)s")

    ydl_opts = {
        'format': 'best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best',
        'outtmpl': file_template,
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'web_safari'],
            }
        },
    }

    downloaded_file = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_title = info.get('title', 'فيديو')
            duration = info.get('duration')
            video_duration = int(duration) if duration else None

            pattern = os.path.join(DOWNLOAD_DIR, f"{message.chat.id}_{info['id']}.*")
            matching_files = glob.glob(pattern)

            if not matching_files:
                raise FileNotFoundError("لم يتم العثور على ملف الفيديو.")

            downloaded_file = matching_files[0]

        bot.edit_message_text("📤 تم التحميل في ثوانٍ! جاري الإرسال لتلجرام...", chat_id=message.chat.id, message_id=status_msg.message_id)

        uploaded = False
        for _ in range(3):
            try:
                with open(downloaded_file, 'rb') as video:
                    bot.send_video(
                        message.chat.id,
                        video,
                        caption=f"🎬 {video_title[:200]}",
                        duration=video_duration,
                        supports_streaming=True,
                        timeout=300
                    )
                uploaded = True
                break
            except Exception:
                time.sleep(2)

        if not uploaded:
            with open(downloaded_file, 'rb') as doc:
                bot.send_document(
                    message.chat.id,
                    doc,
                    caption=f"🎬 {video_title[:200]}",
                    timeout=300
                )

        bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)

    except yt_dlp.utils.DownloadError as de:
        bot.edit_message_text(f"❌ تعذر التنزيل من المصدر: {str(de)[:120]}", chat_id=message.chat.id, message_id=status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ حدث خطأ: {str(e)[:120]}", chat_id=message.chat.id, message_id=status_msg.message_id)
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except OSError:
                pass

if __name__ == "__main__":
    print("البوت السحابي يعمل الآن ومحمي ضد الخمول...")
    bot.infinity_polling()
