import logging
import sqlite3
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
# استيراد مكتبة dotenv لقراءة الملفات النصية محلياً
from dotenv import load_dotenv

# شحن المتغيرات من ملف .env (يعمل محلياً فقط)
load_dotenv()

# ============================================================
# ⚙️ الإعدادات الأساسية
# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot_logs.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# التعديل هنا: قراءة القيم مباشرة من البيئة دون وضع قيم افتراضية مكشوفة
TOKEN    = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) # وضعت 0 كقيمة افتراضية لحماية حسابك

MIN_DEPOSIT = 1_000
MAX_DEPOSIT = 5_000_000
# ============================================================
# 💎 أسعار الفيبوكس
# ============================================================
VBUCKS_PRICES = [
    (800,   9_000),
    (1600,  18_000),
    (2400,  22_000),
    (3200,  30_000),
    (4000,  39_000),
    (4500,  34_000),
    (5300,  42_000),
    (6100,  50_000),
    (6900,  54_000),
    (7700,  62_000),
    (8500,  70_000),
    (9000,  65_000),
    (9800,  72_000),
    (10600, 79_000),
    (12500, 74_000),
    (13300, 81_000),
    (14900, 91_000),
    (17000, 101_000),
    (25000, 140_000),
    (37500, 208_000),
]

def get_vbucks_price(vbucks_amount):
    for vb, price in VBUCKS_PRICES:
        if vb == vbucks_amount:
            return price
    return None

# ============================================================
# 🛡️ الحماية من السبام
# ============================================================
USER_LAST_REQUEST: dict = {}

def is_spam(user_id):
    now = datetime.now()
    if user_id in USER_LAST_REQUEST:
        if (now - USER_LAST_REQUEST[user_id]) < timedelta(milliseconds=500):
            return True
    USER_LAST_REQUEST[user_id] = now
    return False

# ============================================================
# 🗄️ قاعدة البيانات
# ============================================================
DB_PATH = "mero_store.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            balance INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            method TEXT, amount INTEGER, status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            item_name TEXT, price INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            product TEXT, price INTEGER, email TEXT, code TEXT,
            platform TEXT, status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    conn.commit()
    conn.close()
    logger.info("✅ تم تهيئة قاعدة البيانات")

def get_connection():
    return sqlite3.connect(DB_PATH)

def ensure_user_exists(user_id, username=None, first_name=None):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, first_name=excluded.first_name,
                updated_at=datetime('now','localtime')
        """, (user_id, username, first_name))
        conn.commit()

def get_balance(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = c.fetchone()
        return row[0] if row else 0

def update_balance(user_id, amount):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET balance=balance+?, updated_at=datetime('now','localtime') WHERE user_id=?",
                  (amount, user_id))
        conn.commit()
    return get_balance(user_id)

def set_balance(user_id, new_balance):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET balance=?, updated_at=datetime('now','localtime') WHERE user_id=?",
                  (new_balance, user_id))
        conn.commit()
    return get_balance(user_id)

def add_deposit_record(user_id, method, amount, status="approved"):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO deposits (user_id,method,amount,status) VALUES (?,?,?,?)",
                  (user_id, method, amount, status))
        conn.commit()

def add_purchase_record(user_id, item_name, price):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO purchases (user_id,item_name,price) VALUES (?,?,?)",
                  (user_id, item_name, price))
        conn.commit()

def add_order_record(user_id, product, price, email, code, platform):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO orders (user_id,product,price,email,code,platform) VALUES (?,?,?,?,?,?)",
                  (user_id, product, price, email, code, platform))
        conn.commit()

def get_deposit_history(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT method, amount, status, created_at
            FROM deposits WHERE user_id=?
            ORDER BY created_at ASC, id ASC
            LIMIT 50
        """, (user_id,))
        return c.fetchall()

def get_purchase_history(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT item_name, price, created_at
            FROM purchases WHERE user_id=?
            ORDER BY created_at ASC, id ASC
            LIMIT 50
        """, (user_id,))
        return c.fetchall()

# ============================================================
# ✅ التحقق من المدخلات
# ============================================================
def validate_amount(amount_str):
    if not amount_str.isdigit():
        return False, "❌ *يرجى كتابة المبلغ كأرقام فقط!*\n\n⚠️ لا يمكن إرسال حروف أو رموز.\n\n📝 اكتب رقماً فقط مثال: `10000`"
    amount = int(amount_str)
    if amount < MIN_DEPOSIT:
        return False, f"❌ الحد الأدنى للشحن هو *{MIN_DEPOSIT:,} د.ع*"
    if amount > MAX_DEPOSIT:
        return False, f"❌ الحد الأقصى للشحن هو *{MAX_DEPOSIT:,} د.ع*"
    return True, amount


def validate_amount_card_balance(amount_str):
    """التحقق من المبلغ لطرق رصيد الكارت - يجب أن يكون مضاعف 1000"""
    if not amount_str.isdigit():
        return False, (
            "❌ *يرجى كتابة المبلغ كأرقام فقط!*\n\n"
            "⚠️ لا يمكن إرسال حروف أو رموز.\n\n"
            "📝 اكتب رقماً فقط مثال: `10000`"
        )
    amount = int(amount_str)
    if amount < MIN_DEPOSIT:
        return False, f"❌ الحد الأدنى للشحن هو *{MIN_DEPOSIT:,} د.ع*"
    if amount > MAX_DEPOSIT:
        return False, f"❌ الحد الأقصى للشحن هو *{MAX_DEPOSIT:,} د.ع*"
    # ✅ شرط المضاعفات
    if amount % 1000 != 0:
        nearest_down = (amount // 1000) * 1000
        nearest_up   = nearest_down + 1000
        return False, (
            f"❌ *المبلغ يجب أن يكون من مضاعفات الـ 1,000!*\n\n"
            f"🔢 المبلغ الذي كتبته: *{amount:,} د.ع*\n\n"
            f"✅ أقرب مبلغ صحيح أقل: *{nearest_down:,} د.ع*\n"
            f"✅ أقرب مبلغ صحيح أكبر: *{nearest_up:,} د.ع*\n\n"
            f"📝 مثال على مبالغ صحيحة:\n"
            f"`1000` | `2000` | `5000` | `10000` | `25000`"
        )
    return True, amount


# ============================================================
# 🎨 بناء القوائم
# ============================================================
def build_main_menu():
    keyboard = [
        [InlineKeyboardButton("👤 حسابي", callback_data="my_account")],
        [InlineKeyboardButton("💰 شحن رصيدي / محفظتي", callback_data="my_wallet")],
        [InlineKeyboardButton("🛒 عرض جميع المنتجات", callback_data="products")],
        [InlineKeyboardButton("⭐ الثقة والأمان", callback_data="trust")],
        [InlineKeyboardButton("🎯 كيف يعمل البوت؟", callback_data="how_it_works")],
        [InlineKeyboardButton("🎧 خدمة الزبائن والدعم", url="https://t.me/mer14s?text=مرحباً%2C%20أحتاج%20إلى%20مساعدة%20في%20متجر%20ميرو%20ستور%20🛒")],
        [InlineKeyboardButton("اشترك في 📢 قناة المتجر - آخر الأخبار", url="https://t.me/mero14store")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_account_menu():
    keyboard = [
        [InlineKeyboardButton("📝 معلوماتي", callback_data="info_clicked")],
        [InlineKeyboardButton("🛍️ سجل المشتريات", callback_data="purchases_clicked")],
        [InlineKeyboardButton("🔄 سجل الشحنات", callback_data="deposit_clicked")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_wallet_menu():
    keyboard = [
        [InlineKeyboardButton("📱 رصيد اسيا كارت او تحويل", callback_data="w_asia")],
        [InlineKeyboardButton("📱 رصيد اثير (زين) كارت او تحويل", callback_data="w_zain")],
        [InlineKeyboardButton("💸 تحويل مالي زين كاش", callback_data="w_zain_cash")],
        [InlineKeyboardButton("💳 تحويل مالي ماستر كارد رافدين", callback_data="w_rafidain")],
        [InlineKeyboardButton("🔑 تحويل مالي سوبر كي", callback_data="w_super_key")],
        [InlineKeyboardButton("🏦 تحويل مالي FIB", callback_data="w_fib")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_products_menu():
    keyboard = [
        [InlineKeyboardButton("🎮 فورت نايت", callback_data="sec_fortnite")],
        [InlineKeyboardButton("📱 العاب الموبايل", callback_data="sec_mob_games")],
        [InlineKeyboardButton("🛠️ خدمات عامة", callback_data="sec_general_serv")],
        [InlineKeyboardButton("🟢 اكسبوكس", callback_data="sec_xbox")],
        [InlineKeyboardButton("💳 بطاقات شحن الكترونية", callback_data="sec_cards")],
        [InlineKeyboardButton("🎬 اشتراكات المشاهدة والالعاب", callback_data="sec_subs")],
        [InlineKeyboardButton("📈 خدمات التواصل الاجتماعي", callback_data="sec_social_serv")],
        [InlineKeyboardButton("🕹️ العاب منوعة (بلي-PC-Xbox)", callback_data="sec_multi_games")],
        [InlineKeyboardButton("💬 شحن برامج التواصل", callback_data="sec_social_chat")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_fortnite_menu():
    keyboard = [
        [InlineKeyboardButton("💎 فيبوكس (V-Bucks)", callback_data="fn_vbucks")],
        [InlineKeyboardButton("🛍️ حزم الايتم شوب", callback_data="fn_itemshop")],
        [InlineKeyboardButton("🌟 حزم نادرة غير موجودة بالشوب", callback_data="fn_rare")],
        [InlineKeyboardButton("👥 كرو فورت نايت (الطاقم)", callback_data="fn_crew")],
        [InlineKeyboardButton("🎁 هدايا ايتم شوب وبتل باس", callback_data="fn_gifts")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="products")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_vbucks_menu():
    keyboard = []
    for i in range(0, len(VBUCKS_PRICES), 2):
        row = []
        vb1, pr1 = VBUCKS_PRICES[i]
        row.append(InlineKeyboardButton(f"💎 {vb1:,} | {pr1:,}", callback_data=f"vb_{vb1}"))
        if i + 1 < len(VBUCKS_PRICES):
            vb2, pr2 = VBUCKS_PRICES[i + 1]
            row.append(InlineKeyboardButton(f"💎 {vb2:,} | {pr2:,}", callback_data=f"vb_{vb2}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="sec_fortnite")])
    keyboard.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def build_platform_menu():
    keyboard = [
        [InlineKeyboardButton("🎮 Epic Games", callback_data="plt_epic")],
        [InlineKeyboardButton("🟢 Xbox", callback_data="plt_xbox")],
        [InlineKeyboardButton("🔵 PlayStation", callback_data="plt_ps")],
        [InlineKeyboardButton("🟡 Google Play", callback_data="plt_google")],
        [InlineKeyboardButton("❌ إلغاء الطلب", callback_data="cancel_order_to_fn_vbucks")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_confirm_order_keyboard():
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد وإرسال الطلب", callback_data="confirm_order")],
        [InlineKeyboardButton("❌ إلغاء الطلب", callback_data="cancel_order_to_fn_vbucks")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_admin_keyboard(user_id, amount):
    keyboard = [
        [InlineKeyboardButton(f"✅ موافقة على {amount:,} د.ع", callback_data=f"adm_approve_{user_id}_{amount}")],
        [InlineKeyboardButton("✏️ شحن بمبلغ مختلف", callback_data=f"adm_edit_{user_id}")],
        [InlineKeyboardButton("❌ رفض الطلب", callback_data=f"adm_reject_{user_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_admin_order_keyboard(user_id, order_id):
    keyboard = [
        [InlineKeyboardButton("✅ تم التنفيذ", callback_data=f"ordadm_done_{user_id}_{order_id}")],
        [InlineKeyboardButton("❌ رفض واسترداد المبلغ", callback_data=f"ordadm_refund_{user_id}_{order_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_admin_balance_keyboard(target_user_id):
    keyboard = [
        [InlineKeyboardButton("➕ إضافة رصيد", callback_data=f"bal_add_{target_user_id}")],
        [InlineKeyboardButton("➖ خصم رصيد", callback_data=f"bal_sub_{target_user_id}")],
        [InlineKeyboardButton("🔄 تعيين رصيد جديد", callback_data=f"bal_set_{target_user_id}")],
        [InlineKeyboardButton("🔁 تصفير الرصيد", callback_data=f"bal_zero_{target_user_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_two_buttons(back_callback, back_label="🔙 رجوع"):
    keyboard = [
        [InlineKeyboardButton(back_label, callback_data=back_callback)],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_insufficient_balance_keyboard(back_to_browse):
    keyboard = [
        [InlineKeyboardButton("💰 شحن محفظتي", callback_data="my_wallet")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=back_to_browse)],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_after_charge_keyboard(last_product_callback=None):
    keyboard = []
    if last_product_callback:
        keyboard.append([InlineKeyboardButton("🔙 العودة لإكمال الشراء", callback_data=last_product_callback)])
    # ✅ زر جديد: تصفح المنتجات (يعرض جميع الأقسام كالقائمة الرئيسية)
    keyboard.append([InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="products")])
    keyboard.append([InlineKeyboardButton("💰 العودة لمحفظتي", callback_data="my_wallet")])
    keyboard.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def build_fn_product_keyboard():
    keyboard = [
        [InlineKeyboardButton("📞 طلب المنتج - تواصل مع الإدارة", url="https://t.me/mero14store")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="sec_fortnite")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_section_back_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔙 رجوع", callback_data="products")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_cancel_deposit_keyboard(back_to="my_wallet"):
    keyboard = [
        [InlineKeyboardButton("❌ إلغاء والعودة", callback_data=f"cancel_deposit_to_{back_to}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_cancel_order_keyboard(back_to="fn_vbucks"):
    keyboard = [
        [InlineKeyboardButton("❌ إلغاء الطلب", callback_data=f"cancel_order_to_{back_to}")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_how_it_works_menu():
    keyboard = [
        [InlineKeyboardButton("💰 كيف أشحن رصيدي؟", callback_data="hiw_deposit")],
        [InlineKeyboardButton("🛒 كيف أشتري منتجاً؟", callback_data="hiw_purchase")],
        [InlineKeyboardButton("👤 كيف أتحقق من حسابي؟", callback_data="hiw_account")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ============================================================
# 📨 دوال الإشعارات
# ============================================================
async def notify_user(bot, user_id, message, reply_markup=None):
    try:
        await bot.send_message(chat_id=user_id, text=message,
                               parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"⚠️ فشل إرسال إشعار للمستخدم {user_id}: {e}")

async def notify_admin_transfer(bot, user, photo_file_id, method, amount):
    username = f"@{user.username}" if user.username else "لا يوجد يوزر"
    caption = (
        f"💰 *طلب شحن رصيد محفظة جديد*\n\n"
        f"👤 العميل: {user.first_name}\n🆔 الآيدي: `{user.id}`\n"
        f"🔗 اليوزر: {username}\n💳 طريقة الدفع: {method}\n"
        f"💵 المبلغ المطلوب: `{amount:,}` د.ع\n\n📋 راجع الإيصال ثم اتخذ قراراً:"
    )
    try:
        await bot.send_photo(chat_id=ADMIN_ID, photo=photo_file_id, caption=caption,
                             reply_markup=build_admin_keyboard(user.id, amount),
                             parse_mode="Markdown")
    except Exception as e:
        logger.error(f"❌ فشل إرسال إشعار التحويل: {e}")

async def notify_admin_order(bot, user, order_data):
    username = f"@{user.username}" if user.username else "لا يوجد يوزر"
    text = (
        f"🛒 *طلب شراء جديد!*\n\n"
        f"👤 العميل: {user.first_name}\n🆔 الآيدي: `{user.id}`\n"
        f"🔗 اليوزر: {username}\n\n━━━━━━━━━━━━━━━━━\n"
        f"💎 المنتج: *{order_data['product']}*\n"
        f"💰 السعر: *{order_data['price']:,} د.ع*\n"
        f"📧 الإيميل: `{order_data['email']}`\n"
        f"🔑 الرمز: `{order_data['code']}`\n"
        f"🎮 المنصة: *{order_data['platform']}*\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"💵 رصيد العميل بعد الخصم: *{order_data['remaining_balance']:,} د.ع*"
    )
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text,
                               reply_markup=build_admin_order_keyboard(user.id, order_data.get('order_id', 0)),
                               parse_mode="Markdown")
    except Exception as e:
        logger.error(f"❌ فشل إرسال إشعار الطلب: {e}")

# ============================================================
# 🔧 دوال مساعدة
# ============================================================
async def send_or_edit(update, text, reply_markup=None, parse_mode="Markdown"):
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)

def save_last_product(bot_data, user_id, callback_data):
    bot_data[f"last_product_{user_id}"] = callback_data

async def go_to_page(query, page_key, balance, user, context):
    if page_key == "main_menu":
        await query.edit_message_text(
            f"👋 أهلاً بك في *ميرو ستور* يا {user.first_name}!\n\n"
            f"💵 رصيدك الحالي: *{balance:,} د.ع*\n\n🛒 اختر من القائمة أدناه:",
            reply_markup=build_main_menu(), parse_mode="Markdown")
    elif page_key == "my_account":
        await query.edit_message_text(
            f"👤 *قسم حسابي*\n\n💵 رصيدك: *{balance:,} د.ع*\n\nاختر ما تريد:",
            reply_markup=build_account_menu(), parse_mode="Markdown")
    elif page_key == "my_wallet":
        await query.edit_message_text(
            f"💰 *محفظتك في ميرو ستور*\n\n💵 رصيدك: *{balance:,} د.ع*\n🪙 العملة: الدينار العراقي\n\n👇 اختر طريقة الشحن:",
            reply_markup=build_wallet_menu(), parse_mode="Markdown")
    elif page_key == "products":
        await query.edit_message_text(
            f"🛒 *أقسام المنتجات*\n\n💵 رصيدك: *{balance:,} د.ع*\n\nاختر القسم:",
            reply_markup=build_products_menu(), parse_mode="Markdown")
    elif page_key == "sec_fortnite":
        await query.edit_message_text(
            f"🎮 *قسم فورت نايت - Fortnite*\n\n💵 رصيدك: *{balance:,} د.ع*\n\n👇 اختر المنتج:",
            reply_markup=build_fortnite_menu(), parse_mode="Markdown")
    elif page_key == "fn_vbucks":
        await query.edit_message_text(
            f"💎 *عروض فيبوكس V-Bucks*\n\n💵 رصيدك: *{balance:,} د.ع*\n\n"
            f"👇 اختر الكمية (💎 الكمية | السعر بالدينار):",
            reply_markup=build_vbucks_menu(), parse_mode="Markdown")
    elif page_key == "trust":
        keyboard = [
            [InlineKeyboardButton("📸 شاهد إثباتات العملاء", url="https://t.me/mero14store_trust")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "⭐ *قسم الثقة والأمان*\n\nنحن في ميرو ستور نضمن لك:\n\n"
            "🔒 أعلى مستويات الأمان\n⚡ سرعة في التنفيذ\n💯 ضمان الاسترداد\n"
            "🎯 أسعار تنافسية\n📞 دعم على مدار الساعة\n\n👇 شاهد إثباتات عملائنا:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ============================================================
# 🔍 عرض معلومات مستخدم للأدمن
# ============================================================
async def admin_lookup_user(update, user_id_to_lookup):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, balance, created_at, updated_at FROM users WHERE user_id=?",
                  (user_id_to_lookup,))
        user_row = c.fetchone()
        if not user_row:
            await update.message.reply_text(
                f"❌ *لا يوجد مستخدم بهذا الآيدي:* `{user_id_to_lookup}`",
                parse_mode="Markdown")
            return
        uid, uname, fname, bal, created, updated = user_row
        uname_display = f"@{uname}" if uname else "لا يوجد"
        c.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM deposits WHERE user_id=? AND status='approved'",
                  (user_id_to_lookup,))
        dep_count, dep_total = c.fetchone()
        c.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM purchases WHERE user_id=?",
                  (user_id_to_lookup,))
        pur_count, pur_total = c.fetchone()
        c.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id_to_lookup,))
        ord_count = c.fetchone()[0]
        c.execute("""
            SELECT method, amount, status, created_at
            FROM deposits WHERE user_id=?
            ORDER BY created_at DESC, id DESC LIMIT 5
        """, (user_id_to_lookup,))
        last_deposits = c.fetchall()
        c.execute("""
            SELECT item_name, price, created_at
            FROM purchases WHERE user_id=?
            ORDER BY created_at DESC, id DESC LIMIT 5
        """, (user_id_to_lookup,))
        last_purchases = c.fetchall()

    icons = {"approved": "✅", "rejected": "❌", "pending": "⏳"}
    text = (
        f"🔍 *معلومات المستخدم:*\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"👤 الاسم: *{fname}*\n"
        f"🆔 الآيدي: `{uid}`\n"
        f"🔗 اليوزر: {uname_display}\n"
        f"💵 الرصيد: *{bal:,} د.ع*\n"
        f"📅 تاريخ التسجيل: {created}\n"
        f"🕐 آخر تحديث: {updated}\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *الإحصائيات:*\n"
        f"💰 الشحنات: *{dep_count}* عملية | مجموع: *{dep_total:,} د.ع*\n"
        f"🛍️ المشتريات: *{pur_count}* عملية | مجموع: *{pur_total:,} د.ع*\n"
        f"📦 الطلبات: *{ord_count}* طلب\n"
    )
    if last_deposits:
        text += f"\n━━━━━━━━━━━━━━━━━\n💰 *آخر 5 شحنات:*\n"
        for i, d in enumerate(last_deposits, 1):
            text += f"{i}. {icons.get(d[2],'❓')} {d[0]} | {d[1]:,} د.ع | {d[3]}\n"
    if last_purchases:
        text += f"\n━━━━━━━━━━━━━━━━━\n🛍️ *آخر 5 مشتريات:*\n"
        for i, p in enumerate(last_purchases, 1):
            text += f"{i}. 📦 {p[0]} | {p[1]:,} د.ع | {p[2]}\n"
    if not last_deposits and not last_purchases:
        text += "\n📭 لا توجد عمليات سابقة لهذا المستخدم."
    text += "\n\n━━━━━━━━━━━━━━━━━\n🎛️ *التحكم بالرصيد:*"
    await update.message.reply_text(text,
        reply_markup=build_admin_balance_keyboard(user_id_to_lookup),
        parse_mode="Markdown")

# ============================================================
# 🏠 القائمة الرئيسية
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.callback_query.from_user if update.callback_query else update.message.from_user
    ensure_user_exists(user.id, user.username, user.first_name)
    balance = get_balance(user.id)
    text = (
        f"👋 أهلاً بك في *ميرو ستور* يا {user.first_name}!\n\n"
        f"💵 رصيدك الحالي: *{balance:,} د.ع*\n\n"
        f"🛒 اختر من القائمة أدناه:"
    )
    await send_or_edit(update, text, build_main_menu())

# ============================================================
# ❌ معالج إلغاء الشحن
# ============================================================
async def cancel_deposit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    ensure_user_exists(user.id, user.username, user.first_name)
    destination = query.data.replace("cancel_deposit_to_", "")
    for key in ['step', 'setup_method', 'setup_account', 'transferred_amount',
                'waiting_for_proof', 'is_card', 'is_card_balance']:
        context.user_data.pop(key, None)
    balance = get_balance(user.id)
    pages_map = {
        "my_wallet": (
            f"💰 *محفظتك في ميرو ستور*\n\n💵 رصيدك: *{balance:,} د.ع*\n🪙 العملة: الدينار العراقي\n\n👇 اختر طريقة الشحن:",
            build_wallet_menu()
        ),
    }
    if destination in pages_map:
        text, markup = pages_map[destination]
        await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await query.edit_message_text(
            f"💰 *محفظتك في ميرو ستور*\n\n💵 رصيدك: *{balance:,} د.ع*\n\n👇 اختر طريقة الشحن:",
            reply_markup=build_wallet_menu(), parse_mode="Markdown")

# ============================================================
# ❌ معالج إلغاء الطلب
# ============================================================
async def cancel_order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    ensure_user_exists(user.id, user.username, user.first_name)
    destination = query.data.replace("cancel_order_to_", "")
    for key in ['order_step', 'order_vbucks', 'order_price', 'order_email',
                'order_code', 'order_platform']:
        context.user_data.pop(key, None)
    balance = get_balance(user.id)
    await go_to_page(query, destination, balance, user, context)

# ============================================================
# 🖱️ معالج الأزرار
# ============================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user    = query.from_user
    data    = query.data
    user_id = user.id

    ensure_user_exists(user_id, user.username, user.first_name)
    balance = get_balance(user_id)

    if not data.startswith("adm_") and not data.startswith("ordadm_") and not data.startswith("bal_") and is_spam(user_id):
        return

    # =========================================================
    # 🎛️ أدمن: التحكم بالرصيد
    # =========================================================
    if data.startswith("bal_"):
        if user_id != ADMIN_ID:
            await query.answer("🚫 غير مصرح!", show_alert=True)
            return
        parts = data.split("_")
        action = parts[1]
        target = int(parts[2])
        target_balance = get_balance(target)

        if action == "zero":
            old_balance = target_balance
            set_balance(target, 0)
            await query.edit_message_text(
                f"🔁 *تم تصفير رصيد المستخدم* `{target}`\n\n"
                f"💰 الرصيد السابق: *{old_balance:,} د.ع*\n"
                f"💵 الرصيد الآن: *0 د.ع*",
                parse_mode="Markdown")
            await notify_user(context.bot, target,
                f"⚠️ *تنبيه من الإدارة:*\n\n🔁 تم تعديل رصيدك إلى: *0 د.ع*")
            logger.info(f"🎛️ الأدمن صفّر رصيد {target} (كان {old_balance:,})")
            return

        action_names = {"add": "إضافة", "sub": "خصم", "set": "تعيين"}
        action_icons = {"add": "➕", "sub": "➖", "set": "🔄"}
        context.user_data['bal_action'] = action
        context.user_data['bal_target'] = target
        await query.edit_message_text(
            f"{action_icons[action]} *{action_names[action]} رصيد للمستخدم* `{target}`\n\n"
            f"💵 رصيده الحالي: *{target_balance:,} د.ع*\n\n"
            f"✍️ اكتب المبلغ كأرقام فقط:\n📝 مثال: `10000`",
            parse_mode="Markdown")
        return

    # =========================================================
    # 🔴 لوحة الأدمن - شحن الرصيد
    # =========================================================
    if data.startswith("adm_"):
        if user_id != ADMIN_ID:
            await query.answer("🚫 غير مصرح!", show_alert=True)
            return
        parts = data.split("_"); action = parts[1]; target = int(parts[2])

        if action == "approve":
            amount = int(parts[3])
            method = context.bot_data.get(f"method_{target}", "تحويل مالي")
            new_balance = update_balance(target, amount)
            add_deposit_record(target, method, amount, "approved")
            await query.edit_message_caption(
                f"✅ تمت الموافقة وشحن `{target}` بـ {amount:,} د.ع\n💰 رصيده: {new_balance:,} د.ع")
            last_product = context.bot_data.get(f"last_product_{target}", None)
            buttons = build_after_charge_keyboard(last_product)
            await notify_user(context.bot, target,
                f"🎉 *تم تأكيد شحن محفظتك!*\n\n💰 المضاف: *{amount:,} د.ع*\n💵 رصيدك الآن: *{new_balance:,} د.ع*\n\nشكراً لثقتك بميرو ستور! 🛒",
                reply_markup=buttons)

        elif action == "edit":
            context.user_data['admin_editing_for'] = target
            await query.edit_message_caption(
                f"✏️ *تعديل مبلغ الشحن للعميل* `{target}`\n\nاكتب المبلغ الجديد كأرقام:\n📝 مثال: `15000`")

        elif action == "reject":
            add_deposit_record(target, "غير محدد", 0, "rejected")
            await query.edit_message_caption(f"❌ تم رفض طلب `{target}`")
            last_product = context.bot_data.get(f"last_product_{target}", None)
            buttons = build_after_charge_keyboard(last_product)
            await notify_user(context.bot, target,
                "❌ *نعتذر،* تم رفض طلب شحن المحفظة من الإدارة.\n\n📞 للاستفسار تواصل مع الدعم.",
                reply_markup=buttons)
        return

    # =========================================================
    # 🔴 لوحة الأدمن - الطلبات
    # =========================================================
    if data.startswith("ordadm_"):
        if user_id != ADMIN_ID:
            await query.answer("🚫 غير مصرح!", show_alert=True)
            return
        parts = data.split("_"); action = parts[1]; target = int(parts[2]); order_id = int(parts[3])

        if action == "done":
            await query.edit_message_text(
                query.message.text + "\n\n✅ *تم تنفيذ الطلب بنجاح!*", parse_mode="Markdown")
            await notify_user(context.bot, target,
                f"✅ *تم تنفيذ طلبك رقم #{order_id} بنجاح!*\n\n🎮 استمتع بالمنتج!\nشكراً لثقتك بميرو ستور! 🛒",
                reply_markup=build_two_buttons("products", "🛒 تصفح المنتجات"))

        elif action == "refund":
            with get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT price, product FROM orders WHERE id=?", (order_id,))
                row = c.fetchone()
                if row:
                    refund_amount, product_name = row[0], row[1]
                    new_balance = update_balance(target, refund_amount)
                    await query.edit_message_text(
                        query.message.text + f"\n\n❌ *رفض + استرداد {refund_amount:,} د.ع*", parse_mode="Markdown")
                    await notify_user(context.bot, target,
                        f"❌ *تم رفض طلبك: {product_name}*\n\n💰 تم استرداد: *{refund_amount:,} د.ع*\n💵 رصيدك: *{new_balance:,} د.ع*",
                        reply_markup=build_two_buttons("products", "🛒 تصفح المنتجات"))
        return

    # =========================================================
    # 📦 أقسام المنتجات
    # =========================================================
    if data.startswith("sec_"):
        sec_key = "_".join(data.split("_")[1:])
        if sec_key == "fortnite":
            await query.edit_message_text(
                f"🎮 *قسم فورت نايت - Fortnite*\n\n💵 رصيدك: *{balance:,} د.ع*\n\n👇 اختر المنتج:",
                reply_markup=build_fortnite_menu(), parse_mode="Markdown")
            return

        sections = {
            "mob_games": "شحن العاب الموبايل 📱", "general_serv": "خدمات عامة 🛠️",
            "cards": "بطاقات شحن الكترونية 💳", "subs": "اشتراكات المشاهدة والالعاب 🎬",
            "xbox": "العاب الاكسبوكس 🟢", "social_serv": "خدمات التواصل الاجتماعي 📈",
            "multi_games": "العاب منوعة (بلي-PC-Xbox) 🕹️", "social_chat": "شحن برامج التواصل 💬"
        }
        sec_title = sections.get(sec_key, "القسم المختار")
        await query.edit_message_text(
            f"📦 *قسم: {sec_title}*\n\n💵 رصيدك: *{balance:,} د.ع*\n\n⚙️ قيد التحديث حالياً.\nترقبوا الإطلاق! 🚀",
            reply_markup=build_section_back_keyboard(), parse_mode="Markdown")
        return

    # =========================================================
    # 🎮 منتجات فورت نايت
    # =========================================================
    if data.startswith("fn_"):
        if data == "fn_vbucks":
            await query.edit_message_text(
                f"💎 *عروض فيبوكس V-Bucks*\n\n💵 رصيدك: *{balance:,} د.ع*\n\n"
                f"👇 اختر الكمية (💎 الكمية | السعر بالدينار):",
                reply_markup=build_vbucks_menu(), parse_mode="Markdown")
            return

        fn_products = {
            "fn_itemshop": "🛍️ *حزم الايتم شوب*\n\n✅ نوفر لك أي حزمة في الايتم شوب.\n🎯 أرسل اسم أو صورة الحزمة.\n\n💰 الأسعار حسب الفيبوكس.\n\n📌 للطلب تواصل مع الإدارة.",
            "fn_rare": "🌟 *حزم نادرة غير موجودة بالشوب*\n\n🏆 حزم حصرية ونادرة!\n⚡ سكنات وأغراض قديمة.\n\n💰 الأسعار حسب الندرة.\n\n📌 للطلب تواصل مع الإدارة.",
            "fn_crew": "👥 *كرو فورت نايت*\n\n📦 الاشتراك يشمل:\n  • سكن حصري شهري 🎭\n  • 1,000 V-Bucks 💎\n  • بتل باس 🏅\n\n💰 *20,000 د.ع / شهر*\n\n📌 للطلب تواصل مع الإدارة.",
            "fn_gifts": "🎁 *هدايا ايتم شوب وبتل باس*\n\n🎮 نهديك أو نهدي صديقك:\n  • أي غرض من الايتم شوب 🛍️\n  • بتل باس 🏅\n  • بتل باس + 25 مستوى ⭐\n\n💰 الأسعار حسب الغرض.\n\n📌 للطلب تواصل مع الإدارة."
        }
        product_text = fn_products.get(data)
        if product_text:
            await query.edit_message_text(
                f"{product_text}\n\n💵 رصيدك: *{balance:,} د.ع*",
                reply_markup=build_fn_product_keyboard(), parse_mode="Markdown")
        return

    # =========================================================
    # 💎 اختيار عرض فيبوكس
    # =========================================================
    if data.startswith("vb_"):
        vbucks_amount = int(data.replace("vb_", ""))
        price = get_vbucks_price(vbucks_amount)
        if price is None:
            await query.edit_message_text("❌ عرض غير موجود.",
                reply_markup=build_two_buttons("fn_vbucks", "🔙 رجوع"), parse_mode="Markdown")
            return

        save_last_product(context.bot_data, user_id, data)

        if balance < price:
            shortage = price - balance
            await query.edit_message_text(
                f"❌ *رصيدك غير كافٍ لإتمام هذا الطلب!*\n\n"
                f"💎 المنتج: *{vbucks_amount:,} V-Bucks*\n"
                f"💰 السعر: *{price:,} د.ع*\n"
                f"💵 رصيدك الحالي: *{balance:,} د.ع*\n"
                f"📉 ينقصك: *{shortage:,} د.ع*\n\n"
                f"👇 يرجى شحن محفظتك أولاً:",
                reply_markup=build_insufficient_balance_keyboard("fn_vbucks"),
                parse_mode="Markdown")
            return

        context.user_data['order_cancel_destination'] = 'fn_vbucks'
        context.user_data['order_step']   = 'waiting_email'
        context.user_data['order_vbucks'] = vbucks_amount
        context.user_data['order_price']  = price

        await query.edit_message_text(
            f"✅ *رصيدك كافٍ! لنبدأ بإتمام الطلب*\n\n"
            f"💎 المنتج: *{vbucks_amount:,} V-Bucks*\n💰 السعر: *{price:,} د.ع*\n💵 رصيدك: *{balance:,} د.ع*\n\n"
            f"━━━━━━━━━━━━━━━━━\n📧 *الخطوة 1 من 3:* أرسل إيميل حسابك\n\nاكتب الإيميل المرتبط بحساب اللعبة:",
            reply_markup=build_cancel_order_keyboard("fn_vbucks"),
            parse_mode="Markdown")
        return

    # =========================================================
    # 🎮 اختيار المنصة
    # =========================================================
    if data.startswith("plt_"):
        platforms = {"plt_epic": "Epic Games 🎮", "plt_xbox": "Xbox 🟢",
                     "plt_ps": "PlayStation 🔵", "plt_google": "Google Play 🟡"}
        platform = platforms.get(data, "غير محدد")
        context.user_data['order_platform'] = platform
        vbucks = context.user_data.get('order_vbucks', 0)
        price  = context.user_data.get('order_price', 0)
        email  = context.user_data.get('order_email', '')
        code   = context.user_data.get('order_code', '')

        await query.edit_message_text(
            f"📋 *ملخص طلبك قبل التأكيد:*\n\n━━━━━━━━━━━━━━━━━\n"
            f"💎 المنتج: *{vbucks:,} V-Bucks*\n💰 السعر: *{price:,} د.ع*\n"
            f"📧 الإيميل: `{email}`\n🔑 الرمز: `{code}`\n🎮 المنصة: *{platform}*\n"
            f"━━━━━━━━━━━━━━━━━\n\n💵 رصيدك: *{balance:,} د.ع*\n"
            f"💵 بعد الخصم: *{balance - price:,} د.ع*\n\n⚠️ تأكد من البيانات ثم اضغط تأكيد:",
            reply_markup=build_confirm_order_keyboard(), parse_mode="Markdown")
        return

    # =========================================================
    # ✅ تأكيد الطلب
    # =========================================================
    if data == "confirm_order":
        vbucks   = context.user_data.get('order_vbucks', 0)
        price    = context.user_data.get('order_price', 0)
        email    = context.user_data.get('order_email', '')
        code     = context.user_data.get('order_code', '')
        platform = context.user_data.get('order_platform', '')

        current_balance = get_balance(user_id)
        if current_balance < price:
            last_product = context.bot_data.get(f"last_product_{user_id}", "fn_vbucks")
            await query.edit_message_text(
                "❌ *رصيدك لم يعد كافياً!*\n\nيرجى شحن محفظتك والمحاولة مجدداً.",
                reply_markup=build_insufficient_balance_keyboard(last_product),
                parse_mode="Markdown")
            context.user_data.clear()
            return

        new_balance  = update_balance(user_id, -price)
        product_name = f"{vbucks:,} V-Bucks"
        add_purchase_record(user_id, product_name, price)
        add_order_record(user_id, product_name, price, email, code, platform)

        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT MAX(id) FROM orders WHERE user_id=?", (user_id,))
            order_id = c.fetchone()[0] or 0

        await notify_admin_order(context.bot, user, {
            'product': product_name, 'price': price, 'email': email,
            'code': code, 'platform': platform,
            'remaining_balance': new_balance, 'order_id': order_id
        })

        keyboard = [
            [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="products")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            f"🎉 *تم إرسال طلبك بنجاح!*\n\n━━━━━━━━━━━━━━━━━\n"
            f"🔢 رقم الطلب: *#{order_id}*\n💎 المنتج: *{product_name}*\n"
            f"💰 المخصوم: *{price:,} د.ع*\n🎮 المنصة: *{platform}*\n"
            f"━━━━━━━━━━━━━━━━━\n\n💵 رصيدك المتبقي: *{new_balance:,} د.ع*\n\n"
            f"⏳ سيتم تنفيذ طلبك قريباً.\nسيتم إشعارك فور التنفيذ! 🔔",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        context.bot_data.pop(f"last_product_{user_id}", None)
        context.user_data.clear()
        logger.info(f"🛒 {user_id} اشترى {product_name} بـ {price:,} د.ع")
        return

    # =========================================================
    # 🎯 كيف يعمل البوت
    # =========================================================
    if data == "how_it_works":
        await query.edit_message_text(
            "🎯 *كيف يعمل بوت ميرو ستور؟*\n\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "📌 *البوت يعمل بطريقة بسيطة جداً:*\n\n"
            "1️⃣ *تسجيل الدخول:*\n"
            "   • فقط اضغط /start وسيتم تسجيلك تلقائياً\n"
            "   • لا تحتاج كلمة مرور أو أي معلومات معقدة ✅\n\n"
            "2️⃣ *شحن الرصيد:*\n"
            "   • اضغط على 💰 شحن رصيدي\n"
            "   • اختر طريقة الدفع المناسبة لك\n"
            "   • حوّل المبلغ وأرسل صورة الإيصال\n"
            "   • انتظر موافقة الإدارة (1-15 دقيقة) ⏳\n"
            "   • سيتم إشعارك فور إضافة الرصيد 🔔\n\n"
            "3️⃣ *شراء المنتجات:*\n"
            "   • اضغط على 🛒 عرض جميع المنتجات\n"
            "   • اختر المنتج الذي تريده\n"
            "   • أدخل معلومات حسابك (إيميل + رمز + منصة)\n"
            "   • تأكد من البيانات واضغط تأكيد ✅\n"
            "   • سيتم تنفيذ طلبك من الإدارة قريباً 🎮\n\n"
            "4️⃣ *متابعة الطلبات:*\n"
            "   • يمكنك مراجعة سجل مشترياتك من 👤 حسابي\n"
            "   • ستصلك رسالة فور تنفيذ الطلب 📨\n\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "💡 *نصائح مهمة:*\n"
            "• 🔒 لا تشارك معلومات حسابك مع أحد\n"
            "• 📸 تأكد أن صورة الإيصال واضحة\n"
            "• ⏰ أوقات الخدمة: على مدار الساعة\n"
            "• 💬 للمساعدة تواصل مع الدعم",
            reply_markup=build_how_it_works_menu(),
            parse_mode="Markdown")
        return

    if data == "hiw_deposit":
        await query.edit_message_text(
            "💰 *كيف أشحن رصيدي بالتفصيل؟*\n\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "📋 *الخطوات التفصيلية:*\n\n"
            "✅ *الخطوة 1:* اضغط على 💰 شحن رصيدي\n\n"
            "✅ *الخطوة 2:* اختر طريقة الدفع:\n"
            "   📱 آسيا كارت / تحويل\n"
            "   📱 زين (اثير) كارت / تحويل\n"
            "   💸 زين كاش\n"
            "   💳 ماستر كارد رافدين\n"
            "   🔑 سوبر كي\n"
            "   🏦 FIB\n\n"
            "✅ *الخطوة 3:* حوّل المبلغ على الرقم المعطى\n\n"
            "✅ *الخطوة 4:* اكتب المبلغ كأرقام فقط\n"
            "   📝 مثال: `10000`\n\n"
            "✅ *الخطوة 5:* أرسل صورة إيصال التحويل\n"
            "   📸 يجب أن تظهر: الرقم + المبلغ + التاريخ\n\n"
            "✅ *الخطوة 6:* انتظر موافقة الإدارة\n"
            "   ⏱️ المدة: من 1 إلى 15 دقيقة\n\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"⚠️ الحد الأدنى: *{MIN_DEPOSIT:,} د.ع*\n"
            f"⚠️ الحد الأقصى: *{MAX_DEPOSIT:,} د.ع*",
            reply_markup=build_two_buttons("how_it_works", "🔙 رجوع"),
            parse_mode="Markdown")
        return

    if data == "hiw_purchase":
        await query.edit_message_text(
            "🛒 *كيف أشتري منتجاً بالتفصيل؟*\n\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "📋 *الخطوات التفصيلية:*\n\n"
            "✅ *الخطوة 1:* تأكد أن رصيدك كافٍ 💵\n\n"
            "✅ *الخطوة 2:* اضغط على 🛒 عرض جميع المنتجات\n\n"
            "✅ *الخطوة 3:* اختر القسم المناسب\n"
            "   🎮 فورت نايت | 📱 موبايل | 🟢 Xbox | وغيرها\n\n"
            "✅ *الخطوة 4:* اختر المنتج وتحقق من السعر\n\n"
            "✅ *الخطوة 5:* أدخل معلومات حسابك:\n"
            "   📧 الإيميل المرتبط بالحساب\n"
            "   🔑 كلمة المرور أو رمز التحقق\n"
            "   🎮 المنصة (Epic / Xbox / PS / Google)\n\n"
            "✅ *الخطوة 6:* راجع ملخص الطلب ثم اضغط تأكيد\n\n"
            "✅ *الخطوة 7:* انتظر تنفيذ الطلب من الإدارة\n"
            "   📨 ستصلك رسالة فور التنفيذ!\n\n"
            "━━━━━━━━━━━━━━━━━\n"
            "⚠️ *تنبيه:* سيتم خصم المبلغ فور التأكيد\n"
            "💯 في حالة رفض الطلب يتم استرداد المبلغ كاملاً",
            reply_markup=build_two_buttons("how_it_works", "🔙 رجوع"),
            parse_mode="Markdown")
        return

    if data == "hiw_account":
        await query.edit_message_text(
            "👤 *كيف أتحقق من حسابي؟*\n\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "📋 *من قسم حسابي يمكنك:*\n\n"
            "📝 *معلوماتي:*\n"
            "   • اسمك ومعرفك في تيليغرام\n"
            "   • رصيدك الحالي بالدينار العراقي\n\n"
            "🛍️ *سجل المشتريات:*\n"
            "   • قائمة بكل ما اشتريته\n"
            "   • اسم المنتج + السعر + التاريخ\n\n"
            "🔄 *سجل الشحنات:*\n"
            "   • جميع عمليات شحن رصيدك\n"
            "   • طريقة الدفع + المبلغ + الحالة\n"
            "   • ✅ موافق | ❌ مرفوض | ⏳ قيد المراجعة\n\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "💡 *نصيحة:* احتفظ برقم طلبك عند التواصل مع الدعم",
            reply_markup=build_two_buttons("how_it_works", "🔙 رجوع"),
            parse_mode="Markdown")
        return

    # =========================================================
    # 📋 القوائم الرئيسية
    # =========================================================
    if data == "main_menu":
        await start(update, context)

    elif data == "my_account":
        await query.edit_message_text(
            f"👤 *قسم حسابي*\n\n💵 رصيدك: *{balance:,} د.ع*\n\nاختر ما تريد:",
            reply_markup=build_account_menu(), parse_mode="Markdown")

    elif data == "info_clicked":
        username = f"@{user.username}" if user.username else "لا يوجد يوزر"
        await query.edit_message_text(
            f"📋 *معلومات حسابك:*\n\n👤 الاسم: *{user.first_name}*\n🆔 الآيدي: `{user_id}`\n"
            f"🔗 اليوزر: {username}\n💵 الرصيد: *{balance:,} د.ع*\n✨ عميل نشط في ميرو ستور",
            reply_markup=build_two_buttons("my_account", "🔙 رجوع"), parse_mode="Markdown")

    elif data == "purchases_clicked":
        records = get_purchase_history(user_id)
        if not records:
            text = "🛍️ *سجل مشترياتك:*\n\n❌ لا توجد مشتريات سابقة."
        else:
            lines = []
            for i, r in enumerate(records, 1):
                lines.append(f"{i}. 📦 {r[0]} | {r[1]:,} د.ع | 🕐 {r[2]}")
            text = "🛍️ *سجل مشترياتك (من الأقدم للأحدث):*\n\n" + "\n".join(lines)
        await query.edit_message_text(text,
            reply_markup=build_two_buttons("my_account", "🔙 رجوع"), parse_mode="Markdown")

    elif data == "deposit_clicked":
        records = get_deposit_history(user_id)
        icons = {"approved": "✅", "rejected": "❌", "pending": "⏳"}
        if not records:
            text = f"🔄 *سجل الشحنات:*\n\n❌ لا توجد عمليات شحن.\n\n💵 رصيدك: *{balance:,} د.ع*"
        else:
            lines = []
            for i, r in enumerate(records, 1):
                lines.append(f"{i}. {icons.get(r[2],'❓')} {r[0]} | {r[1]:,} د.ع | {r[3]}")
            text = "🔄 *سجل الشحنات (من الأقدم للأحدث):*\n\n" + "\n".join(lines) + f"\n\n💵 رصيدك: *{balance:,} د.ع*"
        await query.edit_message_text(text,
            reply_markup=build_two_buttons("my_account", "🔙 رجوع"), parse_mode="Markdown")

    elif data == "my_wallet":
        await query.edit_message_text(
            f"💰 *محفظتك في ميرو ستور*\n\n💵 رصيدك: *{balance:,} د.ع*\n🪙 العملة: الدينار العراقي\n\n👇 اختر طريقة الشحن:",
            reply_markup=build_wallet_menu(), parse_mode="Markdown")

    # =========================================================
    # 💳 طرق الشحن بالرصيد (آسيا وزين) - مع شرط المضاعفات
    # =========================================================
    elif data in ["w_asia", "w_zain"]:
        methods_info = {
            "w_asia": ("رصيد اسيا", "`07719835446`", "90%", "9,000"),
            "w_zain": ("رصيد اثير (زين)", "`07810836285`", "95%", "9,500"),
        }
        method_title, account_num, percent, example_result = methods_info[data]
        context.user_data['setup_method']    = method_title
        context.user_data['setup_account']   = account_num
        context.user_data['step']            = 'waiting_amount'
        context.user_data['is_card_balance'] = True  # 🔑 علامة لتفعيل شرط المضاعفات

        await query.edit_message_text(
            f"💸 *الشحن عبر {method_title}*\n\n"
            f"اذا عندك كارت ارسل صورته واذا تحويل حول عل رقم\n\n"
            f"📌 رقم الهاتف: {account_num}\n"
            f"💡 اضغط على الرقم لنسخه\n\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✍️ *الخطوة 1 من 2:* كم المبلغ الذي حوّلته؟\n\n"
            f"⚠️ *اكتب المبلغ كأرقام فقط:*\n"
            f"📝 مثال: `10000`\n\n"
            f"⚠️ الحد الأدنى: {MIN_DEPOSIT:,} د.ع\n\n"
            f"🔴 *علماً ان نسبة شحن المحفظة بـ {method_title} هي {percent}*\n"
            f"يعني 10 تنشحن {example_result} بالمحفظة\n\n"
            f"⚠️ *يجب أن يكون المبلغ من مضاعفات الـ 1,000*\n"
            f"📝 مثال: `1000` أو `2000` أو `5000` أو `10000`",
            reply_markup=build_cancel_deposit_keyboard("my_wallet"),
            parse_mode="Markdown")

    elif data.startswith("w_"):
        methods = {
            "w_zain_cash": ("زين كاش", "`07810836285`"),
            "w_rafidain":  ("ماستر كارد رافدين", "`7115189131`"),
            "w_super_key": ("سوبر كي", "`7719835446`"),
            "w_fib":       ("بنك FIB", "`7719835446`")
        }
        method_title, account_num = methods.get(data, ("طريقة دفع", "غير محدد"))
        context.user_data['setup_method']    = method_title
        context.user_data['setup_account']   = account_num
        context.user_data['step']            = 'waiting_amount'
        context.user_data['is_card_balance'] = False  # ❌ لا يحتاج شرط المضاعفات

        await query.edit_message_text(
            f"💸 *الشحن عبر {method_title}*\n\nحول على \n"
            f"📌 رقم الحساب: {account_num}\n"
            f"💡 اضغط على الرقم لنسخه\n\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✍️ *الخطوة 1 من 2:* كم المبلغ الذي حوّلته؟\n\n"
            f"⚠️ *اكتب المبلغ كأرقام فقط:*\n"
            f"📝 مثال: `10000`\n\n"
            f"⚠️ الحد الأدنى: {MIN_DEPOSIT:,} د.ع",
            reply_markup=build_cancel_deposit_keyboard("my_wallet"),
            parse_mode="Markdown")

    elif data == "products":
        await query.edit_message_text(
            f"🛒 *أقسام المنتجات*\n\n💵 رصيدك: *{balance:,} د.ع*\n\nاختر القسم:",
            reply_markup=build_products_menu(), parse_mode="Markdown")

    elif data == "trust":
        keyboard = [
            [InlineKeyboardButton("📸 شاهد إثباتات العملاء", url="https://t.me/mero14store_trust")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "⭐ *قسم الثقة والأمان*\n\nنحن في ميرو ستور نضمن لك:\n\n"
            "🔒 أعلى مستويات الأمان\n⚡ سرعة في التنفيذ\n💯 ضمان الاسترداد\n"
            "🎯 أسعار تنافسية\n📞 دعم على مدار الساعة\n\n👇 شاهد إثباتات عملائنا:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ============================================================
# 💬 معالج النصوص
# ============================================================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text_in = update.message.text.strip()

    # ═══════════════════════════════════════════
    # 🎛️ الأدمن: تنفيذ تعديل الرصيد
    # ═══════════════════════════════════════════
    if user_id == ADMIN_ID and 'bal_action' in context.user_data:
        action = context.user_data['bal_action']
        target = context.user_data['bal_target']

        if not text_in.isdigit():
            await update.message.reply_text(
                "❌ *يرجى كتابة المبلغ كأرقام فقط!*\n📝 مثال: `10000`",
                parse_mode="Markdown")
            return

        amount = int(text_in)
        old_balance = get_balance(target)

        if action == "add":
            new_balance = update_balance(target, amount)
            add_deposit_record(target, "إضافة يدوية (أدمن)", amount, "approved")
            await update.message.reply_text(
                f"✅ *تم إضافة الرصيد بنجاح!*\n\n"
                f"🆔 المستخدم: `{target}`\n"
                f"💰 الرصيد السابق: *{old_balance:,} د.ع*\n"
                f"➕ المضاف: *{amount:,} د.ع*\n"
                f"💵 الرصيد الآن: *{new_balance:,} د.ع*",
                parse_mode="Markdown")
            await notify_user(context.bot, target,
                f"🎉 *تم إضافة رصيد لمحفظتك!*\n\n➕ المضاف: *{amount:,} د.ع*\n💵 رصيدك الآن: *{new_balance:,} د.ع*")
            logger.info(f"🎛️ الأدمن أضاف {amount:,} لـ {target}")

        elif action == "sub":
            if amount > old_balance:
                await update.message.reply_text(
                    f"❌ *لا يمكن خصم أكثر من الرصيد!*\n\n"
                    f"💵 رصيده الحالي: *{old_balance:,} د.ع*\n"
                    f"➖ المطلوب خصمه: *{amount:,} د.ع*\n\n"
                    f"✍️ اكتب مبلغ أقل أو أرسل `0` للإلغاء:",
                    parse_mode="Markdown")
                return
            new_balance = update_balance(target, -amount)
            await update.message.reply_text(
                f"✅ *تم خصم الرصيد بنجاح!*\n\n"
                f"🆔 المستخدم: `{target}`\n"
                f"💰 الرصيد السابق: *{old_balance:,} د.ع*\n"
                f"➖ المخصوم: *{amount:,} د.ع*\n"
                f"💵 الرصيد الآن: *{new_balance:,} د.ع*",
                parse_mode="Markdown")
            await notify_user(context.bot, target,
                f"⚠️ *تنبيه من الإدارة:*\n\n➖ تم خصم: *{amount:,} د.ع*\n💵 رصيدك الآن: *{new_balance:,} د.ع*")
            logger.info(f"🎛️ الأدمن خصم {amount:,} من {target}")

        elif action == "set":
            new_balance = set_balance(target, amount)
            await update.message.reply_text(
                f"✅ *تم تعيين الرصيد بنجاح!*\n\n"
                f"🆔 المستخدم: `{target}`\n"
                f"💰 الرصيد السابق: *{old_balance:,} د.ع*\n"
                f"🔄 الرصيد الجديد: *{new_balance:,} د.ع*",
                parse_mode="Markdown")
            await notify_user(context.bot, target,
                f"⚠️ *تنبيه من الإدارة:*\n\n🔄 تم تعديل رصيدك إلى: *{new_balance:,} د.ع*")
            logger.info(f"🎛️ الأدمن عيّن رصيد {target} إلى {amount:,}")

        context.user_data.pop('bal_action', None)
        context.user_data.pop('bal_target', None)
        return

    # ═══════════════════════════════════════════
    # 🔍 الأدمن: البحث عن مستخدم بالآيدي
    # ═══════════════════════════════════════════
    if user_id == ADMIN_ID and text_in.isdigit() and len(text_in) >= 5:
        if not context.user_data.get('step') and not context.user_data.get('admin_editing_for'):
            await admin_lookup_user(update, int(text_in))
            return

    step       = context.user_data.get('step')
    order_step = context.user_data.get('order_step')

    # أدمن: تعديل المبلغ
    if user_id == ADMIN_ID and 'admin_editing_for' in context.user_data:
        target = context.user_data['admin_editing_for']
        valid, result = validate_amount(text_in)
        if not valid:
            await update.message.reply_text(result, parse_mode="Markdown")
            return
        method = context.bot_data.get(f"method_{target}", "تحويل مالي")
        new_balance = update_balance(target, result)
        add_deposit_record(target, method, result, "approved")
        await update.message.reply_text(
            f"✅ *تم شحن* `{target}` *بنجاح!*\n\n💰 المبلغ: *{result:,} د.ع*\n💵 رصيده: *{new_balance:,} د.ع*",
            parse_mode="Markdown")
        last_product = context.bot_data.get(f"last_product_{target}", None)
        buttons = build_after_charge_keyboard(last_product)
        await notify_user(context.bot, target,
            f"⚠️ *تنبيه من الإدارة:*\n\nالمبلغ الفعلي: *{result:,} د.ع*\n🎉 تم شحن محفظتك!\n💵 رصيدك: *{new_balance:,} د.ع*",
            reply_markup=buttons)
        del context.user_data['admin_editing_for']
        return

    # خطوة 1 طلب: الإيميل
    if order_step == 'waiting_email':
        if '@' not in text_in or '.' not in text_in:
            await update.message.reply_text(
                "❌ *يرجى إدخال إيميل صحيح!*\n\n📝 مثال: `example@gmail.com`",
                reply_markup=build_cancel_order_keyboard("fn_vbucks"), parse_mode="Markdown")
            return
        context.user_data['order_email'] = text_in
        context.user_data['order_step'] = 'waiting_code'
        await update.message.reply_text(
            f"✅ *تم تسجيل الإيميل:* `{text_in}`\n\n━━━━━━━━━━━━━━━━━\n"
            f"🔑 *الخطوة 2 من 3:* أرسل رمز التحقق أو كلمة السر\n\nاكتب الرمز:",
            reply_markup=build_cancel_order_keyboard("fn_vbucks"), parse_mode="Markdown")
        return

    # خطوة 2 طلب: الرمز
    if order_step == 'waiting_code':
        if len(text_in) < 2:
            await update.message.reply_text("❌ *الرمز قصير جداً!*",
                reply_markup=build_cancel_order_keyboard("fn_vbucks"), parse_mode="Markdown")
            return
        context.user_data['order_code'] = text_in
        context.user_data['order_step'] = 'waiting_platform'
        await update.message.reply_text(
            f"✅ *تم تسجيل الرمز!*\n\n━━━━━━━━━━━━━━━━━\n🎮 *الخطوة 3 من 3:* اختر المنصة:",
            reply_markup=build_platform_menu(), parse_mode="Markdown")
        return

    # نص بدل اختيار منصة
    if order_step == 'waiting_platform':
        await update.message.reply_text("⚠️ *يرجى اختيار المنصة من الأزرار!*",
            reply_markup=build_platform_menu(), parse_mode="Markdown")
        return

    # ═══════════════════════════════════════════════════════
    # 💳 شحن - خطوة 1: المبلغ (مع التفريق بين الطريقتين)
    # ═══════════════════════════════════════════════════════
    if step == 'waiting_amount':
        is_card_balance = context.user_data.get('is_card_balance', False)

        if is_card_balance:
            # ✅ رصيد آسيا أو زين: يجب أن يكون مضاعف 1000
            valid, result = validate_amount_card_balance(text_in)
        else:
            # ✅ باقي طرق الدفع: التحقق العادي
            if not text_in.isdigit():
                await update.message.reply_text(
                    "❌ *يرجى كتابة المبلغ كأرقام فقط!*\n\n"
                    "⚠️ لا يمكن إرسال حروف أو رموز أو كلمات.\n\n"
                    "📝 اكتب رقماً فقط مثال: `10000`",
                    reply_markup=build_cancel_deposit_keyboard("my_wallet"),
                    parse_mode="Markdown")
                return
            valid, result = validate_amount(text_in)

        if not valid:
            await update.message.reply_text(
                result,
                reply_markup=build_cancel_deposit_keyboard("my_wallet"),
                parse_mode="Markdown")
            return

        context.user_data['transferred_amount'] = result
        context.user_data['step'] = 'waiting_photo'
        await update.message.reply_text(
            f"✅ *تم تسجيل المبلغ:* {result:,} د.ع\n\n━━━━━━━━━━━━━━━━━\n"
            f"📸 *الخطوة 2 من 2:* أرسل صورة إيصال التحويل\n\n"
            f"⚠️ يجب أن تُظهر الصورة:\n  • رقم الحساب\n  • المبلغ\n  • التاريخ والوقت",
            reply_markup=build_cancel_deposit_keyboard("my_wallet"),
            parse_mode="Markdown")
        return

    # شحن - نص بدل صورة
    if step == 'waiting_photo':
        await update.message.reply_text(
            "⚠️ *يرجى إرسال صورة الإيصال لإكمال الطلب!*\n\n📸 التقط صورة واضحة وأرسلها هنا.",
            reply_markup=build_cancel_deposit_keyboard("my_wallet"),
            parse_mode="Markdown")
        return

    # رسائل عشوائية
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ])
    await update.message.reply_text(
        "⚠️ *المحادثة المباشرة غير مفعّلة.*\n\nاستخدم الأزرار للتنقل:",
        reply_markup=keyboard, parse_mode="Markdown")

# ============================================================
# 🖼️ معالج الصور
# ============================================================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user     = update.message.from_user
    photo_id = update.message.photo[-1].file_id
    step     = context.user_data.get('step')

    ensure_user_exists(user.id, user.username, user.first_name)

    if step == 'waiting_amount':
        await update.message.reply_text(
            "❌ *لا يمكن إرسال صور في هذه الخطوة!*\n\n"
            "⚠️ يرجى كتابة المبلغ كأرقام فقط.\n📝 مثال: `10000`",
            reply_markup=build_cancel_deposit_keyboard("my_wallet"),
            parse_mode="Markdown")
        return

    order_step = context.user_data.get('order_step')
    if order_step in ['waiting_email', 'waiting_code', 'waiting_platform']:
        msgs = {
            'waiting_email': "📧 يرجى كتابة الإيميل وليس إرسال صورة!",
            'waiting_code': "🔑 يرجى كتابة الرمز وليس إرسال صورة!",
            'waiting_platform': "🎮 يرجى اختيار المنصة من الأزرار!"
        }
        await update.message.reply_text(
            f"❌ *لا يمكن إرسال صور في هذه الخطوة!*\n\n{msgs[order_step]}",
            reply_markup=build_cancel_order_keyboard("fn_vbucks"),
            parse_mode="Markdown")
        return

    if step == 'waiting_photo':
        method = context.user_data.get('setup_method', 'غير محدد')
        amount = context.user_data.get('transferred_amount', 0)
        context.bot_data[f"method_{user.id}"] = method
        last_product = context.bot_data.get(f"last_product_{user.id}", None)
        buttons = build_after_charge_keyboard(last_product)
        await update.message.reply_text(
            "✅ *تم استلام الإيصال بنجاح!*\n\n⏳ جاري المراجعة...\n⏱️ من 1 إلى 15 دقيقة\n\nسيتم إشعارك فور الموافقة! 🔔",
            reply_markup=buttons, parse_mode="Markdown")
        await notify_admin_transfer(context.bot, user, photo_id, method, amount)
        context.user_data.clear()
        return

    await update.message.reply_text(
        "⚠️ *لا يمكن استقبال الصور خارج خطوات الشحن.*\n\nاضغط /start لبدء عملية جديدة.",
        reply_markup=build_two_buttons("main_menu", "🏠 القائمة الرئيسية"), parse_mode="Markdown")

# ============================================================
# ❌ معالج الأخطاء
# ============================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ خطأ: {context.error}", exc_info=context.error)
    try:
        await context.bot.send_message(chat_id=ADMIN_ID,
            text=f"🚨 *خطأ في البوت!*\n\n`{context.error}`", parse_mode="Markdown")
    except Exception:
        pass

# ============================================================
# 🚀 تشغيل البوت
# ============================================================
def main():
    init_db()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(
        cancel_deposit_handler, pattern="^cancel_deposit_to_"))
    application.add_handler(CallbackQueryHandler(
        cancel_order_handler, pattern="^cancel_order_to_"))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_error_handler(error_handler)
    logger.info("🚀 ميرو ستور بوت يعمل الآن...")
    print("✅ البوت يعمل | اضغط Ctrl+C للإيقاف")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()