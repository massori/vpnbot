#!/usr/bin/env python3
"""
V2Ray Turbo — ربات فروش VPN حرفه‌ای با کانفیگ خودکار
"""

import os
import json
import logging
import sqlite3
import requests
import uuid
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
BOT_TOKEN   = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID    = int(os.getenv("ADMIN_ID", "0"))
PANEL_URL   = os.getenv("PANEL_URL", "https://156.253.5.155:1050/00MmZQQzNot9ZAclys")
PANEL_USER  = os.getenv("PANEL_USER", "admin")
PANEL_PASS  = os.getenv("PANEL_PASS", "admin")
INBOUND_ID  = int(os.getenv("INBOUND_ID", "1"))

CARD_NUMBER = "6104 3378 5470 0694"
CARD_OWNER  = "ثریا قره ویلی"
DB_PATH     = "/root/vpnbot.db"

# ═══════════════════════════════════════════════════
#  پلن‌ها — ماهانه و سه‌ماهه
# ═══════════════════════════════════════════════════
PLANS = {
    # ── ماهانه ──────────────────────────────────────
    "m_20":  {"name":"🌱 استارتر ۲۰ گیگ",   "gb":20,  "days":30,  "price":150_000,  "period":"ماهانه"},
    "m_50":  {"name":"⚡ برنزی ۵۰ گیگ",      "gb":50,  "days":30,  "price":280_000,  "period":"ماهانه"},
    "m_100": {"name":"🔥 نقره‌ای ۱۰۰ گیگ",  "gb":100, "days":30,  "price":450_000,  "period":"ماهانه"},
    "m_200": {"name":"💎 طلایی ۲۰۰ گیگ",    "gb":200, "days":30,  "price":750_000,  "period":"ماهانه"},
    "m_300": {"name":"🚀 VIP ۳۰۰ گیگ",      "gb":300, "days":30,  "price":950_000,  "period":"ماهانه"},
    # ── سه‌ماهه ─────────────────────────────────────
    "q_20":  {"name":"🌱 استارتر ۲۰ گیگ",   "gb":20,  "days":90,  "price":400_000,  "period":"سه‌ماهه"},
    "q_50":  {"name":"⚡ برنزی ۵۰ گیگ",      "gb":50,  "days":90,  "price":750_000,  "period":"سه‌ماهه"},
    "q_100": {"name":"🔥 نقره‌ای ۱۰۰ گیگ",  "gb":100, "days":90,  "price":1_200_000,"period":"سه‌ماهه"},
    "q_200": {"name":"💎 طلایی ۲۰۰ گیگ",    "gb":200, "days":90,  "price":2_000_000,"period":"سه‌ماهه"},
    "q_300": {"name":"🚀 VIP ۳۰۰ گیگ",      "gb":300, "days":90,  "price":2_500_000,"period":"سه‌ماهه"},
}

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("VPNBot")

# ═══════════════════════════════════════════════════
#  دیتابیس
# ═══════════════════════════════════════════════════
def db():
    c = sqlite3.connect(DB_PATH)
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
            created TEXT, confirmed TEXT
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

def confirm_order(oid, config):
    o = get_order(oid)
    today = datetime.now().strftime("%Y-%m-%d")
    with db() as c:
        c.execute("UPDATE orders SET status='confirmed',config=?,confirmed=? WHERE id=?",
                  (config, datetime.now().isoformat(), oid))
        c.execute("""INSERT INTO stats(date,sales,revenue) VALUES(?,1,?)
                     ON CONFLICT(date) DO UPDATE SET
                     sales=sales+1, revenue=revenue+?""",
                  (today, o["amount"], o["amount"]))

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
        r = requests.post(f"{PANEL_URL}/login",
                          json={"username": PANEL_USER, "password": PANEL_PASS},
                          verify=False, timeout=10)
        if r.ok:
            session_cookie = r.cookies
            return True
    except Exception as e:
        logger.error(f"Panel login error: {e}")
    return False

def create_client(plan_key, email):
    """ساخت کلاینت جدید در پنل و برگرداندن کانفیگ"""
    global session_cookie
    if not panel_login():
        return None
    plan = PLANS[plan_key]
    client_id = str(uuid.uuid4())
    expire_ms = int((datetime.now() + timedelta(days=plan["days"])).timestamp() * 1000)
    total_gb = plan["gb"] * 1024 * 1024 * 1024

    payload = {
        "id": INBOUND_ID,
        "settings": json.dumps({
            "clients": [{
                "id": client_id,
                "email": email,
                "limitIp": 2,
                "totalGB": total_gb,
                "expiryTime": expire_ms,
                "enable": True,
                "tgId": "",
                "subId": str(uuid.uuid4())[:8]
            }]
        })
    }
    try:
        r = requests.post(f"{PANEL_URL}/panel/inbound/addClient",
                          json=payload, cookies=session_cookie,
                          verify=False, timeout=10)
        if r.ok and r.json().get("success"):
            # دریافت لینک اشتراک
            sub = requests.get(f"{PANEL_URL}/panel/inbound/list",
                               cookies=session_cookie, verify=False, timeout=10)
            if sub.ok:
                inbounds = sub.json().get("obj", [])
                for inb in inbounds:
                    if inb["id"] == INBOUND_ID:
                        stream = json.loads(inb.get("streamSettings","{}"))
                        reality = stream.get("realitySettings",{})
                        pub_key = reality.get("settings",{}).get("publicKey","")
                        short_id = reality.get("shortIds",[""])[0]
                        sni = reality.get("serverNames",["www.amd.com"])[0]
                        fp = stream.get("tlsSettings",{}).get("fingerprint","chrome")
                        ip = "156.253.5.155"
                        port = inb.get("port", 443)
                        config = (
                            f"vless://{client_id}@{ip}:{port}"
                            f"?type=tcp&security=reality&pbk={pub_key}"
                            f"&fp={fp}&sni={sni}&sid={short_id}&spx=%2F"
                            f"#{email}"
                        )
                        return config
    except Exception as e:
        logger.error(f"Create client error: {e}")
    return None

def create_test_client(uid):
    """ساخت کانفیگ تست ۲۰ مگابایت"""
    global session_cookie
    if not panel_login():
        return None
    client_id = str(uuid.uuid4())
    email = f"test_{uid}"
    expire_ms = int((datetime.now() + timedelta(days=1)).timestamp() * 1000)
    total_bytes = 20 * 1024 * 1024  # 20 مگابایت

    payload = {
        "id": INBOUND_ID,
        "settings": json.dumps({
            "clients": [{
                "id": client_id,
                "email": email,
                "limitIp": 1,
                "totalGB": total_bytes,
                "expiryTime": expire_ms,
                "enable": True,
                "tgId": "",
                "subId": str(uuid.uuid4())[:8]
            }]
        })
    }
    try:
        r = requests.post(f"{PANEL_URL}/panel/inbound/addClient",
                          json=payload, cookies=session_cookie,
                          verify=False, timeout=10)
        if r.ok and r.json().get("success"):
            sub = requests.get(f"{PANEL_URL}/panel/inbound/list",
                               cookies=session_cookie, verify=False, timeout=10)
            if sub.ok:
                inbounds = sub.json().get("obj", [])
                for inb in inbounds:
                    if inb["id"] == INBOUND_ID:
                        stream = json.loads(inb.get("streamSettings","{}"))
                        reality = stream.get("realitySettings",{})
                        pub_key = reality.get("settings",{}).get("publicKey","")
                        short_id = reality.get("shortIds",[""])[0]
                        sni = reality.get("serverNames",["www.amd.com"])[0]
                        ip = "156.253.5.155"
                        port = inb.get("port", 443)
                        config = (
                            f"vless://{client_id}@{ip}:{port}"
                            f"?type=tcp&security=reality&pbk={pub_key}"
                            f"&fp=chrome&sni={sni}&sid={short_id}&spx=%2F"
                            f"#{email}"
                        )
                        return config
    except Exception as e:
        logger.error(f"Test client error: {e}")
    return None

# ═══════════════════════════════════════════════════
#  متن‌ها و کیبوردها
# ═══════════════════════════════════════════════════
def fmt(n): return f"{n:,}".replace(",","،") + " تومان"

def welcome_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 خرید اشتراک", callback_data="buy"),
         InlineKeyboardButton("🎁 تست رایگان",  callback_data="free_test")],
        [InlineKeyboardButton("💎 تعرفه‌ها",    callback_data="prices"),
         InlineKeyboardButton("📚 آموزش اتصال", callback_data="tutorial")],
        [InlineKeyboardButton("👤 حساب من",     callback_data="account"),
         InlineKeyboardButton("👨‍💻 پشتیبانی",   callback_data="support")],
        [InlineKeyboardButton("👥 زیرمجموعه",   callback_data="referral")],
    ])

def period_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 ماهانه",   callback_data="period_monthly"),
         InlineKeyboardButton("📆 سه‌ماهه",  callback_data="period_quarterly")],
        [InlineKeyboardButton("🔙 بازگشت",   callback_data="back_main")],
    ])

def plans_kb(period):
    prefix = "m_" if period == "monthly" else "q_"
    keys = [k for k in PLANS if k.startswith(prefix)]
    rows = []
    for k in keys:
        p = PLANS[k]
        rows.append([InlineKeyboardButton(
            f"{p['name']} | {fmt(p['price'])}",
            callback_data=f"plan_{k}"
        )])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="buy")])
    return InlineKeyboardMarkup(rows)

def back_kb(cb="back_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=cb)]])

def admin_kb(oid):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تایید — ارسال خودکار کانفیگ", callback_data=f"ok_{oid}"),
        InlineKeyboardButton("❌ رد",                          callback_data=f"no_{oid}"),
    ]])

# ═══════════════════════════════════════════════════
#  هندلرها
# ═══════════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    save_user(u)
    await update.message.reply_text(
        f"🔥 <b>به V2Ray Turbo خوش آمدید</b> {u.first_name}\n\n"
        "⚡ اینترنت بدون محدودیت\n"
        "🎮 مناسب گیم و کالاف دیوتی\n"
        "📈 مناسب ترید و یوتیوب\n"
        "🚀 سرعت و پایداری فوق‌العاده\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "یک گزینه را انتخاب کنید 👇",
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
        f"💰 کل درآمد: <b>{fmt(rev)}</b>\n\n"
        f"📊 <b>آمار ۷ روز اخیر:</b>\n{lines}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 سفارش‌های در انتظار", callback_data="admin_pending")]
        ])
    )

async def cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    uid = q.from_user.id

    if d == "back_main":
        await q.edit_message_text(
            f"🔥 <b>V2Ray Turbo</b>\n\nمنوی اصلی 👇",
            reply_markup=welcome_kb(), parse_mode=ParseMode.HTML
        )

    elif d == "buy":
        await q.edit_message_text(
            "📅 <b>انتخاب دوره اشتراک</b>",
            reply_markup=period_kb(), parse_mode=ParseMode.HTML
        )

    elif d in ("period_monthly", "period_quarterly"):
        period = "monthly" if d == "period_monthly" else "quarterly"
        label = "ماهانه" if period == "monthly" else "سه‌ماهه"
        await q.edit_message_text(
            f"💎 <b>پلن‌های {label}</b>\n\nیک پلن انتخاب کنید:",
            reply_markup=plans_kb(period), parse_mode=ParseMode.HTML
        )

    elif d.startswith("plan_"):
        plan_key = d[5:]
        plan = PLANS[plan_key]
        oid = new_order(uid, plan_key)
        ctx.user_data["pending_order"] = oid
        ctx.user_data["pending_plan"] = plan_key
        await q.edit_message_text(
            f"{plan['name']}\n\n"
            f"📦 حجم: <b>{plan['gb']} گیگابایت</b>\n"
            f"⏱ مدت: <b>{plan['days']} روز ({plan['period']})</b>\n"
            f"💰 مبلغ: <b>{fmt(plan['price'])}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💳 <b>اطلاعات پرداخت:</b>\n\n"
            f"<code>{CARD_NUMBER}</code>\n"
            f"👤 به نام: <b>{CARD_OWNER}</b>\n\n"
            "⚠️ پس از واریز، <b>تصویر رسید</b> را ارسال کنید.",
            reply_markup=back_kb("buy"), parse_mode=ParseMode.HTML
        )

    elif d == "prices":
        lines = ["💎 <b>تعرفه‌های V2Ray Turbo</b>\n"]
        lines.append("📅 <b>ماهانه:</b>")
        for k,p in PLANS.items():
            if k.startswith("m_"):
                lines.append(f"  {p['name']} — {fmt(p['price'])}")
        lines.append("\n📆 <b>سه‌ماهه (صرفه‌جویی ۱۵٪):</b>")
        for k,p in PLANS.items():
            if k.startswith("q_"):
                lines.append(f"  {p['name']} — {fmt(p['price'])}")
        await q.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 خرید همین الان", callback_data="buy")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")],
            ]),
            parse_mode=ParseMode.HTML
        )

    elif d == "free_test":
        if used_free_test(uid):
            await q.edit_message_text(
                "⚠️ شما قبلاً از تست رایگان استفاده کرده‌اید.\n\n"
                "برای ادامه یک پلن خریداری کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 خرید اشتراک", callback_data="buy")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")],
                ])
            )
        else:
            await q.edit_message_text(
                "🎁 <b>تست رایگان</b>\n\n"
                "⏱ مدت: ۱ روز\n"
                "📦 حجم: ۲۰ مگابایت\n\n"
                "در حال ساخت کانفیگ تست... ⏳",
                parse_mode=ParseMode.HTML
            )
            config = create_test_client(uid)
            if config:
                mark_free_test(uid)
                await q.edit_message_text(
                    "🎁 <b>کانفیگ تست رایگان شما:</b>\n\n"
                    f"<code>{config}</code>\n\n"
                    "⏱ اعتبار: ۱ روز | 📦 حجم: ۲۰ مگابایت\n"
                    "━━━━━━━━━━━━━━━━━━━\n"
                    "📚 برای آموزش اتصال منوی آموزش را ببینید.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛒 خرید اشتراک کامل", callback_data="buy")],
                        [InlineKeyboardButton("📚 آموزش اتصال", callback_data="tutorial")],
                    ]),
                    parse_mode=ParseMode.HTML
                )
            else:
                await q.edit_message_text(
                    "⚠️ خطا در ساخت کانفیگ.\nلطفاً با پشتیبانی تماس بگیرید.",
                    reply_markup=back_kb()
                )

    elif d == "tutorial":
        await q.edit_message_text(
            "📚 <b>آموزش اتصال به V2Ray</b>\n\n"
            "📱 <b>اندروید:</b>\n"
            "۱. نصب <b>V2RayNG</b> از پلی‌استور\n"
            "۲. کپی کانفیگ دریافتی\n"
            "۳. منو ← Import from clipboard\n"
            "۴. دکمه اجرا ✅\n\n"
            "🍎 <b>iOS:</b>\n"
            "۱. نصب <b>Streisand</b> یا <b>Shadowrocket</b>\n"
            "۲. کانفیگ را اسکن یا کپی کنید\n"
            "۳. Connect ✅\n\n"
            "💻 <b>ویندوز:</b>\n"
            "۱. دانلود <b>V2RayN</b>\n"
            "۲. Import from clipboard\n"
            "۳. فعال کنید ✅",
            reply_markup=back_kb(), parse_mode=ParseMode.HTML
        )

    elif d == "support":
        await q.edit_message_text(
            "👨‍💻 <b>پشتیبانی V2Ray Turbo</b>\n\n"
            "➡️ @Openvpnme1\n\n"
            "⏱ پاسخگویی: ۹ صبح تا ۱۲ شب",
            reply_markup=back_kb(), parse_mode=ParseMode.HTML
        )

    elif d == "account":
        with db() as c:
            orders = c.execute(
                "SELECT * FROM orders WHERE uid=? ORDER BY created DESC", (uid,)
            ).fetchall()
        confirmed = [o for o in orders if o["status"] == "confirmed"]
        lines = [f"👤 <b>حساب کاربری</b>\n\n🆔 <code>{uid}</code>\n"]
        if confirmed:
            last = confirmed[0]
            p = PLANS.get(last["plan_key"], {})
            lines.append(f"✅ آخرین اشتراک: <b>{p.get('name','')}</b>")
            lines.append(f"📅 تاریخ: {last['confirmed'][:10] if last['confirmed'] else '—'}")
        else:
            lines.append("📦 اشتراک فعالی ندارید.")
        lines.append(f"\n📊 کل سفارش: {len(orders)} | تایید‌شده: {len(confirmed)}")
        await q.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 خرید اشتراک", callback_data="buy")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")],
            ]),
            parse_mode=ParseMode.HTML
        )

    elif d == "referral":
        bot_info = await ctx.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
        with db() as c:
            count = c.execute(
                "SELECT COUNT(*) FROM users WHERE uid IN "
                "(SELECT uid FROM users WHERE uid != ?)", (uid,)
            ).fetchone()[0]
        await q.edit_message_text(
            "👥 <b>سیستم زیرمجموعه</b>\n\n"
            "به ازای هر خرید از طریق لینک شما:\n"
            "🎁 <b>۷ روز رایگان</b> به اشتراک شما اضافه می‌شود!\n\n"
            f"🔗 لینک اختصاصی:\n<code>{link}</code>\n\n"
            f"👥 زیرمجموعه‌های شما: <b>{count}</b>",
            reply_markup=back_kb(), parse_mode=ParseMode.HTML
        )

    elif d == "admin_pending":
        if uid != ADMIN_ID: return
        with db() as c:
            pending = c.execute(
                "SELECT * FROM orders WHERE status='pending' OR status='receipt_sent' "
                "ORDER BY created DESC LIMIT 20"
            ).fetchall()
        if not pending:
            await q.edit_message_text("✅ هیچ سفارش در انتظاری وجود ندارد.")
            return
        lines = ["📋 <b>سفارش‌های در انتظار:</b>\n"]
        for o in pending:
            p = PLANS.get(o["plan_key"], {})
            lines.append(f"🔸 #{o['id']} | {p.get('name','؟')} | {fmt(o['amount'])} | کاربر: <code>{o['uid']}</code>")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif d.startswith("ok_"):
        if uid != ADMIN_ID: return
        oid = int(d[3:])
        order = get_order(oid)
        if not order:
            await q.edit_message_text("❌ سفارش یافت نشد.")
            return
        await q.edit_message_text("⏳ در حال ساخت کانفیگ خودکار...")
        email = f"user_{order['uid']}_{oid}"
        config = create_client(order["plan_key"], email)
        if config:
            confirm_order(oid, config)
            plan = PLANS.get(order["plan_key"], {})
            try:
                await ctx.bot.send_message(
                    order["uid"],
                    f"🎉 <b>سفارش شما تایید شد!</b>\n\n"
                    f"📦 پلن: <b>{plan.get('name','')}</b>\n"
                    f"⏱ مدت: <b>{plan.get('days',30)} روز</b>\n"
                    f"📊 حجم: <b>{plan.get('gb',0)} گیگابایت</b>\n\n"
                    "━━━━━━━━━━━━━━━━━━━\n"
                    "🔑 <b>کانفیگ اتصال شما:</b>\n\n"
                    f"<code>{config}</code>\n\n"
                    "━━━━━━━━━━━━━━━━━━━\n"
                    "📚 آموزش اتصال را از منوی ربات ببینید.\n"
                    "❓ مشکل دارید؟ @Openvpnme1",
                    parse_mode=ParseMode.HTML,
                    reply_markup=welcome_kb()
                )
                await q.edit_message_text(f"✅ کانفیگ برای کاربر {order['uid']} ارسال شد.")
            except Exception as e:
                await q.edit_message_text(f"⚠️ کانفیگ ساخته شد اما ارسال خطا داشت: {e}\n\n<code>{config}</code>",
                                          parse_mode=ParseMode.HTML)
        else:
            await q.edit_message_text(
                "❌ خطا در ساخت کانفیگ از پنل.\n"
                "پنل را چک کنید و دوباره تلاش کنید.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 تلاش دوباره", callback_data=f"ok_{oid}")
                ]])
            )

    elif d.startswith("no_"):
        if uid != ADMIN_ID: return
        oid = int(d[3:])
        order = get_order(oid)
        set_order(oid, status="rejected")
        try:
            await ctx.bot.send_message(
                order["uid"],
                "❌ سفارش شما تأیید نشد.\n"
                "برای پیگیری با پشتیبانی تماس بگیرید:\n@Openvpnme1"
            )
        except: pass
        await q.edit_message_text(f"❌ سفارش #{oid} رد شد.")

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    photo = update.message.photo[-1]
    oid = ctx.user_data.get("pending_order")
    if not oid:
        await update.message.reply_text("⚠️ ابتدا یک پلن انتخاب کنید.", reply_markup=welcome_kb())
        return
    plan_key = ctx.user_data.get("pending_plan","")
    plan = PLANS.get(plan_key, {})
    set_order(oid, receipt_id=photo.file_id, status="receipt_sent")
    await update.message.reply_text(
        "✅ <b>رسید دریافت شد!</b>\n\n"
        "⏳ در حال بررسی توسط ادمین...\n"
        "کمتر از ۳۰ دقیقه دیگر کانفیگ ارسال می‌شود.",
        parse_mode=ParseMode.HTML
    )
    try:
        await ctx.bot.send_photo(
            ADMIN_ID, photo.file_id,
            caption=(
                f"📥 <b>رسید جدید!</b>\n\n"
                f"👤 {u.full_name}\n"
                f"🆔 <code>{u.id}</code>\n"
                f"🌐 @{u.username or '—'}\n"
                f"📦 {plan.get('name','')}\n"
                f"💰 {fmt(plan.get('price',0))}\n"
                f"🔢 سفارش #{oid}"
            ),
            reply_markup=admin_kb(oid),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Send to admin error: {e}")
    ctx.user_data.pop("pending_order", None)
    ctx.user_data.pop("pending_plan", None)

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("از منوی زیر انتخاب کنید 👇", reply_markup=welcome_kb())

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
