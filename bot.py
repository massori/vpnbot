#!/usr/bin/env python3
"""
V2Ray Turbo — ربات فروش VPN حرفه‌ای
"""

import os, json, logging, sqlite3, requests, uuid, threading
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# ═══════════════════════════════════════════════════
#  تنظیمات اصلی
# ═══════════════════════════════════════════════════
BOT_TOKEN  = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID   = int(os.getenv("ADMIN_ID", "0"))
PANEL_URL  = os.getenv("PANEL_URL", "https://156.253.5.155:1050/00MmZQQzNot9ZAclys")
PANEL_USER = os.getenv("PANEL_USER", "admin")
PANEL_PASS = os.getenv("PANEL_PASS", "admin")
INBOUND_ID = int(os.getenv("INBOUND_ID", "1"))

CARD_NUMBER = "6104 3378 5470 0694"
CARD_OWNER  = "ثریا قره ویلی"
DB_PATH     = "/root/vpnbot.db"

# قفل جلوگیری از تایید همزمان
_order_locks = {}
_locks_mutex = threading.Lock()

def get_order_lock(oid):
    with _locks_mutex:
        if oid not in _order_locks:
            _order_locks[oid] = threading.Lock()
        return _order_locks[oid]

# ═══════════════════════════════════════════════════
#  پلن‌ها
# ═══════════════════════════════════════════════════
PLANS = {
    # ── ماهانه ──────────────────────────────────────
    "m_20":  {"name":"🥈 نقره‌ای  — ۲۰ گیگ",   "gb":20,  "days":30, "price":150_000, "period":"ماهانه"},
    "m_50":  {"name":"🥇 طلایی   — ۵۰ گیگ",    "gb":50,  "days":30, "price":300_000, "period":"ماهانه"},
    "m_75":  {"name":"💎 الماس   — ۷۵ گیگ",    "gb":75,  "days":30, "price":400_000, "period":"ماهانه"},
    "m_100": {"name":"👑 پلاتینیوم — ۱۰۰ گیگ", "gb":100, "days":30, "price":550_000, "period":"ماهانه"},
    # ── دوماهه ──────────────────────────────────────
    "t_20":  {"name":"🥈 نقره‌ای  — ۲۰ گیگ",   "gb":20,  "days":60, "price":225_000, "period":"دوماهه"},
    "t_50":  {"name":"🥇 طلایی   — ۵۰ گیگ",    "gb":50,  "days":60, "price":450_000, "period":"دوماهه"},
    "t_75":  {"name":"💎 الماس   — ۷۵ گیگ",    "gb":75,  "days":60, "price":600_000, "period":"دوماهه"},
    "t_100": {"name":"👑 پلاتینیوم — ۱۰۰ گیگ", "gb":100, "days":60, "price":825_000, "period":"دوماهه"},
    # ── سه‌ماهه ─────────────────────────────────────
    "q_20":  {"name":"🥈 نقره‌ای  — ۲۰ گیگ",   "gb":20,  "days":90, "price":300_000,   "period":"سه‌ماهه"},
    "q_50":  {"name":"🥇 طلایی   — ۵۰ گیگ",    "gb":50,  "days":90, "price":600_000,   "period":"سه‌ماهه"},
    "q_75":  {"name":"💎 الماس   — ۷۵ گیگ",    "gb":75,  "days":90, "price":800_000,   "period":"سه‌ماهه"},
    "q_100": {"name":"👑 پلاتینیوم — ۱۰۰ گیگ", "gb":100, "days":90, "price":1_100_000, "period":"سه‌ماهه"},
}

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("VPNBot")

# ═══════════════════════════════════════════════════
#  دیتابیس
# ═══════════════════════════════════════════════════
def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            uid INTEGER PRIMARY KEY, username TEXT, name TEXT,
            joined TEXT, free_test INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER, plan_key TEXT, amount INTEGER,
            status TEXT DEFAULT 'pending',
            receipt_id TEXT, config TEXT,
            created TEXT, confirmed TEXT,
            confirmed_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS stats (
            date TEXT PRIMARY KEY,
            sales INTEGER DEFAULT 0, revenue INTEGER DEFAULT 0
        );
        """)

def save_user(u):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(uid,username,name,joined) VALUES(?,?,?,?)",
                  (u.id, u.username, u.full_name, datetime.now().isoformat()))
        c.execute("UPDATE users SET username=?,name=? WHERE uid=?",
                  (u.username, u.full_name, u.id))

def new_order(uid, plan_key):
    with db() as c:
        cur = c.execute("INSERT INTO orders(uid,plan_key,amount,created) VALUES(?,?,?,?)",
                        (uid, plan_key, PLANS[plan_key]["price"], datetime.now().isoformat()))
        return cur.lastrowid

def get_order(oid):
    with db() as c:
        return c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()

def set_order(oid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    with db() as c:
        c.execute(f"UPDATE orders SET {sets} WHERE id=?", (*kw.values(), oid))

def confirm_order(oid, config, admin_uid):
    """تایید اتمی — فقط اگر هنوز pending/receipt_sent باشد"""
    with db() as c:
        cur = c.execute(
            "UPDATE orders SET status='confirmed', config=?, confirmed=?, confirmed_by=? "
            "WHERE id=? AND status IN ('pending','receipt_sent')",
            (config, datetime.now().isoformat(), admin_uid, oid)
        )
        if cur.rowcount == 0:
            return False   # قبلاً پردازش شده
        o = c.execute("SELECT amount FROM orders WHERE id=?", (oid,)).fetchone()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("""INSERT INTO stats(date,sales,revenue) VALUES(?,1,?)
                     ON CONFLICT(date) DO UPDATE SET
                     sales=sales+1, revenue=revenue+?""",
                  (today, o["amount"], o["amount"]))
        return True

def reject_order(oid):
    """رد اتمی"""
    with db() as c:
        cur = c.execute(
            "UPDATE orders SET status='rejected' WHERE id=? AND status IN ('pending','receipt_sent')",
            (oid,)
        )
        return cur.rowcount > 0

def used_free_test(uid):
    with db() as c:
        r = c.execute("SELECT free_test FROM users WHERE uid=?", (uid,)).fetchone()
        return r and r["free_test"] == 1

def mark_free_test(uid):
    with db() as c:
        c.execute("UPDATE users SET free_test=1 WHERE uid=?", (uid,))

def get_stats(days=7):
    with db() as c:
        return c.execute("SELECT * FROM stats ORDER BY date DESC LIMIT ?", (days,)).fetchall()

def total_stats():
    with db() as c:
        r = c.execute("SELECT COUNT(*),SUM(amount) FROM orders WHERE status='confirmed'").fetchone()
        u = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return r[0] or 0, r[1] or 0, u

# ═══════════════════════════════════════════════════
#  پنل 3x-ui API
# ═══════════════════════════════════════════════════
session_cookie = None

def panel_login():
    global session_cookie
    try:
        r = requests.post(
            f"{PANEL_URL}/login",
            json={"username": PANEL_USER, "password": PANEL_PASS},
            verify=False, timeout=15
        )
        logger.info(f"Panel login status: {r.status_code} | body: {r.text[:200]}")
        if r.ok:
            session_cookie = r.cookies
            return True
    except Exception as e:
        logger.error(f"Panel login error: {e}")
    return False

def create_client(plan_key, email):
    global session_cookie
    if not panel_login():
        logger.error("Panel login failed")
        return None

    plan = PLANS[plan_key]
    client_id = str(uuid.uuid4())
    expire_ms  = int((datetime.now() + timedelta(days=plan["days"])).timestamp() * 1000)
    total_bytes = plan["gb"] * 1024 * 1024 * 1024

    payload = {
        "id": INBOUND_ID,
        "settings": json.dumps({
            "clients": [{
                "id": client_id,
                "email": email,
                "limitIp": 2,
                "totalGB": total_bytes,
                "expiryTime": expire_ms,
                "enable": True,
                "tgId": "",
                "subId": str(uuid.uuid4())[:8]
            }]
        })
    }
    try:
        r = requests.post(
            f"{PANEL_URL}/panel/inbound/addClient",
            json=payload, cookies=session_cookie,
            verify=False, timeout=15
        )
        logger.info(f"addClient status: {r.status_code} | body: {r.text[:300]}")

        if not r.ok:
            return None

        resp = r.json()
        if not resp.get("success"):
            logger.error(f"addClient not success: {resp}")
            return None

        # دریافت اطلاعات inbound برای ساخت لینک
        sub = requests.get(
            f"{PANEL_URL}/panel/inbound/list",
            cookies=session_cookie, verify=False, timeout=15
        )
        logger.info(f"inbound/list status: {sub.status_code}")

        if not sub.ok:
            return None

        inbounds = sub.json().get("obj", [])
        for inb in inbounds:
            if inb["id"] == INBOUND_ID:
                stream   = json.loads(inb.get("streamSettings", "{}"))
                reality  = stream.get("realitySettings", {})
                pub_key  = reality.get("settings", {}).get("publicKey", "")
                short_id = reality.get("shortIds", [""])[0]
                sni      = reality.get("serverNames", ["www.amd.com"])[0]
                ip       = "156.253.5.155"
                port     = inb.get("port", 443)
                config   = (
                    f"vless://{client_id}@{ip}:{port}"
                    f"?type=tcp&security=reality&pbk={pub_key}"
                    f"&fp=chrome&sni={sni}&sid={short_id}&spx=%2F"
                    f"#{email}"
                )
                logger.info(f"Config created: {config[:80]}...")
                return config

        logger.error("INBOUND_ID not found in panel list")
    except Exception as e:
        logger.error(f"create_client error: {e}")
    return None

def create_test_client(uid):
    global session_cookie
    if not panel_login():
        return None
    client_id  = str(uuid.uuid4())
    email      = f"test_{uid}"
    expire_ms  = int((datetime.now() + timedelta(days=1)).timestamp() * 1000)
    total_bytes = 20 * 1024 * 1024

    payload = {
        "id": INBOUND_ID,
        "settings": json.dumps({
            "clients": [{
                "id": client_id, "email": email,
                "limitIp": 1, "totalGB": total_bytes,
                "expiryTime": expire_ms, "enable": True,
                "tgId": "", "subId": str(uuid.uuid4())[:8]
            }]
        })
    }
    try:
        r = requests.post(f"{PANEL_URL}/panel/inbound/addClient",
                          json=payload, cookies=session_cookie, verify=False, timeout=15)
        if r.ok and r.json().get("success"):
            sub = requests.get(f"{PANEL_URL}/panel/inbound/list",
                               cookies=session_cookie, verify=False, timeout=15)
            if sub.ok:
                for inb in sub.json().get("obj", []):
                    if inb["id"] == INBOUND_ID:
                        stream   = json.loads(inb.get("streamSettings","{}"))
                        reality  = stream.get("realitySettings",{})
                        pub_key  = reality.get("settings",{}).get("publicKey","")
                        short_id = reality.get("shortIds",[""])[0]
                        sni      = reality.get("serverNames",["www.amd.com"])[0]
                        config   = (
                            f"vless://{client_id}@156.253.5.155:{inb.get('port',443)}"
                            f"?type=tcp&security=reality&pbk={pub_key}"
                            f"&fp=chrome&sni={sni}&sid={short_id}&spx=%2F#{email}"
                        )
                        return config
    except Exception as e:
        logger.error(f"Test client error: {e}")
    return None

# ═══════════════════════════════════════════════════
#  متن‌ها و کیبوردها
# ═══════════════════════════════════════════════════
def fmt(n):
    return f"{n:,}".replace(",", "،") + " تومان"

DIVIDER   = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
DIVIDER2  = "▪️▪️▪️▪️▪️▪️▪️▪️▪️▪️"

def welcome_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 خرید اشتراک",    callback_data="buy"),
         InlineKeyboardButton("🎁 تست رایگان",     callback_data="free_test")],
        [InlineKeyboardButton("💰 تعرفه‌ها",        callback_data="prices"),
         InlineKeyboardButton("📚 آموزش اتصال",    callback_data="tutorial")],
        [InlineKeyboardButton("👤 حساب من",         callback_data="account"),
         InlineKeyboardButton("🎧 پشتیبانی",       callback_data="support")],
        [InlineKeyboardButton("👥 دعوت دوستان",    callback_data="referral")],
    ])

def period_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 یک‌ماهه",  callback_data="period_monthly"),
         InlineKeyboardButton("📆 دوماهه",   callback_data="period_bimonthly")],
        [InlineKeyboardButton("🗓 سه‌ماهه",  callback_data="period_quarterly")],
        [InlineKeyboardButton("🔙 بازگشت",   callback_data="back_main")],
    ])

def plans_kb(period):
    prefix = {"monthly":"m_","bimonthly":"t_","quarterly":"q_"}.get(period,"m_")
    keys = [k for k in PLANS if k.startswith(prefix)]
    rows = []
    for k in keys:
        p = PLANS[k]
        rows.append([InlineKeyboardButton(
            f"{p['name']}  |  {fmt(p['price'])}",
            callback_data=f"plan_{k}"
        )])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="buy")])
    return InlineKeyboardMarkup(rows)

def back_kb(cb="back_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=cb)]])

def admin_kb(oid):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تایید و ارسال کانفیگ", callback_data=f"ok_{oid}"),
        InlineKeyboardButton("❌ رد پرداخت",            callback_data=f"no_{oid}"),
    ]])

# ═══════════════════════════════════════════════════
#  هندلرها
# ═══════════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    save_user(u)
    await update.message.reply_text(
        f"✨ <b>سلام {u.first_name} عزیز</b>\n\n"
        f"{DIVIDER2}\n"
        "به <b>V2Ray Turbo</b> خوش آمدید\n"
        "اینترنت بدون محدودیت — پرسرعت و پایدار\n"
        f"{DIVIDER2}\n\n"
        "⚡️ سرعت فوق‌العاده برای استریم و گیم\n"
        "🔐 رمزگذاری قوی و حریم خصوصی کامل\n"
        "🌍 سرور اختصاصی اروپا\n"
        "📲 پشتیبانی از همه دستگاه‌ها\n\n"
        "از منوی زیر انتخاب کنید 👇",
        reply_markup=welcome_kb(), parse_mode=ParseMode.HTML
    )

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    sales, rev, users = total_stats()
    stats = get_stats(7)
    lines = "\n".join(
        f"  📅 {r['date']} | {r['sales']} فروش | {fmt(r['revenue'])}"
        for r in stats
    ) or "  هنوز داده‌ای ثبت نشده"
    await update.message.reply_text(
        f"🛡 <b>پنل مدیریت V2Ray Turbo</b>\n\n"
        f"👥 کاربران: <b>{users:,}</b>\n"
        f"✅ فروش تایید‌شده: <b>{sales:,}</b>\n"
        f"💰 درآمد کل: <b>{fmt(rev)}</b>\n\n"
        f"📊 <b>آمار ۷ روز اخیر:</b>\n{lines}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 سفارش‌های در انتظار", callback_data="admin_pending")]
        ])
    )

async def cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    await q.answer()
    d   = q.data
    uid = q.from_user.id

    # ── منوی اصلی ──────────────────────────────────
    if d == "back_main":
        await q.edit_message_text(
            f"🏠 <b>منوی اصلی V2Ray Turbo</b>\n\n{DIVIDER}\nیک گزینه انتخاب کنید 👇",
            reply_markup=welcome_kb(), parse_mode=ParseMode.HTML
        )

    # ── خرید ───────────────────────────────────────
    elif d == "buy":
        await q.edit_message_text(
            f"🛒 <b>خرید اشتراک</b>\n\n{DIVIDER}\n"
            "دوره اشتراک خود را انتخاب کنید:",
            reply_markup=period_kb(), parse_mode=ParseMode.HTML
        )

    elif d in ("period_monthly", "period_bimonthly", "period_quarterly"):
        map_ = {"period_monthly":"monthly","period_bimonthly":"bimonthly","period_quarterly":"quarterly"}
        lbl  = {"monthly":"یک‌ماهه","bimonthly":"دوماهه","quarterly":"سه‌ماهه"}
        period = map_[d]
        await q.edit_message_text(
            f"💎 <b>پلن‌های {lbl[period]}</b>\n\n{DIVIDER}\nپلن مورد نظر را انتخاب کنید:",
            reply_markup=plans_kb(period), parse_mode=ParseMode.HTML
        )

    elif d.startswith("plan_"):
        plan_key = d[5:]
        if plan_key not in PLANS:
            await q.edit_message_text("❌ پلن یافت نشد.")
            return
        plan = PLANS[plan_key]
        oid  = new_order(uid, plan_key)
        ctx.user_data["pending_order"] = oid
        ctx.user_data["pending_plan"]  = plan_key
        await q.edit_message_text(
            f"🧾 <b>جزئیات سفارش</b>\n\n"
            f"{DIVIDER}\n"
            f"📦 پلن: <b>{plan['name']}</b>\n"
            f"📊 حجم: <b>{plan['gb']} گیگابایت</b>\n"
            f"⏱ مدت: <b>{plan['days']} روز ({plan['period']})</b>\n"
            f"💰 مبلغ قابل پرداخت: <b>{fmt(plan['price'])}</b>\n"
            f"{DIVIDER}\n\n"
            "💳 <b>اطلاعات کارت:</b>\n\n"
            f"<code>{CARD_NUMBER}</code>\n"
            f"🏦 به نام: <b>{CARD_OWNER}</b>\n\n"
            "⚠️ پس از واریز، <b>تصویر رسید</b> را در همین چت ارسال کنید.\n"
            "✅ کانفیگ شما کمتر از ۳۰ دقیقه ارسال می‌شود.",
            reply_markup=back_kb("buy"), parse_mode=ParseMode.HTML
        )

    # ── تعرفه‌ها ────────────────────────────────────
    elif d == "prices":
        lines = [f"💰 <b>تعرفه‌های V2Ray Turbo</b>\n\n{DIVIDER}\n"]
        for period, prefix, label in [
            ("monthly","m_","📅 یک‌ماهه"),
            ("bimonthly","t_","📆 دوماهه"),
            ("quarterly","q_","🗓 سه‌ماهه"),
        ]:
            lines.append(f"\n<b>{label}:</b>")
            for k, p in PLANS.items():
                if k.startswith(prefix):
                    lines.append(f"  {p['name']}  ←  {fmt(p['price'])}")
        lines.append(f"\n{DIVIDER}")
        lines.append("🎁 تست رایگان ۱ روزه برای کاربران جدید!")
        await q.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 خرید همین الان", callback_data="buy")],
                [InlineKeyboardButton("🎁 تست رایگان",     callback_data="free_test")],
                [InlineKeyboardButton("🔙 بازگشت",         callback_data="back_main")],
            ]),
            parse_mode=ParseMode.HTML
        )

    # ── تست رایگان ─────────────────────────────────
    elif d == "free_test":
        if used_free_test(uid):
            await q.edit_message_text(
                "⚠️ <b>تست رایگان قبلاً استفاده شده</b>\n\n"
                "شما قبلاً از تست رایگان استفاده کرده‌اید.\n"
                "برای ادامه یک پلن تهیه کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 خرید اشتراک", callback_data="buy")],
                    [InlineKeyboardButton("🔙 بازگشت",      callback_data="back_main")],
                ]),
                parse_mode=ParseMode.HTML
            )
        else:
            await q.edit_message_text(
                "🎁 <b>تست رایگان</b>\n\n"
                f"{DIVIDER}\n"
                "⏱ مدت: ۱ روز  |  📦 حجم: ۲۰ مگابایت\n\n"
                "⏳ در حال ساخت کانفیگ...",
                parse_mode=ParseMode.HTML
            )
            config = create_test_client(uid)
            if config:
                mark_free_test(uid)
                await q.edit_message_text(
                    f"🎁 <b>کانفیگ تست رایگان شما آماده است!</b>\n\n"
                    f"{DIVIDER}\n"
                    "⏱ اعتبار: ۱ روز  |  📦 حجم: ۲۰ مگابایت\n\n"
                    f"<code>{config}</code>\n\n"
                    f"{DIVIDER}\n"
                    "📚 آموزش اتصال را از منو ببینید.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛒 خرید اشتراک کامل", callback_data="buy")],
                        [InlineKeyboardButton("📚 آموزش اتصال",      callback_data="tutorial")],
                    ]),
                    parse_mode=ParseMode.HTML
                )
            else:
                await q.edit_message_text(
                    "⚠️ خطا در ساخت کانفیگ.\nبا پشتیبانی تماس بگیرید: @Openvpnme1",
                    reply_markup=back_kb()
                )

    # ── آموزش ──────────────────────────────────────
    elif d == "tutorial":
        await q.edit_message_text(
            f"📚 <b>آموزش اتصال به V2Ray</b>\n\n{DIVIDER}\n\n"
            "📱 <b>اندروید:</b>\n"
            "۱. نصب <b>V2RayNG</b> از پلی‌استور\n"
            "۲. کپی لینک کانفیگ\n"
            "۳. منو ← Import from clipboard\n"
            "۴. دکمه اجرا ✅\n\n"
            "🍎 <b>iOS:</b>\n"
            "۱. نصب <b>Streisand</b> یا <b>Shadowrocket</b>\n"
            "۲. کانفیگ را کپی یا اسکن کنید\n"
            "۳. Connect ✅\n\n"
            "💻 <b>ویندوز:</b>\n"
            "۱. دانلود <b>V2RayN</b>\n"
            "۲. Import from clipboard\n"
            "۳. فعال‌سازی ✅\n\n"
            f"{DIVIDER}\n"
            "❓ مشکل داشتید: @Openvpnme1",
            reply_markup=back_kb(), parse_mode=ParseMode.HTML
        )

    # ── پشتیبانی ───────────────────────────────────
    elif d == "support":
        await q.edit_message_text(
            f"🎧 <b>پشتیبانی V2Ray Turbo</b>\n\n{DIVIDER}\n\n"
            "📬 ارتباط مستقیم:\n"
            "➡️ @Openvpnme1\n\n"
            "⏰ ساعات پاسخگویی:\n"
            "🕘 ۹ صبح تا ۱۲ شب",
            reply_markup=back_kb(), parse_mode=ParseMode.HTML
        )

    # ── حساب من ────────────────────────────────────
    elif d == "account":
        with db() as c:
            orders = c.execute(
                "SELECT * FROM orders WHERE uid=? ORDER BY created DESC", (uid,)
            ).fetchall()
        confirmed = [o for o in orders if o["status"] == "confirmed"]
        lines = [f"👤 <b>حساب کاربری</b>\n\n{DIVIDER}\n\n🆔 شناسه: <code>{uid}</code>\n"]
        if confirmed:
            last = confirmed[0]
            p = PLANS.get(last["plan_key"], {})
            lines.append(f"✅ آخرین اشتراک: <b>{p.get('name','')}</b>")
            lines.append(f"📅 تاریخ تایید: {last['confirmed'][:10] if last['confirmed'] else '—'}")
        else:
            lines.append("📦 اشتراک فعالی ندارید.")
        lines.append(f"\n📊 کل سفارش‌ها: {len(orders)}  |  تایید‌شده: {len(confirmed)}")
        await q.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 خرید اشتراک", callback_data="buy")],
                [InlineKeyboardButton("🔙 بازگشت",      callback_data="back_main")],
            ]),
            parse_mode=ParseMode.HTML
        )

    # ── زیرمجموعه ──────────────────────────────────
    elif d == "referral":
        bot_info = await ctx.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
        await q.edit_message_text(
            f"👥 <b>دعوت دوستان</b>\n\n{DIVIDER}\n\n"
            "به ازای هر خرید از طریق لینک شما:\n"
            "🎁 <b>۷ روز رایگان</b> به اشتراکتان اضافه می‌شود!\n\n"
            f"🔗 لینک اختصاصی شما:\n<code>{link}</code>",
            reply_markup=back_kb(), parse_mode=ParseMode.HTML
        )

    # ── ادمین: سفارش‌های در انتظار ─────────────────
    elif d == "admin_pending":
        if uid != ADMIN_ID: return
        with db() as c:
            pending = c.execute(
                "SELECT * FROM orders WHERE status IN ('pending','receipt_sent') "
                "ORDER BY created DESC LIMIT 20"
            ).fetchall()
        if not pending:
            await q.edit_message_text("✅ هیچ سفارش در انتظاری وجود ندارد.")
            return
        lines = ["📋 <b>سفارش‌های در انتظار:</b>\n"]
        for o in pending:
            p = PLANS.get(o["plan_key"], {})
            lines.append(
                f"🔸 #{o['id']} | {p.get('name','؟')} | {fmt(o['amount'])} | "
                f"کاربر: <code>{o['uid']}</code>"
            )
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_kb())

    # ── ادمین: تایید پرداخت ────────────────────────
    elif d.startswith("ok_"):
        if uid != ADMIN_ID: return
        oid   = int(d[3:])
        lock  = get_order_lock(oid)

        if not lock.acquire(blocking=False):
            await q.answer("⏳ این سفارش در حال پردازش است...", show_alert=True)
            return

        try:
            order = get_order(oid)
            if not order:
                await q.edit_message_text("❌ سفارش یافت نشد.")
                return

            if order["status"] not in ("pending", "receipt_sent"):
                await q.answer("⚠️ این سفارش قبلاً پردازش شده است.", show_alert=True)
                return

            await q.edit_message_text("⏳ در حال ساخت کانفیگ از پنل...")

            email  = f"u{order['uid']}_{oid}"
            config = create_client(order["plan_key"], email)

            if not config:
                await q.edit_message_text(
                    "❌ خطا در اتصال به پنل یا ساخت کانفیگ.\n"
                    "پنل را چک کنید و دوباره تلاش کنید.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 تلاش دوباره", callback_data=f"ok_{oid}")
                    ]])
                )
                return

            # ثبت اتمی در دیتابیس
            ok = confirm_order(oid, config, uid)
            if not ok:
                await q.answer("⚠️ این سفارش قبلاً پردازش شده است.", show_alert=True)
                return

            plan = PLANS.get(order["plan_key"], {})
            expire_date = (datetime.now() + timedelta(days=plan.get("days",30))).strftime("%Y/%m/%d")

            # ارسال کانفیگ به کاربر
            try:
                await ctx.bot.send_message(
                    chat_id=int(order["uid"]),
                    text=(
                        f"🎉 <b>سفارش شما تایید شد!</b>\n\n"
                        f"{DIVIDER}\n"
                        f"📦 پلن: <b>{plan.get('name','')}</b>\n"
                        f"📊 حجم: <b>{plan.get('gb',0)} گیگابایت</b>\n"
                        f"⏱ مدت: <b>{plan.get('days',30)} روز</b>\n"
                        f"📅 انقضا: <b>{expire_date}</b>\n"
                        f"{DIVIDER}\n\n"
                        "🔑 <b>کانفیگ اتصال شما:</b>\n\n"
                        f"<code>{config}</code>\n\n"
                        f"{DIVIDER}\n"
                        "📚 آموزش اتصال را از منوی ربات ببینید.\n"
                        "❓ مشکل دارید؟ @Openvpnme1"
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=welcome_kb()
                )
                await q.edit_message_text(
                    f"✅ کانفیگ برای کاربر <code>{order['uid']}</code> ارسال شد.\n"
                    f"🔢 سفارش #{oid}",
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Config sent to user {order['uid']} for order #{oid}")
            except Exception as e:
                logger.error(f"Send config to user error: {e}")
                await q.edit_message_text(
                    f"⚠️ کانفیگ ساخته شد اما ارسال به کاربر با خطا مواجه شد!\n\n"
                    f"خطا: {e}\n\n"
                    f"کانفیگ:\n<code>{config}</code>",
                    parse_mode=ParseMode.HTML
                )
        finally:
            lock.release()

    # ── ادمین: رد پرداخت ───────────────────────────
    elif d.startswith("no_"):
        if uid != ADMIN_ID: return
        oid   = int(d[3:])
        order = get_order(oid)
        if not order:
            await q.edit_message_text("❌ سفارش یافت نشد.")
            return

        ok = reject_order(oid)
        if not ok:
            await q.answer("⚠️ این سفارش قبلاً پردازش شده است.", show_alert=True)
            return

        try:
            await ctx.bot.send_message(
                chat_id=int(order["uid"]),
                text=(
                    "❌ <b>سفارش شما تأیید نشد.</b>\n\n"
                    "احتمالاً رسید ارسالی مشکل داشته است.\n"
                    "برای پیگیری با پشتیبانی تماس بگیرید:\n"
                    "📬 @Openvpnme1"
                ),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Reject notify error: {e}")

        await q.edit_message_text(f"❌ سفارش #{oid} رد شد.")

# ═══════════════════════════════════════════════════
#  هندلر عکس (رسید پرداخت)
# ═══════════════════════════════════════════════════
async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u     = update.effective_user
    photo = update.message.photo[-1]
    oid   = ctx.user_data.get("pending_order")

    if not oid:
        await update.message.reply_text(
            "⚠️ ابتدا یک پلن انتخاب کنید.",
            reply_markup=welcome_kb()
        )
        return

    plan_key = ctx.user_data.get("pending_plan", "")
    plan     = PLANS.get(plan_key, {})
    set_order(oid, receipt_id=photo.file_id, status="receipt_sent")

    await update.message.reply_text(
        f"✅ <b>رسید پرداخت دریافت شد!</b>\n\n"
        f"{DIVIDER}\n"
        "⏳ سفارش شما در حال بررسی توسط ادمین است.\n"
        "⚡️ کمتر از ۳۰ دقیقه دیگر کانفیگ ارسال می‌شود.",
        parse_mode=ParseMode.HTML
    )

    try:
        await ctx.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo.file_id,
            caption=(
                f"📥 <b>رسید جدید دریافت شد!</b>\n\n"
                f"{DIVIDER}\n"
                f"👤 نام: {u.full_name}\n"
                f"🆔 آیدی: <code>{u.id}</code>\n"
                f"🌐 یوزرنیم: @{u.username or '—'}\n\n"
                f"📦 پلن: <b>{plan.get('name','')}</b>\n"
                f"💰 مبلغ: <b>{fmt(plan.get('price',0))}</b>\n"
                f"🔢 شماره سفارش: <b>#{oid}</b>"
            ),
            reply_markup=admin_kb(oid),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Send receipt to admin error: {e}")

    ctx.user_data.pop("pending_order", None)
    ctx.user_data.pop("pending_plan", None)

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "از منوی زیر انتخاب کنید 👇",
        reply_markup=welcome_kb()
    )

# ═══════════════════════════════════════════════════
#  اجرا
# ═══════════════════════════════════════════════════
def main():
    import urllib3
    urllib3.disable_warnings()
    init_db()
    logger.info("DB ready ✅")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    logger.info("V2Ray Turbo Bot running 🚀")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
