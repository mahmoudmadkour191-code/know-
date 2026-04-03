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
import logging
import datetime
import zipfile
import rarfile
import shutil
from contextlib import closing
from functools import wraps

# -------------------- التكوينات --------------------
TOKEN = "8646051647:AAEl7jlia5tc_IQp3G1ipNja_MHQFntSTmM"  # استخدم متغير بيئة في الإنتاج
ADMIN_IDS = [6472365461]  # قائمة بالأدمن (يمكن إضافتهم لاحقاً)
MAX_FILES_NORMAL = 5    # الحد الأقصى للمستخدم العادي
MAX_FILES_VIP = 20      # الحد الأقصى لمستخدم VIP
DB_NAME = "bot_host.db"

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)

# -------------------- المكتبات المدمجة وخريطة الحزم --------------------
BUILTINS = {
    'sys','os','re','math','random','datetime','time','json','pickle',
    'subprocess','threading','multiprocessing','socket','ssl','http',
    'urllib','xml','csv','sqlite3','hashlib','itertools','functools',
    'collections','argparse','glob','pathlib','shutil','logging','warnings',
    'traceback','inspect','weakref','copy','pprint','enum','typing',
    'dataclasses','abc','io','base64','codecs','gettext','locale','calendar',
    'decimal','fractions','statistics','cmath','errno','fnmatch','linecache',
    'posixpath','ntpath','genericpath','ast','keyword','token','tokenize',
    'parser','py_compile','compileall','dis','pickletools','pydoc','doctest',
    'unittest','venv','ensurepip','distutils','setuptools','pkg_resources',
    'builtins','__main__','ctypes','struct','array','mmap','fcntl','grp','pwd',
    'spwd','crypt','termios','tty','pty','select','selectors','asyncio',
    'concurrent','queue','sched','contextvars'
}

PACKAGE_MAP = {
    'PIL': 'Pillow',
    'sklearn': 'scikit-learn',
    'cv2': 'opencv-python',
    'bs4': 'beautifulsoup4',
    'yaml': 'pyyaml',
    'dotenv': 'python-dotenv',
    'dateutil': 'python-dateutil',
    'requests': 'requests',
    'flask': 'Flask',
    'django': 'Django',
    'tensorflow': 'tensorflow',
    'torch': 'torch',
    'keras': 'keras',
    'transformers': 'transformers',
    'discord': 'discord.py',
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'vkbottle': 'vkbottle',
    'aiogram': 'aiogram',
    'aiohttp': 'aiohttp',
    'fastapi': 'fastapi',
    'uvicorn': 'uvicorn',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'matplotlib': 'matplotlib',
    'seaborn': 'seaborn',
    'plotly': 'plotly',
    'scipy': 'scipy',
    'sympy': 'sympy',
    'statsmodels': 'statsmodels',
    'xgboost': 'xgboost',
    'lightgbm': 'lightgbm',
    'catboost': 'catboost',
    'selenium': 'selenium',
    'playwright': 'playwright',
    'pyautogui': 'pyautogui',
    'pynput': 'pynput',
    'keyboard': 'keyboard',
    'mouse': 'mouse',
    'pygame': 'pygame'
}

DEVELOPERS = [
    ("M_C_V", "https://t.me/M_C_V_M"),
    ("Elkayoo", "https://t.me/elkayootelasle")
]

# -------------------- قاعدة البيانات --------------------
def init_db():
    """إنشاء الجداول في قاعدة البيانات"""
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_admin INTEGER DEFAULT 0,
                    is_vip INTEGER DEFAULT 0,
                    vip_expiry TEXT,
                    join_date TEXT,
                    files_count INTEGER DEFAULT 0,
                    subscribed INTEGER DEFAULT 0
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    file_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    name TEXT,
                    path TEXT,
                    pid INTEGER,
                    status TEXT,
                    uploaded_at TEXT,
                    token TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id INTEGER PRIMARY KEY,
                    channel_link TEXT,
                    mandatory INTEGER DEFAULT 1
                )
            ''')
            # إضافة الأدمن المبدئيين
            for admin_id in ADMIN_IDS:
                conn.execute('''
                    INSERT OR IGNORE INTO users (user_id, username, is_admin, join_date, subscribed)
                    VALUES (?, ?, ?, ?, 1)
                ''', (admin_id, "admin", 1, datetime.datetime.now().isoformat()))
            conn.commit()

def get_file_by_rowid(rowid):
    """جيب file_id الكامل من rowid الصغير"""
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT file_id FROM files WHERE rowid = ?", (rowid,))
        row = cursor.fetchone()
        return row[0] if row else None

def get_rowid_for_file(file_id):
    """جيب rowid البسيط لاستخدامه في callback_data"""
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT rowid FROM files WHERE file_id = ?", (file_id,))
        row = cursor.fetchone()
        return row[0] if row else None

# -------------------- دوال المساعدة --------------------
def get_user(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()

def register_user(user_id, username, first_name, last_name):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute('''
                INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, join_date, subscribed)
                VALUES (?, ?, ?, ?, ?, 0)
            ''', (user_id, username, first_name, last_name, datetime.datetime.now().isoformat()))
            # تحديث الاسم إذا تغير
            conn.execute('''
                UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE user_id = ?
            ''', (username, first_name, last_name, user_id))

def set_subscribed(user_id, value):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute("UPDATE users SET subscribed = ? WHERE user_id = ?", (1 if value else 0, user_id))

def is_subscribed(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT subscribed FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row and row[0] == 1

def is_admin(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row and row[0] == 1

def is_vip(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT is_vip, vip_expiry FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row and row[0] == 1:
            if row[1]:
                expiry = datetime.datetime.fromisoformat(row[1])
                if expiry > datetime.datetime.now():
                    return True
                else:
                    # انتهت صلاحية VIP
                    conn.execute("UPDATE users SET is_vip = 0, vip_expiry = NULL WHERE user_id = ?", (user_id,))
                    conn.commit()
                    return False
            return True
        return False

def get_user_files_count(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,))
        return cursor.fetchone()[0]

def can_upload(user_id):
    if is_admin(user_id):
        return True
    count = get_user_files_count(user_id)
    if is_vip(user_id):
        return count < MAX_FILES_VIP
    return count < MAX_FILES_NORMAL

def add_file_to_db(file_id, user_id, name, path, pid, token):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute('''
                INSERT INTO files (file_id, user_id, name, path, pid, status, uploaded_at, token)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (file_id, user_id, name, path, pid, 'running' if pid else 'stopped', datetime.datetime.now().isoformat(), token))
            conn.execute("UPDATE users SET files_count = files_count + 1 WHERE user_id = ?", (user_id,))

def update_file_status(file_id, pid, status):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute("UPDATE files SET pid = ?, status = ? WHERE file_id = ?", (pid, status, file_id))

def delete_file_from_db(file_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            # الحصول على user_id لتقليل العداد
            cursor = conn.execute("SELECT user_id FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
            if row:
                conn.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
                conn.execute("UPDATE users SET files_count = files_count - 1 WHERE user_id = ?", (row[0],))

def get_user_files(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT file_id, name, pid, status, token FROM files WHERE user_id = ?", (user_id,))
        return cursor.fetchall()

def get_all_files():
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT file_id, user_id, name, pid, status FROM files")
        return cursor.fetchall()

def get_all_users():
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT user_id, username, first_name, last_name, is_admin, is_vip FROM users")
        return cursor.fetchall()

def get_mandatory_channels():
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT channel_id, channel_link FROM channels WHERE mandatory = 1")
        return cursor.fetchall()

def add_channel(channel_id, channel_link):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute("INSERT OR IGNORE INTO channels (channel_id, channel_link, mandatory) VALUES (?, ?, 1)", (channel_id, channel_link))

def remove_channel(channel_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))

def set_admin(user_id, value):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute("UPDATE users SET is_admin = ? WHERE user_id = ?", (1 if value else 0, user_id))

def set_vip(user_id, value, expiry_days=None):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            expiry = None
            if value and expiry_days:
                expiry = (datetime.datetime.now() + datetime.timedelta(days=expiry_days)).isoformat()
            conn.execute("UPDATE users SET is_vip = ?, vip_expiry = ? WHERE user_id = ?", (1 if value else 0, expiry, user_id))

def delete_user(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            # حذف ملفات المستخدم من القرص
            cursor = conn.execute("SELECT path FROM files WHERE user_id = ?", (user_id,))
            for (path,) in cursor:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except:
                    pass
            conn.execute("DELETE FROM files WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

def get_all_admins():
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT user_id FROM users WHERE is_admin = 1")
        return [row[0] for row in cursor]

# -------------------- التحقق من الاشتراك الإجباري --------------------
def check_all_subscriptions(user_id):
    channels = get_mandatory_channels()
    if not channels:
        return True, None
    unsubscribed = []
    for channel_id, channel_link in channels:
        try:
            chat_member = bot.get_chat_member(channel_id, user_id)
            if chat_member.status not in ['member', 'administrator', 'creator']:
                unsubscribed.append(channel_link)
        except Exception as e:
            logger.error(f"Failed to check subscription for {user_id} in {channel_id}: {e}")
            unsubscribed.append(channel_link)
    if unsubscribed:
        return False, unsubscribed
    return True, None

def subscription_required(func):
    @wraps(func)
    def wrapper(message_or_call, *args, **kwargs):
        # تحديد user_id
        if hasattr(message_or_call, 'from_user'):
            user_id = message_or_call.from_user.id
        else:
            user_id = message_or_call.chat.id if hasattr(message_or_call, 'chat') else None
            if not user_id:
                return func(message_or_call, *args, **kwargs)
        
        # إذا كان المستخدم أدمن، لا نتحقق من الاشتراك
        if is_admin(user_id):
            return func(message_or_call, *args, **kwargs)
        
        ok, _ = check_all_subscriptions(user_id)
        if not ok:
            # إرسال رسالة بها أزرار القنوات وزر التحقق
            send_subscription_required_message(message_or_call, user_id)
            return
        return func(message_or_call, *args, **kwargs)
    return wrapper

def send_subscription_required_message(msg_or_call, user_id):
    channels = get_mandatory_channels()
    text = "⚠️ **يجب عليك الاشتراك في القنوات التالية لاستخدام البوت:**\n\n"
    markup = types.InlineKeyboardMarkup()
    for _, link in channels:
        text += f"• [اضغط للاشتراك]({link})\n"
        markup.add(types.InlineKeyboardButton("📢 اشترك في القناة", url=link))
    markup.add(types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data=f"check_sub_{user_id}"))
    
    if hasattr(msg_or_call, 'chat'):
        bot.send_message(msg_or_call.chat.id, text, parse_mode='Markdown', reply_markup=markup, disable_web_page_preview=True)
    else:
        bot.edit_message_text(text, msg_or_call.message.chat.id, msg_or_call.message.message_id, parse_mode='Markdown', reply_markup=markup, disable_web_page_preview=True)

# -------------------- دوال إدارة الملفات المضغوطة --------------------
def extract_archive(file_path, extract_to):
    """فك ضغط ملف zip أو rar"""
    try:
        if file_path.endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
            return True
        elif file_path.endswith('.rar'):
            with rarfile.RarFile(file_path, 'r') as rar_ref:
                rar_ref.extractall(extract_to)
            return True
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return False
    return False

def find_py_files(directory):
    """البحث عن جميع ملفات .py داخل مجلد"""
    py_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                py_files.append(os.path.join(root, file))
    return py_files

# -------------------- دوال إدارة العمليات --------------------
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
            return "لا توجد مكتبات خارجية."
        
        results = []
        for mod in needed:
            pkg = PACKAGE_MAP.get(mod, mod)
            try:
                __import__(mod)
                results.append(f"⏩ {pkg} مثبت مسبقاً")
            except ImportError:
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    results.append(f"✅ تم تثبيت {pkg}")
                except:
                    results.append(f"❌ فشل تثبيت {pkg}")
        return "\n".join(results)
    except Exception as e:
        return f"خطأ في تثبيت المكتبات: {e}"

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
        if sys.platform != "win32":
            proc = subprocess.Popen([sys.executable, file_path],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    preexec_fn=os.setsid)
        else:
            proc = subprocess.Popen([sys.executable, file_path],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        return proc.pid
    except Exception as e:
        logger.error(f"Failed to run {file_path}: {e}")
        return None

def stop_bot(pid):
    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        else:
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        return True
    except:
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except:
            return False

# -------------------- دوال البوت - واجهة احترافية --------------------
def get_welcome_text(user_id):
    user = get_user(user_id)
    if not user:
        return "مرحباً بك في بوت استضافة بايثون الاحترافي!"
    first_name = user[2] or user[1] or f"مستخدم {user_id}"
    vip_badge = "⭐ VIP" if is_vip(user_id) else ""
    admin_badge = "👑 أدمن" if is_admin(user_id) else ""
    badges = " │ ".join(filter(None, [vip_badge, admin_badge]))
    files_used = get_user_files_count(user_id)
    files_limit = "∞ أدمن" if is_admin(user_id) else (str(MAX_FILES_VIP) if is_vip(user_id) else str(MAX_FILES_NORMAL))
    tier = f"🏅 {badges}" if badges else "👤 مستخدم عادي"
    return f"""
╔══════════════════════════╗
  🤖 **Python Host Pro**
╚══════════════════════════╝

👋 أهلاً **{first_name}**!

━━━━━━━━ 📋 حسابك ━━━━━━━━
🆔 المعرف: `{user_id}`
{tier}
📂 الملفات: `{files_used}` / `{files_limit}`

━━━━━━━━ ⚡ المميزات ━━━━━━━━
🟢 رفع وتشغيل ملفات `.py`
🟢 دعم الأرشيفات `zip` و `rar`
🟢 تثبيت المكتبات تلقائياً
🟢 تحكم كامل: تشغيل / إيقاف / إعادة
🟢 نظام VIP بدون حدود
🟢 إشعارات فورية للمشرفين

━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

def main_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_upload = types.InlineKeyboardButton("📤 رفع ملف جديد", callback_data="upload")
    btn_my_files = types.InlineKeyboardButton("🗂 ملفاتي", callback_data="my_files")
    markup.add(btn_upload, btn_my_files)
    if is_admin(user_id):
        markup.add(types.InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel"))
    markup.add(types.InlineKeyboardButton("👨‍💻 المطورون", callback_data="devs"))
    return markup

def my_files_markup(user_id, page=0):
    files = get_user_files(user_id)
    if not files:
        return None, "🗂 **ملفاتي**\n\n⚠️ لا توجد ملفات مرفوعة بعد.\nارفع ملف `.py` أو أرشيف مضغوط للبدء.", None
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_files = files[start:end]
    total_pages = (len(files) + per_page - 1) // per_page
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_id, name, pid, status, token in page_files:
        icon = "🟢" if pid else "🔴"
        state = "يعمل" if pid else "متوقف"
        short_name = name[:22] + "…" if len(name) > 22 else name
        btn_text = f"{icon} {short_name}  [{state}]"
        rowid = get_rowid_for_file(file_id)
        if rowid:
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"filectl_{rowid}"))
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("◀️ السابق", callback_data=f"myfiles_page_{page-1}"))
    if end < len(files):
        nav_buttons.append(types.InlineKeyboardButton("التالي ▶️", callback_data=f"myfiles_page_{page+1}"))
    if nav_buttons:
        markup.row(*nav_buttons)
    markup.add(types.InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="back_to_main"))
    return markup, f"🗂 **ملفاتي** — الصفحة {page+1} من {total_pages}\n\nاختر ملفاً للتحكم به:", None

def file_control_markup(file_id, user_id):
    rowid = get_rowid_for_file(file_id)
    rid = rowid if rowid else file_id
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("▶️ تشغيل", callback_data=f"run_{rid}"),
        types.InlineKeyboardButton("⏹️ إيقاف", callback_data=f"stop_{rid}"),
    )
    markup.add(
        types.InlineKeyboardButton("🔄 إعادة تشغيل", callback_data=f"restart_{rid}"),
        types.InlineKeyboardButton("🗑️ حذف الملف", callback_data=f"del_{rid}"),
    )
    markup.add(types.InlineKeyboardButton("◀️ رجوع للملفات", callback_data="my_files"))
    return markup

def admin_panel_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="admin_users"),
        types.InlineKeyboardButton("📂 إدارة الملفات", callback_data="admin_files"),
        types.InlineKeyboardButton("📢 إذاعة", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("👑 إدارة الأدمن", callback_data="admin_manage_admins"),
        types.InlineKeyboardButton("⭐ إدارة VIP", callback_data="admin_manage_vip"),
        types.InlineKeyboardButton("📢 قنوات الاشتراك", callback_data="admin_channels"),
        types.InlineKeyboardButton("🔙 العودة للرئيسية", callback_data="back_to_main")
    )
    return markup

def admin_manage_admins_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ إضافة أدمن", callback_data="admin_add_admin"),
        types.InlineKeyboardButton("➖ حذف أدمن", callback_data="admin_remove_admin"),
        types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")
    )
    return markup

def admin_manage_vip_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("⭐ إضافة VIP", callback_data="admin_add_vip"),
        types.InlineKeyboardButton("⭐ حذف VIP", callback_data="admin_remove_vip"),
        types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")
    )
    return markup

def users_list_markup(page=0):
    users = get_all_users()
    if not users:
        return None, "لا يوجد مستخدمون.", None
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_users = users[start:end]
    markup = types.InlineKeyboardMarkup(row_width=1)
    for uid, username, first_name, last_name, is_admin, is_vip in page_users:
        name = first_name or username or str(uid)
        badge = "👑 " if is_admin else ("⭐ " if is_vip else "")
        btn_text = f"{badge}{name} ({uid})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"admin_user_{uid}"))
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("◀️ السابق", callback_data=f"admin_users_page_{page-1}"))
    if end < len(users):
        nav_buttons.append(types.InlineKeyboardButton("التالي ▶️", callback_data=f"admin_users_page_{page+1}"))
    if nav_buttons:
        markup.row(*nav_buttons)
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
    total_pages = (len(users) + per_page - 1) // per_page
    return markup, f"👥 **قائمة المستخدمين** (الصفحة {page+1}/{total_pages})", None

def user_control_markup(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("⭐ جعل VIP", callback_data=f"admin_make_vip_{user_id}"),
        types.InlineKeyboardButton("⭐ إزالة VIP", callback_data=f"admin_remove_vip_{user_id}"),
        types.InlineKeyboardButton("👑 جعل أدمن", callback_data=f"admin_make_admin_{user_id}"),
        types.InlineKeyboardButton("👑 إزالة أدمن", callback_data=f"admin_remove_admin_{user_id}"),
        types.InlineKeyboardButton("🗑 حذف المستخدم", callback_data=f"admin_del_user_{user_id}"),
        types.InlineKeyboardButton("📂 ملفات المستخدم", callback_data=f"admin_user_files_{user_id}"),
        types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")
    )
    return markup

def all_files_markup(page=0):
    files = get_all_files()
    if not files:
        return None, "لا توجد ملفات.", None
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_files = files[start:end]
    markup = types.InlineKeyboardMarkup(row_width=2)
    for file_id, user_id, name, pid, status in page_files:
        icon = "🟢" if pid else "🔴"
        btn_text = f"{icon} {name[:15]}... (المستخدم: {user_id})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"admin_file_{file_id}"))
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("◀️ السابق", callback_data=f"admin_files_page_{page-1}"))
    if end < len(files):
        nav_buttons.append(types.InlineKeyboardButton("التالي ▶️", callback_data=f"admin_files_page_{page+1}"))
    if nav_buttons:
        markup.row(*nav_buttons)
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
    total_pages = (len(files) + per_page - 1) // per_page
    return markup, f"📂 **جميع الملفات** (الصفحة {page+1}/{total_pages})", None

def channels_markup():
    channels = get_mandatory_channels()
    markup = types.InlineKeyboardMarkup(row_width=1)
    if channels:
        for cid, link in channels:
            btn_text = f"❌ {cid} - {link[:30]}..."
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"admin_channel_del_{cid}"))
    else:
        markup.add(types.InlineKeyboardButton("⚠️ لا توجد قنوات", callback_data="noop"))
    markup.add(types.InlineKeyboardButton("➕ إضافة قناة جديدة", callback_data="admin_add_channel"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
    return markup

# -------------------- أوامر البوت --------------------
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name, user.last_name)
    # التحقق من الاشتراك
    ok, _ = check_all_subscriptions(user.id)
    if not ok:
        send_subscription_required_message(message, user.id)
        return
    set_subscribed(user.id, True)
    welcome_text = get_welcome_text(user.id)
    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=main_menu(user.id))

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("check_sub_"))
def check_subscription_callback(call):
    user_id = int(call.data.split("_")[-1])
    if user_id != call.from_user.id:
        bot.answer_callback_query(call.id, "هذا الزر ليس لك", show_alert=True)
        return
    ok, _ = check_all_subscriptions(user_id)
    if ok:
        set_subscribed(user_id, True)
        bot.answer_callback_query(call.id, "✅ تم التحقق! يمكنك الآن استخدام البوت.")
        bot.edit_message_text(get_welcome_text(user_id), call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=main_menu(user_id))
    else:
        bot.answer_callback_query(call.id, "❌ لم تشترك في جميع القنوات بعد. اشترك ثم اضغط تحقق.", show_alert=True)

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "❌ هذا الأمر مخصص للأدمن فقط.")
        return
    bot.send_message(message.chat.id, "👑 **لوحة التحكم**", parse_mode='Markdown', reply_markup=admin_panel_markup())

@bot.message_handler(commands=['developer'])
def developer_cmd(message):
    markup = types.InlineKeyboardMarkup()
    for name, url in DEVELOPERS:
        markup.add(types.InlineKeyboardButton(name, url=url))
    bot.send_message(message.chat.id, "👨‍💻 **المطورون**", parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(content_types=['document'])
@subscription_required
def handle_file(message):
    user_id = message.from_user.id
    if not can_upload(user_id):
        limit = MAX_FILES_VIP if is_vip(user_id) else MAX_FILES_NORMAL
        bot.reply_to(message, f"❌ وصلت للحد الأقصى `{limit}` ملف.\n{'ترقية حسابك لـ VIP تتيح لك 20 ملف.' if not is_vip(user_id) else 'تواصل مع الأدمن لرفع الحد.'}")
        return
    doc = message.document
    file_name = doc.file_name
    # التحقق من الامتداد
    if not (file_name.endswith('.py') or file_name.endswith('.zip') or file_name.endswith('.rar')):
        bot.reply_to(message, "❌ يرجى رفع ملف `.py` أو ملف مضغوط `.zip`/`.rar`.")
        return
    
    wait_msg = bot.reply_to(message, "⏳ جاري التحميل والتثبيت...")
    try:
        finfo = bot.get_file(doc.file_id)
        data = bot.download_file(finfo.file_path)
        # حفظ الملف في مجلد خاص بالمستخدم
        user_dir = f"files/{user_id}"
        os.makedirs(user_dir, exist_ok=True)
        safe_name = re.sub(r'[^\w\-_\.]', '_', file_name)
        file_path = os.path.join(user_dir, safe_name)
        with open(file_path, 'wb') as f:
            f.write(data)
        
        # إذا كان الملف مضغوطاً
        if file_name.endswith('.zip') or file_name.endswith('.rar'):
            extract_dir = os.path.join(user_dir, os.path.splitext(safe_name)[0])
            os.makedirs(extract_dir, exist_ok=True)
            if extract_archive(file_path, extract_dir):
                py_files = find_py_files(extract_dir)
                if not py_files:
                    bot.edit_message_text("❌ **لم يتم العثور على أي ملفات .py داخل الأرشيف.**", message.chat.id, wait_msg.message_id, parse_mode='Markdown')
                    os.remove(file_path)
                    shutil.rmtree(extract_dir, ignore_errors=True)
                    return
                # إرسال قائمة بالملفات للمستخدم لاختيار أي منها يريد تشغيله
                markup = types.InlineKeyboardMarkup()
                for pyf in py_files:
                    rel_path = os.path.relpath(pyf, extract_dir)
                    markup.add(types.InlineKeyboardButton(rel_path, callback_data=f"select_py_{doc.file_id}_{rel_path}"))
                markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_extract"))
                bot.edit_message_text(f"📦 **تم فك الضغط بنجاح.**\nتم العثور على {len(py_files)} ملف .py. اختر الملف الذي تريد تشغيله:", 
                                     message.chat.id, wait_msg.message_id, parse_mode='Markdown', reply_markup=markup)
                # تخزين معلومات الأرشيف مؤقتاً
                if not hasattr(bot, 'extract_data'):
                    bot.extract_data = {}
                bot.extract_data[doc.file_id] = {
                    'user_id': user_id,
                    'extract_dir': extract_dir,
                    'py_files': py_files,
                    'original_path': file_path
                }
                return
            else:
                bot.edit_message_text("❌ **فشل فك الضغط. تأكد من صحة الملف.**", message.chat.id, wait_msg.message_id, parse_mode='Markdown')
                os.remove(file_path)
                return
        
        # إذا كان ملف .py مباشراً
        install_result = install_needed(file_path)
        token = get_token(file_path)
        pid = run_bot(file_path)
        add_file_to_db(doc.file_id, user_id, file_name, file_path, pid, token)
        status = f"✅ يعمل (PID: {pid})" if pid else "❌ فشل التشغيل"
        
        # تحضير النص للإشعار
        user_info = f"👤 **المستخدم:** {message.from_user.first_name} (@{message.from_user.username})\n🆔 **ID:** `{user_id}`"
        file_info = f"📄 **الملف:** `{file_name}`\n🔑 **التوكن:** `{token}`"
        status_info = f"🚀 **حالة التشغيل:** {status}\n📦 **نتيجة التثبيت:**\n{install_result}"
        
        # رسالة للمستخدم
        bot.edit_message_text(
            f"✅ **تم رفع الملف بنجاح**\n\n"
            f"📄 **الاسم:** `{file_name}`\n"
            f"🔑 **التوكن:** `{token}`\n"
            f"📦 **تثبيت المكتبات:**\n{install_result}\n"
            f"🚀 **حالة التشغيل:** {status}",
            chat_id=message.chat.id,
            message_id=wait_msg.message_id,
            parse_mode='Markdown',
            reply_markup=main_menu(user_id)
        )
        
        # إشعار لجميع الأدمن مع الملف وإمكانية النسخ
        for admin_id in get_all_admins():
            try:
                # إرسال رسالة نصية مفصلة مع اقتباس
                admin_text = f"📦 **رفع ملف جديد**\n\n{user_info}\n\n{file_info}\n\n{status_info}"
                
                # إرسال الرسالة النصية مع إمكانية النسخ
                sent_msg = bot.send_message(admin_id, admin_text, parse_mode='Markdown')
                
                # إرسال الملف نفسه للأدمن
                with open(file_path, 'rb') as f:
                    bot.send_document(admin_id, f, caption=f"📎 الملف المرفوع: {file_name}")
                
                # إرسال رسالة منسقة بشكل اقتباس
                quote_text = f"```\nالمستخدم: {message.from_user.first_name} (@{message.from_user.username})\nالملف: {file_name}\nالتوكن: {token}\nالحالة: {status}\n```"
                bot.send_message(admin_id, quote_text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Failed to send admin notification: {e}")
                
    except Exception as e:
        logger.exception("Error handling file upload")
        bot.edit_message_text(f"❌ **حدث خطأ:**\n`{e}`", message.chat.id, wait_msg.message_id, parse_mode='Markdown')

# -------------------- معالج اختيار الملف من الأرشيف --------------------
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("select_py_"))
def select_py_from_archive(call):
    parts = call.data.split('_')
    file_id = parts[2]
    rel_path = '_'.join(parts[3:])
    if not hasattr(bot, 'extract_data') or file_id not in bot.extract_data:
        bot.answer_callback_query(call.id, "انتهت صلاحية هذه العملية.", show_alert=True)
        return
    data = bot.extract_data[file_id]
    if call.from_user.id != data['user_id']:
        bot.answer_callback_query(call.id, "هذا الملف ليس لك.", show_alert=True)
        return
    # العثور على المسار الكامل
    full_path = None
    for pyf in data['py_files']:
        if os.path.relpath(pyf, data['extract_dir']) == rel_path:
            full_path = pyf
            break
    if not full_path:
        bot.answer_callback_query(call.id, "الملف غير موجود.", show_alert=True)
        return
    # تثبيت المكتبات وتشغيل الملف
    install_result = install_needed(full_path)
    token = get_token(full_path)
    pid = run_bot(full_path)
    # إضافة الملف إلى قاعدة البيانات (نستخدم file_id من الأرشيف مع إضافة اسم الملف)
    unique_file_id = f"{file_id}_{rel_path}"
    add_file_to_db(unique_file_id, data['user_id'], rel_path, full_path, pid, token)
    status = f"✅ يعمل (PID: {pid})" if pid else "❌ فشل التشغيل"
    
    # تحضير النص للإشعار
    user_info = f"👤 **المستخدم:** {call.from_user.first_name} (@{call.from_user.username})\n🆔 **ID:** `{data['user_id']}`"
    file_info = f"📄 **الملف:** `{rel_path}`\n🔑 **التوكن:** `{token}`"
    status_info = f"🚀 **حالة التشغيل:** {status}\n📦 **نتيجة التثبيت:**\n{install_result}"
    
    # رسالة للمستخدم
    bot.edit_message_text(
        f"✅ **تم تشغيل الملف**\n\n"
        f"📄 **الاسم:** `{rel_path}`\n"
        f"🔑 **التوكن:** `{token}`\n"
        f"📦 **تثبيت المكتبات:**\n{install_result}\n"
        f"🚀 **حالة التشغيل:** {status}",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode='Markdown',
        reply_markup=main_menu(data['user_id'])
    )
    
    # إشعار لجميع الأدمن مع الملف
    for admin_id in get_all_admins():
        try:
            admin_text = f"📦 **رفع ملف جديد (من أرشيف)**\n\n{user_info}\n\n{file_info}\n\n{status_info}"
            bot.send_message(admin_id, admin_text, parse_mode='Markdown')
            
            # إرسال الملف نفسه للأدمن
            with open(full_path, 'rb') as f:
                bot.send_document(admin_id, f, caption=f"📎 الملف المرفوع: {rel_path}")
            
            quote_text = f"```\nالمستخدم: {call.from_user.first_name} (@{call.from_user.username})\nالملف: {rel_path}\nالتوكن: {token}\nالحالة: {status}\n```"
            bot.send_message(admin_id, quote_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to send admin notification: {e}")
    
    # تنظيف مؤقت
    del bot.extract_data[file_id]
    bot.answer_callback_query(call.id, "✅ تم تشغيل الملف")

@bot.callback_query_handler(func=lambda c: c.data == "cancel_extract")
def cancel_extract(call):
    if hasattr(bot, 'extract_data'):
        for fid, data in list(bot.extract_data.items()):
            if data['user_id'] == call.from_user.id:
                try:
                    os.remove(data['original_path'])
                    shutil.rmtree(data['extract_dir'], ignore_errors=True)
                except:
                    pass
                del bot.extract_data[fid]
    bot.edit_message_text("❌ **تم الإلغاء.**", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

# -------------------- معالج الأزرار العامة --------------------
@bot.callback_query_handler(func=lambda c: True)
@subscription_required
def callback_handler(call):
    data = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    user_id = call.from_user.id

    if data == "noop":
        bot.answer_callback_query(call.id)
        return

    if data == "back_to_main":
        bot.edit_message_text(get_welcome_text(user_id), chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu(user_id))
        bot.answer_callback_query(call.id)

    elif data == "upload":
        bot.send_message(chat_id, "📤 أرسل ملف `.py` أو ملف مضغوط `.zip`/`.rar` الآن.")
        bot.answer_callback_query(call.id)

    elif data == "my_files":
        markup, text, _ = my_files_markup(user_id)
        if markup is None:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu(user_id))
        else:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif data.startswith("myfiles_page_"):
        page = int(data.split("_")[-1])
        markup, text, _ = my_files_markup(user_id, page)
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif data.startswith("filectl_"):
        rowid = data[8:]
        file_id = get_file_by_rowid(rowid)
        if not file_id:
            bot.answer_callback_query(call.id, "❌ الملف غير موجود", show_alert=True)
            return
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.execute("SELECT name, pid, status, token, path FROM files WHERE file_id = ? AND user_id = ?", (file_id, user_id))
            row = cursor.fetchone()
        if not row:
            bot.answer_callback_query(call.id, "❌ الملف غير موجود أو لا تملك صلاحية الوصول", show_alert=True)
            return
        name, pid, status, token, path = row
        status_icon = "🟢 يعمل" if pid else "🔴 متوقف"
        text = (
            f"📄 **{name}**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 التوكن: `{token}`\n"
            f"📊 الحالة: {status_icon}\n"
        )
        if pid:
            text += f"🆔 PID: `{pid}`\n"
        text += f"📂 المسار: `{path}`"
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=file_control_markup(file_id, user_id))
        bot.answer_callback_query(call.id)

    # التحكم بالملفات — نستخدم rowid لتجنب مشكلة _ في file_id
    elif data.startswith("run_"):
        rowid = data[4:]
        file_id = get_file_by_rowid(rowid)
        if not file_id:
            bot.answer_callback_query(call.id, "❌ ملف غير موجود", show_alert=True)
            return
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.execute("SELECT path, user_id, pid FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
        if not row:
            bot.answer_callback_query(call.id, "❌ ملف غير موجود", show_alert=True)
            return
        path, owner, cur_pid = row
        if owner != user_id and not is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ لا تملك صلاحية التحكم بهذا الملف", show_alert=True)
            return
        if cur_pid:
            bot.answer_callback_query(call.id, "⚠️ الملف يعمل بالفعل!", show_alert=True)
            return
        pid = run_bot(path)
        if pid:
            update_file_status(file_id, pid, 'running')
            bot.answer_callback_query(call.id, "✅ تم التشغيل بنجاح")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=file_control_markup(file_id, user_id))
        else:
            bot.answer_callback_query(call.id, "❌ فشل التشغيل — تحقق من الملف", show_alert=True)

    elif data.startswith("stop_"):
        rowid = data[5:]
        file_id = get_file_by_rowid(rowid)
        if not file_id:
            bot.answer_callback_query(call.id, "❌ ملف غير موجود", show_alert=True)
            return
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.execute("SELECT pid, user_id FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
        if not row:
            bot.answer_callback_query(call.id, "❌ ملف غير موجود", show_alert=True)
            return
        pid, owner = row
        if owner != user_id and not is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ لا تملك صلاحية التحكم بهذا الملف", show_alert=True)
            return
        if not pid:
            bot.answer_callback_query(call.id, "⚠️ الملف متوقف بالفعل", show_alert=True)
            return
        if stop_bot(pid):
            update_file_status(file_id, None, 'stopped')
            bot.answer_callback_query(call.id, "⏹️ تم الإيقاف")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=file_control_markup(file_id, user_id))
        else:
            bot.answer_callback_query(call.id, "❌ فشل الإيقاف", show_alert=True)

    elif data.startswith("restart_"):
        rowid = data[8:]
        file_id = get_file_by_rowid(rowid)
        if not file_id:
            bot.answer_callback_query(call.id, "❌ ملف غير موجود", show_alert=True)
            return
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.execute("SELECT path, pid, user_id FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
        if not row:
            bot.answer_callback_query(call.id, "❌ ملف غير موجود", show_alert=True)
            return
        path, old_pid, owner = row
        if owner != user_id and not is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ لا تملك صلاحية التحكم بهذا الملف", show_alert=True)
            return
        if old_pid:
            stop_bot(old_pid)
            time.sleep(1)
        pid = run_bot(path)
        if pid:
            update_file_status(file_id, pid, 'running')
            bot.answer_callback_query(call.id, "🔄 تمت إعادة التشغيل")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=file_control_markup(file_id, user_id))
        else:
            bot.answer_callback_query(call.id, "❌ فشل إعادة التشغيل", show_alert=True)

    elif data.startswith("del_"):
        rowid = data[4:]
        file_id = get_file_by_rowid(rowid)
        if not file_id:
            bot.answer_callback_query(call.id, "❌ ملف غير موجود", show_alert=True)
            return
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.execute("SELECT path, pid, user_id FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
        if not row:
            bot.answer_callback_query(call.id, "❌ ملف غير موجود", show_alert=True)
            return
        path, pid, owner = row
        if owner != user_id and not is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ لا تملك صلاحية التحكم بهذا الملف", show_alert=True)
            return
        if pid:
            stop_bot(pid)
        try:
            if os.path.exists(path):
                os.remove(path)
        except:
            pass
        delete_file_from_db(file_id)
        bot.answer_callback_query(call.id, "🗑️ تم الحذف")
        markup, text, _ = my_files_markup(user_id)
        if markup is None:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu(user_id))
        else:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=markup)

    # لوحة الأدمن
    elif data == "admin_panel":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        bot.edit_message_text("👑 **لوحة التحكم**", chat_id, msg_id, parse_mode='Markdown', reply_markup=admin_panel_markup())
        bot.answer_callback_query(call.id)

    elif data == "admin_manage_admins":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        bot.edit_message_text("👑 **إدارة الأدمن**", chat_id, msg_id, parse_mode='Markdown', reply_markup=admin_manage_admins_markup())
        bot.answer_callback_query(call.id)

    elif data == "admin_manage_vip":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        bot.edit_message_text("⭐ **إدارة VIP**", chat_id, msg_id, parse_mode='Markdown', reply_markup=admin_manage_vip_markup())
        bot.answer_callback_query(call.id)

    elif data == "admin_users":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        markup, text, _ = users_list_markup()
        if markup is None:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=admin_panel_markup())
        else:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif data.startswith("admin_users_page_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        page = int(data.split("_")[-1])
        markup, text, _ = users_list_markup(page)
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif data.startswith("admin_user_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        target_id = int(data.split("_")[-1])
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.execute("SELECT user_id, username, first_name, last_name, is_admin, is_vip FROM users WHERE user_id = ?", (target_id,))
            row = cursor.fetchone()
        if not row:
            bot.answer_callback_query(call.id, "مستخدم غير موجود", show_alert=True)
            return
        _, username, first_name, last_name, admin_status, vip_status = row
        name = first_name or username or str(target_id)
        text = f"👤 **المستخدم:** {name}\n"
        text += f"🆔 ID: `{target_id}`\n"
        text += f"👑 أدمن: {'نعم' if admin_status else 'لا'}\n"
        text += f"⭐ VIP: {'نعم' if vip_status else 'لا'}"
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=user_control_markup(target_id))
        bot.answer_callback_query(call.id)

    elif data.startswith("admin_make_vip_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        target_id = int(data.split("_")[-1])
        set_vip(target_id, True, 30)
        bot.answer_callback_query(call.id, "✅ تم جعل المستخدم VIP")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=user_control_markup(target_id))

    elif data.startswith("admin_remove_vip_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        target_id = int(data.split("_")[-1])
        set_vip(target_id, False)
        bot.answer_callback_query(call.id, "✅ تم إزالة VIP")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=user_control_markup(target_id))

    elif data.startswith("admin_make_admin_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        target_id = int(data.split("_")[-1])
        set_admin(target_id, True)
        bot.answer_callback_query(call.id, "✅ تم جعل المستخدم أدمن")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=user_control_markup(target_id))

    elif data.startswith("admin_remove_admin_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        target_id = int(data.split("_")[-1])
        set_admin(target_id, False)
        bot.answer_callback_query(call.id, "✅ تم إزالة الأدمن")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=user_control_markup(target_id))

    elif data.startswith("admin_del_user_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        target_id = int(data.split("_")[-1])
        delete_user(target_id)
        bot.answer_callback_query(call.id, "🗑 تم حذف المستخدم")
        markup, text, _ = users_list_markup()
        if markup is None:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=admin_panel_markup())
        else:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=markup)

    elif data.startswith("admin_user_files_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        target_id = int(data.split("_")[-1])
        files = get_user_files(target_id)
        if not files:
            bot.answer_callback_query(call.id, "لا توجد ملفات لهذا المستخدم", show_alert=True)
            return
        text = f"📂 **ملفات المستخدم {target_id}:**\n"
        for file_id, name, pid, status, token in files:
            text += f"\n📄 {name}\n   🆔 {file_id}\n   {'🟢 يعمل' if pid else '🔴 متوقف'}"
        bot.send_message(chat_id, text, parse_mode='Markdown')
        bot.answer_callback_query(call.id)

    elif data == "admin_files":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        markup, text, _ = all_files_markup()
        if markup is None:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=admin_panel_markup())
        else:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif data.startswith("admin_files_page_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        page = int(data.split("_")[-1])
        markup, text, _ = all_files_markup(page)
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif data.startswith("admin_file_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        file_id = data.split("_")[-1]
        with closing(sqlite3.connect(DB_NAME)) as conn:
            cursor = conn.execute("SELECT name, pid, status, token, path, user_id FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
        if not row:
            bot.answer_callback_query(call.id, "ملف غير موجود", show_alert=True)
            return
        name, pid, status, token, path, owner = row
        text = f"📄 **{name}**\n"
        text += f"👤 المالك: `{owner}`\n"
        text += f"🔑 التوكن: `{token}`\n"
        text += f"🟢 الحالة: {'يعمل' if pid else 'متوقف'}\n"
        if pid:
            text += f"🆔 PID: `{pid}`\n"
        text += f"📂 المسار: `{path}`"
        markup = types.InlineKeyboardMarkup(row_width=2)
        rid = get_rowid_for_file(file_id) or file_id
        markup.add(
            types.InlineKeyboardButton("▶️ تشغيل", callback_data=f"run_{rid}"),
            types.InlineKeyboardButton("⏹️ إيقاف", callback_data=f"stop_{rid}"),
            types.InlineKeyboardButton("🔄 إعادة تشغيل", callback_data=f"restart_{rid}"),
            types.InlineKeyboardButton("🗑️ حذف", callback_data=f"del_{rid}"),
        )
        markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_files"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif data == "admin_broadcast":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        bot.send_message(chat_id, "📢 **أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين.**")
        bot.register_next_step_handler_by_chat_id(chat_id, broadcast_message)
        bot.answer_callback_query(call.id)

    elif data == "admin_add_admin":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        bot.send_message(chat_id, "➕ **أرسل ID المستخدم الذي تريد جعله أدمن.**")
        bot.register_next_step_handler_by_chat_id(chat_id, add_admin_step)
        bot.answer_callback_query(call.id)

    elif data == "admin_remove_admin":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        bot.send_message(chat_id, "➖ **أرسل ID المستخدم الذي تريد إزالة الأدمن عنه.**")
        bot.register_next_step_handler_by_chat_id(chat_id, remove_admin_step)
        bot.answer_callback_query(call.id)

    elif data == "admin_add_vip":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        bot.send_message(chat_id, "⭐ **أرسل ID المستخدم الذي تريد جعله VIP (مع عدد الأيام اختيارياً، مثلاً: 12345 30)**")
        bot.register_next_step_handler_by_chat_id(chat_id, add_vip_step)
        bot.answer_callback_query(call.id)

    elif data == "admin_remove_vip":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        bot.send_message(chat_id, "⭐ **أرسل ID المستخدم الذي تريد إزالة VIP عنه.**")
        bot.register_next_step_handler_by_chat_id(chat_id, remove_vip_step)
        bot.answer_callback_query(call.id)

    elif data == "admin_channels":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        bot.edit_message_text("📢 **قنوات الاشتراك الإجباري**\n\nاختر قناة لحذفها أو أضف قناة جديدة.", chat_id, msg_id, parse_mode='Markdown', reply_markup=channels_markup())
        bot.answer_callback_query(call.id)

    elif data == "admin_add_channel":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        bot.send_message(chat_id, "➕ **أرسل معرف القناة (مثل -1001234567890) ورابطها (مثل https://t.me/joinchat/...)**\n\nالصيغة: `معرف_القناة رابط_القناة`")
        bot.register_next_step_handler_by_chat_id(chat_id, add_channel_step)
        bot.answer_callback_query(call.id)

    elif data.startswith("admin_channel_del_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "غير مصرح", show_alert=True)
            return
        channel_id = int(data.split("_")[-1])
        remove_channel(channel_id)
        bot.answer_callback_query(call.id, "✅ تم حذف القناة")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=channels_markup())

    elif data == "devs":
        markup = types.InlineKeyboardMarkup()
        for name, url in DEVELOPERS:
            markup.add(types.InlineKeyboardButton(name, url=url))
        bot.edit_message_text("👨‍💻 **المطورون**", chat_id, msg_id, parse_mode='Markdown', reply_markup=markup)
        bot.answer_callback_query(call.id)

# -------------------- دوال الخطوات المتعددة --------------------
def broadcast_message(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    text = message.text
    users = get_all_users()
    sent = 0
    for (uid, _, _, _, _, _) in users:
        try:
            bot.send_message(uid, text)
            sent += 1
        except:
            pass
    bot.reply_to(message, f"✅ **تم الإذاعة إلى {sent} مستخدم.**")

def add_admin_step(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    try:
        target_id = int(message.text.strip())
    except:
        bot.reply_to(message, "❌ ID غير صالح.")
        return
    set_admin(target_id, True)
    bot.reply_to(message, f"✅ **تم جعل المستخدم {target_id} أدمن.**")

def remove_admin_step(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    try:
        target_id = int(message.text.strip())
    except:
        bot.reply_to(message, "❌ ID غير صالح.")
        return
    set_admin(target_id, False)
    bot.reply_to(message, f"✅ **تم إزالة الأدمن عن المستخدم {target_id}.**")

def add_vip_step(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    parts = message.text.strip().split()
    if len(parts) < 1:
        bot.reply_to(message, "❌ يجب إرسال ID المستخدم.")
        return
    try:
        target_id = int(parts[0])
        days = int(parts[1]) if len(parts) > 1 else 30
    except:
        bot.reply_to(message, "❌ صيغة غير صحيحة. مثال: 123456789 30")
        return
    set_vip(target_id, True, days)
    bot.reply_to(message, f"✅ **تم جعل المستخدم {target_id} VIP لمدة {days} يوماً.**")

def remove_vip_step(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    try:
        target_id = int(message.text.strip())
    except:
        bot.reply_to(message, "❌ ID غير صالح.")
        return
    set_vip(target_id, False)
    bot.reply_to(message, f"✅ **تم إزالة VIP عن المستخدم {target_id}.**")

def add_channel_step(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ يجب إرسال معرف القناة ورابطها.\nمثال: -1001234567890 https://t.me/joinchat/...")
        return
    try:
        channel_id = int(parts[0])
        link = parts[1]
    except:
        bot.reply_to(message, "❌ معرف القناة غير صالح.")
        return
    add_channel(channel_id, link)
    bot.reply_to(message, f"✅ **تم إضافة القناة {channel_id}**")
    # عرض القنوات المحدثة
    bot.send_message(user_id, "📢 **قنوات الاشتراك الإجباري**", reply_markup=channels_markup())

# -------------------- تشغيل البوت --------------------
def startup_run_all_files():
    """تشغيل جميع الملفات المحفوظة في قاعدة البيانات عند بدء البوت"""
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.execute("SELECT file_id, path, name FROM files")
        files = cursor.fetchall()
    if not files:
        logger.info("لا توجد ملفات لتشغيلها عند البدء.")
        return
    logger.info(f"🚀 جاري تشغيل {len(files)} ملف محفوظ...")
    for file_id, path, name in files:
        if not path or not os.path.exists(path):
            logger.warning(f"⚠️ الملف غير موجود على القرص: {name} — تم تخطيه.")
            update_file_status(file_id, None, 'stopped')
            continue
        pid = run_bot(path)
        if pid:
            update_file_status(file_id, pid, 'running')
            logger.info(f"✅ تم تشغيل: {name} (PID: {pid})")
        else:
            update_file_status(file_id, None, 'stopped')
            logger.warning(f"❌ فشل تشغيل: {name}")

if __name__ == "__main__":
    print("🚀 Python Host Pro — جاري التشغيل...")
    init_db()  # إنشاء قاعدة البيانات إذا لم تكن موجودة
    startup_run_all_files()
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        logger.error(f"Bot stopped: {e}")