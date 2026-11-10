import os
import re
import glob
import time
import math
import uuid
import html
import sqlite3
import subprocess
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import apihelper, types
import yt_dlp

# 1. خادم مصغر لمنع Render من الخمول
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"VIP Bot is online and running!")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# 2. التنبيه الذاتي كل 10 دقائق
def keep_alive_ping():
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen("https://telegram-downloader-0owh.onrender.com", timeout=15)
        except Exception:
            pass

threading.Thread(target=keep_alive_ping, daemon=True).start()

# 3. التحديث التلقائي لمحرك التحميل كل 24 ساعة
def auto_update_ytdlp():
    while True:
        time.sleep(86400)
        try:
            subprocess.run(["pip", "install", "--upgrade", "yt-dlp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

threading.Thread(target=auto_update_ytdlp, daemon=True).start()

# 4. منظف القرص الدوري التلقائي
def auto_disk_cleaner():
    while True:
        time.sleep(600)
        now = time.time()
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
            try:
                if os.path.isfile(f) and (now - os.path.getmtime(f)) > 600:
                    os.remove(f)
            except Exception:
                pass

threading.Thread(target=auto_disk_cleaner, daemon=True).start()

# 5. إعدادات تلجرام
apihelper.CONNECT_TIMEOUT = 30
apihelper.READ_TIMEOUT = 300

BOT_TOKEN = "9265561235:AAFyaR6rCz1xnZYHxTOP7eI5gOuDO5IVz9k"
bot = telebot.TeleBot(BOT_TOKEN)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

DOWNLOAD_SEMAPHORE = threading.Semaphore(2)
INFO_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# قاعدة بيانات الكاش الذكي
DB_PATH = "media_cache.db"
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS media_cache (
            url TEXT,
            quality TEXT,
            file_id TEXT,
            title TEXT,
            file_type TEXT,
            PRIMARY KEY (url, quality)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_cached_file(url, quality):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT file_id, title, file_type FROM media_cache WHERE url = ? AND quality = ?", (url, quality))
    row = cur.fetchone()
    conn.close()
    return row

def save_to_cache(url, quality, file_id, title, file_type):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO media_cache VALUES (?, ?, ?, ?, ?)", (url, quality, file_id, title, file_type))
        conn.commit()
        conn.close()
    except Exception:
        pass

MEDIA_STORE = {}
MAX_CHUNK_BYTES = 47 * 1024 * 1024
COOKIE_PATH = "cookies.txt" if os.path.exists("cookies.txt") else None

SUPPORTED_DOMAINS = [
    'tiktok.com', 'douyin.com', 'youtube.com', 'youtu.be',
    'instagram.com', 'facebook.com', 'fb.watch', 'twitter.com',
    'x.com', 'reddit.com', 'pinterest.com'
]

def extract_all_media_urls(text):
    if not text:
        return []
    raw_urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    if not raw_urls:
        return []

    valid_urls = []
    for u in raw_urls:
        u = re.sub(r'[\.,!?،؛:)]+$', '', u)
        if not u.startswith('http'):
            u = 'https://' + u
        if 'tiktoklite' in u.lower() or 'tiktok.com/download' in u.lower():
            continue
        for d in SUPPORTED_DOMAINS:
            if d in u.lower() and u not in valid_urls:
                valid_urls.append(u)
                break

    if not valid_urls:
        for u in raw_urls:
            u = re.sub(r'[\.,!?،؛:)]+$', '', u)
            if not u.startswith('http'): u = 'https://' + u
            if u not in valid_urls and 'tiktoklite' not in u.lower():
                valid_urls.append(u)

    return valid_urls

def get_base_ydl_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,       # منع فحص القوائم أو المواقع الكاملة حتى لا يعلق البوت
        'playlist_items': '1',    # سحب أول فيديو فقط دائماً
        'socket_timeout': 12,
        'retries': 2,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {'youtube': {'player_client': ['ios', 'web_safari']}},
    }
    if COOKIE_PATH:
        opts['cookiefile'] = COOKIE_PATH
    return opts

def fetch_video_info(url):
    """دالة معزولة لفحص الرابط مع حماية ضد التعليق"""
    ydl_info_opts = get_base_ydl_opts()
    with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info and 'entries' in info:
            entries = list(info['entries'])
            if not entries:
                raise ValueError("لا يوجد مقطع فيديو في هذا الرابط.")
            info = entries[0]
        return info

def format_count(count):
    if not count:
        return "غير متوفر"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)

def fast_split_and_send(chat_id, file_path, title, total_duration, status_msg_id, url, quality):
    file_size = os.path.getsize(file_path)
    safe_title = html.escape(title[:140])

    if file_size <= 48 * 1024 * 1024:
        bot.edit_message_text("⚡ جاري الرفع لتلجرام بأقصى سرعة...", chat_id=chat_id, message_id=status_msg_id)
        with open(file_path, 'rb') as v:
            sent_msg = bot.send_video(
                chat_id, v, 
                caption=f"🎬 <b>{safe_title}</b>\n\n🤖 @raad_downloader_bot", 
                duration=int(total_duration) if total_duration else None, 
                supports_streaming=True,
                parse_mode="HTML"
            )
            if sent_msg.video:
                save_to_cache(url, quality, sent_msg.video.file_id, title, "video")

        bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
        return

    num_parts = math.ceil(file_size / MAX_CHUNK_BYTES)
    chunk_duration = math.ceil(total_duration / num_parts) if total_duration else 180

    bot.edit_message_text(
        f"✂️ حجم المقطع ({file_size / (1024*1024):.1f}MB) كبير.\n⚡ جاري التقطيع الفوري لـ {num_parts} أجزاء ورفعها...", 
        chat_id=chat_id, message_id=status_msg_id
    )

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
                "-avoid_negative_ts", "1",
                part_path
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.exists(part_path) and os.path.getsize(part_path) > 0:
                with open(part_path, 'rb') as part_v:
                    bot.send_video(
                        chat_id, 
                        part_v, 
                        caption=f"🎬 <b>{safe_title[:100]}</b>\n📦 <b>الجزء ({i+1}/{num_parts})</b>\n\n🤖 @raad_downloader_bot",
                        duration=int(chunk_duration),
                        supports_streaming=True,
                        parse_mode="HTML"
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
        "👑 <b>أهلاً بك في محمل الوسائط السحابي VIP!</b> 🚀\n\n"
        "أرسل لي رابطاً واحداً أو روابط متعددة أو نصاً طويلاً:\n"
        "• YouTube • TikTok • Instagram • Facebook • X\n\n"
        "💎 <b>مميزات نسخة VIP:</b>\n"
        "├ ⚡ أرشيف ذكي فوري (0.1 ثانية للروابط المكررة)\n"
        "├ 🚫 بدون علامة مائية لمقاطع تيك توك\n"
        "├ 🛡️ حماية ضد التعليق والرموز الخاصة\n"
        "└ ✂️ تقطيع فوري للمقاطع الضخمة\n\n"
        "👇 <b>شارك أي رابط لتجربته الآن!</b>"
    )
    bot.reply_to(message, welcome_text, parse_mode="HTML")

@bot.message_handler(commands=['update'])
def manual_update(message):
    status_msg = bot.reply_to(message, "⏳ جاري فحص وتحديث مكتبة التحميل لأحدث إصدار...")
    try:
        subprocess.run(["pip", "install", "--upgrade", "yt-dlp"], capture_output=True, text=True)
        bot.edit_message_text("✅ <b>تم تحديث محرك التحميل بنجاح لأحدث إصدار رسمي!</b>", chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="HTML")
    except Exception as e:
        bot.edit_message_text(f"❌ فشل التحديث: {str(e)}", chat_id=message.chat.id, message_id=status_msg.message_id)

@bot.message_handler(func=lambda message: True)
def handle_link_request(message):
    urls = extract_all_media_urls(message.text)

    if not urls:
        bot.reply_to(message, "⚠️ لم أجد أي رابط صالح في رسالتك. يرجى إرسال رابط فيديو واضح.")
        return

    urls = urls[:5]
    total = len(urls)
    status_msg = bot.reply_to(message, f"🔍 تم العثور على ({total}) روابط، جاري فحصها واستخراج بطاقات التحميل...")

    for idx, url in enumerate(urls, 1):
        try:
            # تشغيل الفحص مع مؤقت قاطع (20 ثانية بحد أقصى) لمنع التعليق نهائياً
            future = INFO_EXECUTOR.submit(fetch_video_info, url)
            info = future.result(timeout=20)

            if not info:
                bot.send_message(message.chat.id, f"⚠️ الرابط ({idx}) لا يحتوي على فيديو قابل للتحميل.")
                continue

            title = info.get('title') or 'مقطع فيديو'
            duration = info.get('duration') or 0
            uploader = info.get('uploader') or info.get('channel') or "غير معروف"
            views = info.get('view_count') or 0
            thumb = info.get('thumbnail')

            req_id = uuid.uuid4().hex[:8]
            MEDIA_STORE[req_id] = {
                "url": url, 
                "title": title, 
                "duration": duration,
                "uploader": uploader
            }

            markup = types.InlineKeyboardMarkup(row_width=2)
            btn_1080 = types.InlineKeyboardButton("💎 Full HD 1080p", callback_data=f"dl:1080:{req_id}")
            btn_720 = types.InlineKeyboardButton("⚡ 720p (موصى به)", callback_data=f"dl:720:{req_id}")
            btn_480 = types.InlineKeyboardButton("📱 480p (خفيف)", callback_data=f"dl:480:{req_id}")
            btn_mp3 = types.InlineKeyboardButton("🎧 صوت نقي MP3", callback_data=f"dl:mp3:{req_id}")
            btn_close = types.InlineKeyboardButton("❌ إغلاق", callback_data=f"dl:close:{req_id}")

            markup.add(btn_1080)
            markup.add(btn_720, btn_480)
            markup.add(btn_mp3)
            markup.add(btn_close)

            dur_text = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "غير محدد"
            
            # تنظيف النصوص من الرموز لمنع خطأ 400 Bad Request في تلجرام
            safe_title = html.escape(title[:110])
            safe_uploader = html.escape(str(uploader)[:50])

            caption = (
                f"🎬 <b>[{idx}/{total}] {safe_title}</b>\n\n"
                f"👤 <b>الناشر:</b> {safe_uploader}\n"
                f"⏱ <b>المدة:</b> {dur_text} دقيقة\n"
                f"👁 <b>المشاهدات:</b> {format_count(views)}\n\n"
                f"👇 <b>اختر صيغة التحميل المطلوبة:</b>"
            )

            # محاولة إرسال الغلاف، وإذا رفض تلجرام رابط صورة تيك توك يرسل البطاقة النصية فوراً
            sent_card = False
            if thumb:
                try:
                    bot.send_photo(message.chat.id, thumb, caption=caption, reply_markup=markup, parse_mode="HTML")
                    sent_card = True
                except Exception:
                    sent_card = False

            if not sent_card:
                bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="HTML")

        except FuturesTimeoutError:
            bot.send_message(message.chat.id, f"⏱ انتهت مهلة فحص الرابط ({idx}): هذا الموقع بطيء جداً أو لا يحتوي على فيديو مباشر.")
        except Exception as e:
            err_str = str(e)
            if "Unsupported URL" in err_str:
                bot.send_message(message.chat.id, f"❌ الرابط ({idx}) هو صفحة موقع عامة وليس رابط فيديو مدعوم.")
            else:
                bot.send_message(message.chat.id, f"⚠️ تعذر تحليل الرابط ({idx}): تأكد من أنه رابط فيديو عام وصحيح.")

    try:
        bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
    except Exception:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("dl:"))
def handle_download_option(call):
    chat_id = call.message.chat.id
    _, choice, req_id = call.data.split(":")

    if choice == "close":
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        return

    if req_id not in MEDIA_STORE:
        bot.answer_callback_query(call.id, "⚠️ انتهت صلاحية هذا الطلب، أرسل الرابط مجدداً.", show_alert=True)
        return

    data = MEDIA_STORE[req_id]
    url = data["url"]
    title = data["title"]
    duration = data["duration"]
    uploader = data["uploader"]
    safe_title = html.escape(title[:140])

    # 1. فحص الكاش الذكي أولاً
    cached = get_cached_file(url, choice)
    if cached:
        file_id, c_title, f_type = cached
        safe_c_title = html.escape(c_title[:140])
        bot.answer_callback_query(call.id, "⚡ جلب فوري من الأرشيف السحابي (0.1 ثانية)!")
        if f_type == "audio":
            bot.send_audio(chat_id, file_id, caption=f"🎵 <b>{safe_c_title}</b>\n⚡ (أرشيف سحابي فوري 🚀)\n\n🤖 @raad_downloader_bot", parse_mode="HTML")
        else:
            bot.send_video(chat_id, file_id, caption=f"🎬 <b>{safe_c_title}</b>\n⚡ (أرشيف سحابي فوري 🚀)\n\n🤖 @raad_downloader_bot", parse_mode="HTML")
        return

    bot.answer_callback_query(call.id, "🚀 جاري التحميل والمعالجة...")
    status_msg = bot.send_message(chat_id, f"⚡ <b>جاري سحب ومعالجة:</b> <code>{html.escape(title[:50])}...</code>", parse_mode="HTML")

    file_prefix = f"{chat_id}_{req_id}_{int(time.time())}"
    downloaded_file = None

    with DOWNLOAD_SEMAPHORE:
        try:
            ydl_opts = get_base_ydl_opts()

            if choice == "mp3":
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                })
            elif 'tiktok.com' in url.lower():
                # صيغة متوافقة ومضمونة لمقاطع تيك توك بدون علامة مائية
                ydl_opts.update({
                    'format': 'best[ext=mp4]/best',
                    'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                })
            elif choice == "1080":
                ydl_opts.update({
                    'format': 'bestvideo+bestaudio/best',
                    'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                    'merge_output_format': 'mp4',
                })
            elif choice == "720":
                ydl_opts.update({
                    'format': 'best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                    'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_prefix}.%(ext)s"),
                    'merge_output_format': 'mp4',
                })
            else: # 480
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

            if choice == "mp3":
                bot.edit_message_text("🎧 جاري رفع الملف الصوتي...", chat_id=chat_id, message_id=status_msg.message_id)
                with open(downloaded_file, 'rb') as audio:
                    sent = bot.send_audio(
                        chat_id, audio, 
                        title=title[:100], 
                        performer=str(uploader)[:50],
                        duration=int(duration) if duration else None, 
                        caption=f"🎵 <b>{safe_title}</b>\n\n🤖 @raad_downloader_bot",
                        parse_mode="HTML"
                    )
                    if sent.audio:
                        save_to_cache(url, choice, sent.audio.file_id, title, "audio")
                bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
            else:
                fast_split_and_send(chat_id, downloaded_file, title, duration, status_msg.message_id, url, choice)

        except Exception as e:
            bot.edit_message_text(f"❌ تعذر تنزيل المقطع: تأكد من أن الرابط صالح وعام.", chat_id=chat_id, message_id=status_msg.message_id)
        finally:
            if downloaded_file and os.path.exists(downloaded_file):
                try: os.remove(downloaded_file)
                except OSError: pass

if __name__ == "__main__":
    print("البوت السحابي VIP المحصن ضد أخطاء 400 والتعليق يعمل الآن...")
    bot.infinity_polling()
