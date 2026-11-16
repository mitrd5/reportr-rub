# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║        ربات همه‌کاره ریپورتر  —  روبیکا + تلگرام  (تک فایل)          ║
╠══════════════════════════════════════════════════════════════════════╣
║  نصب:                                                               ║
║      pip install aiogram rubpy-py pycryptodome telethon pytz        ║
║                                                                      ║
║  اجرا:                                                               ║
║      python reporter_bot.py                                         ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import os
import random
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── روبیکا ──
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15 as pkcs1_15_sig
from rubpy import Client as RubikaClient
from rubpy.crypto import Crypto
from rubpy.enums import ReportType

# ── ربات تلگرام ──
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ButtonStyle, ChatMemberStatus
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)

# ── اکانت‌های تلگرام (ریپورتر) ──
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import (
    CheckChatInviteRequest,
    ReportRequest,
)
from telethon.tl.types import (
    InputReportReasonChildAbuse,
    InputReportReasonCopyright,
    InputReportReasonFake,
    InputReportReasonIllegalDrugs,
    InputReportReasonOther,
    InputReportReasonPersonalDetails,
    InputReportReasonPornography,
    InputReportReasonSpam,
    InputReportReasonViolence,
)

# ══════════════════════════════════════════════════════════════════════
#  تنظیمات
# ══════════════════════════════════════════════════════════════════════
TELEGRAM_TOKEN = "8179859382:AAHnhHIa5-DXV923UfRdbEgOUnLO5P79qIs"
ADMIN_IDS: set[int] = {8503523539}
ADMIN_USERNAME = "@Saeqehe"
SUPPORT_USERNAME = ADMIN_USERNAME

# ── اشتراک ──
ADMIN_CARD_NUMBER = "6219861453153586"   # ← شماره کارت برای واریز
PREMIUM_PRICE     = "350,000 تومان"      # ← قیمت اشتراک
PREMIUM_MONTHS    = 1                    # تعداد ماه
FREE_LIMIT        = 100                  # سقف رایگان هر نوع گزارش
PREMIUM_LIMIT     = 1000                 # سقف اشتراکی هر نوع گزارش
DEFAULT_SUB_QUOTA = 2000                 # سقف پیش‌فرض اشتراک خریداری‌شده (کل)
REPORT_DELAY      = 3                    # فاصله پیش‌فرض بین گزارش‌ها (ثانیه)
RUBIKA_TYPE_GAP   = 8                    # مکث بین «انواع» گزارش روبیکا (ثانیه) — ضد بن

# ── کانال‌های اجباری ──
REQUIRED_CHANNELS = ["mrvpn294", "amirwebcode1"]

# ── API اکانت‌های تلگرام (ریپورتر) ──
TELEGRAM_API_ID   = 26956028
TELEGRAM_API_HASH = "734deef3f0e1f9e3fec13ad19b5bff9e"
TG_CODE_TTL       = 240          # مدت اعتبار کد ورود تلگرام (ثانیه)

# ── گروه گزارش عملیات (اختیاری) ──
# مثال: -1001234567890  یا  "@my_report_channel"  — اگر نمی‌خواهی خالی بگذار
REPORT_GROUP_ID = None

# ══════════════════════════════════════════════════════════════════════
#  لاگ و مسیرها
# ══════════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
DB_PATH           = os.path.join(BASE_DIR, "users.db")
RUBIKA_SESSIONS   = os.path.join(BASE_DIR, "rubika_sessions")
os.makedirs(RUBIKA_SESSIONS, exist_ok=True)

# وضعیت توقف عملیات هر کاربر
user_stop: dict[int, bool] = {}
# قفل انتخاب نوع گزارش تا کلیک‌های سریع، انتخاب‌های قبلی را پاک نکنند
_rt_locks: dict[int, asyncio.Lock] = {}
# کلاینت‌های موقت هنگام لاگین تلگرام
TG_LOGIN_CLIENTS: dict[int, TelegramClient] = {}
# اطلاعات کد ارسال‌شده (phone / hash / زمان ارسال) برای هر کاربر
TG_LOGIN_META: dict[int, dict] = {}
# قفل ورود هر کاربر تا درخواست‌های هم‌زمان کد قبلی را باطل نکنند
TG_LOGIN_LOCKS: dict[int, asyncio.Lock] = {}

# ══════════════════════════════════════════════════════════════════════
#  انواع گزارش روبیکا
# ══════════════════════════════════════════════════════════════════════
REPORT_TYPES_MAP: dict[str, tuple[str, ReportType]] = {
    "1": ("🔞 محتوای مستهجن", ReportType.PORNOGRAPHY),
    "2": ("⚔️ خشونت",         ReportType.VIOLENCE),
    "3": ("📛 اسپم",          ReportType.SPAM),
    "4": ("👶 کودک‌آزاری",    ReportType.CHILD_ABUSE),
    "5": ("©️ نقض حق‌نشر",    ReportType.COPYRIGHT),
    "6": ("🎣 فیشینگ",        ReportType.FISHING),
    "7": ("📝 سایر",          ReportType.OTHER),
}

# ══════════════════════════════════════════════════════════════════════
#  دلایل گزارش تلگرام
# ══════════════════════════════════════════════════════════════════════
TG_REASONS: dict[str, tuple[str, object, str]] = {
    "1":  ("🚫 اسپم",              InputReportReasonSpam(),            "This content is spam and violates Telegram policies"),
    "2":  ("❌ جعلی",              InputReportReasonFake(),            "This content is fake and misleading"),
    "3":  ("🔪 خشونت",             InputReportReasonViolence(),        "This content promotes violence"),
    "4":  ("🔞 مستهجن",            InputReportReasonPornography(),     "This content contains illegal pornography"),
    "5":  ("👶 کودک‌آزاری",        InputReportReasonChildAbuse(),      "This content involves child abuse"),
    "6":  ("©️ حق‌نشر",             InputReportReasonCopyright(),       "This content violates copyright laws"),
    "7":  ("📋 اطلاعات شخصی",      InputReportReasonPersonalDetails(), "This content exposes personal details without consent"),
    "8":  ("📝 سایر",              InputReportReasonOther(),           "This content violates Telegram Terms of Service"),
    "9":  ("💸 کلاهبرداری",        InputReportReasonOther(),           "This channel/post/user is involved in scam and fraud"),
    "10": ("💊 مواد مخدر",         InputReportReasonIllegalDrugs(),    "This content promotes illegal drugs"),
}

# ══════════════════════════════════════════════════════════════════════
#  FSM
# ══════════════════════════════════════════════════════════════════════
class Form(StatesGroup):
    main_menu = State()

    # ── لاگین روبیکا ──
    rb_phone    = State()
    rb_password = State()
    rb_code     = State()

    # ── گزارش روبیکا ──
    rb_guid        = State()
    rb_resolve     = State()
    rb_report_type = State()
    rb_other_text  = State()
    rb_count       = State()
    rb_delay       = State()
    rb_type_gap    = State()
    rb_accounts    = State()

    # ── لاگین تلگرام ──
    tg_phone    = State()
    tg_code     = State()
    tg_password = State()

    # ── گزارش تلگرام ──
    tg_accounts   = State()
    tg_target     = State()
    tg_links      = State()
    tg_join       = State()
    tg_reason     = State()
    tg_manual     = State()
    tg_per_acc    = State()
    tg_delay      = State()

    # ── بقیه ──
    receipt         = State()
    support_message = State()
    admin_panel     = State()
    broadcast       = State()
    admin_reply     = State()


# ══════════════════════════════════════════════════════════════════════
#  دیتابیس
# ══════════════════════════════════════════════════════════════════════
def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    except sqlite3.OperationalError:
        return []


def _forces_single_account(conn: sqlite3.Connection, table: str) -> bool:
    """آیا جدول فقط اجازه می‌دهد هر کاربر یک اکانت داشته باشد؟ (UNIQUE فقط روی telegram_id)"""
    if not _table_columns(conn, table):
        return False
    try:
        indexes = conn.execute(f'PRAGMA index_list("{table}")').fetchall()
    except sqlite3.OperationalError:
        return False
    for idx in indexes:
        if not idx[2]:                      # غیر یکتا
            continue
        try:
            cols = [r[2] for r in conn.execute(f'PRAGMA index_info("{idx[1]}")').fetchall()]
        except sqlite3.OperationalError:
            continue
        if cols == ["telegram_id"]:
            return True
    return False


def _has_composite_unique(conn: sqlite3.Connection, table: str) -> bool:
    if not _table_columns(conn, table):
        return False
    try:
        indexes = conn.execute(f'PRAGMA index_list("{table}")').fetchall()
    except sqlite3.OperationalError:
        return False
    for idx in indexes:
        if not idx[2]:
            continue
        try:
            cols = [r[2] for r in conn.execute(f'PRAGMA index_info("{idx[1]}")').fetchall()]
        except sqlite3.OperationalError:
            continue
        if cols == ["telegram_id", "phone"]:
            return True
    return False


def _rebuild_accounts_table(conn: sqlite3.Connection, table: str, create_sql: str) -> None:
    """جدول قدیمی (تک‌اکانتی) را با اسکیمای جدید (اکانت نامحدود) بازسازی می‌کند و داده‌ها را نگه می‌دارد."""
    old_cols = _table_columns(conn, table)
    if not old_cols:
        conn.execute(create_sql)
        return

    backup = f"{table}_old"
    conn.execute(f'DROP TABLE IF EXISTS "{backup}"')
    conn.execute(f'ALTER TABLE "{table}" RENAME TO "{backup}"')
    conn.execute(create_sql)
    new_cols = _table_columns(conn, table)
    common = [c for c in new_cols if c in old_cols]
    if common:
        cols = ", ".join(f'"{c}"' for c in common)
        conn.execute(f'INSERT OR IGNORE INTO "{table}" ({cols}) SELECT {cols} FROM "{backup}"')
    conn.execute(f'DROP TABLE "{backup}"')
    logger.warning("DB migration: جدول %s برای پشتیبانی از چند اکانت بازسازی شد.", table)


def init_db() -> None:
    rubika_accounts_sql = """
            CREATE TABLE IF NOT EXISTS rubika_accounts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                phone       TEXT NOT NULL,
                session_path TEXT NOT NULL,
                auth        TEXT,
                private_key TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                UNIQUE(telegram_id, phone)
            )
        """
    telegram_accounts_sql = """
            CREATE TABLE IF NOT EXISTS telegram_accounts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                phone       TEXT NOT NULL,
                session_str TEXT NOT NULL,
                label       TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                UNIQUE(telegram_id, phone)
            )
        """

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id        INTEGER PRIMARY KEY,
                phone              TEXT,
                rubika_session     TEXT,
                rubika_auth        TEXT,
                rubika_private_key TEXT,
                is_premium         INTEGER DEFAULT 0,
                premium_until      TEXT,
                coins              INTEGER DEFAULT 0,
                total_reports      INTEGER DEFAULT 0,
                total_invites      INTEGER DEFAULT 0,
                last_daily_reward  TEXT,
                created_at         TEXT DEFAULT (datetime('now'))
            )
        """)
        # ── ستون‌های جدول کاربران (ترمیم دیتابیس‌های قدیمی) ──
        for col, ctype in {
            "phone": "TEXT",
            "rubika_session": "TEXT",
            "rubika_auth": "TEXT",
            "rubika_private_key": "TEXT",
            "is_premium": "INTEGER DEFAULT 0",
            "premium_until": "TEXT",
            "coins": "INTEGER DEFAULT 0",
            "total_reports": "INTEGER DEFAULT 0",
            "total_invites": "INTEGER DEFAULT 0",
            "last_daily_reward": "TEXT",
            "created_at": "TEXT",
            "sub_quota": "INTEGER DEFAULT 0",
            "sub_used": "INTEGER DEFAULT 0",
            "sub_type": "TEXT",
            "sub_granted_at": "TEXT",
            "tg_access": "INTEGER DEFAULT 0",
            "is_blocked": "INTEGER DEFAULT 0",
        }.items():
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ctype}")
            except sqlite3.OperationalError:
                pass

        # ── جدول اکانت‌ها: هر کاربر باید بتواند تعداد نامحدود اکانت اضافه کند ──
        for table, create_sql in (
            ("rubika_accounts", rubika_accounts_sql),
            ("telegram_accounts", telegram_accounts_sql),
        ):
            if _forces_single_account(conn, table):
                _rebuild_accounts_table(conn, table, create_sql)
            else:
                conn.execute(create_sql)

        # ── در نبود قید یکتای ترکیبی، ایندکس یکتا روی (کاربر، شماره) بساز ──
        for table in ("rubika_accounts", "telegram_accounts"):
            if not _has_composite_unique(conn, table):
                try:
                    conn.execute(
                        f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_user_phone '
                        f'ON "{table}" (telegram_id, phone)'
                    )
                except sqlite3.OperationalError:
                    pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS report_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                platform    TEXT NOT NULL,
                target      TEXT NOT NULL,
                target_type TEXT,
                reason      TEXT,
                success     INTEGER DEFAULT 0,
                failed      INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS targets (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id   INTEGER NOT NULL,
                platform      TEXT NOT NULL,
                target        TEXT NOT NULL,
                target_type   TEXT,
                status        TEXT DEFAULT 'unknown',
                total_success INTEGER DEFAULT 0,
                total_failed  INTEGER DEFAULT 0,
                first_at      TEXT,
                last_at       TEXT,
                UNIQUE(telegram_id, platform, target)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS operations (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id   INTEGER NOT NULL,
                platform      TEXT NOT NULL,
                target        TEXT,
                reason        TEXT,
                total_planned INTEGER DEFAULT 0,
                success       INTEGER DEFAULT 0,
                failed        INTEGER DEFAULT 0,
                status        TEXT DEFAULT 'running',
                started_at    TEXT,
                finished_at   TEXT
            )
        """)
        conn.commit()


def mark_stale_ops() -> None:
    """عملیات‌هایی که با ری‌استارت ربات نیمه‌کاره مانده‌اند را خطا علامت می‌زند."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE operations SET status = 'error', finished_at = ? WHERE status = 'running'",
            (tehran_now().isoformat(timespec="seconds"),),
        )
        conn.commit()


def get_user(telegram_id: int) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None


def upsert_user(telegram_id: int, **kwargs) -> None:
    existing = get_user(telegram_id)
    with sqlite3.connect(DB_PATH) as conn:
        if existing:
            if kwargs:
                sets = ", ".join(f"{k} = ?" for k in kwargs)
                conn.execute(
                    f"UPDATE users SET {sets} WHERE telegram_id = ?",
                    (*kwargs.values(), telegram_id),
                )
        else:
            kwargs["telegram_id"] = telegram_id
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" * len(kwargs))
            conn.execute(
                f"INSERT INTO users ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )
        conn.commit()


def add_stats(telegram_id: int, sent: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET total_reports = COALESCE(total_reports, 0) + ? WHERE telegram_id = ?",
            (sent, telegram_id),
        )
        conn.commit()


def get_all_users() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM users").fetchall()
    return [dict(r) for r in rows]


def count_users() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def is_premium_active(user: dict | None) -> bool:
    """اشتراک وقتی فعال است که هم زمانش نگذشته باشد هم سقف گزارش باقی داشته باشد.
    sub_quota = 0 یعنی بدون سقف (فقط محدود به زمان)."""
    if not user or not user.get("is_premium"):
        return False
    until = user.get("premium_until")
    if not until:
        return False
    try:
        if datetime.now() >= datetime.fromisoformat(until):
            return False
    except (ValueError, TypeError):
        return False
    quota = user.get("sub_quota") or 0
    used = user.get("sub_used") or 0
    return quota <= 0 or used < quota


def is_premium(telegram_id: int) -> bool:
    return is_premium_active(get_user(telegram_id))


def has_tg_access(telegram_id: int) -> bool:
    """دسترسی به ریپورتر تلگرام: دسترسی اختصاصی + اشتراک فعال."""
    user = get_user(telegram_id)
    if not user:
        return False
    return bool(user.get("tg_access")) and is_premium_active(user)


def limit_of(telegram_id: int) -> int:
    return PREMIUM_LIMIT if is_premium(telegram_id) else FREE_LIMIT


def remaining_quota(telegram_id: int) -> Optional[int]:
    """باقی‌مانده سقف اشتراک.
    None یعنی محدودیتی از طرف اشتراک نیست (کاربر رایگان/منقضی → سقف رایگان)."""
    user = get_user(telegram_id)
    if not user or not is_premium_active(user):
        return None
    quota = user.get("sub_quota") or 0
    if quota <= 0:
        return None
    return max(1, quota - (user.get("sub_used") or 0))


def grant_subscription(telegram_id: int, quota: int, hours: int,
                       sub_type: str = "gift", tg_access: bool = True) -> None:
    """اشتراک سفارشی: سقف گزارش + مدت به ساعت. مقدار قبلی جایگزین می‌شود."""
    now = datetime.now()
    until = now + timedelta(hours=max(1, int(hours)))
    upsert_user(
        telegram_id,
        is_premium=1,
        premium_until=until.isoformat(),
        sub_quota=int(quota),
        sub_used=0,
        sub_type=sub_type,
        sub_granted_at=now.isoformat(timespec="seconds"),
        tg_access=1 if tg_access else 0,
    )


def set_premium(telegram_id: int, months: int = 1, hours: int = 0, days: int = 0,
                quota: int = 0, sub_type: str = "gift") -> None:
    """سازگاری با کد قبلی."""
    total_hours = months * 30 * 24 + days * 24 + hours
    grant_subscription(telegram_id, quota, total_hours, sub_type=sub_type, tg_access=True)


def extend_subscription(telegram_id: int, add_quota: int, add_hours: int,
                        sub_type: str = "gift", tg_access: bool = False) -> None:
    """اشتراک فعلی را تمدید/تقویت می‌کند: سقف باقی‌مانده + سقف جدید و زمان از انتهای فعلی."""
    now = datetime.now()
    user = get_user(telegram_id)
    base = now
    quota = 0
    used = 0
    was_premium = is_premium_active(user)
    if was_premium:
        try:
            base = datetime.fromisoformat(user["premium_until"])
        except (ValueError, TypeError):
            base = now
        quota = user.get("sub_quota") or 0
        used = user.get("sub_used") or 0

    until = base + timedelta(hours=max(1, int(add_hours)))
    if quota <= 0 and was_premium:
        new_quota = 0                      # از قبل بی‌نهایت بوده
    else:
        new_quota = max(0, quota - used) + max(0, int(add_quota))

    kwargs = dict(
        is_premium=1,
        premium_until=until.isoformat(),
        sub_quota=new_quota,
        sub_used=0,
        sub_type=(user.get("sub_type") or sub_type) if was_premium else sub_type,
        sub_granted_at=now.isoformat(timespec="seconds"),
    )
    # دسترسی تلگرام فقط وقتی صریحاً خواسته شود؛ هرگز پس گرفته نمی‌شود
    if tg_access:
        kwargs["tg_access"] = 1
    upsert_user(telegram_id, **kwargs)


def consume_reports(telegram_id: int, amount: int) -> None:
    user = get_user(telegram_id)
    if user:
        used = (user.get("sub_used") or 0) + int(amount)
        upsert_user(telegram_id, sub_used=used)
    add_stats(telegram_id, amount)


def mask_phone(phone: str | None) -> str:
    """شماره را برای حریم خصوصی مخفی می‌کند: 98******1234"""
    if not phone:
        return "-"
    p = str(phone)
    if len(p) <= 4:
        return "*" * len(p)
    return p[:2] + "*" * max(3, len(p) - 6) + p[-4:]


# ── لاگ گزارش‌ها و اهداف ──
def log_report(telegram_id: int, platform: str, target: str, target_type: str,
               reason: str, success: int, failed: int) -> None:
    now = tehran_now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO report_logs (telegram_id, platform, target, target_type, reason, success, failed, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (telegram_id, platform, str(target), target_type, reason, int(success), int(failed), now),
        )
        conn.execute(
            "INSERT INTO targets (telegram_id, platform, target, target_type, total_success, total_failed, first_at, last_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(telegram_id, platform, target) DO UPDATE SET "
            "total_success = total_success + excluded.total_success, "
            "total_failed = total_failed + excluded.total_failed, "
            "target_type = excluded.target_type, last_at = excluded.last_at",
            (telegram_id, platform, str(target), target_type, int(success), int(failed), now, now),
        )
        conn.commit()


def get_user_targets(telegram_id: int) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM targets WHERE telegram_id = ? ORDER BY last_at DESC", (telegram_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_user_logs(telegram_id: int, limit: int = 15) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM report_logs WHERE telegram_id = ? ORDER BY id DESC LIMIT ?",
            (telegram_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def set_target_status(telegram_id: int, platform: str, target: str, status: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE targets SET status = ? WHERE telegram_id = ? AND platform = ? AND target = ?",
            (status, telegram_id, platform, str(target)),
        )
        conn.commit()


def target_status_label(status: str) -> str:
    return {
        "active": "🟢 سالم",
        "suspended": "🔴 تعلیق/مسدود",
        "unknown": "⚪ نامشخص",
    }.get(status, "⚪ نامشخص")


def sub_type_label(sub_type: str | None) -> str:
    return {
        "paid": "💳 خرید اشتراک",
        "gift": "🎁 اهدایی ادمین",
        "reward": "🎲 جایزه روزانه",
        "free": "🆓 رایگان",
    }.get(sub_type or "free", "🆓 رایگان")


# ── زمان تهران (برای نمایش تاریخ و ساعت) ──
try:
    from zoneinfo import ZoneInfo
    TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except Exception:  # اگر بسته tzdata روی سرور نصب نباشد
    TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def tehran_now() -> datetime:
    return datetime.now(TEHRAN_TZ)


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    return None


def to_tehran(value) -> datetime | None:
    """تبدیل هر تاریخ/ساعت ذخیره‌شده به وقت تهران."""
    dt = _parse_dt(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        raw = str(value)
        # datetime.now() (با T) = ساعت محلی سرور؛ پیش‌فرض SQLite (با فاصله) = UTC
        dt = dt.astimezone() if "T" in raw else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TEHRAN_TZ)


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد، بدون کتابخانه خارجی)."""
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def jalali_date(value) -> str:
    """تاریخ شمسی به شکل YYYY/MM/DD بر اساس وقت تهران."""
    dt = to_tehran(value)
    if dt is None:
        return "-"
    jy, jm, jd = _gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def now_label() -> str:
    """تاریخ میلادی + شمسی و ساعت، به وقت تهران."""
    dt = tehran_now()
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} | شمسی: {jalali_date(dt)} (تهران)"


# ── عملیات (زنده / تاریخچه) ──
def op_start(telegram_id: int, platform: str, target: str, reason: str, total: int) -> int:
    now = tehran_now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO operations (telegram_id, platform, target, reason, total_planned, started_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'running')",
            (telegram_id, platform, str(target), reason, int(total), now),
        )
        conn.commit()
        return int(cur.lastrowid)


def op_progress(op_id: int, success: int, failed: int, status: str | None = None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        if status:
            conn.execute(
                "UPDATE operations SET success = success + ?, failed = failed + ?, status = ?, "
                "finished_at = CASE WHEN ? IN ('done','stopped','error') THEN ? ELSE finished_at END "
                "WHERE id = ?",
                (int(success), int(failed), status, status,
                 tehran_now().isoformat(timespec="seconds"), op_id),
            )
        else:
            conn.execute(
                "UPDATE operations SET success = success + ?, failed = failed + ? WHERE id = ?",
                (int(success), int(failed), op_id),
            )
        conn.commit()


def get_running_ops(telegram_id: Optional[int] = None) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if telegram_id is None:
            rows = conn.execute(
                "SELECT * FROM operations WHERE status = 'running' ORDER BY id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM operations WHERE status = 'running' AND telegram_id = ? ORDER BY id DESC",
                (telegram_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_user_ops(telegram_id: int, limit: int = 10) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM operations WHERE telegram_id = ? ORDER BY id DESC LIMIT ?",
            (telegram_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    dt = to_tehran(value)
    if dt is None:
        return str(value).replace("T", " ")[:19]
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} | شمسی: {jalali_date(dt)}"


# ── اکانت‌های روبیکا ──
def _run_account_write(fn) -> None:
    """نوشتن اکانت در دیتابیس؛ اگر قید قدیمی «یک اکانت» جلویش را گرفت، جدول را ترمیم و دوباره تلاش می‌کند."""
    try:
        fn()
    except sqlite3.IntegrityError:
        logger.warning("IntegrityError در ثبت اکانت؛ تلاش برای ترمیم جدول اکانت‌ها...")
        init_db()
        fn()


# ── اکانت‌های روبیکا ──
def _rb_phone_key(phone: str | None) -> str:
    """کلید یکسان شماره روبیکا (۰۹۱۲...، ۹۸۹۱۲... و +۹۸۹۱۲... یکی می‌شوند)."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    elif len(digits) == 12 and digits.startswith("98"):
        digits = digits[2:]
    return digits


def add_rubika_account(tg_id: int, phone: str, session_path: str,
                       auth: str, private_key: str) -> None:
    def _write() -> None:
        with sqlite3.connect(DB_PATH) as conn:
            # حذف رکوردهای تکراری همان شماره با هر قالبی
            key = _rb_phone_key(phone)
            dup_ids = [
                r[0] for r in conn.execute(
                    "SELECT id, phone FROM rubika_accounts WHERE telegram_id = ?", (tg_id,)
                ).fetchall()
                if _rb_phone_key(r[1]) == key
            ]
            for dup_id in dup_ids:
                conn.execute(
                    "DELETE FROM rubika_accounts WHERE id = ? AND telegram_id = ?",
                    (dup_id, tg_id),
                )
            conn.execute(
                "INSERT INTO rubika_accounts (telegram_id, phone, session_path, auth, private_key) "
                "VALUES (?, ?, ?, ?, ?)",
                (tg_id, phone, session_path, auth, private_key),
            )
            conn.commit()

    _run_account_write(_write)
    upsert_user(tg_id, phone=phone, rubika_session=session_path,
                rubika_auth=auth, rubika_private_key=private_key)


def get_rubika_accounts(tg_id: int) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM rubika_accounts WHERE telegram_id = ? ORDER BY id", (tg_id,)
        ).fetchall()
    seen: set[str] = set()
    result: list[dict] = []
    for row in rows:
        acc = dict(row)
        key = _rb_phone_key(acc.get("phone") or "") or f"id:{acc['id']}"
        if key in seen:
            continue
        seen.add(key)
        result.append(acc)
    return result


def delete_rubika_account(tg_id: int, acc_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT phone, session_path FROM rubika_accounts WHERE id = ? AND telegram_id = ?",
            (acc_id, tg_id),
        ).fetchone()
        key = _rb_phone_key(row["phone"]) if row else ""
        if row:
            cleanup_session_files(row["session_path"])
        conn.execute(
            "DELETE FROM rubika_accounts WHERE id = ? AND telegram_id = ?",
            (acc_id, tg_id),
        )
        if key:
            dups = conn.execute(
                "SELECT id, phone, session_path FROM rubika_accounts WHERE telegram_id = ?",
                (tg_id,),
            ).fetchall()
            for dup in dups:
                if _rb_phone_key(dup["phone"]) == key:
                    cleanup_session_files(dup["session_path"])
                    conn.execute(
                        "DELETE FROM rubika_accounts WHERE id = ? AND telegram_id = ?",
                        (dup["id"], tg_id),
                    )
        conn.commit()


def get_rubika_sessions(tg_id: int) -> list[str]:
    """سشن‌های معتبر روبیکای همان کاربر."""
    result = []
    for acc in get_rubika_accounts(tg_id):
        if session_exists(acc["session_path"]):
            result.append(acc["session_path"])
    return result


def get_all_rubika_sessions() -> list[str]:
    """سشن‌های معتبر همه کاربران (بانک مشترک) — هر شماره یک‌بار."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT phone, session_path FROM rubika_accounts ORDER BY id"
        ).fetchall()
    seen: set[str] = set()
    result: list[str] = []
    for row in rows:
        if not session_exists(row["session_path"]):
            continue
        key = _rb_phone_key(row["phone"])
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(row["session_path"])
    return result


# ── بانک مشترک اکانت‌ها (اکانت‌های همه کاربران) ──
POOL_ME = "me"
POOL_ALL = "global"


def rubika_pool(tg_id: int, mode: str | None = POOL_ALL) -> list[str]:
    """سشن‌های روبیکا برای گزارش.

    در حالت پیش‌فرض (بانک مشترک) اکانت‌های خودِ کاربر اول فهرست می‌شوند،
    بعد اکانت‌های بقیه کاربران — هر شماره فقط یک‌بار.
    """
    if mode == POOL_ME:
        return get_rubika_sessions(tg_id)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT telegram_id, phone, session_path FROM rubika_accounts "
            "ORDER BY CASE WHEN telegram_id = ? THEN 0 ELSE 1 END, id",
            (tg_id,),
        ).fetchall()

    seen: set[str] = set()
    result: list[str] = []
    for row in rows:
        if not session_exists(row["session_path"]):
            continue
        key = _rb_phone_key(row["phone"]) or row["session_path"]
        if key in seen:
            continue
        seen.add(key)
        result.append(row["session_path"])
    return result


def tg_pool(tg_id: int, mode: str | None = POOL_ALL) -> list[dict]:
    """اکانت‌های تلگرام برای گزارش (اکانت‌های خودِ کاربر اول، بعد دیگران)."""
    if mode == POOL_ME:
        return get_tg_accounts(tg_id)

    seen: set[str] = set()
    result: list[dict] = []
    for acc in list(get_tg_accounts(tg_id)) + get_all_tg_accounts():
        key = tg_phone_key(acc.get("phone") or "") or f"id:{acc.get('id')}"
        if key in seen:
            continue
        seen.add(key)
        result.append(acc)
    return result


# ── اکانت‌های تلگرام ──
def add_tg_account(tg_id: int, phone: str, session_str: str, label: str = "") -> None:
    def _write() -> None:
        with sqlite3.connect(DB_PATH) as conn:
            # حذف رکوردهای تکراری همان شماره با هر قالبی (۰۹۱۲... / +۹۸۹۱۲... / ۹۸۹۱۲...)
            key = tg_phone_key(phone)
            dup_ids = [
                r[0] for r in conn.execute(
                    "SELECT id, phone FROM telegram_accounts WHERE telegram_id = ?", (tg_id,)
                ).fetchall()
                if tg_phone_key(r[1]) == key
            ]
            for dup_id in dup_ids:
                conn.execute(
                    "DELETE FROM telegram_accounts WHERE id = ? AND telegram_id = ?",
                    (dup_id, tg_id),
                )
            conn.execute(
                "INSERT INTO telegram_accounts (telegram_id, phone, session_str, label) "
                "VALUES (?, ?, ?, ?)",
                (tg_id, phone, session_str, label),
            )
            conn.commit()

    _run_account_write(_write)


def get_tg_accounts(tg_id: int) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM telegram_accounts WHERE telegram_id = ? ORDER BY id", (tg_id,)
        ).fetchall()
    seen: set[str] = set()
    result: list[dict] = []
    for row in rows:
        acc = dict(row)
        key = tg_phone_key(acc.get("phone") or "") or f"id:{acc['id']}"
        if key in seen:
            continue
        seen.add(key)
        result.append(acc)
    return result


def get_all_tg_accounts() -> list[dict]:
    """کل اکانت‌های تلگرام ثبت‌شده در ربات (بانک مشترک) — هر شماره یک‌بار."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM telegram_accounts ORDER BY id").fetchall()
    seen: set[str] = set()
    result: list[dict] = []
    for row in rows:
        acc = dict(row)
        key = tg_phone_key(acc.get("phone") or "") or f"id:{acc['id']}"
        if key in seen:
            continue
        seen.add(key)
        result.append(acc)
    return result


def get_tg_account(tg_id: int, acc_id: int) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM telegram_accounts WHERE id = ? AND telegram_id = ?",
            (acc_id, tg_id),
        ).fetchone()
    return dict(row) if row else None


def delete_tg_account(tg_id: int, acc_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, phone FROM telegram_accounts WHERE id = ? AND telegram_id = ?",
            (acc_id, tg_id),
        ).fetchone()
        key = tg_phone_key(row[1]) if row else ""
        conn.execute(
            "DELETE FROM telegram_accounts WHERE id = ? AND telegram_id = ?",
            (acc_id, tg_id),
        )
        if key:
            dup_ids = [
                r[0] for r in conn.execute(
                    "SELECT id, phone FROM telegram_accounts WHERE telegram_id = ?", (tg_id,)
                ).fetchall()
                if tg_phone_key(r[1]) == key
            ]
            for dup_id in dup_ids:
                conn.execute(
                    "DELETE FROM telegram_accounts WHERE id = ? AND telegram_id = ?",
                    (dup_id, tg_id),
                )
        conn.commit()


# ══════════════════════════════════════════════════════════════════════
#  ابزارهای کمکی
# ══════════════════════════════════════════════════════════════════════
SESSION_EXTENSIONS = (".rp", ".rubika", ".session")
GUID_PREFIXES = ("u0", "c0", "g0", "b0", "m0", "s0", "o0", "p0", "ch0", "t0", "e0")


def _normalize_phone(phone: str) -> Optional[str]:
    """نرمال‌سازی شماره ایرانی (روبیکا)."""
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    phone = phone.translate(trans)
    phone = re.sub(r"[^\d+]", "", phone)
    if phone.startswith("+98"):
        phone = "98" + phone[3:]
    elif phone.startswith("0098"):
        phone = "98" + phone[4:]
    elif phone.startswith("0"):
        phone = "98" + phone[1:]
    elif not phone.startswith("98") and len(phone) == 10:
        phone = "98" + phone
    if re.match(r"^98\d{10}$", phone):
        return phone
    return None


def validate_tg_phone(phone: str) -> bool:
    if not phone.startswith("+"):
        return False
    clean = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if len(clean) < 8 or len(clean) > 16:
        return False
    return clean[1:].isdigit()


def normalize_tg_phone(raw: str | None) -> Optional[str]:
    """شماره تلگرام را به شکل +<کد کشور><شماره> برمی‌گرداند."""
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    text = (raw or "").translate(trans).strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if text.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):   # شماره محلی ایرانی
        digits = "98" + digits[1:]
    if len(digits) < 8 or len(digits) > 15:
        return None
    return "+" + digits


def tg_phone_key(phone: str | None) -> str:
    """کلید یکسان‌سازی شماره برای حذف تکراری‌ها (۰۹۱۲...، +۹۸۹۱۲... و ۹۸۹۱۲... یکی می‌شوند)."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    elif len(digits) == 12 and digits.startswith("98"):
        digits = digits[2:]
    return digits


def session_exists(session_path: str | None) -> bool:
    if not session_path:
        return False
    return any(os.path.isfile(session_path + ext) for ext in SESSION_EXTENSIONS) or os.path.isfile(session_path)


def cleanup_session_files(session_path: str | None) -> None:
    if not session_path:
        return
    for f in [session_path] + [session_path + ext for ext in SESSION_EXTENSIONS]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass


def looks_like_guid(text: str) -> bool:
    text = text.strip()
    if any(text.startswith(p) for p in GUID_PREFIXES):
        return bool(re.match(r"^(u0|c0|g0|b0|m0|s0|o0|p0|ch0|t0|e0)[A-Za-z0-9_\-]{6,}$", text))
    return False


def _search_guid_in(obj, _seen: set | None = None) -> Optional[str]:
    if _seen is None:
        _seen = set()
    if obj is None or isinstance(obj, (int, float, bool)):
        return None
    if isinstance(obj, str):
        return obj if looks_like_guid(obj) else None
    try:
        if id(obj) in _seen:
            return None
        _seen.add(id(obj))
    except TypeError:
        pass
    if isinstance(obj, dict):
        for v in obj.values():
            r = _search_guid_in(v, _seen)
            if r:
                return r
    else:
        for attr in dir(obj):
            if attr.startswith("_"):
                continue
            try:
                v = getattr(obj, attr)
            except Exception:
                continue
            if callable(v):
                continue
            r = _search_guid_in(v, _seen)
            if r:
                return r
    return None


def fmt_time(seconds: int) -> str:
    if seconds < 60:
        return f"{int(seconds)} ثانیه"
    if seconds < 3600:
        m, s = int(seconds) // 60, int(seconds) % 60
        return f"{m} دقیقه و {s} ثانیه" if s else f"{m} دقیقه"
    h, m = int(seconds) // 3600, (int(seconds) % 3600) // 60
    return f"{h} ساعت و {m} دقیقه" if m else f"{h} ساعت"


# ══════════════════════════════════════════════════════════════════════
#  عضویت اجباری
# ══════════════════════════════════════════════════════════════════════
async def check_user_membership(bot: Bot, user_id: int) -> bool:
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=f"@{channel}", user_id=user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                return False
        except Exception as exc:
            logger.warning("check_member @%s user=%d: %s (بات ادمین کانال نیست؟)", channel, user_id, exc)
            # اگر بررسی ممکن نبود، مانع ورود کاربر نشو
            continue
    return True


def kb_force_join() -> InlineKeyboardMarkup:
    buttons = []
    for ch in REQUIRED_CHANNELS:
        buttons.append([InlineKeyboardButton(text=f"📢 @{ch}", url=f"https://t.me/{ch}", style=ButtonStyle.PRIMARY)])
    buttons.append([InlineKeyboardButton(text="✅ بررسی عضویت", callback_data="check_join", style=ButtonStyle.SUCCESS)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ══════════════════════════════════════════════════════════════════════
#  لاگین روبیکا
# ══════════════════════════════════════════════════════════════════════
async def rubika_send_code(phone: str, pass_key: str = None) -> dict:
    tmp_path = os.path.join(RUBIKA_SESSIONS, f"tmp_{phone}_{random.randint(1000, 9999)}")
    client = RubikaClient(name=tmp_path)
    await client.connect()
    try:
        kwargs = {"phone_number": phone, "send_type": "SMS"}
        if pass_key is not None:
            kwargs["pass_key"] = pass_key
        result = await client.send_code(**kwargs)
        return {
            "status": result.status,
            "phone_code_hash": result.phone_code_hash,
            "hint_pass_key": getattr(result, "hint_pass_key", None),
        }
    except Exception as e:
        raise RuntimeError(f"خطا در ارسال کد: {e}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        cleanup_session_files(tmp_path)


async def rubika_sign_in(tg_id: int, phone: str, code: str, phone_code_hash: str) -> dict:
    session_name = f"rb_{tg_id}_{phone}"
    session_path = os.path.join(RUBIKA_SESSIONS, session_name)
    client = RubikaClient(name=session_path)
    await client.connect()
    try:
        public_key, private_key = Crypto.create_keys()
        result = await client.sign_in(
            phone_code=code,
            phone_number=phone,
            phone_code_hash=phone_code_hash,
            public_key=public_key,
        )
        if result.status != "OK":
            raise RuntimeError(f"خطا در ورود: {result.status}")

        decrypted_auth = Crypto.decrypt_RSA_OAEP(private_key, result.auth)
        client.auth = decrypted_auth
        client.key = Crypto.passphrase(decrypted_auth)
        client.decode_auth = Crypto.decode_auth(decrypted_auth)
        client.import_key = pkcs1_15_sig.new(RSA.import_key(private_key.encode()))
        client.private_key = private_key
        client.guid = result.user.user_guid

        client.session.insert(
            auth=decrypted_auth,
            guid=result.user.user_guid,
            user_agent=client.user_agent,
            phone_number=phone,
            private_key=private_key,
        )
        await client.register_device(device_model=session_name)
        await client.disconnect()
        return {
            "session_path": session_path,
            "auth": decrypted_auth,
            "private_key": private_key,
        }
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        cleanup_session_files(session_path)
        raise RuntimeError(f"خطا در ورود: {e}")


async def resolve_object_guid(session_path: str, text: str) -> Optional[str]:
    text = text.strip().lstrip("@").strip()
    if looks_like_guid(text):
        return text
    try:
        client = RubikaClient(name=session_path)
        async with client:
            result = await client.get_object_by_username(text)
            for attr in ("object_guid", "user_guid", "guid", "group_guid", "channel_guid"):
                val = getattr(result, attr, None)
                if val and looks_like_guid(val):
                    return val
            found = _search_guid_in(result)
            if found:
                return found
            logger.error("resolve_object_guid: شناسه‌ای پیدا نشد: %s", result)
            return None
    except Exception as exc:
        logger.error("resolve_object_guid: %s", exc)
        return None

# ══════════════════════════════════════════════════════════════════════
#  کیبوردها (دکمه‌های رنگی)
# ══════════════════════════════════════════════════════════════════════
def btn(text: str, data: str | None = None, style: ButtonStyle = ButtonStyle.PRIMARY,
        url: str | None = None) -> InlineKeyboardButton:
    if url:
        return InlineKeyboardButton(text=text, url=url, style=style)
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def kb_main(tg_id: int) -> InlineKeyboardMarkup:
    prem = is_premium(tg_id)
    plan = "⭐ اشتراک فعال" if prem else "💎 خرید اشتراک"
    rows = [
        [
            btn("🚨 ریپورتر روبیکا", "menu_rubika", ButtonStyle.DANGER),
            btn("🚀 ریپورتر تلگرام", "menu_telegram", ButtonStyle.PRIMARY),
        ],
        [
            btn("📡 عملیات زنده", "live_ops", ButtonStyle.SUCCESS),
            btn("🎯 اهداف من", "my_targets", ButtonStyle.PRIMARY),
        ],
        [
            btn("📋 تاریخچه گزارش‌ها", "my_history", ButtonStyle.PRIMARY),
            btn("📊 وضعیت حساب", "account_status", ButtonStyle.PRIMARY),
        ],
        [
            btn(plan, "subscription", ButtonStyle.SUCCESS),
            btn("🎁 جایزه روزانه", "daily_reward", ButtonStyle.SUCCESS),
        ],
        [
            btn("🔗 لینک دعوت", "referral_link", ButtonStyle.PRIMARY),
            btn("❓ راهنما", "help", ButtonStyle.PRIMARY),
        ],
        [
            btn("📞 پشتیبانی", "support", ButtonStyle.DANGER),
        ],
    ]
    if tg_id in ADMIN_IDS:
        rows.append([btn("🛠 پنل مدیریت", "admin_open", ButtonStyle.SUCCESS)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_menu_return() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("🔙 بازگشت به منو", "back_menu", ButtonStyle.PRIMARY)],
    ])


def kb_tg_resend() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("♻️ ارسال کد جدید", "tg_resend", ButtonStyle.SUCCESS)],
        [btn("🔙 بازگشت به منو", "back_menu", ButtonStyle.PRIMARY)],
    ])


def kb_rubika(tg_id: int) -> InlineKeyboardMarkup:
    accounts = get_rubika_accounts(tg_id)
    rows = [
        [
            btn("🚨 ثبت گزارش روبیکا", "rb_report", ButtonStyle.DANGER),
            btn("➕ افزودن اکانت", "rb_add", ButtonStyle.SUCCESS),
        ],
        [
            btn(f"📱 اکانت‌های من ({len(accounts)})", "rb_accounts", ButtonStyle.PRIMARY),
            btn("📊 وضعیت حساب", "account_status", ButtonStyle.PRIMARY),
        ],
        [btn("🔙 بازگشت به منو", "back_menu", ButtonStyle.PRIMARY)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_telegram(tg_id: int) -> InlineKeyboardMarkup:
    accounts = get_tg_accounts(tg_id)
    rows = [
        [
            btn("📝 ریپورت کانال/گروه", "tgr_channel", ButtonStyle.DANGER),
            btn("📝 ریپورت پست", "tgr_post", ButtonStyle.DANGER),
        ],
        [
            btn("👤 ریپورت پروفایل", "tgr_profile", ButtonStyle.PRIMARY),
            btn("🤖 ریپورت ربات", "tgr_bot", ButtonStyle.PRIMARY),
        ],
        [
            btn("👤 ریپورت اکانت", "tgr_account", ButtonStyle.PRIMARY),
            btn("📋 ریپورت دستی", "tgr_manual", ButtonStyle.PRIMARY),
        ],
        [
            btn(f"➕ افزودن اکانت تلگرام", "tga_add", ButtonStyle.SUCCESS),
            btn(f"📱 اکانت‌های من ({len(accounts)})", "tga_list", ButtonStyle.PRIMARY),
        ],
        [
            btn("🔙 بازگشت به منو", "back_menu", ButtonStyle.PRIMARY),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_report_types(selected) -> InlineKeyboardMarkup:
    # ترتیب انتخاب کاربر حفظ می‌شود (اولین انتخاب، اول اجرا می‌شود)
    if isinstance(selected, (list, tuple)):
        order = [k for k in selected if k in REPORT_TYPES_MAP]
    else:
        order = [k for k in REPORT_TYPES_MAP if k in (selected or ())]

    buttons = []
    for k, (label, _) in REPORT_TYPES_MAP.items():
        if k in order:
            text = f"✅ {label} ({order.index(k) + 1})"
            style = ButtonStyle.SUCCESS
        else:
            text = f"⬜ {label}"
            style = ButtonStyle.PRIMARY
        buttons.append([btn(text, f"rt_{k}", style)])
    buttons.append([
        btn("✅ انتخاب همه", "rt_all", ButtonStyle.SUCCESS),
        btn("🗑 پاک کردن", "rt_clear", ButtonStyle.DANGER),
    ])
    buttons.append([btn("▶️ شروع گزارش", "rt_confirm", ButtonStyle.SUCCESS)])
    buttons.append([btn("🔙 بازگشت", "menu_rubika", ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_running() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("📡 عملیات زنده", "live_ops", ButtonStyle.SUCCESS)],
        [btn("🛑 توقف", "stop_op", ButtonStyle.DANGER)],
    ])


def kb_reason() -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for k, (label, _, _) in TG_REASONS.items():
        row.append(btn(label, f"tgreason_{k}", ButtonStyle.PRIMARY))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([btn("🔙 بازگشت", "menu_telegram", ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_join_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            btn("✅ جوین بشن", "tgjoin_yes", ButtonStyle.SUCCESS),
            btn("❌ جوین نشن", "tgjoin_no", ButtonStyle.DANGER),
        ],
        [btn("🔙 بازگشت", "menu_telegram", ButtonStyle.PRIMARY)],
    ])


def kb_buy() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("💎 خرید اشتراک", "subscription", ButtonStyle.SUCCESS)],
        [btn("📞 پشتیبانی", "support", ButtonStyle.DANGER)],
        [btn("🔙 بازگشت به منو", "back_menu", ButtonStyle.PRIMARY)],
    ])


def kb_support() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("🔙 بازگشت به منو", "back_menu", ButtonStyle.PRIMARY)],
    ])


def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            btn("👥 مدیریت کاربران", "admin_list", ButtonStyle.PRIMARY),
            btn("📊 آمار ربات", "admin_stats", ButtonStyle.PRIMARY),
        ],
        [
            btn("📡 عملیات زنده", "admin_live", ButtonStyle.SUCCESS),
            btn("👑 تمدید اشتراک", "admin_grant", ButtonStyle.SUCCESS),
        ],
        [
            btn("📢 پیام همگانی", "admin_broadcast", ButtonStyle.SUCCESS),
            btn("🎫 پشتیبانی", "admin_support", ButtonStyle.DANGER),
        ],
        [
            btn("🚪 خروج از پنل", "admin_exit", ButtonStyle.DANGER),
        ],
    ])


def kb_admin_reply(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("💬 پاسخ به کاربر", f"admin_reply_{user_id}", ButtonStyle.PRIMARY)],
        [btn("🚫 بستن", "admin_close_ticket", ButtonStyle.DANGER)],
    ])


# ══════════════════════════════════════════════════════════════════════
#  شروع / منو
# ══════════════════════════════════════════════════════════════════════
async def cmd_start(message: Message, command: CommandStart, state: FSMContext) -> None:
    bot = message.bot
    tg_id = message.from_user.id
    await state.clear()

    args = (command.args or "").split()
    if args and args[0].startswith("ref_"):
        try:
            referrer_id = int(args[0][4:])
            if referrer_id != tg_id:
                await state.update_data(referrer_id=referrer_id)
        except (ValueError, IndexError):
            pass

    is_member = await check_user_membership(bot, tg_id)
    if not is_member:
        await message.answer(
            "⛔ برای استفاده از ربات ابتدا باید در کانال‌های زیر عضو شوید:\n\n"
            "بعد از عضویت، دکمه «بررسی عضویت» را بزنید:",
            reply_markup=kb_force_join(),
        )
        return

    upsert_user(tg_id)
    prem = is_premium(tg_id)
    await message.answer(
        "👋 به ربات ریپورتر خوش آمدید!\n\n"
        "یکی از بخش‌های زیر را انتخاب کنید:\n"
        "🚨 <b>ریپورتر روبیکا</b> — رایگان تا ۱۰۰ گزارش\n"
        "🚀 <b>ریپورتر تلگرام</b> — نیازمند اشتراک\n\n"
        f"وضعیت شما: {'⭐ اشتراکی' if prem else '🆓 رایگان'}",
        reply_markup=kb_main(tg_id),
        parse_mode="HTML",
    )
    await state.set_state(Form.main_menu)


async def check_join_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id

    if not await check_user_membership(callback.bot, tg_id):
        await callback.message.answer(
            "❌ هنوز در کانال‌ها عضو نشدید!\n\n"
            "لطفاً ابتدا در هر دو کانال عضو شوید و سپس «بررسی عضویت» را بزنید:",
            reply_markup=kb_force_join(),
        )
        return

    upsert_user(tg_id)
    await callback.message.answer(
        "✅ عضویت تایید شد! 👋\nمنوی اصلی:",
        reply_markup=kb_main(tg_id),
    )
    await state.set_state(Form.main_menu)


async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    await callback.message.answer("🏠 منوی اصلی:", reply_markup=kb_main(tg_id))
    await state.set_state(Form.main_menu)


async def account_status(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    user = get_user(tg_id)
    prem = is_premium_active(user)
    limit = PREMIUM_LIMIT if prem else FREE_LIMIT
    plan = sub_type_label(user.get("sub_type") if user else "free") if prem else "🆓 رایگان"

    quota = (user.get("sub_quota") or 0) if user else 0
    used = (user.get("sub_used") or 0) if user else 0
    if prem and quota > 0:
        quota_line = f"📦 سقف اشتراک: {quota} | مصرف‌شده: {used} | باقی‌مانده: {max(0, quota - used)}"
    elif prem:
        quota_line = "📦 سقف اشتراک: بدون محدودیت تعداد"
    else:
        quota_line = f"📦 سقف هر عملیات: {FREE_LIMIT} گزارش"

    until = ""
    if prem and user and user.get("premium_until"):
        until = f"\n⏳ انقضا: {fmt_dt(user['premium_until'])}"

    rb = len(get_rubika_accounts(tg_id))
    tg = len(get_tg_accounts(tg_id))
    tg_line = "🚀 ریپورتر تلگرام: " + ("فعال ✅" if has_tg_access(tg_id) else "غیرفعال ⛔")

    await callback.message.answer(
        f"📊 <b>وضعیت حساب</b>\n\n"
        f"پلن: {plan}{until}\n"
        f"{quota_line}\n"
        f"🎯 سقف هر نوع گزارش در هر عملیات: {limit}\n"
        f"{tg_line}\n"
        f"📱 اکانت روبیکا: {rb}\n"
        f"✈️ اکانت تلگرام: {tg}\n"
        f"📢 کل گزارش‌های ارسال‌شده: {user.get('total_reports', 0) if user else 0}",
        reply_markup=kb_menu_return(),
        parse_mode="HTML",
    )


async def subscription_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    user = get_user(tg_id)

    if is_premium_active(user):
        quota = user.get("sub_quota") or 0
        used = user.get("sub_used") or 0
        left = "بی‌نهایت" if quota <= 0 else str(max(0, quota - used))
        await callback.message.answer(
            f"👑 اشتراک شما فعال است.\n"
            f"📅 تا: {fmt_dt(user['premium_until'])}\n"
            f"📦 نوع: {sub_type_label(user.get('sub_type'))}\n"
            f"🎯 باقی‌مانده: {left}\n\n"
            f"🚀 ریپورتر تلگرام: {'فعال' if has_tg_access(tg_id) else 'غیرفعال'}\n\n"
            "برای تمدید یا افزایش سقف، رسید پرداخت جدید را بفرستید.",
            reply_markup=kb_menu_return(),
        )
        await state.set_state(Form.receipt)
        return

    await callback.message.answer(
        f"💎 <b>خرید اشتراک</b>\n\n"
        f"با خرید اشتراک:\n"
        f"• 🚀 ریپورتر تلگرام فعال می‌شود\n"
        f"• 🚨 سقف گزارش روبیکا تا {PREMIUM_LIMIT} در هر نوع می‌رسد\n"
        f"• 📦 {DEFAULT_SUB_QUOTA} گزارش در کل\n\n"
        f"💰 مبلغ: {PREMIUM_PRICE}\n"
        f"⏳ مدت: {PREMIUM_MONTHS} ماه\n\n"
        f"💳 شماره کارت:\n<code>{ADMIN_CARD_NUMBER}</code>\n\n"
        f"📸 بعد از پرداخت، <b>عکس رسید</b> را همین‌جا بفرستید تا ادمین تایید کند.",
        reply_markup=kb_menu_return(),
        parse_mode="HTML",
    )
    await state.set_state(Form.receipt)


async def help_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer(
        "❓ <b>راهنما</b>\n\n"
        "🚨 <b>ریپورتر روبیکا</b>\n"
        "۱) از منوی روبیکا اکانت اضافه کن (شماره + کد)\n"
        "۲) «ثبت گزارش روبیکا» را بزن\n"
        "۳) هدف را با یوزرنیم یا شناسه بفرست\n"
        "۴) نوع، تعداد، فاصله و تعداد اکانت را انتخاب کن\n\n"
        "🚀 <b>ریپورتر تلگرام</b> (نیازمند اشتراک)\n"
        "۱) اکانت تلگرام اضافه کن (شماره + کد + رمز دو مرحله‌ای)\n"
        "۲) نوع ریپورت را انتخاب کن\n"
        "۳) لینک/یوزرنیم هدف را بفرست\n"
        "۴) دلیل، تعداد هر اکانت و فاصله را بده\n\n"
        f"🆓 رایگان: {FREE_LIMIT} گزارش در هر نوع\n"
        f"💎 اشتراکی: {PREMIUM_LIMIT} گزارش در هر نوع\n\n"
        "⛔ توقف عملیات: /stop",
        reply_markup=kb_menu_return(),
        parse_mode="HTML",
    )


async def referral_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    user = get_user(tg_id)
    if not user:
        await callback.message.answer("ابتدا /start بزن.")
        return
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{tg_id}"
    await callback.message.answer(
        f"🔗 <b>لینک دعوت شما</b>\n\n<code>{ref_link}</code>\n\n"
        f"👥 تعداد دعوت‌ها: {user.get('total_invites', 0)}\n\n"
        "🎁 با هر نفری که با لینک شما عضو شود، ۱ ساعت اشتراک رایگان می‌گیرید.",
        reply_markup=kb_menu_return(),
        parse_mode="HTML",
    )


async def daily_reward_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    user = get_user(tg_id)
    if not user:
        await callback.message.answer("ابتدا /start بزن.")
        return

    now = datetime.now()
    last_reward = user.get("last_daily_reward")
    if last_reward:
        try:
            diff = now - datetime.fromisoformat(last_reward)
            if diff < timedelta(hours=24):
                remaining = timedelta(hours=24) - diff
                h = remaining.seconds // 3600
                m = (remaining.seconds % 3600) // 60
                await callback.message.answer(
                    f"⏳ جایزه بعدی در {h} ساعت و {m} دقیقه",
                    reply_markup=kb_menu_return(),
                )
                return
        except (ValueError, TypeError):
            pass

    dice_msg = await callback.message.answer("🎲")
    for dots in (".", "..", "..."):
        await asyncio.sleep(0.5)
        try:
            await dice_msg.edit_text(f"🎲 {dots}")
        except Exception:
            pass

    roll = random.randint(1, 6)
    if roll == 6:
        prize_days, prize_text = 3, "🏆 شماره ۶! اشتراک ۳ روزه برنده شدید!"
    elif roll in (4, 5):
        prize_days, prize_text = 1, "🎉 اشتراک ۱ روزه برنده شدید!"
    else:
        prize_days, prize_text = 0, f"😔 شماره {roll} آمد. برنده نشدید!"

    upsert_user(tg_id, last_daily_reward=now.isoformat())

    result = (
        "🎲 ━━━━━━━━━━━━━━━━ 🎲\n"
        f"       [ {roll} ]\n"
        "🎲 ━━━━━━━━━━━━━━━━ 🎲\n\n"
        f"{prize_text}"
    )

    if prize_days > 0:
        extend_subscription(
            tg_id,
            add_quota=300 if prize_days == 3 else 100,
            add_hours=prize_days * 24,
            sub_type="reward",
        )
        u = get_user(tg_id)
        result += (
            f"\n\n👑 اشتراک تا {fmt_dt(u['premium_until'])} فعال است."
            f"\n📦 سقف: {u.get('sub_quota', 0)} گزارش"
        )
        await dice_msg.edit_text(result, reply_markup=kb_main(tg_id))
    else:
        result += "\n\n💡 فردا دوباره امتحان کنید!"
        await dice_msg.edit_text(result, reply_markup=kb_menu_return())


# ══════════════════════════════════════════════════════════════════════
#  پشتیبانی + رسید اشتراک
# ══════════════════════════════════════════════════════════════════════
async def support_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer(
        "📞 <b>پشتیبانی</b>\n\n"
        "پیام، عکس یا فایل خود را بفرستید تا برای پشتیبانی ارسال شود.",
        reply_markup=kb_support(),
        parse_mode="HTML",
    )
    await state.set_state(Form.support_message)


async def receive_support_message(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    user = get_user(tg_id)

    sent = False
    for admin_id in ADMIN_IDS:
        try:
            forwarded = await message.forward(chat_id=admin_id)
            await forwarded.reply(
                "📨 پیام پشتیبانی جدید\n"
                f"🆔 تلگرام: {tg_id}",
                reply_markup=kb_admin_reply(tg_id),
            )
            sent = True
        except Exception as exc:
            logger.error("forward support to admin %d: %s", admin_id, exc)

    if sent:
        await message.answer(
            "✅ پیام شما برای پشتیبانی ارسال شد.\nمنتظر پاسخ بمانید.",
            reply_markup=kb_menu_return(),
        )
    else:
        await message.answer("❌ ارسال پیام به پشتیبانی ممکن نشد. بعداً تلاش کنید.")
    await state.set_state(Form.main_menu)


async def receive_receipt(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    user = get_user(tg_id)

    if not message.photo:
        await message.answer(
            "❌ لطفاً عکس رسید پرداخت (فیش واریز) را بفرستید.",
            reply_markup=kb_menu_return(),
        )
        return

    photo = message.photo[-1]
    approve_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        btn("✅ تایید", f"approve_sub_{tg_id}", ButtonStyle.SUCCESS),
        btn("❌ رد", f"reject_sub_{tg_id}", ButtonStyle.DANGER),
    ]])

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_photo(
                chat_id=admin_id,
                photo=photo.file_id,
                caption=(
                    "💎 رسید پرداخت اشتراک\n\n"
                    f"🆔 تلگرام: {tg_id}\n"
                    f"💰 مبلغ: {PREMIUM_PRICE}\n"
                    f"⏰ تاریخ: {now_label()}"
                ),
                reply_markup=approve_keyboard,
            )
        except Exception as exc:
            logger.error("Failed to send receipt to admin %d: %s", admin_id, exc)

    await message.answer(
        "✅ رسید شما برای ادمین ارسال شد!\n\n"
        f"💰 مبلغ: {PREMIUM_PRICE}\n\n"
        "⏳ منتظر تایید ادمین بمانید؛ پس از تایید اشتراک فعال می‌شود.",
        reply_markup=kb_menu_return(),
    )
    await state.set_state(Form.main_menu)


async def admin_approve_sub(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return
    await callback.answer()

    data = callback.data
    if data.startswith("approve_sub_"):
        target_id = int(data.split("_")[-1])
        grant_subscription(target_id, DEFAULT_SUB_QUOTA, PREMIUM_MONTHS * 30 * 24,
                           sub_type="paid", tg_access=True)
        try:
            await callback.message.edit_caption(
                caption=f"✅ اشتراک فعال شد!\n👤 کاربر: {target_id}", reply_markup=None
            )
        except Exception:
            pass
        try:
            user = get_user(target_id)
            until = fmt_dt(user.get("premium_until")) if user else ""
            await callback.bot.send_message(
                chat_id=target_id,
                text=(
                    "🎉 اشتراک شما فعال شد!\n\n"
                    f"👑 اشتراک تا {until} فعال است.\n"
                    f"📦 سقف: {user.get('sub_quota', 0) if user else 0} گزارش\n"
                    f"🚀 ریپورتر تلگرام فعال شد."
                ),
                reply_markup=kb_main(target_id),
            )
        except Exception as exc:
            logger.error("Failed to notify user %d: %s", target_id, exc)

    elif data.startswith("reject_sub_"):
        target_id = int(data.split("_")[-1])
        try:
            await callback.message.edit_caption(
                caption=f"❌ درخواست رد شد.\n👤 کاربر: {target_id}", reply_markup=None
            )
        except Exception:
            pass
        try:
            await callback.bot.send_message(
                chat_id=target_id,
                text="❌ درخواست اشتراک شما توسط ادمین رد شد.\nبرای اطلاعات بیشتر با پشتیبانی تماس بگیرید.",
            )
        except Exception as exc:
            logger.error("Failed to notify user %d: %s", target_id, exc)

# ══════════════════════════════════════════════════════════════════════
#  بخش کاربر: عملیات زنده / اهداف / تاریخچه
# ══════════════════════════════════════════════════════════════════════
PLATFORM_ICON = {"rubika": "🚨", "telegram": "🚀"}
OP_STATUS_LABEL = {
    "running": "🟡 در حال اجرا",
    "done": "🟢 تمام شد",
    "stopped": "🛑 متوقف شد",
    "error": "🔴 خطا",
}


async def live_ops_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    ops = get_running_ops(tg_id)

    if not ops:
        await callback.message.answer(
            "📡 <b>عملیات زنده</b>\n\n"
            "در حال حاضر هیچ عملیاتی در حال اجرا نیست.\n"
            "وقتی گزارش‌گیری شروع شود، پیشرفت لحظه‌ای همین‌جا نمایش داده می‌شود.\n\n"
            f"🕒 الان: {now_label()}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("🔄 بروزرسانی", "live_ops", ButtonStyle.SUCCESS)],
                [btn("🔙 منو", "back_menu", ButtonStyle.PRIMARY)],
            ]),
            parse_mode="HTML",
        )
        return

    lines = [
        "📡 <b>عملیات زنده</b>\n",
        f"🕒 الان: {now_label()}\n",
    ]
    for op in ops[:5]:
        done = (op.get("success") or 0) + (op.get("failed") or 0)
        total = op.get("total_planned") or 0
        pct = int(done * 100 / total) if total else 0
        bar = "🟩" * (pct // 10) + "⬜" * (10 - pct // 10)
        lines.append(
            f"{PLATFORM_ICON.get(op['platform'], '•')} <b>{op['platform']}</b>\n"
            f"🎯 هدف: <code>{op.get('target', '-')}</code>\n"
            f"📝 دلیل: {op.get('reason', '-')}\n"
            f"{bar} {pct}%  ({done}/{total})\n"
            f"✅ {op.get('success', 0)} | ❌ {op.get('failed', 0)}\n"
            f"⏰ شروع (تهران): {fmt_dt(op.get('started_at'))}\n"
        )

    await callback.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("🔄 بروزرسانی", "live_ops", ButtonStyle.SUCCESS)],
            [btn("🛑 توقف عملیات", "stop_op", ButtonStyle.DANGER)],
            [btn("🔙 منو", "back_menu", ButtonStyle.PRIMARY)],
        ]),
        parse_mode="HTML",
    )


async def my_targets_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    targets = get_user_targets(tg_id)

    if not targets:
        await callback.message.answer(
            "🎯 <b>اهداف من</b>\n\n"
            "هنوز روی هیچ هدفی گزارش نزده‌اید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("🔙 منو", "back_menu", ButtonStyle.PRIMARY)],
            ]),
            parse_mode="HTML",
        )
        return

    suspended = [t for t in targets if t.get("status") == "suspended"]
    active = [t for t in targets if t.get("status") == "active"]
    lines = [
        "🎯 <b>اهداف من</b>\n",
        f"📌 مجموع: {len(targets)} | 🟢 سالم: {len(active)} | 🔴 تعلیق: {len(suspended)}\n",
    ]
    for t in targets[:15]:
        lines.append(
            f"{PLATFORM_ICON.get(t['platform'], '•')} <code>{t['target']}</code>\n"
            f"   وضعیت: {target_status_label(t.get('status'))}\n"
            f"   📢 {t.get('total_success', 0)} موفق / {t.get('total_failed', 0)} ناموفق\n"
            f"   🕐 آخرین: {fmt_dt(t.get('last_at'))}\n"
        )

    await callback.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("🔄 بررسی وضعیت اهداف", "refresh_targets", ButtonStyle.SUCCESS)],
            [btn("🔙 منو", "back_menu", ButtonStyle.PRIMARY)],
        ]),
        parse_mode="HTML",
    )


async def my_history_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    ops = get_user_ops(tg_id, 12)

    if not ops:
        await callback.message.answer(
            "📋 <b>تاریخچه گزارش‌ها</b>\n\n"
            "هنوز عملیاتی ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("🔙 منو", "back_menu", ButtonStyle.PRIMARY)],
            ]),
            parse_mode="HTML",
        )
        return

    lines = ["📋 <b>تاریخچه عملیات</b>\n"]
    for op in ops:
        lines.append(
            f"{PLATFORM_ICON.get(op['platform'], '•')} {OP_STATUS_LABEL.get(op.get('status'), '')}\n"
            f"🎯 <code>{op.get('target', '-')}</code>\n"
            f"📝 {op.get('reason', '-')}\n"
            f"✅ {op.get('success', 0)} | ❌ {op.get('failed', 0)} | 📦 {op.get('total_planned', 0)}\n"
            f"🕐 شروع (تهران): {fmt_dt(op.get('started_at'))}\n"
            f"🏁 پایان (تهران): {fmt_dt(op.get('finished_at'))}\n"
        )

    await callback.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("🔄 بروزرسانی", "my_history", ButtonStyle.SUCCESS)],
            [btn("🔙 منو", "back_menu", ButtonStyle.PRIMARY)],
        ]),
        parse_mode="HTML",
    )


def _tg_ban_errors() -> tuple:
    return (
        errors.ChannelPrivateError,
        errors.UsernameNotOccupiedError,
        errors.UserDeactivatedBanError,
        errors.UserDeactivatedError,
        errors.ChannelInvalidError,
        errors.PeerIdInvalidError,
    )


async def refresh_targets_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("🔄 در حال بررسی...")
    tg_id = callback.from_user.id
    targets = get_user_targets(tg_id)
    if not targets:
        await callback.message.answer("🎯 هنوز هدفی ثبت نکرده‌اید.")
        return

    checked = 0
    suspended = 0
    active = 0

    # ── بررسی اهداف تلگرام با اولین اکانت ──
    tg_targets = [t for t in targets if t["platform"] == "telegram"][:10]
    accounts = get_tg_accounts(tg_id)
    if tg_targets and accounts:
        client = TelegramClient(
            StringSession(accounts[0]["session_str"]),
            TELEGRAM_API_ID, TELEGRAM_API_HASH,
            device_model="Reporter", system_version="1.0",
        )
        try:
            await client.connect()
            if await client.is_user_authorized():
                for t in tg_targets:
                    checked += 1
                    try:
                        ent = await tg_resolve_entity(client, t["target"])
                        if ent:
                            set_target_status(tg_id, "telegram", t["target"], "active")
                            active += 1
                    except _tg_ban_errors():
                        set_target_status(tg_id, "telegram", t["target"], "suspended")
                        suspended += 1
                    except Exception:
                        pass
        except Exception as exc:
            logger.error("refresh_targets tg: %s", exc)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    # ── بررسی اهداف روبیکا (یوزرنیم‌ها) ──
    rb_targets = [t for t in targets if t["platform"] == "rubika"][:10]
    rb_sessions = rubika_pool(tg_id)
    if rb_targets and rb_sessions:
        for t in rb_targets:
            checked += 1
            target = t["target"]
            if looks_like_guid(target):
                continue
            try:
                resolved = await resolve_object_guid(rb_sessions[0], target)
                if resolved:
                    set_target_status(tg_id, "rubika", target, "active")
                    active += 1
                else:
                    set_target_status(tg_id, "rubika", target, "suspended")
                    suspended += 1
            except Exception:
                pass

    if checked == 0:
        await callback.message.answer(
            "ℹ️ برای بررسی وضعیت، حداقل یک اکانت (تلگرام یا روبیکا) لازم است.",
            reply_markup=kb_menu_return(),
        )
        return

    await callback.message.answer(
        "✅ بررسی وضعیت انجام شد.\n\n"
        f"🔍 بررسی‌شده: {checked}\n"
        f"🟢 سالم: {active}\n"
        f"🔴 تعلیق/مسدود: {suspended}\n"
        "⚠️ شناسه‌های دستی روبیکا قابل بررسی خودکار نیستند.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("🎯 اهداف من", "my_targets", ButtonStyle.PRIMARY)],
            [btn("🔙 منو", "back_menu", ButtonStyle.PRIMARY)],
        ]),
    )


async def stop_op_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    user_stop[tg_id] = True
    await callback.message.answer(
        "🛑 درخواست توقف ثبت شد. عملیات در حال اجرا در اولین فرصت متوقف می‌شود.",
        reply_markup=kb_menu_return(),
    )


# ══════════════════════════════════════════════════════════════════════
#  روبیکا — منو و مدیریت اکانت‌ها
# ══════════════════════════════════════════════════════════════════════
async def menu_rubika_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    accounts = get_rubika_accounts(tg_id)
    await callback.message.answer(
        "🚨 <b>ریپورتر روبیکا</b>\n\n"
        f"📱 اکانت‌های ثبت‌شده: {len(accounts)}\n"
        f"🌍 کل اکانت‌های ربات: {len(get_all_rubika_sessions())}\n"
        f"🎯 سقف فعلی هر نوع گزارش: {limit_of(tg_id)}\n\n"
        "از دکمه‌های زیر استفاده کنید:",
        reply_markup=kb_rubika(tg_id),
        parse_mode="HTML",
    )
    await state.set_state(Form.main_menu)


ACCOUNTS_PER_PAGE = 8


def _page_of(data: str, prefix: str, default: int = 0) -> int:
    if not data.startswith(prefix):
        return default
    try:
        return max(0, int(data[len(prefix):]))
    except (ValueError, TypeError):
        return default


def _pager_row(prefix: str, page: int, pages: int) -> list:
    row = []
    if page > 0:
        row.append(btn("◀️ قبلی", f"{prefix}{page - 1}", ButtonStyle.PRIMARY))
    row.append(btn(f"صفحه {page + 1}/{pages}", "noop", ButtonStyle.PRIMARY))
    if page + 1 < pages:
        row.append(btn("بعدی ▶️", f"{prefix}{page + 1}", ButtonStyle.PRIMARY))
    return row


async def rb_accounts_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    page = _page_of(callback.data or "", "rb_acc_")
    accounts = get_rubika_accounts(tg_id)
    if not accounts:
        await callback.message.answer(
            "📱 هنوز اکانت روبیکایی اضافه نکرده‌اید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("➕ افزودن اکانت", "rb_add", ButtonStyle.SUCCESS)],
                [btn("🔙 بازگشت", "menu_rubika", ButtonStyle.PRIMARY)],
            ]),
        )
        return

    per = ACCOUNTS_PER_PAGE
    pages = max(1, (len(accounts) + per - 1) // per)
    page = min(page, pages - 1)
    chunk = accounts[page * per:(page + 1) * per]

    rows = []
    for acc in chunk:
        valid = "🟢" if session_exists(acc["session_path"]) else "🔴"
        rows.append([btn(f"{valid} {mask_phone(acc['phone'])}  🗑 حذف", f"rb_del_{acc['id']}", ButtonStyle.DANGER)])
    if pages > 1:
        rows.append(_pager_row("rb_acc_", page, pages))
    rows.append([btn("➕ افزودن اکانت جدید", "rb_add", ButtonStyle.SUCCESS)])
    rows.append([btn("🔙 بازگشت", "menu_rubika", ButtonStyle.PRIMARY)])

    await callback.message.answer(
        f"📱 <b>اکانت‌های روبیکا</b>\n"
        f"📊 مجموع اکانت‌های شما: {len(accounts)}\n"
        f"🌍 مجموع اکانت‌های ربات: {len(get_all_rubika_sessions())}\n"
        "برای حفظ حریم خصوصی، شماره‌ها مخفی نمایش داده می‌شوند.\n"
        "روی هر اکانت بزنید تا حذف شود:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )


async def rb_delete_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    try:
        acc_id = int(callback.data.split("_")[-1])
    except ValueError:
        return
    delete_rubika_account(tg_id, acc_id)
    await callback.message.answer("✅ اکانت حذف شد.", reply_markup=kb_rubika(tg_id))


# ══════════════════════════════════════════════════════════════════════
#  روبیکا — افزودن اکانت
# ══════════════════════════════════════════════════════════════════════
async def rb_add_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer(
        "📱 شماره روبیکا را بفرستید:\nمثال: 09123456789",
        reply_markup=kb_menu_return(),
    )
    await state.set_state(Form.rb_phone)


async def rb_receive_phone(message: Message, state: FSMContext) -> None:
    if message.contact:
        phone_raw = message.contact.phone_number
    else:
        phone_raw = (message.text or "").strip()

    normalized = _normalize_phone(phone_raw)
    if not normalized:
        await message.answer("❌ شماره نامعتبر.\nیک شماره معتبر ایرانی وارد کنید.")
        return

    await state.update_data(phone=normalized)
    await message.answer("⏳ ارسال کد تایید...", reply_markup=ReplyKeyboardRemove())

    try:
        result = await rubika_send_code(normalized)
        await state.update_data(phone_code_hash=result["phone_code_hash"])

        if result.get("status") == "SendPassKey":
            hint = result.get("hint_pass_key", "ندارد")
            await message.answer(
                "🔑 این حساب رمز دو مرحله‌ای دارد.\n"
                f"راهنمایی: {hint}\n\nرمز عبور را وارد کنید:"
            )
            await state.set_state(Form.rb_password)
            return

        await message.answer("✅ کد تایید ارسال شد.\nکد ۶ رقمی را بفرستید:")
        await state.set_state(Form.rb_code)
    except Exception as exc:
        logger.error("rb send_code: %s", exc)
        await message.answer(f"❌ {exc}\nدوباره /start بزن.")
        await state.clear()


async def rb_receive_password(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    data = await state.get_data()
    phone = data.get("phone", "")

    if not password:
        await message.answer("❌ رمز نمی‌تواند خالی باشد. دوباره:")
        return

    await message.answer("⏳ بررسی رمز عبور...")
    try:
        result = await rubika_send_code(phone, pass_key=password)
        await state.update_data(phone_code_hash=result["phone_code_hash"])
        if result.get("status") == "SendPassKey":
            hint = result.get("hint_pass_key", "ندارد")
            await message.answer(f"❌ رمز اشتباه است. راهنمایی: {hint}\nدوباره:")
            return
        await message.answer("✅ رمز تایید شد!\nکد ۶ رقمی را بفرستید:")
        await state.set_state(Form.rb_code)
    except Exception as exc:
        logger.error("rb passkey: %s", exc)
        await message.answer(f"❌ {exc}")


async def rb_receive_code(message: Message, state: FSMContext) -> None:
    code_digits = re.sub(r"\D", "", message.text or "")
    data = await state.get_data()
    phone = data.get("phone", "")
    phone_code_hash = data.get("phone_code_hash", "")
    tg_id = message.from_user.id

    if len(code_digits) < 4 or len(code_digits) > 8:
        await message.answer("❌ کد ۴ تا ۸ رقم باید باشد. دوباره:")
        return

    await message.answer("⏳ در حال ورود...")
    try:
        login_data = await rubika_sign_in(tg_id, phone, code_digits, phone_code_hash)
        add_rubika_account(
            tg_id, phone,
            login_data["session_path"],
            login_data["auth"],
            login_data["private_key"],
        )

        referrer_id = data.get("referrer_id")
        if referrer_id:
            referrer = get_user(referrer_id)
            if referrer:
                upsert_user(referrer_id, total_invites=(referrer.get("total_invites", 0) + 1))
                extend_subscription(referrer_id, add_quota=50, add_hours=1, sub_type="gift")
                try:
                    await message.bot.send_message(
                        chat_id=referrer_id,
                        text=(
                            "🎁 یک نفر با لینک دعوت شما عضو شد!\n"
                            "👑 ۱ ساعت اشتراک رایگان اضافه شد.\n"
                            f"👥 مجموع دعوت‌ها: {referrer.get('total_invites', 0) + 1}"
                        ),
                    )
                except Exception:
                    pass
            await state.update_data(referrer_id=None)

        await message.answer(
            f"✅ اکانت روبیکا اضافه شد!\n📱 {mask_phone(phone)}\n\n"
            f"📱 مجموع اکانت‌ها: {len(get_rubika_accounts(tg_id))}",
            reply_markup=kb_rubika(tg_id),
        )
        await state.set_state(Form.main_menu)
    except Exception as exc:
        logger.error("rb sign_in: %s", exc)
        await message.answer(f"❌ {exc}")


# ══════════════════════════════════════════════════════════════════════
#  روبیکا — گزارش
# ══════════════════════════════════════════════════════════════════════
async def rb_report_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id

    if not rubika_pool(tg_id):
        await callback.message.answer(
            "❌ هنوز هیچ اکانت روبیکایی در ربات ثبت نشده است.\n"
            "ابتدا یک اکانت اضافه کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("➕ افزودن اکانت روبیکا", "rb_add", ButtonStyle.SUCCESS)],
                [btn("🔙 بازگشت", "menu_rubika", ButtonStyle.PRIMARY)],
            ]),
        )
        return

    await callback.message.answer(
        "🎯 <b>چطور هدف را وارد کنیم؟</b>\n\n"
        "• اگر یوزرنیم/آیدی دارید، ربات خودش شناسه را پیدا می‌کند.\n"
        "• یا شناسه (object_guid) را دستی بفرستید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("🔍 با یوزرنیم/آیدی", "rb_username", ButtonStyle.DANGER)],
            [btn("✍️ شناسه دستی", "rb_guid_manual", ButtonStyle.PRIMARY)],
            [btn("🔙 بازگشت", "menu_rubika", ButtonStyle.PRIMARY)],
        ]),
        parse_mode="HTML",
    )
    await state.set_state(Form.rb_guid)


async def rb_username_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer(
        "👤 یوزرنیم یا آیدی روبیکا را بفرستید:\nمثال: @username یا username",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("🔙 بازگشت", "menu_rubika", ButtonStyle.PRIMARY)],
        ]),
    )
    await state.set_state(Form.rb_resolve)


async def rb_guid_manual_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer(
        "🎯 شناسه (object_guid) را بفرستید:\n"
        "مثال: u0A1bC2dE3fG4hI5jK6lM7nO8pQ9rS0T",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("🔙 بازگشت", "menu_rubika", ButtonStyle.PRIMARY)],
        ]),
    )
    await state.set_state(Form.rb_guid)


async def rb_receive_guid(message: Message, state: FSMContext) -> None:
    guid = (message.text or "").strip()
    tg_id = message.from_user.id

    if looks_like_guid(guid):
        await state.update_data(object_guid=guid, selected_types=[])
        await message.answer("نوع گزارش را انتخاب کنید:", reply_markup=kb_report_types([]))
        await state.set_state(Form.rb_report_type)
        return

    sessions = rubika_pool(tg_id)
    if not sessions:
        await message.answer("❌ سشن معتبر نیست. /start بزن.", reply_markup=kb_menu_return())
        await state.set_state(Form.main_menu)
        return

    await message.answer("⏳ در حال جستجوی شناسه...")
    resolved = await resolve_object_guid(sessions[0], guid)
    if not resolved:
        await message.answer(
            "❌ شناسه‌ای پیدا نشد.",
            reply_markup=kb_menu_return(),
        )
        await state.set_state(Form.main_menu)
        return

    await state.update_data(object_guid=resolved, selected_types=[])
    await message.answer(
        f"✅ شناسه پیدا شد:\n<code>{resolved}</code>\n\nنوع گزارش را انتخاب کنید:",
        reply_markup=kb_report_types([]),
        parse_mode="HTML",
    )
    await state.set_state(Form.rb_report_type)


async def rb_receive_resolve(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    tg_id = message.from_user.id
    sessions = rubika_pool(tg_id)
    if not sessions:
        await message.answer("❌ سشن معتبر نیست. /start بزن.", reply_markup=kb_menu_return())
        await state.set_state(Form.main_menu)
        return

    await message.answer("⏳ در حال جستجوی شناسه...")
    guid = await resolve_object_guid(sessions[0], text)
    if not guid:
        await message.answer(
            "❌ شناسه‌ای پیدا نشد.\nیوزرنیم را درست وارد کنید یا «شناسه دستی» را بزنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("🔍 با یوزرنیم/آیدی", "rb_username", ButtonStyle.DANGER)],
                [btn("✍️ شناسه دستی", "rb_guid_manual", ButtonStyle.PRIMARY)],
                [btn("🔙 بازگشت", "menu_rubika", ButtonStyle.PRIMARY)],
            ]),
        )
        await state.set_state(Form.rb_guid)
        return

    await state.update_data(object_guid=guid, selected_types=[])
    await message.answer(
        f"✅ شناسه پیدا شد:\n<code>{guid}</code>\n\nنوع گزارش را انتخاب کنید:",
        reply_markup=kb_report_types([]),
        parse_mode="HTML",
    )
    await state.set_state(Form.rb_report_type)


async def rb_receive_other_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    tg_id = message.from_user.id
    user = get_user(tg_id)

    if not text or len(text) < 3:
        await message.answer("❌ حداقل ۳ کاراکتر بنویسید.", reply_markup=kb_menu_return())
        return

    await state.update_data(other_report_text=text)
    data = await state.get_data()
    selected: list = data.get("selected_types") or []
    limit = limit_of(tg_id)
    remaining = remaining_quota(tg_id)
    if remaining is not None:
        limit = min(limit, remaining)
    labels = [REPORT_TYPES_MAP[k][0] for k in selected]

    await message.answer(
        f"🔁 ترتیب اجرا: {' → '.join(labels)}\n"
        f"چند گزارش از هر نوع؟ (حداکثر {limit})",
        reply_markup=kb_menu_return(),
    )
    await state.set_state(Form.rb_count)


async def rb_receive_count(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    tg_id = message.from_user.id

    if not text.isdigit() or int(text) < 1:
        await message.answer("❌ عدد مثبت وارد کنید.", reply_markup=kb_menu_return())
        return

    count = int(text)
    limit = limit_of(tg_id)
    remaining = remaining_quota(tg_id)
    if remaining is not None:
        limit = min(limit, remaining)

    if limit <= 0:
        await message.answer(
            "❌ سقف گزارش اشتراک شما تمام شده است.\n"
            "برای افزایش سقف، از منو «خرید اشتراک» را بزنید.",
            reply_markup=kb_buy(),
        )
        await state.set_state(Form.main_menu)
        return

    if count > limit:
        await message.answer(
            f"❌ محدودیت: {limit} گزارش.\nعدد کمتر وارد کنید:",
            reply_markup=kb_buy() if not is_premium(tg_id) else kb_menu_return(),
        )
        return

    await state.update_data(count=count)
    await message.answer(
        "⏱️ هر چند ثانیه یک گزارش ارسال شود؟\n\n"
        "عددی که می‌فرستی دقیقاً همان فاصله بین گزارش‌ها می‌شود.\n"
        "پیشنهاد: ۳ ثانیه یا بیشتر — مثال: 3",
        reply_markup=kb_menu_return(),
    )
    await state.set_state(Form.rb_delay)


async def rb_receive_delay(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    tg_id = message.from_user.id

    if not text.isdigit() or int(text) < 1:
        await message.answer("❌ عدد مثبت (ثانیه) وارد کنید.", reply_markup=kb_menu_return())
        return

    delay = int(text)
    sessions = rubika_pool(tg_id)
    total = len(sessions)
    if total == 0:
        await message.answer(
            "❌ هیچ اکانت روبیکای معتبری در ربات نیست.",
            reply_markup=kb_menu_return(),
        )
        await state.set_state(Form.main_menu)
        return

    await state.update_data(report_delay=delay)
    await message.answer(
        f"✅ فاصله هر گزارش: {delay} ثانیه\n\n"
        "🔁 وقتی چند نوع گزارش انتخاب کردی، بین هر نوع چند ثانیه مکث باشد؟\n"
        "۰ = بدون مکث (مثلاً 10)",
        reply_markup=kb_menu_return(),
    )
    await state.set_state(Form.rb_type_gap)


async def rb_receive_type_gap(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    tg_id = message.from_user.id

    if not text.isdigit():
        await message.answer("❌ عدد صفر یا مثبت وارد کنید.", reply_markup=kb_menu_return())
        return

    type_gap = min(int(text), 3600)
    sessions = rubika_pool(tg_id)
    total = len(sessions)
    if total == 0:
        await message.answer(
            "❌ هیچ اکانت روبیکای معتبری در ربات وجود ندارد.\n"
            "ابتدا یک اکانت روبیکا اضافه کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("➕ افزودن اکانت", "rb_add", ButtonStyle.SUCCESS)],
                [btn("🔙 بازگشت", "menu_rubika", ButtonStyle.PRIMARY)],
            ]),
        )
        await state.set_state(Form.main_menu)
        return

    await state.update_data(type_gap=type_gap, pool_mode=POOL_ALL)
    await message.answer(
        f"✅ مکث بین انواع: {type_gap} ثانیه\n\n"
        f"👥 در ربات {total} اکانت روبیکا اد شده است (شامل اکانت‌های خودتان).\n"
        f"با چند اکانت گزارش بزنم؟ (۱ تا {total})",
        reply_markup=kb_menu_return(),
    )
    await state.set_state(Form.rb_accounts)


async def rb_receive_accounts(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    tg_id = message.from_user.id

    if not text.isdigit() or int(text) < 1:
        await message.answer("❌ عدد مثبت وارد کنید.", reply_markup=kb_menu_return())
        return

    data = await state.get_data()
    sessions = rubika_pool(tg_id)
    total = len(sessions)
    num_accounts = int(text)
    if num_accounts > total:
        await message.answer(
            f"❌ فقط {total} اکانت موجود است. عدد کمتر:",
            reply_markup=kb_menu_return(),
        )
        return

    object_guid = data.get("object_guid", "")
    count = data.get("count", 0)
    delay = data.get("report_delay", REPORT_DELAY)
    type_gap = data.get("type_gap", RUBIKA_TYPE_GAP)
    selected = data.get("selected_types") or []
    other_text = data.get("other_report_text", "")

    if not selected:
        await message.answer("❌ حداقل یک نوع گزارش انتخاب کنید.", reply_markup=kb_menu_return())
        await state.set_state(Form.main_menu)
        return
    if not object_guid:
        await message.answer("❌ شناسه هدف پیدا نشد. /start بزن.", reply_markup=kb_menu_return())
        await state.set_state(Form.main_menu)
        return

    planned = count * len(selected)
    remaining = remaining_quota(tg_id)
    if remaining is not None and planned > remaining:
        await message.answer(
            f"❌ سقف باقی‌مانده اشتراک: {remaining} گزارش.\n"
            f"این عملیات {planned} گزارش نیاز دارد.",
            reply_markup=kb_buy(),
        )
        await state.set_state(Form.main_menu)
        return

    session_paths = sessions[:num_accounts]
    selected_types = [
        (REPORT_TYPES_MAP[k][0], REPORT_TYPES_MAP[k][1], other_text if k == "7" else "")
        for k in selected
    ]
    reason_label = ", ".join(REPORT_TYPES_MAP[k][0] for k in selected)

    await state.update_data(object_guid=None, selected_types=None, other_report_text=None,
                            count=None, report_delay=None, type_gap=None)

    op_id = op_start(tg_id, "rubika", object_guid, reason_label, planned)

    status_msg = await message.answer(
        f"🚀 شروع گزارش روبیکا\n"
        f"🎯 هدف: <code>{object_guid}</code>\n"
        f"📦 برنامه: {planned} گزارش | ⏱ هر {delay} ثانیه | 👥 {num_accounts} اکانت\n"
        f"⏸ مکث بین انواع: {type_gap} ثانیه\n"
        f"🔁 ترتیب انواع: {' → '.join(REPORT_TYPES_MAP[k][0] for k in selected)}\n"
        f"📡 پیشرفت را از «عملیات زنده» ببینید.\n"
        f"⛔ توقف: /stop",
        reply_markup=kb_running(),
        parse_mode="HTML",
    )

    asyncio.create_task(
        rb_pipeline(
            tg_id=tg_id,
            session_paths=session_paths,
            object_guid=object_guid,
            selected_types=selected_types,
            count=count,
            delay=delay,
            type_gap=type_gap,
            status_message=status_msg,
            reason_label=reason_label,
            op_id=op_id,
        )
    )
    await state.set_state(Form.main_menu)


async def rb_pipeline(tg_id: int, session_paths: list[str], object_guid: str,
                      selected_types: list[tuple[str, ReportType, str]], count: int,
                      delay: int, type_gap: int, status_message: Message,
                      reason_label: str, op_id: int) -> None:
    user_stop[tg_id] = False

    async def reply(msg: str) -> None:
        try:
            await status_message.answer(msg)
        except Exception:
            pass

    if not session_paths:
        op_progress(op_id, 0, 0, "error")
        await reply("❌ سشن معتبری برای گزارش پیدا نشد.")
        return

    n = len(session_paths)
    total_sent = 0
    total_failed = 0
    lines = []
    type_total = len(selected_types)

    async def note(msg: str) -> None:
        """پیام وضعیت را ویرایش می‌کند تا چت شلوغ نشود."""
        try:
            await status_message.edit_text(msg, reply_markup=kb_running(), parse_mode="HTML")
        except Exception:
            pass

    for t_index, (label, rt_enum, other_text) in enumerate(selected_types, 1):
        if user_stop.get(tg_id):
            break

        # ── مکث بین انواع گزارش: اول یک نوع کامل، بعد نوع بعدی ──
        if t_index > 1 and type_gap > 0:
            for left in range(int(type_gap), 0, -1):
                if user_stop.get(tg_id):
                    break
                # برای مکث‌های طولانی هر ۵ ثانیه یک‌بار پیام ویرایش می‌شود
                if left <= 5 or left % 5 == 0:
                    await note(
                        f"⏳ مکث بین انواع: {left} ثانیه\n"
                        f"➡️ نوع بعدی ({t_index}/{type_total}): {label}"
                    )
                await asyncio.sleep(1)
            if user_stop.get(tg_id):
                break

        await note(
            f"🚀 گزارش روبیکا در حال اجرا\n"
            f"🎯 <code>{object_guid}</code>\n"
            f"🔁 نوع {t_index} از {type_total}: <b>{label}</b>\n"
            f"✅ {total_sent} | ❌ {total_failed} | 📦 {count * type_total}"
        )

        per = count // n
        rem = count % n
        tasks = []
        for idx, sp in enumerate(session_paths):
            c = per + (1 if idx < rem else 0)
            if c > 0:
                # شروع پلکانی اکانت‌ها: دقیقاً فاصله‌ی خود کاربر، تقسیم بر تعداد اکانت
                start_delay = idx * (delay / max(1, n))
                tasks.append(asyncio.create_task(
                    _rb_single_loop(sp, object_guid, rt_enum, other_text, c, delay,
                                    label, tg_id, start_delay)
                ))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        sent = failed = 0
        for r in results:
            if isinstance(r, Exception):
                lines.append(f"❌ خطا ({label}): {r}")
            else:
                s, f = r
                sent += s
                failed += f
        total_sent += sent
        total_failed += failed
        op_progress(op_id, sent, failed)
        lines.append(f"✅ {label}: {sent} ارسال | {failed} ناموفق")

        # اگر نوع فعلی کاملاً ناموفق بود و هنوز نوع دیگری مانده، بقیه را متوقف کن
        if sent == 0 and failed > 0 and t_index < type_total:
            lines.append("🛑 نوع فعلی ناموفق بود؛ ادامه انواع متوقف شد تا سشن بن نشود.")
            break

    stopped = user_stop.get(tg_id)
    status = "stopped" if stopped else "done"
    op_progress(op_id, 0, 0, status)

    log_report(tg_id, "rubika", object_guid, "guid", reason_label, total_sent, total_failed)
    # بعد از ساخت ردیف هدف، وضعیت را ثبت کن (وگرنه به unknown برمی‌گردد)
    if total_sent > 0:
        consume_reports(tg_id, total_sent)
        set_target_status(tg_id, "rubika", object_guid, "active")
    elif total_failed > 0:
        set_target_status(tg_id, "rubika", object_guid, "suspended")

    summary = (
        f"📊 <b>نتیجه گزارش روبیکا</b>\n"
        f"🎯 <code>{object_guid}</code>\n\n"
        + "\n".join(lines)
        + f"\n\n✅ مجموع موفق: {total_sent}\n❌ مجموع ناموفق: {total_failed}"
    )
    await reply(summary)

    try:
        await status_message.answer("🏠 منو:", reply_markup=kb_main(tg_id))
    except Exception:
        pass

    if REPORT_GROUP_ID:
        try:
            await status_message.bot.send_message(
                REPORT_GROUP_ID,
                f"📊 گزارش عملیات روبیکا\n👤 {tg_id}\n🎯 {object_guid}\n{reason_label}\n"
                f"✅ {total_sent} | ❌ {total_failed}",
            )
        except Exception as exc:
            logger.error("report group: %s", exc)


async def _rb_single_loop(session_path: str, object_guid: str, report_type_enum: ReportType,
                          other_text: str, count: int, delay: int, label: str,
                          tg_id: int, start_delay: float = 0.0) -> tuple[int, int]:
    sent = failed = 0
    if start_delay > 0:
        await asyncio.sleep(start_delay)     # شروع پلکانی اکانت‌ها
    try:
        client = RubikaClient(name=session_path)
        async with client:
            for i in range(1, count + 1):
                if user_stop.get(tg_id):
                    break
                try:
                    if report_type_enum == ReportType.OTHER:
                        await client.report_object(object_guid, report_type_enum, description=other_text)
                    else:
                        await client.report_object(object_guid, report_type_enum)
                    sent += 1
                except Exception as exc:
                    failed += 1
                    logger.error("[%s][%d/%d] %s", label, i, count, exc)
                    # اگر خطا شبیه محدودیت/بن بود، این اکانت را رها کن
                    msg = str(exc).lower()
                    if any(w in msg for w in ("flood", "limit", "block", "ban", "too many", "captcha")):
                        logger.warning("rubika: توقف اکانت %s به دلیل محدودیت", session_path)
                        break
                if i < count:
                    await asyncio.sleep(delay)     # دقیقاً فاصله‌ای که کاربر وارد کرد
    except Exception as exc:
        logger.error("rubika session %s error: %s", session_path, exc)
    return sent, failed

# ══════════════════════════════════════════════════════════════════════
#  تلگرام — ابزار هدف و گزارش
# ══════════════════════════════════════════════════════════════════════
def parse_tg_link(text: str) -> tuple[object, Optional[int]]:
    """ورودی: لینک/یوزرنیم/آیدی. خروجی: (username یا id عددی، msg_id)"""
    t = (text or "").strip()
    t = re.sub(r"^(https?://)?(www\.)?(t\.me|telegram\.me|telegram\.dog)/", "", t, flags=re.I)
    t = t.strip().strip("/")
    if not t:
        return None, None
    parts = [p for p in t.split("/") if p]
    if not parts:
        return None, None
    # لینک خصوصی: t.me/c/123456/78
    if parts[0] == "c" and len(parts) >= 2 and parts[1].isdigit():
        channel_id = int("-100" + parts[1])
        msg_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        return channel_id, msg_id
    if re.fullmatch(r"-?\d+", parts[0]):
        msg_id = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else None
        return int(parts[0]), msg_id
    username = parts[0].lstrip("@")
    msg_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return username, msg_id


async def tg_resolve_entity(client: TelegramClient, text: str):
    t = (text or "").strip()
    low = t.lower()

    # لینک دعوت خصوصی
    if "joinchat" in low or "/+" in t or low.startswith("+"):
        invite = t.rstrip("/").split("/")[-1].lstrip("+")
        res = await client(CheckChatInviteRequest(invite))
        return getattr(res, "chat", None)

    ident, _ = parse_tg_link(t)
    if ident is None:
        raise ValueError("هدف نامعتبر است")
    if isinstance(ident, int):
        return await client.get_entity(ident)
    return await client.get_entity("@" + str(ident))


async def tg_send_report(client: TelegramClient, entity, msg_id: Optional[int],
                         reason, message: str) -> None:
    peer = await client.get_input_entity(entity)
    if msg_id:
        # در API جدید تلگرام، گزارش پست دلیل (reason) جداگانه ندارد
        try:
            await client(ReportRequest(peer=peer, id=[msg_id], option=b"", message=message))
            return
        except Exception as exc:
            logger.warning("report post failed (%s), fallback to peer report", exc)
    await client(ReportPeerRequest(peer=peer, reason=reason, message=message))


def new_tg_client(session_str: str = "") -> TelegramClient:
    return TelegramClient(
        StringSession(session_str or None),
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
        device_model="Reporter",
        system_version="1.0",
        app_version="1.0",
    )


# ══════════════════════════════════════════════════════════════════════
#  تلگرام — منو
# ══════════════════════════════════════════════════════════════════════
async def menu_telegram_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    user = get_user(tg_id)

    if not is_premium_active(user):
        await callback.message.answer(
            "🚀 <b>ریپورتر تلگرام</b>\n\n"
            "⛔ این بخش فقط برای کاربران اشتراکی فعال است.\n"
            "برای استفاده ابتدا اشتراک تهیه کنید.\n\n"
            f"💰 {PREMIUM_PRICE} / {PREMIUM_MONTHS} ماه\n"
            f"📦 {DEFAULT_SUB_QUOTA} گزارش + دسترسی ریپورتر تلگرام",
            reply_markup=kb_buy(),
            parse_mode="HTML",
        )
        return

    if not user.get("tg_access"):
        await callback.message.answer(
            "🚀 <b>ریپورتر تلگرام</b>\n\n"
            "🔒 این بخش <b>اختصاصی</b> است و فقط کاربرانی که ادمین اجازه داده باشد "
            "می‌توانند از پنل استفاده کنند.\n\n"
            "برای دریافت دسترسی با پشتیبانی تماس بگیرید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("📞 درخواست دسترسی از پشتیبانی", "support", ButtonStyle.SUCCESS)],
                [btn("🔙 بازگشت", "back_menu", ButtonStyle.PRIMARY)],
            ]),
            parse_mode="HTML",
        )
        return

    accounts = get_tg_accounts(tg_id)
    await callback.message.answer(
        "🚀 <b>ریپورتر تلگرام</b>\n\n"
        f"📱 اکانت‌های تلگرام شما: {len(accounts)}\n"
        f"🌍 کل اکانت‌های ربات: {len(get_all_tg_accounts())}\n"
        f"🎯 سقف هر نوع گزارش: {PREMIUM_LIMIT}\n"
        f"📦 باقی‌مانده اشتراک: {'بی‌نهایت' if remaining_quota(tg_id) is None else remaining_quota(tg_id)}\n\n"
        "از دکمه‌های زیر استفاده کنید:",
        reply_markup=kb_telegram(tg_id),
        parse_mode="HTML",
    )
    await state.set_state(Form.main_menu)


async def tga_list_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    page = _page_of(callback.data or "", "tga_page_")
    accounts = get_tg_accounts(tg_id)

    if not accounts:
        await callback.message.answer(
            "📱 هنوز اکانت تلگرامی اضافه نکرده‌اید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("➕ افزودن اکانت تلگرام", "tga_add", ButtonStyle.SUCCESS)],
                [btn("🔙 بازگشت", "menu_telegram", ButtonStyle.PRIMARY)],
            ]),
        )
        return

    per = ACCOUNTS_PER_PAGE
    pages = max(1, (len(accounts) + per - 1) // per)
    page = min(page, pages - 1)
    chunk = accounts[page * per:(page + 1) * per]

    rows = []
    for acc in chunk:
        label = acc.get("label") or "اکانت"
        rows.append([
            btn(f"📱 {mask_phone(acc['phone'])} | {label}", f"tga_del_{acc['id']}", ButtonStyle.DANGER),
        ])
    if pages > 1:
        rows.append(_pager_row("tga_page_", page, pages))
    rows.append([btn("➕ افزودن اکانت جدید", "tga_add", ButtonStyle.SUCCESS)])
    rows.append([btn("🔙 بازگشت", "menu_telegram", ButtonStyle.PRIMARY)])

    await callback.message.answer(
        f"📱 <b>اکانت‌های تلگرام</b>\n"
        f"📊 مجموع اکانت‌های شما: {len(accounts)}\n"
        f"🌍 مجموع اکانت‌های ربات: {len(get_all_tg_accounts())}\n"
        "برای حفظ حریم خصوصی، شماره‌ها مخفی هستند.\n"
        "روی هر اکانت بزنید تا حذف شود:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )


async def tga_delete_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    try:
        acc_id = int(callback.data.split("_")[-1])
    except ValueError:
        return
    delete_tg_account(tg_id, acc_id)
    await callback.message.answer("✅ اکانت حذف شد.", reply_markup=kb_telegram(tg_id))


# ══════════════════════════════════════════════════════════════════════
#  تلگرام — افزودن اکانت (شماره + کد + رمز)
# ══════════════════════════════════════════════════════════════════════
def _tg_gate_msg() -> str:
    return (
        "⛔ این بخش نیازمند اشتراک فعال و دسترسی اختصاصی است.\n"
        "از منو «خرید اشتراک» را بزنید یا با پشتیبانی تماس بگیرید."
    )


async def tga_add_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    if not has_tg_access(tg_id):
        await callback.message.answer(_tg_gate_msg(), reply_markup=kb_buy())
        return

    await callback.message.answer(
        "📱 شماره تلگرام را با کد کشور بفرستید:\nمثال: +989123456789",
        reply_markup=kb_menu_return(),
    )
    await state.set_state(Form.tg_phone)


def _tg_lock(tg_id: int) -> asyncio.Lock:
    lock = TG_LOGIN_LOCKS.get(tg_id)
    if lock is None:
        lock = asyncio.Lock()
        TG_LOGIN_LOCKS[tg_id] = lock
    return lock


async def _tg_send_code(tg_id: int, phone: str) -> str:
    """کلاینت تازه می‌سازد، کد می‌فرستد و hash کد را برای ورود ذخیره می‌کند."""
    await _close_tg_login(tg_id)
    client = new_tg_client()
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
    except Exception:
        try:
            await client.disconnect()
        except Exception:
            pass
        raise

    code_hash = getattr(sent, "phone_code_hash", "") or ""
    TG_LOGIN_CLIENTS[tg_id] = client
    TG_LOGIN_META[tg_id] = {
        "phone": phone,
        "hash": code_hash,
        "sent_at": time.time(),
        "tries": 0,
    }
    logger.info("tg send_code ok for %s (hash=%s)", tg_phone_key(phone), bool(code_hash))
    return code_hash


async def _tg_resend_code(tg_id: int, phone: str) -> str:
    """کد جدید می‌فرستد (کد قبلی باطل می‌شود) و hash تازه را برمی‌گرداند."""
    client = TG_LOGIN_CLIENTS.get(tg_id)
    if client is None:
        return await _tg_send_code(tg_id, phone)

    try:
        if not client.is_connected():
            await client.connect()
        sent = await client.send_code_request(phone)
    except Exception as exc:
        logger.warning("tg resend on old client failed (%s); building new client", exc)
        return await _tg_send_code(tg_id, phone)

    code_hash = getattr(sent, "phone_code_hash", "") or ""
    TG_LOGIN_META[tg_id] = {
        "phone": phone,
        "hash": code_hash,
        "sent_at": time.time(),
        "tries": 0,
    }
    logger.info("tg resend_code ok for %s (hash=%s)", tg_phone_key(phone), bool(code_hash))
    return code_hash


async def tg_receive_phone(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    if not has_tg_access(tg_id):
        await message.answer(_tg_gate_msg(), reply_markup=kb_buy())
        await state.set_state(Form.main_menu)
        return

    raw = message.contact.phone_number if message.contact else (message.text or "")
    phone = normalize_tg_phone(raw)
    if not phone or not validate_tg_phone(phone):
        await message.answer("❌ شماره نامعتبر است.\nمثال: +989123456789")
        return

    lock = _tg_lock(tg_id)
    if lock.locked():
        await message.answer("⏳ درخواست قبلی در حال انجام است. چند لحظه صبر کنید.")
        return

    async with lock:
        meta = TG_LOGIN_META.get(tg_id) or {}
        existing = TG_LOGIN_CLIENTS.get(tg_id)
        same_phone = tg_phone_key(meta.get("phone")) == tg_phone_key(phone)
        still_fresh = (time.time() - float(meta.get("sent_at") or 0)) < TG_CODE_TTL

        # اگر همین الان برای همین شماره کد فرستاده‌ایم، دوباره نفرست
        # (ارسال دوباره، کد قبلی را باطل می‌کند و کاربر را سردرگم می‌کند)
        if existing and same_phone and still_fresh and meta.get("hash"):
            await state.update_data(tg_phone=phone)
            await state.set_state(Form.tg_code)
            await message.answer(
                "✅ کد این شماره همین چند لحظه پیش ارسال شده و هنوز معتبر است.\n"
                "همان کد پیامک‌شده را وارد کنید.\n\n"
                "اگر کدی نرسیده یا کد قبلی را گم کرده‌اید، از دکمه زیر کد جدید بگیرید:",
                reply_markup=kb_tg_resend(),
            )
            return

        await message.answer("⏳ اتصال به تلگرام و ارسال کد...")
        try:
            await _tg_send_code(tg_id, phone)
        except errors.FloodWaitError as exc:
            await message.answer(
                f"⏳ تلگرام محدودیت گذاشته. {fmt_time(exc.seconds)} دیگر تلاش کنید.",
                reply_markup=kb_telegram(tg_id),
            )
            await state.set_state(Form.main_menu)
            return
        except errors.PhoneNumberInvalidError:
            await message.answer("❌ شماره از نظر تلگرام نامعتبر است. با کد کشور بفرستید: +98912...")
            return
        except errors.PhoneNumberBannedError:
            await message.answer("❌ این شماره در تلگرام مسدود شده است.")
            return
        except errors.ApiIdInvalidError:
            logger.error("TELEGRAM_API_ID/HASH نامعتبر است")
            await message.answer("❌ تنظیمات API ربات (api_id/api_hash) مشکل دارد. به ادمین اطلاع بدهید.")
            await state.set_state(Form.main_menu)
            return
        except Exception as exc:
            logger.exception("tg send_code: %s", exc)
            await message.answer(f"❌ خطا در ارسال کد:\n{str(exc)[:150]}")
            return

    await state.update_data(tg_phone=phone)
    await state.set_state(Form.tg_code)
    await message.answer(
        "✅ کد تایید ارسال شد.\n"
        "کد ارسال‌شده را وارد کنید:\n\n"
        "⚠️ فقط «جدیدترین» کد را بفرستید. هر بار ارسال کد جدید، کد قبلی باطل می‌شود.",
        reply_markup=kb_tg_resend(),
    )


async def tg_receive_code(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    code = re.sub(r"\D", "", (message.text or "").translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")))
    data = await state.get_data()
    meta = TG_LOGIN_META.get(tg_id) or {}
    phone = data.get("tg_phone") or meta.get("phone") or ""
    client = TG_LOGIN_CLIENTS.get(tg_id)

    if not client or not phone:
        await message.answer(
            "❌ جلسه ورود منقضی شده. دوباره «افزودن اکانت تلگرام» را بزنید.",
            reply_markup=kb_telegram(tg_id),
        )
        await state.set_state(Form.main_menu)
        return
    if not (4 <= len(code) <= 7):
        await message.answer("❌ کد باید ۴ تا ۷ رقم باشد. دوباره:")
        return

    lock = _tg_lock(tg_id)
    if lock.locked():
        await message.answer("⏳ کد قبلی در حال بررسی است. چند لحظه صبر کنید.")
        return

    async with lock:
        try:
            if not client.is_connected():
                await client.connect()
        except Exception as exc:
            logger.error("tg reconnect: %s", exc)
            await message.answer("❌ ارتباط با تلگرام قطع شد. دوباره اکانت اضافه کنید.")
            await _close_tg_login(tg_id)
            await state.set_state(Form.main_menu)
            return

        try:
            # hash ذخیره‌شده را صریح می‌فرستیم تا هیچ‌وقت با کد اشتباه نشود
            await client.sign_in(phone, code, phone_code_hash=meta.get("hash") or None)
        except errors.SessionPasswordNeededError:
            await state.update_data(tg_phone=phone)
            await message.answer("🔐 این اکانت رمز دو مرحله‌ای (2FA) دارد.\nرمز را وارد کنید:")
            await state.set_state(Form.tg_password)
            return
        except errors.PhoneCodeInvalidError:
            meta["tries"] = int(meta.get("tries") or 0) + 1
            TG_LOGIN_META[tg_id] = meta
            if meta["tries"] >= 5:
                await message.answer(
                    "❌ تعداد تلاش‌های اشتباه زیاد شد. دوباره «افزودن اکانت» را بزنید.",
                    reply_markup=kb_telegram(tg_id),
                )
                await _close_tg_login(tg_id)
                await state.set_state(Form.main_menu)
            else:
                await message.answer(f"❌ کد اشتباه است ({meta['tries']}/۵). دوباره:")
            return
        except errors.PhoneCodeExpiredError:
            # کد باطل شده؛ خودکار کد تازه می‌فرستیم تا کاربر مجبور به شروع از صفر نباشد
            try:
                await _tg_resend_code(tg_id, phone)
            except errors.FloodWaitError as exc:
                await message.answer(f"⏳ {fmt_time(exc.seconds)} صبر کنید و دوباره تلاش کنید.")
                return
            except Exception as exc:
                logger.exception("tg auto-resend: %s", exc)
                await message.answer("❌ ارسال کد جدید ممکن نشد. دوباره «افزودن اکانت» را بزنید.")
                await _close_tg_login(tg_id)
                await state.set_state(Form.main_menu)
                return
            await state.set_state(Form.tg_code)
            await message.answer(
                "♻️ کد قبلی منقضی شده بود؛ برای شما یک کد «جدید» ارسال شد.\n"
                "لطفاً فقط جدیدترین کد پیامک‌شده را وارد کنید:",
                reply_markup=kb_tg_resend(),
            )
            return
        except errors.PhoneNumberUnoccupiedError:
            await message.answer("❌ این شماره اکانت تلگرام ندارد. ابتدا در تلگرام ثبت‌نام کنید.")
            await _close_tg_login(tg_id)
            await state.set_state(Form.main_menu)
            return
        except errors.FloodWaitError as exc:
            await message.answer(f"⏳ {fmt_time(exc.seconds)} صبر کنید و دوباره تلاش کنید.")
            return
        except Exception as exc:
            logger.exception("tg sign_in: %s", exc)
            await message.answer(f"❌ خطا:\n{str(exc)[:150]}")
            return

    await _finish_tg_login_safe(message, client, phone)
    await state.set_state(Form.main_menu)


async def tg_resend_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    data = await state.get_data()
    phone = data.get("tg_phone") or (TG_LOGIN_META.get(tg_id) or {}).get("phone", "")
    if not phone:
        await callback.message.answer(
            "❌ ابتدا شماره را بفرستید.",
            reply_markup=kb_telegram(tg_id),
        )
        await state.set_state(Form.tg_phone)
        return

    lock = _tg_lock(tg_id)
    if lock.locked():
        await callback.message.answer("⏳ درخواست قبلی در حال انجام است. چند لحظه صبر کنید.")
        return

    async with lock:
        try:
            await _tg_resend_code(tg_id, phone)
        except errors.FloodWaitError as exc:
            await callback.message.answer(f"⏳ {fmt_time(exc.seconds)} صبر کنید و دوباره تلاش کنید.")
            return
        except Exception as exc:
            logger.exception("tg resend: %s", exc)
            await callback.message.answer(f"❌ خطا در ارسال کد جدید:\n{str(exc)[:150]}")
            return

    await state.update_data(tg_phone=phone)
    await state.set_state(Form.tg_code)
    await callback.message.answer(
        "♻️ کد جدید ارسال شد.\nلطفاً فقط جدیدترین کد را وارد کنید:",
        reply_markup=kb_tg_resend(),
    )


async def tg_receive_password(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    password = (message.text or "").strip()
    data = await state.get_data()
    phone = data.get("tg_phone") or (TG_LOGIN_META.get(tg_id) or {}).get("phone", "")
    client = TG_LOGIN_CLIENTS.get(tg_id)

    if not client:
        await message.answer(
            "❌ جلسه ورود منقضی شده. دوباره اکانت اضافه کنید.",
            reply_markup=kb_telegram(tg_id),
        )
        await state.set_state(Form.main_menu)
        return
    if not password:
        await message.answer("❌ رمز نمی‌تواند خالی باشد.")
        return

    lock = _tg_lock(tg_id)
    if lock.locked():
        await message.answer("⏳ در حال بررسی رمز قبلی. چند لحظه صبر کنید.")
        return

    async with lock:
        try:
            if not client.is_connected():
                await client.connect()
            await client.sign_in(password=password)
        except errors.PasswordHashInvalidError:
            await message.answer("❌ رمز اشتباه است. دوباره:")
            return
        except errors.FloodWaitError as exc:
            await message.answer(f"⏳ {fmt_time(exc.seconds)} صبر کنید.")
            return
        except Exception as exc:
            logger.exception("tg 2fa: %s", exc)
            await message.answer(f"❌ خطا:\n{str(exc)[:150]}")
            return

    await _finish_tg_login_safe(message, client, phone)
    await state.set_state(Form.main_menu)


async def _finish_tg_login_safe(message: Message, client: TelegramClient, phone: str) -> None:
    """ثبت اکانت با گزارش خطای واضح به کاربر (اشکال دیتابیس/سشن)."""
    try:
        await _finish_tg_login(message, client, phone)
    except Exception as exc:
        logger.exception("finish tg login: %s", exc)
        await _close_tg_login(message.from_user.id)
        await message.answer(
            "❌ ورود انجام شد ولی ذخیره اکانت با خطا مواجه شد:\n"
            f"{str(exc)[:200]}\n\n"
            "دوباره تلاش کنید؛ اگر تکرار شد به ادمین اطلاع بدهید.",
            reply_markup=kb_telegram(message.from_user.id),
        )


async def _close_tg_login(tg_id: int) -> None:
    client = TG_LOGIN_CLIENTS.pop(tg_id, None)
    TG_LOGIN_META.pop(tg_id, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass


async def _finish_tg_login(message: Message, client: TelegramClient, phone: str) -> None:
    tg_id = message.from_user.id
    try:
        authorized = await client.is_user_authorized()
    except Exception:
        authorized = False
    if not authorized:
        raise RuntimeError("ورود کامل نشد؛ دوباره تلاش کنید.")

    session_str = client.session.save()
    try:
        me = await client.get_me()
        label = (me.first_name or "اکانت") + (f" @{me.username}" if getattr(me, "username", None) else "")
        uid = getattr(me, "id", "")
    except Exception:
        label, uid = "اکانت", ""

    add_tg_account(tg_id, phone, session_str, label)
    await _close_tg_login(tg_id)

    await message.answer(
        "✅ اکانت تلگرام اضافه شد!\n\n"
        f"📱 {mask_phone(phone)}\n"
        f"👤 {label}\n"
        f"🆔 {uid}\n\n"
        f"📱 مجموع اکانت‌های شما: {len(get_tg_accounts(tg_id))}\n"
        f"🌍 مجموع اکانت‌های ربات: {len(get_all_tg_accounts())}",
        reply_markup=kb_telegram(tg_id),
    )


# ══════════════════════════════════════════════════════════════════════
#  تلگرام — شروع عملیات
# ══════════════════════════════════════════════════════════════════════
TG_KINDS = {
    "tgr_channel": ("channel", "کانال/گروه"),
    "tgr_post": ("post", "پست"),
    "tgr_profile": ("profile", "پروفایل"),
    "tgr_bot": ("bot", "ربات"),
    "tgr_account": ("account", "اکانت"),
    "tgr_manual": ("manual", "دستی"),
}


async def tgr_select_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    if not has_tg_access(tg_id):
        await callback.message.answer(_tg_gate_msg(), reply_markup=kb_buy())
        return

    kind, label = TG_KINDS[callback.data]
    accounts = tg_pool(tg_id)
    if not accounts:
        await callback.message.answer(
            "❌ هنوز هیچ اکانت تلگرامی در ربات ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("➕ افزودن اکانت", "tga_add", ButtonStyle.SUCCESS)],
                [btn("🔙 بازگشت", "menu_telegram", ButtonStyle.PRIMARY)],
            ]),
        )
        return

    await state.update_data(tg_kind=kind, tg_label=label, pool_mode=POOL_ALL)
    await callback.message.answer(
        f"📝 نوع گزارش: <b>{label}</b>\n\n"
        f"👥 در ربات {len(accounts)} اکانت تلگرام اد شده است (شامل اکانت‌های خودتان).\n"
        f"با چند اکانت گزارش بزنم؟ (۱ تا {len(accounts)})",
        reply_markup=kb_menu_return(),
        parse_mode="HTML",
    )
    await state.set_state(Form.tg_accounts)


async def tg_receive_accounts(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    tg_id = message.from_user.id
    if not text.isdigit() or int(text) < 1:
        await message.answer("❌ عدد مثبت وارد کنید.", reply_markup=kb_menu_return())
        return

    data = await state.get_data()
    total = len(tg_pool(tg_id))
    n = int(text)
    if n > total:
        await message.answer(f"❌ فقط {total} اکانت موجود است. عدد کمتر:", reply_markup=kb_menu_return())
        return

    kind = data.get("tg_kind")
    await state.update_data(tg_use=n)

    if kind == "post":
        await message.answer(
            "🔗 لینک پست‌ها را بفرستید (هر خط یک لینک، ۱ تا ۶ عدد):\n"
            "مثال: https://t.me/username/123",
            reply_markup=kb_menu_return(),
        )
        await state.set_state(Form.tg_links)
    else:
        await message.answer(
            "🔗 لینک/یوزرنیم/آیدی هدف را بفرستید:\n"
            "مثال: @username یا https://t.me/username یا -1001234567890",
            reply_markup=kb_menu_return(),
        )
        await state.set_state(Form.tg_target)


async def tg_receive_target(message: Message, state: FSMContext) -> None:
    target = (message.text or "").strip()
    if not target:
        await message.answer("❌ هدف خالی است.", reply_markup=kb_menu_return())
        return
    await state.update_data(tg_target=target, tg_links=[])
    await message.answer(
        f"🎯 هدف: <code>{target}</code>\n\n"
        "اکانت‌ها قبل از گزارش به هدف جوین شوند؟\n"
        "(برای کانال/گروه مفید است)",
        reply_markup=kb_join_choice(),
        parse_mode="HTML",
    )
    await state.set_state(Form.tg_join)


async def tg_receive_links(message: Message, state: FSMContext) -> None:
    links = [x.strip() for x in (message.text or "").splitlines() if x.strip()]
    if not links:
        await message.answer("❌ حداقل یک لینک بفرستید.", reply_markup=kb_menu_return())
        return
    if len(links) > 6:
        await message.answer("❌ حداکثر ۶ لینک مجاز است.", reply_markup=kb_menu_return())
        return

    await state.update_data(tg_target=links[0], tg_links=links)
    await message.answer(
        f"🔗 {len(links)} پست انتخاب شد.\n\n"
        "اکانت‌ها قبل از گزارش به کانال جوین شوند؟",
        reply_markup=kb_join_choice(),
    )
    await state.set_state(Form.tg_join)


async def tg_join_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    should_join = callback.data == "tgjoin_yes"
    await state.update_data(tg_join=should_join)
    await callback.message.answer(
        "📝 دلیل گزارش را انتخاب کنید:",
        reply_markup=kb_reason(),
    )
    await state.set_state(Form.tg_reason)


async def tg_reason_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    if not has_tg_access(tg_id):
        await callback.message.answer(_tg_gate_msg(), reply_markup=kb_buy())
        return

    key = callback.data.replace("tgreason_", "")
    if key not in TG_REASONS:
        return
    await state.update_data(tg_reason=key)

    data = await state.get_data()
    if data.get("tg_kind") == "manual":
        await callback.message.answer(
            "📝 متن گزارش سفارشی را بنویسید (حداقل ۴ کاراکتر):",
            reply_markup=kb_menu_return(),
        )
        await state.set_state(Form.tg_manual)
    else:
        await callback.message.answer(
            "🔢 تعداد گزارش هر اکانت؟ (۱ تا ۱۰۰)",
            reply_markup=kb_menu_return(),
        )
        await state.set_state(Form.tg_per_acc)


async def tg_receive_manual(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 4:
        await message.answer("❌ حداقل ۴ کاراکتر بنویسید.", reply_markup=kb_menu_return())
        return
    await state.update_data(tg_other_text=text)
    await message.answer(
        "🔢 تعداد گزارش هر اکانت؟ (۱ تا ۱۰۰)",
        reply_markup=kb_menu_return(),
    )
    await state.set_state(Form.tg_per_acc)


async def tg_receive_per_acc(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 100):
        await message.answer("❌ عددی بین ۱ تا ۱۰۰ وارد کنید.", reply_markup=kb_menu_return())
        return
    await state.update_data(tg_per=int(text))
    await message.answer(
        "⏱️ هر چند ثانیه یک گزارش ارسال شود؟\n\n"
        "عددی که می‌فرستی دقیقاً همان فاصله بین گزارش‌ها می‌شود.\n"
        "پیشنهاد: ۳ ثانیه یا بیشتر — مثال: 3",
        reply_markup=kb_menu_return(),
    )
    await state.set_state(Form.tg_delay)


async def tg_receive_delay(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    tg_id = message.from_user.id
    if not text.isdigit() or int(text) < 1:
        await message.answer("❌ عدد مثبت (ثانیه) وارد کنید.", reply_markup=kb_menu_return())
        return

    delay = int(text)
    data = await state.get_data()
    kind = data.get("tg_kind")
    label = data.get("tg_label", kind)
    target = data.get("tg_target", "")
    links = data.get("tg_links") or []
    reason_key = data.get("tg_reason", "8")
    per = int(data.get("tg_per", 1))
    use = int(data.get("tg_use", 1))
    join = bool(data.get("tg_join"))
    other_text = data.get("tg_other_text", "")

    accounts = tg_pool(tg_id)[:use]
    if not accounts:
        await message.answer("❌ اکانتی موجود نیست.", reply_markup=kb_menu_return())
        await state.set_state(Form.main_menu)
        return

    target_count = max(1, len(links)) if kind == "post" else 1
    planned = per * len(accounts) * target_count
    remaining = remaining_quota(tg_id)
    if remaining is not None and planned > remaining:
        await message.answer(
            f"❌ سقف باقی‌مانده اشتراک: {remaining} گزارش.\n"
            f"این عملیات {planned} گزارش نیاز دارد.",
            reply_markup=kb_buy(),
        )
        await state.set_state(Form.main_menu)
        return

    reason_label = TG_REASONS.get(reason_key, ("سایر",))[0]
    op_id = op_start(tg_id, "telegram", target, reason_label, planned)

    status_msg = await message.answer(
        f"🚀 شروع گزارش تلگرام\n"
        f"📝 نوع: {label}\n"
        f"🎯 هدف: <code>{target}</code>\n"
        f"📦 برنامه: {planned} گزارش | ⏱ {delay} ثانیه | 👥 {len(accounts)} اکانت\n"
        f"📡 پیشرفت را از «عملیات زنده» ببینید.\n"
        f"⛔ توقف: /stop",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("📡 عملیات زنده", "live_ops", ButtonStyle.SUCCESS)],
            [btn("🛑 توقف", "stop_op", ButtonStyle.DANGER)],
        ]),
        parse_mode="HTML",
    )

    asyncio.create_task(tg_pipeline(
        tg_id=tg_id,
        accounts=accounts,
        kind=kind,
        target=target,
        links=links,
        reason_key=reason_key,
        per=per,
        delay=delay,
        join=join,
        other_text=other_text,
        status_message=status_msg,
        op_id=op_id,
        planned=planned,
    ))
    await state.set_state(Form.main_menu)


# ══════════════════════════════════════════════════════════════════════
#  تلگرام — اجرای گزارش با Telethon
# ══════════════════════════════════════════════════════════════════════
async def tg_pipeline(tg_id: int, accounts: list[dict], kind: str, target: str,
                      links: list[str], reason_key: str, per: int, delay: int,
                      join: bool, other_text: str, status_message: Message,
                      op_id: int, planned: int) -> None:
    user_stop[tg_id] = False
    reason_obj, reason_default, _ = TG_REASONS.get(reason_key, TG_REASONS["8"])
    reason_label = TG_REASONS.get(reason_key, ("سایر",))[0]

    total_ok = 0
    total_fail = 0
    lines: list[str] = []
    target_status = "unknown"

    for idx, acc in enumerate(accounts, 1):
        if user_stop.get(tg_id):
            break

        label = acc.get("label") or mask_phone(acc.get("phone"))
        client = new_tg_client(acc["session_str"])
        acc_ok = 0
        acc_fail = 0
        try:
            await client.connect()
            if not await client.is_user_authorized():
                acc_fail = per * (len(links) if kind == "post" else 1)
                lines.append(f"🔴 {label}: سشن منقضی شده")
                total_fail += acc_fail
                op_progress(op_id, 0, acc_fail)
                continue

            # ── حل هدف‌ها ──
            resolved: list[tuple[object, Optional[int]]] = []
            if kind == "post":
                for ln in links:
                    try:
                        ent = await tg_resolve_entity(client, ln)
                        _, mid = parse_tg_link(ln)
                        if ent:
                            resolved.append((ent, mid))
                    except _tg_ban_errors():
                        target_status = "suspended"
                    except Exception as exc:
                        logger.error("tg resolve post %s: %s", ln, exc)
            else:
                try:
                    ent = await tg_resolve_entity(client, target)
                    if ent:
                        resolved.append((ent, None))
                        target_status = "active"
                except _tg_ban_errors():
                    target_status = "suspended"
                except Exception as exc:
                    logger.error("tg resolve %s: %s", target, exc)

            if not resolved:
                acc_fail = per * max(1, len(links) if kind == "post" else 1)
                lines.append(f"🔴 {label}: هدف پیدا نشد/مسدود است")
                total_fail += acc_fail
                op_progress(op_id, 0, acc_fail)
                continue

            # ── جوین ──
            if join:
                for ent, _mid in resolved:
                    try:
                        await client(JoinChannelRequest(ent))
                        await asyncio.sleep(random.uniform(1, 2))
                    except errors.UserAlreadyParticipantError:
                        pass
                    except Exception:
                        pass

            # ── گزارش ──
            for i in range(per):
                if user_stop.get(tg_id):
                    break
                for ent, mid in resolved:
                    if user_stop.get(tg_id):
                        break
                    try:
                        await tg_send_report(client, ent, mid, reason_obj,
                                             other_text if kind == "manual" else reason_default)
                        acc_ok += 1
                        target_status = "active"
                    except errors.FloodWaitError as exc:
                        wait = min(exc.seconds, 30)
                        await asyncio.sleep(wait)
                        try:
                            await tg_send_report(client, ent, mid, reason_obj,
                                                 other_text if kind == "manual" else reason_default)
                            acc_ok += 1
                            target_status = "active"
                        except Exception:
                            acc_fail += 1
                    except _tg_ban_errors():
                        acc_fail += 1
                        target_status = "suspended"
                    except Exception as exc:
                        acc_fail += 1
                        logger.error("tg report %s: %s", target, exc)
                if i < per - 1:
                    await asyncio.sleep(delay)     # دقیقاً فاصله‌ای که کاربر وارد کرد

        except Exception as exc:
            logger.error("tg account %s: %s", label, exc)
            acc_fail += max(0, per - acc_ok - acc_fail)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        total_ok += acc_ok
        total_fail += acc_fail
        op_progress(op_id, acc_ok, acc_fail)
        lines.append(f"{'🟢' if acc_fail == 0 else '🟡'} {label}: ✅ {acc_ok} | ❌ {acc_fail}")

        try:
            done = total_ok + total_fail
            pct = int(done * 100 / planned) if planned else 0
            bar = "🟩" * (pct // 10) + "⬜" * (10 - pct // 10)
            await status_message.edit_text(
                f"🚀 گزارش تلگرام در حال اجرا...\n"
                f"{bar} {pct}%\n"
                f"✅ {total_ok} | ❌ {total_fail} | 📦 {planned}\n"
                f"🎯 <code>{target}</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [btn("🛑 توقف", "stop_op", ButtonStyle.DANGER)],
                ]),
            )
        except Exception:
            pass

    stopped = user_stop.get(tg_id)
    op_progress(op_id, 0, 0, "stopped" if stopped else "done")

    log_report(tg_id, "telegram", target, kind, reason_label, total_ok, total_fail)
    if total_ok > 0:
        consume_reports(tg_id, total_ok)
    set_target_status(tg_id, "telegram", target, target_status)

    summary = (
        "📊 <b>نتیجه گزارش تلگرام</b>\n"
        f"🎯 <code>{target}</code>\n\n"
        + "\n".join(lines)
        + f"\n\n✅ مجموع موفق: {total_ok}\n❌ مجموع ناموفق: {total_fail}\n"
        + (f"🛑 عملیات متوقف شد" if stopped else "🏁 پایان عملیات")
    )
    try:
        await status_message.answer(summary, parse_mode="HTML")
        await status_message.answer("🏠 منو:", reply_markup=kb_main(tg_id))
    except Exception:
        pass

    if REPORT_GROUP_ID:
        try:
            await status_message.bot.send_message(
                REPORT_GROUP_ID,
                f"📊 گزارش عملیات تلگرام\n👤 {tg_id}\n🎯 {target}\n{reason_label}\n"
                f"✅ {total_ok} | ❌ {total_fail}",
            )
        except Exception as exc:
            logger.error("report group: %s", exc)

# ══════════════════════════════════════════════════════════════════════
#  پنل مدیریت — اشتراک و کاربران
# ══════════════════════════════════════════════════════════════════════
def is_blocked(tg_id: int) -> bool:
    user = get_user(tg_id)
    return bool(user and user.get("is_blocked"))


def user_summary_text(uid: int) -> str:
    u = get_user(uid)
    if not u:
        return "کاربر یافت نشد."
    prem = is_premium_active(u)
    quota = u.get("sub_quota") or 0
    used = u.get("sub_used") or 0
    left = "بی‌نهایت" if quota <= 0 else str(max(0, quota - used))
    return (
        f"👤 <b>کاربر</b> <code>{uid}</code>\n"
        f"وضعیت: {'⭐ اشتراکی' if prem else '🆓 رایگان'}\n"
        f"نوع اشتراک: {sub_type_label(u.get('sub_type'))}\n"
        f"📅 انقضا: {fmt_dt(u.get('premium_until'))}\n"
        f"📦 سقف: {'بی‌نهایت' if quota <= 0 else quota} | "
        f"مصرف: {used} | باقی: {left}\n"
        f"🚀 دسترسی تلگرام: {'✅ دارد' if u.get('tg_access') else '⛔ ندارد'}\n"
        f"🚫 بلاک: {'✅ بله' if u.get('is_blocked') else '❌ خیر'}\n\n"
        f"📱 اکانت روبیکا: {len(get_rubika_accounts(uid))}\n"
        f"✈️ اکانت تلگرام: {len(get_tg_accounts(uid))}\n"
        f"📢 کل گزارش: {u.get('total_reports', 0)}\n"
        f"👥 دعوت‌ها: {u.get('total_invites', 0)}\n"
        f"🎁 آخرین جایزه: {fmt_dt(u.get('last_daily_reward'))}\n"
        f"⏰ عضویت: {fmt_dt(u.get('created_at'))}"
    )


def kb_admin_user(uid: int) -> InlineKeyboardMarkup:  # type: ignore[misc]
    u = get_user(uid) or {}
    tg_on = bool(u.get("tg_access"))
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            btn("👑 تغییر/تمدید اشتراک", f"adm_sub_{uid}", ButtonStyle.SUCCESS),
            btn("✍️ سفارشی", f"adm_custom_{uid}", ButtonStyle.PRIMARY),
        ],
        [
            btn(
                f"🚀 دسترسی تلگرام: {'✅ روشن' if tg_on else '⛔ خاموش'}",
                f"adm_toggle_tg_{uid}",
                ButtonStyle.SUCCESS if tg_on else ButtonStyle.DANGER,
            )
        ],
        [
            btn("📋 گزارش‌های اخیر", f"adm_logs_{uid}", ButtonStyle.PRIMARY),
            btn("🎯 اهداف کاربر", f"adm_targets_{uid}", ButtonStyle.PRIMARY),
        ],
        [
            btn("♻️ صفر کردن مصرف", f"adm_reset_{uid}", ButtonStyle.SUCCESS),
            btn("🚫 بلاک / آنبلاک", f"adm_block_{uid}", ButtonStyle.DANGER),
        ],
        [btn("🔙 لیست کاربران", "admin_list", ButtonStyle.PRIMARY)],
    ])


def kb_admin_subs(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("1000 گزارش / ۱ ساعت", f"adm_preset_{uid}_1000_1", ButtonStyle.PRIMARY)],
        [btn("2000 گزارش / ۱ هفته", f"adm_preset_{uid}_2000_168", ButtonStyle.PRIMARY)],
        [btn("5000 گزارش / ۱ ماه", f"adm_preset_{uid}_5000_720", ButtonStyle.PRIMARY)],
        [btn("بدون سقف / ۱ ماه", f"adm_preset_{uid}_0_720", ButtonStyle.SUCCESS)],
        [btn("✍️ مدت و سقف دلخواه", f"adm_custom_{uid}", ButtonStyle.SUCCESS)],
        [btn("♻️ صفر کردن مصرف", f"adm_reset_{uid}", ButtonStyle.PRIMARY)],
        [btn("🔙 بازگشت", f"adm_user_{uid}", ButtonStyle.PRIMARY)],
    ])


async def admin_open_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("🛠 <b>پنل مدیریت</b>", reply_markup=kb_admin_panel(), parse_mode="HTML")
    await state.set_state(Form.admin_panel)


async def admin_live_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return

    ops = get_running_ops(None)
    if not ops:
        await callback.message.answer(
            "📡 هیچ عملیات در حال اجرایی وجود ندارد.\n"
            f"🕒 الان: {now_label()}",
            reply_markup=kb_admin_panel(),
        )
        return

    lines = [
        "📡 <b>عملیات زنده همه کاربران</b>\n",
        f"🕒 الان: {now_label()}\n",
    ]
    for op in ops[:10]:
        done = (op.get("success") or 0) + (op.get("failed") or 0)
        total = op.get("total_planned") or 0
        pct = int(done * 100 / total) if total else 0
        lines.append(
            f"{PLATFORM_ICON.get(op['platform'], '•')} کاربر <code>{op['telegram_id']}</code>\n"
            f"🎯 <code>{op.get('target', '-')}</code>\n"
            f"📝 {op.get('reason', '-')}\n"
            f"📦 {done}/{total} ({pct}%) | ✅ {op.get('success', 0)} ❌ {op.get('failed', 0)}\n"
            f"⏰ شروع (تهران): {fmt_dt(op.get('started_at'))}\n"
        )
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [btn("🔄 بروزرسانی", "admin_live", ButtonStyle.SUCCESS)],
            [btn("🔙 پنل", "admin_open", ButtonStyle.PRIMARY)],
        ]),
        parse_mode="HTML",
    )


async def admin_panel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return
    await callback.answer()

    data = callback.data

    if data in ("admin_open", "admin_panel"):
        await callback.message.answer("🛠 <b>پنل مدیریت</b>", reply_markup=kb_admin_panel(), parse_mode="HTML")
        await state.set_state(Form.admin_panel)
        return

    if data == "admin_live":
        return await admin_live_cb(callback, state)

    if data == "admin_exit":
        await callback.message.answer("🚪 خروج از پنل.", reply_markup=kb_menu_return())
        await state.set_state(Form.main_menu)
        return

    if data == "admin_broadcast":
        await callback.message.answer(
            "📢 پیام همگانی\nپیام، عکس یا فایل خود را بفرستید تا برای همه کاربران ارسال شود:",
            reply_markup=kb_menu_return(),
        )
        await state.set_state(Form.broadcast)
        return

    if data == "admin_stats":
        users = get_all_users()
        total = len(users)
        prem = sum(1 for u in users if is_premium_active(u))
        reps = sum(u.get("total_reports", 0) or 0 for u in users)
        tb = sum(1 for u in users if u.get("is_blocked"))
        running = len(get_running_ops(None))
        rb_sessions = len(get_all_rubika_sessions())
        tg_sessions = 0
        for u in users:
            tg_sessions += len(get_tg_accounts(u["telegram_id"]))
        await callback.message.answer(
            "📊 <b>آمار ربات</b>\n\n"
            f"👥 کل کاربران: {total}\n"
            f"👑 اشتراکی‌ها: {prem}\n"
            f"🚫 بلاک‌شده‌ها: {tb}\n"
            f"📱 سشن روبیکا: {rb_sessions}\n"
            f"✈️ اکانت تلگرام: {tg_sessions}\n"
            f"📡 عملیات در حال اجرا: {running}\n"
            f"📢 کل گزارش‌ها: {reps}",
            reply_markup=kb_admin_panel(),
            parse_mode="HTML",
        )
        return

    if data == "admin_grant":
        await callback.message.answer(
            "👑 <b>تمدید/اشتراک دستی</b>\n\n"
            "دو روش:\n"
            "۱) از «مدیریت کاربران» کاربر را انتخاب کنید.\n"
            "۲) دستور:\n"
            "<code>/grant آیدی سقف ساعت</code>\n"
            "مثال: <code>/grant 123456789 2000 168</code>\n"
            "(۰ برای سقف = بی‌نهایت)",
            reply_markup=kb_admin_panel(),
            parse_mode="HTML",
        )
        return

    if data == "admin_support":
        await callback.message.answer(
            "🎫 <b>پشتیبانی</b>\n"
            "پیام‌های کاربران با دکمه «پاسخ به کاربر» برایتان فوروارد می‌شود.",
            reply_markup=kb_admin_panel(),
            parse_mode="HTML",
        )
        return

    if data == "admin_list":
        users = get_all_users()
        if not users:
            await callback.message.answer("هیچ کاربری ثبت نشده.", reply_markup=kb_admin_panel())
            return
        rows = []
        for u in users[-30:][::-1]:
            uid = u["telegram_id"]
            icon = "👑" if is_premium_active(u) else "🆓"
            if u.get("is_blocked"):
                icon = "🚫"
            rows.append([btn(f"{icon} {uid}", f"adm_user_{uid}", ButtonStyle.PRIMARY)])
        rows.append([btn("🔙 پنل", "admin_open", ButtonStyle.PRIMARY)])
        await callback.message.answer(
            "👥 <b>مدیریت کاربران</b>\nیک کاربر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            parse_mode="HTML",
        )
        return

    if data.startswith("admin_reply_"):
        target_id = int(data.split("_")[-1])
        await state.update_data(reply_target=target_id)
        await state.set_state(Form.admin_reply)
        await callback.message.answer(
            f"💬 در حال پاسخ به کاربر {target_id}\nپیام/عکس/فایل خود را بفرستید:",
            reply_markup=kb_menu_return(),
        )
        return

    if data == "admin_close_ticket":
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.edit_text((callback.message.text or "") + "\n\n🚫 تیکت بسته شد.")
        except Exception:
            pass
        return

    await callback.message.answer("⚠️ گزینه نامشخص است.", reply_markup=kb_admin_panel())


async def admin_user_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """هندلر adm_*"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return
    await callback.answer()

    data = callback.data

    if data.startswith("adm_preset_"):
        parts = data.split("_")  # adm preset uid quota hours
        try:
            uid, quota, hours = int(parts[2]), int(parts[3]), int(parts[4])
        except (IndexError, ValueError):
            return
        grant_subscription(uid, quota, hours, sub_type="gift", tg_access=True)
        await _notify_user(uid, callback.bot)
        await _show_admin_user(callback.message, uid)
        return

    if data.startswith("adm_custom_"):
        uid = int(data.split("_")[-1])
        await state.update_data(admin_action="custom_sub", target=uid, sub_step="quota")
        await state.set_state(Form.admin_reply)
        await callback.message.answer(
            "✍️ <b>اشتراک سفارشی</b>\n\n"
            "سقف تعداد گزارش را وارد کنید:\n"
            "مثال: 2000\n"
            "(۰ = بدون سقف)",
            reply_markup=kb_menu_return(),
            parse_mode="HTML",
        )
        return

    if data.startswith("adm_sub_"):
        uid = int(data.split("_")[-1])
        await callback.message.answer(
            f"👑 <b>اشتراک کاربر</b> <code>{uid}</code>\n\n{user_summary_text(uid)}",
            reply_markup=kb_admin_subs(uid),
            parse_mode="HTML",
        )
        return

    if data.startswith("adm_toggle_tg_"):
        uid = int(data.split("_")[-1])
        u = get_user(uid)
        if u:
            upsert_user(uid, tg_access=0 if u.get("tg_access") else 1)
        await _show_admin_user(callback.message, uid)
        return

    if data.startswith("adm_reset_"):
        uid = int(data.split("_")[-1])
        upsert_user(uid, sub_used=0)
        await callback.message.answer(f"♻️ مصرف اشتراک کاربر {uid} صفر شد.")
        await _show_admin_user(callback.message, uid)
        return

    if data.startswith("adm_block_"):
        uid = int(data.split("_")[-1])
        u = get_user(uid)
        if u:
            new_state = 0 if u.get("is_blocked") else 1
            upsert_user(uid, is_blocked=new_state)
            try:
                await callback.bot.send_message(
                    uid,
                    "⛔ دسترسی شما به ربات توسط ادمین بسته شد."
                    if new_state else "✅ دسترسی شما به ربات باز شد.",
                )
            except Exception:
                pass
        await _show_admin_user(callback.message, uid)
        return

    if data.startswith("adm_logs_"):
        uid = int(data.split("_")[-1])
        logs = get_user_logs(uid, 15)
        if not logs:
            await callback.message.answer(
                "📋 گزارشی ثبت نشده.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [btn("🔙 بازگشت", f"adm_user_{uid}", ButtonStyle.PRIMARY)],
                ]),
            )
            return
        lines = [f"📋 <b>آخرین گزارش‌های</b> <code>{uid}</code>\n"]
        for lg in logs:
            lines.append(
                f"{PLATFORM_ICON.get(lg['platform'], '•')} <code>{lg.get('target')}</code>\n"
                f"   نوع: {lg.get('target_type', '-')} | دلیل: {lg.get('reason', '-')}\n"
                f"   ✅ {lg.get('success', 0)} | ❌ {lg.get('failed', 0)}\n"
                f"   🕐 {fmt_dt(lg.get('created_at'))}\n"
            )
        await callback.message.answer(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("🔙 بازگشت", f"adm_user_{uid}", ButtonStyle.PRIMARY)],
            ]),
            parse_mode="HTML",
        )
        return

    if data.startswith("adm_targets_"):
        uid = int(data.split("_")[-1])
        targets = get_user_targets(uid)
        if not targets:
            await callback.message.answer(
                "🎯 هدفی ثبت نشده.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [btn("🔙 بازگشت", f"adm_user_{uid}", ButtonStyle.PRIMARY)],
                ]),
            )
            return
        lines = [f"🎯 <b>اهداف کاربر</b> <code>{uid}</code>\n"]
        for t in targets[:20]:
            lines.append(
                f"{PLATFORM_ICON.get(t['platform'], '•')} <code>{t.get('target')}</code>\n"
                f"   وضعیت: {target_status_label(t.get('status'))}\n"
                f"   ✅ {t.get('total_success', 0)} | ❌ {t.get('total_failed', 0)}\n"
                f"   🕐 آخرین: {fmt_dt(t.get('last_at'))}\n"
            )
        await callback.message.answer(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("🔙 بازگشت", f"adm_user_{uid}", ButtonStyle.PRIMARY)],
            ]),
            parse_mode="HTML",
        )
        return

    if data.startswith("adm_user_"):
        uid = int(data.split("_")[-1])
        await _show_admin_user(callback.message, uid)
        return

    await callback.message.answer("⚠️ گزینه نامشخص است.", reply_markup=kb_admin_panel())


async def _show_admin_user(message: Message, uid: int) -> None:
    await message.answer(
        user_summary_text(uid),
        reply_markup=kb_admin_user(uid),
        parse_mode="HTML",
    )


async def _notify_user(uid: int, bot: Bot) -> None:
    u = get_user(uid)
    if not u:
        return
    quota = u.get("sub_quota") or 0
    try:
        await bot.send_message(
            uid,
            "🎁 <b>اشتراک شما توسط ادمین تنظیم شد</b>\n\n"
            f"📦 سقف: {'بی‌نهایت' if quota <= 0 else quota} گزارش\n"
            f"📅 انقضا: {fmt_dt(u.get('premium_until'))}\n"
            "🚀 ریپورتر تلگرام: فعال",
            reply_markup=kb_main(uid),
            parse_mode="HTML",
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  دستورات
# ══════════════════════════════════════════════════════════════════════
async def cmd_stop(message: Message) -> None:
    user_stop[message.from_user.id] = True
    await message.answer("⛔ درخواست توقف ثبت شد.")


async def cmd_admin(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("🛠 <b>پنل مدیریت</b>", reply_markup=kb_admin_panel(), parse_mode="HTML")
    await state.set_state(Form.admin_panel)


async def cmd_grant(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    args = (message.text or "").split()[1:]
    if len(args) < 2:
        await message.answer(
            "فرمت: <code>/grant آیدی سقف ساعت</code>\n"
            "مثال: <code>/grant 123456789 2000 168</code>",
            parse_mode="HTML",
        )
        return
    try:
        target_id = int(args[0])
        quota = int(args[1])
        hours = int(args[2]) if len(args) > 2 else 720
        grant_subscription(target_id, quota, hours, sub_type="gift", tg_access=True)
        await message.answer(
            f"✅ اشتراک برای {target_id} تنظیم شد.\n"
            f"📦 سقف: {'بی‌نهایت' if quota <= 0 else quota} | ⏳ {hours} ساعت"
        )
        await _notify_user(target_id, message.bot)
    except (ValueError, IndexError):
        await message.answer("❌ آرگومان نامعتبر.")


async def cmd_stats(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    users = get_all_users()
    total = len(users)
    prem = sum(1 for u in users if is_premium_active(u))
    reps = sum(u.get("total_reports", 0) or 0 for u in users)
    await message.answer(
        f"📊 آمار\n👥 کاربران: {total}\n👑 اشتراکی: {prem}\n📢 گزارش‌ها: {reps}"
        f"\n📡 در حال اجرا: {len(get_running_ops(None))}"
    )


async def cmd_reply(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("/reply <telegram_id> متن پاسخ")
        return
    target_id = int(parts[1])
    text = message.text[len(parts[0]) + len(parts[1]) + 2:].strip()
    try:
        await message.bot.send_message(chat_id=target_id, text=f"💬 پاسخ پشتیبانی:\n{text}")
        await message.answer("✅ پاسخ ارسال شد.")
    except Exception as exc:
        await message.answer(f"❌ خطا: {exc}")


# ══════════════════════════════════════════════════════════════════════
#  پیام‌های ادمین (پاسخ پشتیبانی / اشتراک سفارشی / همگانی)
# ══════════════════════════════════════════════════════════════════════
async def receive_admin_reply(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return

    data = await state.get_data()

    # ── اشتراک سفارشی ──
    if data.get("admin_action") == "custom_sub":
        target_id = int(data.get("target", 0))
        step = data.get("sub_step")

        if step == "quota":
            txt = (message.text or "").strip()
            if not txt.isdigit():
                await message.answer("❌ عدد وارد کنید (۰ = بی‌نهایت).")
                return
            await state.update_data(sub_quota=int(txt), sub_step="hours")
            await message.answer(
                "⏳ مدت اشتراک را به <b>ساعت</b> وارد کنید:\n"
                "مثال: 1 (یک ساعت) | 24 (یک روز) | 168 (یک هفته) | 720 (یک ماه)",
                parse_mode="HTML",
            )
            return

        if step == "hours":
            txt = (message.text or "").strip()
            if not txt.isdigit() or int(txt) < 1:
                await message.answer("❌ عدد مثبت (ساعت) وارد کنید.")
                return
            quota = int(data.get("sub_quota", 0))
            hours = int(txt)
            grant_subscription(target_id, quota, hours, sub_type="gift", tg_access=True)
            await _notify_user(target_id, message.bot)
            await message.answer(
                f"✅ اشتراک کاربر {target_id} تنظیم شد.\n"
                f"📦 سقف: {'بی‌نهایت' if quota <= 0 else quota} | ⏳ {hours} ساعت",
                reply_markup=kb_admin_panel(),
            )
            await _show_admin_user(message, target_id)
            await state.set_state(Form.admin_panel)
            await state.update_data(admin_action=None, target=None, sub_step=None)
            return

    # ── پاسخ به کاربر ──
    target_id = data.get("reply_target")
    if target_id:
        try:
            await message.forward(chat_id=target_id)
            await message.answer("✅ پاسخ برای کاربر ارسال شد.", reply_markup=kb_admin_panel())
        except Exception as exc:
            logger.error("admin reply to %d: %s", target_id, exc)
            await message.answer(f"❌ ارسال پاسخ ناموفق: {exc}", reply_markup=kb_admin_panel())
        await state.set_state(Form.admin_panel)
        await state.update_data(reply_target=None)
        return


async def receive_broadcast(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return

    users = get_all_users()
    total = len(users)
    success = fail = 0
    await message.answer(f"📤 ارسال همگانی به {total} کاربر...")
    for u in users:
        uid = u.get("telegram_id")
        if not uid or u.get("is_blocked"):
            continue
        try:
            await message.forward(chat_id=uid)
            success += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await message.answer(
        f"✅ همگانی تمام شد.\nموفق: {success}\nناموفق: {fail}",
        reply_markup=kb_admin_panel(),
    )
    await state.set_state(Form.admin_panel)


# ══════════════════════════════════════════════════════════════════════
#  روتر کالبک‌ها
# ══════════════════════════════════════════════════════════════════════
async def rt_cb(callback: CallbackQuery, state: FSMContext) -> None:
    # کلیک‌های سریع روی دکمه‌های نوع گزارش نباید همدیگر را خراب کنند
    lock = _rt_locks.setdefault(callback.from_user.id, asyncio.Lock())
    async with lock:
        await _rt_cb_locked(callback, state)


async def _rt_cb_locked(callback: CallbackQuery, state: FSMContext) -> None:
    tg_id = callback.from_user.id
    data = await state.get_data()
    selected: list = data.get("selected_types") or []
    if not isinstance(selected, list):
        selected = list(selected)

    if callback.data in ("rt_all", "rt_clear"):
        await callback.answer()
        if callback.data == "rt_all":
            selected = list(REPORT_TYPES_MAP.keys())      # هر ۷ نوع، به ترتیب پیش‌فرض
        else:
            selected = []
        await state.update_data(selected_types=selected)
        try:
            await callback.message.edit_reply_markup(reply_markup=kb_report_types(selected))
        except Exception:
            pass
        return

    if callback.data == "rt_confirm":
        if not selected:
            await callback.answer("حداقل یک نوع انتخاب کنید.", show_alert=True)
            return
        await callback.answer()
        if "7" in selected:
            await callback.message.answer(
                "متن گزارش «سایر» را بنویسید:",
                reply_markup=kb_menu_return(),
            )
            await state.set_state(Form.rb_other_text)
            return

        limit = limit_of(tg_id)
        remaining = remaining_quota(tg_id)
        if remaining is not None:
            limit = min(limit, remaining)
        labels = [REPORT_TYPES_MAP[k][0] for k in selected]
        await callback.message.answer(
            f"🔁 ترتیب اجرا: {' → '.join(labels)}\n"
            f"هر نوع بعد از تمام شدن نوع قبلی اجرا می‌شود.\n\n"
            f"چند گزارش از هر نوع؟ (حداکثر {limit})",
            reply_markup=kb_menu_return(),
        )
        await state.set_state(Form.rb_count)
        return

    await callback.answer()
    key = callback.data.replace("rt_", "")
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)          # ترتیب انتخاب حفظ می‌شود
    await state.update_data(selected_types=selected)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb_report_types(selected))
    except Exception:
        pass


SIMPLE_CALLBACKS = {
    "back_menu": back_to_menu,
    "menu_rubika": menu_rubika_cb,
    "menu_telegram": menu_telegram_cb,
    "account_status": account_status,
    "subscription": subscription_cb,
    "help": help_cb,
    "referral_link": referral_cb,
    "daily_reward": daily_reward_cb,
    "support": support_cb,
    "live_ops": live_ops_cb,
    "my_targets": my_targets_cb,
    "my_history": my_history_cb,
    "refresh_targets": refresh_targets_cb,
    "stop_op": stop_op_cb,
    "rb_report": rb_report_cb,
    "rb_add": rb_add_cb,
    "rb_accounts": rb_accounts_cb,
    "rb_username": rb_username_cb,
    "rb_guid_manual": rb_guid_manual_cb,
    "tga_add": tga_add_cb,
    "tga_list": tga_list_cb,
    "tg_resend": tg_resend_cb,
}


async def process_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = callback.data or ""
    tg_id = callback.from_user.id

    if data in ("noop", "none", ""):
        await callback.answer()
        return

    # ── تایید/رد رسید ──
    if data.startswith("approve_sub_") or data.startswith("reject_sub_"):
        return await admin_approve_sub(callback, state)

    # ── بررسی عضویت ──
    if data == "check_join":
        return await check_join_callback(callback, state)

    # ── بلاک ──
    if tg_id not in ADMIN_IDS and is_blocked(tg_id):
        await callback.answer("⛔ دسترسی شما بسته شده است.", show_alert=True)
        return

    upsert_user(tg_id)

    # ── ادمین ──
    if data.startswith("adm_"):
        return await admin_user_cb(callback, state)
    if data.startswith("admin_") or data in ("admin_panel",):
        return await admin_panel_callback(callback, state)

    # ── روبیکا / تلگرام ──
    if data.startswith("rb_del_"):
        return await rb_delete_cb(callback, state)
    if data.startswith("tga_del_"):
        return await tga_delete_cb(callback, state)
    if data == "rt_confirm" or data.startswith("rt_"):
        return await rt_cb(callback, state)
    if data.startswith("tgreason_"):
        return await tg_reason_cb(callback, state)
    if data in ("tgjoin_yes", "tgjoin_no"):
        return await tg_join_cb(callback, state)
    if data in TG_KINDS:
        return await tgr_select_cb(callback, state)

    if data.startswith("rb_acc_"):
        return await rb_accounts_cb(callback, state)
    if data.startswith("tga_page_"):
        return await tga_list_cb(callback, state)
    handler = SIMPLE_CALLBACKS.get(data)
    if handler:
        return await handler(callback, state)

    await callback.answer("نامشخص")


# ══════════════════════════════════════════════════════════════════════
#  فالبک منو
# ══════════════════════════════════════════════════════════════════════
async def fallback_menu(message: Message, state: FSMContext) -> None:
    await message.answer(
        "از دکمه‌های زیر استفاده کنید:",
        reply_markup=kb_main(message.from_user.id),
    )


# ══════════════════════════════════════════════════════════════════════
#  ساخت اپ و اجرا
# ══════════════════════════════════════════════════════════════════════
async def global_error_handler(update: Update, exception: Exception) -> bool:
    logger.exception("UNHANDLED EXCEPTION: %s", exception)
    try:
        if update.callback_query:
            await update.callback_query.answer(f"❌ خطا:\n{exception}", show_alert=True)
        elif update.message:
            await update.message.answer(f"❌ خطا:\n{exception}")
    except Exception:
        pass
    return True


def build_app() -> tuple[Bot, Dispatcher]:
    init_db()
    mark_stale_ops()
    bot = Bot(token=TELEGRAM_TOKEN)
    dp = Dispatcher()
    router = Router()

    # ── دستورات ──
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_stop, Command("stop"))
    router.message.register(cmd_admin, Command("admin", "panel"))
    router.message.register(cmd_grant, Command("grant"))
    router.message.register(cmd_stats, Command("stats"))
    router.message.register(cmd_reply, Command("reply"))

    # ── روبیکا: لاگین ──
    router.message.register(rb_receive_phone, Form.rb_phone, F.text | F.contact)
    router.message.register(rb_receive_password, Form.rb_password, F.text)
    router.message.register(rb_receive_code, Form.rb_code, F.text)

    # ── روبیکا: گزارش ──
    router.message.register(rb_receive_guid, Form.rb_guid, F.text)
    router.message.register(rb_receive_resolve, Form.rb_resolve, F.text)
    router.message.register(rb_receive_other_text, Form.rb_other_text, F.text)
    router.message.register(rb_receive_count, Form.rb_count, F.text)
    router.message.register(rb_receive_delay, Form.rb_delay, F.text)
    router.message.register(rb_receive_type_gap, Form.rb_type_gap, F.text)
    router.message.register(rb_receive_accounts, Form.rb_accounts, F.text)

    # ── تلگرام: لاگین ──
    router.message.register(tg_receive_phone, Form.tg_phone, F.text | F.contact)
    router.message.register(tg_receive_code, Form.tg_code, F.text)
    router.message.register(tg_receive_password, Form.tg_password, F.text)

    # ── تلگرام: گزارش ──
    router.message.register(tg_receive_accounts, Form.tg_accounts, F.text)
    router.message.register(tg_receive_target, Form.tg_target, F.text)
    router.message.register(tg_receive_links, Form.tg_links, F.text)
    router.message.register(tg_receive_manual, Form.tg_manual, F.text)
    router.message.register(tg_receive_per_acc, Form.tg_per_acc, F.text)
    router.message.register(tg_receive_delay, Form.tg_delay, F.text)

    # ── بقیه ──
    router.message.register(receive_receipt, Form.receipt)
    router.message.register(receive_support_message, Form.support_message)
    router.message.register(receive_broadcast, Form.broadcast)
    router.message.register(receive_admin_reply, Form.admin_reply)

    # ── فالبک منو ──
    router.message.register(fallback_menu, Form.main_menu, F.text)

    # ── کالبک‌ها ──
    router.callback_query.register(process_callback)

    dp.include_router(router)
    dp.errors.register(global_error_handler)
    return bot, dp


async def main() -> None:
    bot, dp = build_app()
    logger.warning("[POLLING] starting...")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())




