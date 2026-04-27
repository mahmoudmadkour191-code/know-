#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import telebot
from telebot import types
import subprocess
import os
import re
import signal
import sys
import ast
import time
import sqlite3
import datetime
import shutil
from contextlib import closing

# ---------- التوكن والتكوينات ----------
TOKEN = "8457233918:AAFHD1dbVlPrMpC6W1jMjEMhyNMhGY9mwoI"
DB_NAME = "bot_host.db"

bot = telebot.TeleBot(TOKEN)

# ---------- المكتبات المضمنة وخريطة الحزم ----------
BUILTINS = {
    'sys','os','re','math','random','datetime','time','json','pickle',
    'subprocess','threading','socket','ssl','http','urllib','csv','sqlite3',
    'hashlib','itertools','functools','collections','pathlib','shutil','logging',
    'ast','base64','codecs'
}

PACKAGE_MAP = {
    'PIL': 'Pillow',
    'sklearn': 'scikit-learn',
    'cv2': 'opencv-python',
    'bs4': 'beautifulsoup4',
    'requests': 'requests',
    'flask': 'Flask',
    'django': 'Django',
    'telebot': 'pyTelegramBotAPI',
    'pandas': 'pandas',
    'numpy': 'numpy',
}

# ---------- قاعدة البيانات ----------
def init_db():
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    file_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    name TEXT,
                    path TEXT,
                    pid INTEGER,
                    status TEXT,
                    uploaded_at TEXT,
                    token TEXT
                )
            ''')

def add_file(file_id, user_id, name, path, pid, token):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute('''
                INSERT INTO files (file_id, user_id, name, path, pid, status, uploaded_at, token)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (file_id, user_id, name, path, pid, 'running' if pid else 'stopped',
                  datetime.datetime.now().isoformat(), token))

def update_file_status(file_id, pid, status):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute("UPDATE files SET pid = ?, status = ? WHERE file_id = ?", (pid, status, file_id))

def delete_file(file_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute("DELETE FROM files WHERE file_id = ?", (file_id,))

def get_user_files(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT file_id, name, pid, status, token FROM files WHERE user_id = ?", (user_id,))
        return cursor.fetchall()

def get_file_by_rowid(rowid):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT file_id FROM files WHERE rowid = ?", (rowid,))
        row = cursor.fetchone()
        return row[0] if row else None

def get_rowid(file_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT rowid FROM files WHERE file_id = ?", (file_id,))
        row = cursor.fetchone()
        return row[0] if row else None

def get_file_info(file_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT name, pid, status, token, path, user_id FROM files WHERE file_id = ?", (file_id,))
        return cursor.fetchone()

# ---------- دوال تشغيل الملفات ----------
def get_imports(code):
    try:
        tree = ast.parse(code)
    except:
        return set()
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split('.')[0])
    return imports

def install_needed(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        modules = get_imports(code)
        needed = [m for m in modules if m not in BUILTINS]
        if not needed:
            return "✅ لا توجد مكتبات خارجية."
        results = []
        for mod in needed:
            pkg = PACKAGE_MAP.get(mod, mod)
            try:
                __import__(mod)
                results.append(f"⏩ {pkg} موجود مسبقاً")
            except ImportError:
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    results.append(f"✅ تم تثبيت {pkg}")
                except:
                    results.append(f"❌ فشل تثبيت {pkg}")
        return "\n".join(results)
    except Exception as e:
        return f"❌ خطأ في التثبيت: {e}"

def get_token(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        m = re.search(r'TOKEN\s*=\s*[\'"]([^\'"]*)[\'"]', content)
        return m.group(1) if m else "غير موجود"
    except:
        return "خطأ"

def run_bot(file_path):
    try:
        # تشغيل بسيط جداً بدون أي خيارات معقدة لتجنب "منهي غير صحيح"
        proc = subprocess.Popen([sys.executable, file_path],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        return proc.pid
    except Exception as e:
        return None

def stop_bot(pid):
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except:
        return False

# ---------- واجهة الأزرار ----------
def main_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📤 رفع ملف", callback_data="upload"),
        types.InlineKeyboardButton("🗂 ملفاتي", callback_data="my_files")
    )
    return markup

def my_files_markup(user_id, page=0):
    files = get_user_files(user_id)
    if not files:
        return None, "⚠️ لا توجد ملفات مرفوعة.\nأرسل ملف `.py` الآن."
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_files = files[start:end]
    total = (len(files) + per_page - 1) // per_page
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_id, name, pid, status, token in page_files:
        icon = "🟢" if pid else "🔴"
        state = "يعمل" if pid else "متوقف"
        short = name[:22] + "…" if len(name) > 22 else name
        rid = get_rowid(file_id)
        if rid:
            markup.add(types.InlineKeyboardButton(f"{icon} {short} [{state}]", callback_data=f"filectl_{rid}"))
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀️ السابق", callback_data=f"myfiles_page_{page-1}"))
    if end < len(files):
        nav.append(types.InlineKeyboardButton("التالي ▶️", callback_data=f"myfiles_page_{page+1}"))
    if nav:
        markup.row(*nav)
    markup.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main"))
    return markup, f"📂 ملفاتي - صفحة {page+1} من {total}", None

def file_control_markup(file_id):
    rid = get_rowid(file_id)
    if not rid:
        return None
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("▶️ تشغيل", callback_data=f"run_{rid}"),
        types.InlineKeyboardButton("⏹️ إيقاف", callback_data=f"stop_{rid}")
    )
    markup.add(
        types.InlineKeyboardButton("🔄 إعادة تشغيل", callback_data=f"restart_{rid}"),
        types.InlineKeyboardButton("🗑️ حذف", callback_data=f"del_{rid}")
    )
    markup.add(types.InlineKeyboardButton("◀️ رجوع", callback_data="my_files"))
    return markup

# ---------- أوامر البوت ----------
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(
        message.chat.id,
        f"👋 أهلاً {message.from_user.first_name}!\nأرسل ملف `.py` لرفعه وتشغيله فوراً.",
        reply_markup=main_menu()
    )

@bot.message_handler(content_types=['document'])
def handle_file(message):
    user_id = message.from_user.id
    doc = message.document
    file_name = doc.file_name
    if not file_name.endswith('.py'):
        bot.reply_to(message, "❌ يسمح فقط بملفات `.py`.")
        return

    wait = bot.reply_to(message, "⏳ جاري التحميل والتثبيت...")
    try:
        finfo = bot.get_file(doc.file_id)
        data = bot.download_file(finfo.file_path)
        user_dir = f"files/{user_id}"
        os.makedirs(user_dir, exist_ok=True)
        safe_name = re.sub(r'[^\w\-_\.]', '_', file_name)
        file_path = os.path.join(user_dir, safe_name)
        with open(file_path, 'wb') as f:
            f.write(data)

        install_res = install_needed(file_path)
        token = get_token(file_path)
        pid = run_bot(file_path)
        add_file(doc.file_id, user_id, file_name, file_path, pid, token)
        status = f"✅ يعمل (PID: {pid})" if pid else "❌ فشل التشغيل"

        msg = f"✅ تم الرفع\n📄 {file_name}\n🔑 التوكن: `{token}`\n📦 {install_res}\n🚀 الحالة: {status}"
        bot.edit_message_text(msg, message.chat.id, wait.message_id, parse_mode='Markdown', reply_markup=main_menu())

    except Exception as e:
        bot.edit_message_text(f"❌ خطأ: {e}", message.chat.id, wait.message_id)

# ---------- معالج الأزرار ----------
@bot.callback_query_handler(func=lambda c: True)
def callback(call):
    data = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    user_id = call.from_user.id

    if data == "back_to_main":
        bot.edit_message_text("القائمة الرئيسية", chat_id, msg_id, reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "upload":
        bot.send_message(chat_id, "📤 أرسل ملف `.py` الآن.")
        bot.answer_callback_query(call.id)
        return

    if data == "my_files":
        markup, text, _ = my_files_markup(user_id)
        if markup is None:
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=main_menu())
        else:
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("myfiles_page_"):
        page = int(data.split("_")[-1])
        markup, text, _ = my_files_markup(user_id, page)
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("filectl_"):
        rowid = data[8:]
        file_id = get_file_by_rowid(rowid)
        if not file_id:
            bot.answer_callback_query(call.id, "ملف غير موجود", show_alert=True)
            return
        info = get_file_info(file_id)
        if not info or info[5] != user_id:
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        name, pid, status, token, path, _ = info
        status_text = "🟢 يعمل" if pid else "🔴 متوقف"
        text = f"📄 **{name}**\n🔑 التوكن: `{token}`\n📊 {status_text}"
        if pid:
            text += f"\n🆔 PID: `{pid}`"
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=file_control_markup(file_id))
        bot.answer_callback_query(call.id)
        return

    # أوامر التحكم: run_ / stop_ / restart_ / del_
    cmd, rid = data.split('_', 1)
    file_id = get_file_by_rowid(rid)
    if not file_id:
        bot.answer_callback_query(call.id, "ملف غير موجود", show_alert=True)
        return
    info = get_file_info(file_id)
    if not info or info[5] != user_id:
        bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
        return
    name, pid, status, token, path, _ = info

    if cmd == "run":
        if pid:
            bot.answer_callback_query(call.id, "الملف يعمل بالفعل", show_alert=True)
            return
        new_pid = run_bot(path)
        if new_pid:
            update_file_status(file_id, new_pid, 'running')
            bot.answer_callback_query(call.id, "✅ تم التشغيل")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=file_control_markup(file_id))
        else:
            bot.answer_callback_query(call.id, "❌ فشل التشغيل", show_alert=True)

    elif cmd == "stop":
        if not pid:
            bot.answer_callback_query(call.id, "الملف متوقف بالفعل", show_alert=True)
            return
        if stop_bot(pid):
            update_file_status(file_id, None, 'stopped')
            bot.answer_callback_query(call.id, "⏹️ تم الإيقاف")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=file_control_markup(file_id))
        else:
            bot.answer_callback_query(call.id, "❌ فشل الإيقاف", show_alert=True)

    elif cmd == "restart":
        if pid:
            stop_bot(pid)
            time.sleep(1)
        new_pid = run_bot(path)
        if new_pid:
            update_file_status(file_id, new_pid, 'running')
            bot.answer_callback_query(call.id, "🔄 تم إعادة التشغيل")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=file_control_markup(file_id))
        else:
            bot.answer_callback_query(call.id, "❌ فشل إعادة التشغيل", show_alert=True)

    elif cmd == "del":
        if pid:
            stop_bot(pid)
        try:
            if os.path.exists(path):
                os.remove(path)
        except:
            pass
        delete_file(file_id)
        bot.answer_callback_query(call.id, "🗑️ تم الحذف")
        markup, text, _ = my_files_markup(user_id)
        if markup is None:
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=main_menu())
        else:
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup)

# ---------- تشغيل الملفات المحفوظة عند بدء البوت ----------
def start_saved_files():
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT file_id, path FROM files")
        rows = cursor.fetchall()
    for file_id, path in rows:
        if path and os.path.exists(path):
            pid = run_bot(path)
            update_file_status(file_id, pid, 'running' if pid else 'stopped')

if __name__ == "__main__":
    init_db()
    start_saved_files()
    print("✅ البوت يعمل بشكل خفيف وسريع...")
    bot.infinity_polling(timeout=30)