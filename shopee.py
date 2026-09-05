import os
import re
import time
import uuid

from datetime import datetime, timedelta, time as dt_time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)


# =========================================================
# CẤU HÌNH
# =========================================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

BASE_URL = (
    os.getenv("WEBHOOK_BASE_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///bot.db"
)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


# =========================================================
# CẤU HÌNH QUÀ ĐỔI ĐIỂM
# Có thể sửa tên/điểm tại đây sau này
# =========================================================

REWARDS = {
    "phone20": {
        "name": "📱 Thẻ điện thoại 20.000đ",
        "points": 22000,
    },
    "phone50": {
        "name": "📱 Thẻ điện thoại 50.000đ",
        "points": 55000,
    },
    "garena20": {
        "name": "🎮 Thẻ Garena 20.000đ",
        "points": 22000,
    },
    "garena50": {
        "name": "🎮 Thẻ Garena 50.000đ",
        "points": 55000,
    },
    "voucher20": {
        "name": "🎟 Voucher 20.000đ",
        "points": 20000,
    },
    "voucher50": {
        "name": "🎟 Voucher 50.000đ",
        "points": 50000,
    },
}


# =========================================================
# DATABASE URL
# =========================================================

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+psycopg://",
        1,
    )
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )


# =========================================================
# DATABASE ENGINE
# =========================================================

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
    )


# =========================================================
# TẠO DATABASE
# Giữ nguyên users_v3 + requests_v3 để không mất dữ liệu cũ.
# Hai cột available_balance/pending_balance được dùng như ĐIỂM.
# =========================================================

def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users_v3 (
                chat_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                available_balance BIGINT NOT NULL DEFAULT 0,
                pending_balance BIGINT NOT NULL DEFAULT 0,
                created_ts BIGINT NOT NULL
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS requests_v3 (
                request_id TEXT PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                platform TEXT NOT NULL,
                original_url TEXT NOT NULL,
                affiliate_url TEXT,
                status TEXT NOT NULL,
                created_ts BIGINT NOT NULL,
                updated_ts BIGINT NOT NULL
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_state_v3 (
                admin_chat_id BIGINT PRIMARY KEY,
                request_id TEXT
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reward_requests_v1 (
                reward_id TEXT PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                reward_code TEXT NOT NULL,
                reward_name TEXT NOT NULL,
                points BIGINT NOT NULL,
                gift_value TEXT,
                status TEXT NOT NULL,
                created_ts BIGINT NOT NULL,
                updated_ts BIGINT NOT NULL
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_reward_state_v1 (
                admin_chat_id BIGINT PRIMARY KEY,
                reward_id TEXT
            )
        """))


# =========================================================
# MENU CHÍNH
# =========================================================

main_keyboard = ReplyKeyboardMarkup(
    [
        ["👤 Thông tin tài khoản"],
        ["🛒 Gửi link Shopee", "🎵 Gửi link TikTok"],
        ["🎁 Đổi quà", "🪙 Điểm của tôi"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


# =========================================================
# USER / ĐIỂM
# =========================================================

def save_user(user):
    now = int(time.time())

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO users_v3 (
                    chat_id,
                    username,
                    full_name,
                    available_balance,
                    pending_balance,
                    created_ts
                )
                VALUES (
                    :chat_id,
                    :username,
                    :full_name,
                    0,
                    0,
                    :created_ts
                )
                ON CONFLICT(chat_id)
                DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name
            """),
            {
                "chat_id": user.id,
                "username": user.username or "",
                "full_name": user.full_name or "",
                "created_ts": now,
            },
        )


def get_points(chat_id):
    with engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT
                    available_balance,
                    pending_balance
                FROM users_v3
                WHERE chat_id = :chat_id
            """),
            {"chat_id": chat_id},
        ).fetchone()

    if not row:
        return 0, 0

    return int(row[0]), int(row[1])


# =========================================================
# LINK
# =========================================================

def extract_url(message):
    match = re.search(r"https?://[^\s]+", message)

    if not match:
        return None

    return match.group(0).strip().rstrip(".,);]}>\"'")


def detect_platform(url):
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().split(":")[0]

        if host.startswith("www."):
            host = host[4:]

        if (
            host == "shopee.vn"
            or host.endswith(".shopee.vn")
            or host == "shp.ee"
            or host.endswith(".shp.ee")
        ):
            return "Shopee"

        if (
            host == "tiktok.com"
            or host.endswith(".tiktok.com")
        ):
            return "TikTok"

        return None

    except Exception:
        return None


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    name = user.first_name or "bạn"

    await update.message.reply_text(
        f"👋 Xin chào {name}!\n\n"
        "🎉 Chào mừng bạn đến với Shopee Tích Xu.\n\n"
        "🛍 Hãy gửi link sản phẩm Shopee hoặc TikTok.\n"
        "Hệ thống sẽ tiếp nhận và xử lý link cho bạn.\n\n"
        "🪙 Khi đơn được đối soát, admin sẽ cộng điểm cho bạn.\n"
        "🎁 Điểm khả dụng có thể dùng để đổi voucher hoặc thẻ quà.\n\n"
        "👇 Chọn chức năng bên dưới:",
        reply_markup=main_keyboard,
    )


# =========================================================
# /ID
# =========================================================

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👤 Thông tin tài khoản của bạn\n\n"
        f"🆔 ID hội viên: {update.effective_chat.id}"
    )


# =========================================================
# THÔNG TIN TÀI KHOẢN
# =========================================================

async def account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    chat_id = user.id
    available_points, pending_points = get_points(chat_id)

    with engine.begin() as conn:
        total = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM requests_v3
                WHERE chat_id = :chat_id
            """),
            {"chat_id": chat_id},
        ).scalar() or 0

        completed = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM requests_v3
                WHERE chat_id = :chat_id
                AND status = 'done'
            """),
            {"chat_id": chat_id},
        ).scalar() or 0

        rewards_done = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM reward_requests_v1
                WHERE chat_id = :chat_id
                AND status = 'done'
            """),
            {"chat_id": chat_id},
        ).scalar() or 0

    username = f"@{user.username}" if user.username else "Chưa có"

    await update.message.reply_text(
        "👤 THÔNG TIN TÀI KHOẢN\n\n"
        f"🆔 ID hội viên: {chat_id}\n"
        f"👤 Họ tên: {user.full_name}\n"
        f"📱 Username: {username}\n\n"
        f"🪙 Điểm khả dụng: {available_points:,}\n"
        f"⏳ Điểm chờ duyệt: {pending_points:,}\n\n"
        f"📦 Tổng yêu cầu link: {total}\n"
        f"✅ Đã hoàn tất link: {completed}\n"
        f"🎁 Quà đã đổi: {rewards_done}\n\n"
        "📜 Gõ /history để xem lịch sử link.",
        reply_markup=main_keyboard,
    )


# =========================================================
# ĐIỂM CỦA TÔI
# =========================================================

async def my_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    available_points, pending_points = get_points(chat_id)

    await update.message.reply_text(
        "🪙 ĐIỂM CỦA TÔI\n\n"
        f"✅ Điểm khả dụng: {available_points:,}\n"
        f"⏳ Điểm chờ duyệt: {pending_points:,}\n\n"
        "ℹ️ Điểm chờ duyệt chưa thể dùng đổi quà.\n"
        "Khi hoa hồng được xác nhận, admin sẽ chuyển sang điểm khả dụng.",
        reply_markup=main_keyboard,
    )


# =========================================================
# KHO ĐỔI QUÀ
# =========================================================

def reward_keyboard():
    rows = []

    for code, item in REWARDS.items():
        rows.append([
            InlineKeyboardButton(
                f"{item['name']} — {item['points']:,} điểm",
                callback_data=f"reward:{code}",
            )
        ])

    return InlineKeyboardMarkup(rows)


async def rewards_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    available_points, _ = get_points(chat_id)

    await update.message.reply_text(
        "🎁 KHO ĐỔI QUÀ\n\n"
        f"🪙 Điểm khả dụng của bạn: {available_points:,}\n\n"
        "👇 Chọn phần quà muốn đổi:",
        reply_markup=reward_keyboard(),
    )


# =========================================================
# HISTORY LINK CỦA KHÁCH
# =========================================================

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    request_id,
                    platform,
                    status,
                    created_ts
                FROM requests_v3
                WHERE chat_id = :chat_id
                ORDER BY created_ts DESC
                LIMIT 10
            """),
            {"chat_id": chat_id},
        ).fetchall()

    if not rows:
        await update.message.reply_text("📜 Bạn chưa có yêu cầu nào.")
        return

    status_names = {
        "pending": "⏳ Chờ xử lý",
        "processing": "🔄 Đang xử lý",
        "done": "✅ Hoàn tất",
    }

    lines = ["📜 LỊCH SỬ YÊU CẦU\n"]

    for row in rows:
        request_id, platform, status, created_ts = row
        created_time = datetime.fromtimestamp(created_ts, TZ).strftime(
            "%d/%m/%Y %H:%M"
        )

        lines.append(
            "\n"
            f"🆔 Mã: {request_id}\n"
            f"🏪 {platform}\n"
            f"📅 {created_time}\n"
            f"{status_names.get(status, status)}\n"
        )

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=main_keyboard,
    )


# =========================================================
# CHỐNG LINK TRÙNG 5 PHÚT
# =========================================================

def find_recent_duplicate(chat_id, url):
    five_minutes_ago = int(time.time()) - 300

    with engine.begin() as conn:
        return conn.execute(
            text("""
                SELECT
                    request_id,
                    status,
                    affiliate_url
                FROM requests_v3
                WHERE chat_id = :chat_id
                AND original_url = :url
                AND created_ts >= :limit_ts
                ORDER BY created_ts DESC
                LIMIT 1
            """),
            {
                "chat_id": chat_id,
                "url": url,
                "limit_ts": five_minutes_ago,
            },
        ).fetchone()


# =========================================================
# ADMIN: CỘNG ĐIỂM CHỜ DUYỆT
# /addpoints CHAT_ID SODIEM
# =========================================================

async def add_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (
        not ADMIN_CHAT_ID
        or str(update.effective_chat.id) != str(ADMIN_CHAT_ID)
    ):
        await update.message.reply_text("⛔ Bạn không có quyền.")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Dùng:\n\n/addpoints CHAT_ID SODIEM"
        )
        return

    try:
        chat_id = int(context.args[0])
        points = int(context.args[1])

        if points <= 0:
            raise ValueError()

    except ValueError:
        await update.message.reply_text("❌ Số điểm không hợp lệ.")
        return

    now = int(time.time())

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO users_v3 (
                    chat_id,
                    username,
                    full_name,
                    available_balance,
                    pending_balance,
                    created_ts
                )
                VALUES (
                    :chat_id,
                    '',
                    '',
                    0,
                    :points,
                    :created_ts
                )
                ON CONFLICT(chat_id)
                DO UPDATE SET
                    pending_balance = users_v3.pending_balance + :points
            """),
            {
                "chat_id": chat_id,
                "points": points,
                "created_ts": now,
            },
        )

    await update.message.reply_text(
        f"✅ Đã cộng {points:,} điểm vào điểm chờ duyệt của khách {chat_id}."
    )

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⏳ ĐIỂM CHỜ DUYỆT\n\n"
                f"➕ +{points:,} điểm\n\n"
                "Điểm sẽ được chuyển sang khả dụng sau khi hoa hồng được xác nhận."
            ),
        )
    except Exception:
        pass


# =========================================================
# ADMIN: DUYỆT ĐIỂM
# /approvepoints CHAT_ID SODIEM
# =========================================================

async def approve_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (
        not ADMIN_CHAT_ID
        or str(update.effective_chat.id) != str(ADMIN_CHAT_ID)
    ):
        await update.message.reply_text("⛔ Bạn không có quyền.")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Dùng:\n\n/approvepoints CHAT_ID SODIEM"
        )
        return

    try:
        chat_id = int(context.args[0])
        points = int(context.args[1])

        if points <= 0:
            raise ValueError()

    except ValueError:
        await update.message.reply_text("❌ Số điểm không hợp lệ.")
        return

    with engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT pending_balance
                FROM users_v3
                WHERE chat_id = :chat_id
            """),
            {"chat_id": chat_id},
        ).fetchone()

        if not row:
            await update.message.reply_text("❌ Không tìm thấy khách.")
            return

        pending_points = int(row[0])

        if points > pending_points:
            await update.message.reply_text(
                f"❌ Khách chỉ có {pending_points:,} điểm đang chờ duyệt."
            )
            return

        conn.execute(
            text("""
                UPDATE users_v3
                SET
                    pending_balance = pending_balance - :points,
                    available_balance = available_balance + :points
                WHERE chat_id = :chat_id
            """),
            {
                "points": points,
                "chat_id": chat_id,
            },
        )

    await update.message.reply_text(
        f"✅ Đã duyệt {points:,} điểm cho khách {chat_id}."
    )

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ ĐIỂM ĐÃ ĐƯỢC DUYỆT\n\n"
                f"🪙 +{points:,} điểm khả dụng\n\n"
                "Bạn có thể dùng điểm này để đổi quà."
            ),
        )
    except Exception:
        pass


# =========================================================
# CALLBACK CHUNG: TRẢ LINK + ĐỔI QUÀ
# =========================================================

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""

    # -----------------------------------------------------
    # KHÁCH CHỌN QUÀ
    # -----------------------------------------------------
    if data.startswith("reward:"):
        await query.answer()

        reward_code = data.split(":", 1)[1]
        reward = REWARDS.get(reward_code)

        if not reward:
            await query.message.reply_text("❌ Phần quà không hợp lệ.")
            return

        chat_id = query.from_user.id
        available_points, _ = get_points(chat_id)
        cost = int(reward["points"])

        if available_points < cost:
            await query.answer(
                f"Bạn cần {cost:,} điểm, hiện có {available_points:,} điểm.",
                show_alert=True,
            )
            return

        reward_id = uuid.uuid4().hex[:8]
        now = int(time.time())

        with engine.begin() as conn:
            # Trừ điểm ngay để giữ điểm cho yêu cầu này.
            result = conn.execute(
                text("""
                    UPDATE users_v3
                    SET available_balance = available_balance - :cost
                    WHERE chat_id = :chat_id
                    AND available_balance >= :cost
                """),
                {
                    "cost": cost,
                    "chat_id": chat_id,
                },
            )

            if result.rowcount != 1:
                await query.message.reply_text(
                    "❌ Điểm không đủ hoặc số dư vừa thay đổi."
                )
                return

            conn.execute(
                text("""
                    INSERT INTO reward_requests_v1 (
                        reward_id,
                        chat_id,
                        reward_code,
                        reward_name,
                        points,
                        gift_value,
                        status,
                        created_ts,
                        updated_ts
                    )
                    VALUES (
                        :reward_id,
                        :chat_id,
                        :reward_code,
                        :reward_name,
                        :points,
                        NULL,
                        'pending',
                        :created_ts,
                        :updated_ts
                    )
                """),
                {
                    "reward_id": reward_id,
                    "chat_id": chat_id,
                    "reward_code": reward_code,
                    "reward_name": reward["name"],
                    "points": cost,
                    "created_ts": now,
                    "updated_ts": now,
                },
            )

        await query.message.reply_text(
            "✅ ĐÃ TẠO YÊU CẦU ĐỔI QUÀ\n\n"
            f"🆔 Mã: {reward_id}\n"
            f"🎁 Quà: {reward['name']}\n"
            f"🪙 Đã giữ: {cost:,} điểm\n\n"
            "⏳ Đang chờ admin xử lý."
        )

        if ADMIN_CHAT_ID:
            buttons = InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🎁 Gửi mã quà",
                        callback_data=f"rewardsend:{reward_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ Từ chối",
                        callback_data=f"rewardreject:{reward_id}",
                    ),
                ]]
            )

            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(
                    "🎁 YÊU CẦU ĐỔI QUÀ\n\n"
                    f"🆔 Mã: {reward_id}\n"
                    f"👤 ID khách: {chat_id}\n"
                    f"🎁 Quà: {reward['name']}\n"
                    f"🪙 Điểm: {cost:,}"
                ),
                reply_markup=buttons,
            )

        return

    # Từ đây trở xuống là nút chỉ dành cho admin
    if (
        not ADMIN_CHAT_ID
        or str(query.from_user.id) != str(ADMIN_CHAT_ID)
    ):
        await query.answer("Bạn không có quyền.", show_alert=True)
        return

    await query.answer()

    # -----------------------------------------------------
    # ADMIN BẤM TRẢ AFFILIATE LINK
    # -----------------------------------------------------
    if data.startswith("reply:"):
        request_id = data.split(":", 1)[1]

        with engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT chat_id, status
                    FROM requests_v3
                    WHERE request_id = :request_id
                """),
                {"request_id": request_id},
            ).fetchone()

            if not row:
                await query.message.reply_text("❌ Không tìm thấy yêu cầu.")
                return

            customer_chat_id, status = row

            if status == "done":
                await query.message.reply_text("✅ Yêu cầu này đã hoàn tất.")
                return

            conn.execute(
                text("""
                    UPDATE requests_v3
                    SET
                        status = 'processing',
                        updated_ts = :now
                    WHERE request_id = :request_id
                """),
                {
                    "now": int(time.time()),
                    "request_id": request_id,
                },
            )

            conn.execute(
                text("""
                    INSERT INTO admin_state_v3 (
                        admin_chat_id,
                        request_id
                    )
                    VALUES (
                        :admin_chat_id,
                        :request_id
                    )
                    ON CONFLICT(admin_chat_id)
                    DO UPDATE SET
                        request_id = excluded.request_id
                """),
                {
                    "admin_chat_id": int(ADMIN_CHAT_ID),
                    "request_id": request_id,
                },
            )

        await query.message.reply_text(
            f"📤 Đang xử lý mã {request_id}\n\n"
            "👉 Bây giờ bạn chỉ cần dán LINK AFFILIATE vào bot.\n\n"
            "Bot sẽ tự gửi đúng cho khách."
        )

        try:
            await context.bot.send_message(
                chat_id=customer_chat_id,
                text=(
                    "🔄 Yêu cầu của bạn đang được xử lý.\n\n"
                    "Bot sẽ gửi link mua hàng ngay khi hoàn tất."
                ),
            )
        except Exception:
            pass

        return

    # -----------------------------------------------------
    # ADMIN BẤM GỬI MÃ QUÀ
    # -----------------------------------------------------
    if data.startswith("rewardsend:"):
        reward_id = data.split(":", 1)[1]

        with engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT chat_id, reward_name, status
                    FROM reward_requests_v1
                    WHERE reward_id = :reward_id
                """),
                {"reward_id": reward_id},
            ).fetchone()

            if not row:
                await query.message.reply_text("❌ Không tìm thấy yêu cầu đổi quà.")
                return

            customer_chat_id, reward_name, status = row

            if status != "pending":
                await query.message.reply_text("Yêu cầu này đã được xử lý.")
                return

            conn.execute(
                text("""
                    UPDATE reward_requests_v1
                    SET
                        status = 'processing',
                        updated_ts = :now
                    WHERE reward_id = :reward_id
                """),
                {
                    "now": int(time.time()),
                    "reward_id": reward_id,
                },
            )

            conn.execute(
                text("""
                    INSERT INTO admin_reward_state_v1 (
                        admin_chat_id,
                        reward_id
                    )
                    VALUES (
                        :admin_chat_id,
                        :reward_id
                    )
                    ON CONFLICT(admin_chat_id)
                    DO UPDATE SET
                        reward_id = excluded.reward_id
                """),
                {
                    "admin_chat_id": int(ADMIN_CHAT_ID),
                    "reward_id": reward_id,
                },
            )

        await query.message.reply_text(
            f"🎁 Đang xử lý {reward_name}\n"
            f"🆔 Mã: {reward_id}\n\n"
            "👉 Bây giờ dán MÃ THẺ / MÃ VOUCHER / LINK QUÀ vào bot."
        )

        try:
            await context.bot.send_message(
                chat_id=customer_chat_id,
                text=(
                    "🔄 Yêu cầu đổi quà của bạn đang được xử lý.\n\n"
                    "Bot sẽ gửi mã quà ngay khi hoàn tất."
                ),
            )
        except Exception:
            pass

        return

    # -----------------------------------------------------
    # ADMIN TỪ CHỐI ĐỔI QUÀ -> HOÀN ĐIỂM
    # -----------------------------------------------------
    if data.startswith("rewardreject:"):
        reward_id = data.split(":", 1)[1]

        with engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT chat_id, points, reward_name, status
                    FROM reward_requests_v1
                    WHERE reward_id = :reward_id
                """),
                {"reward_id": reward_id},
            ).fetchone()

            if not row:
                await query.message.reply_text("❌ Không tìm thấy yêu cầu đổi quà.")
                return

            chat_id, points, reward_name, status = row
            points = int(points)

            if status not in ("pending", "processing"):
                await query.message.reply_text("Yêu cầu này đã được xử lý.")
                return

            conn.execute(
                text("""
                    UPDATE reward_requests_v1
                    SET
                        status = 'rejected',
                        updated_ts = :now
                    WHERE reward_id = :reward_id
                """),
                {
                    "now": int(time.time()),
                    "reward_id": reward_id,
                },
            )

            conn.execute(
                text("""
                    UPDATE users_v3
                    SET available_balance = available_balance + :points
                    WHERE chat_id = :chat_id
                """),
                {
                    "points": points,
                    "chat_id": chat_id,
                },
            )

            conn.execute(
                text("""
                    DELETE FROM admin_reward_state_v1
                    WHERE reward_id = :reward_id
                """),
                {"reward_id": reward_id},
            )

        await query.message.reply_text(
            f"❌ Đã từ chối {reward_name} và hoàn {points:,} điểm cho khách."
        )

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "❌ Yêu cầu đổi quà chưa thể hoàn tất.\n\n"
                    f"🪙 {points:,} điểm đã được hoàn lại vào tài khoản của bạn."
                ),
            )
        except Exception:
            pass

        return


# =========================================================
# ADMIN DÁN AFFILIATE LINK
# =========================================================

async def handle_admin_link(update, context, url):
    if not ADMIN_CHAT_ID:
        return False

    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return False

    with engine.begin() as conn:
        state = conn.execute(
            text("""
                SELECT request_id
                FROM admin_state_v3
                WHERE admin_chat_id = :admin_chat_id
            """),
            {"admin_chat_id": int(ADMIN_CHAT_ID)},
        ).fetchone()

        if not state:
            return False

        request_id = state[0]

        request = conn.execute(
            text("""
                SELECT chat_id
                FROM requests_v3
                WHERE request_id = :request_id
            """),
            {"request_id": request_id},
        ).fetchone()

        if not request:
            return False

        customer_chat_id = request[0]

        conn.execute(
            text("""
                UPDATE requests_v3
                SET
                    affiliate_url = :url,
                    status = 'done',
                    updated_ts = :now
                WHERE request_id = :request_id
            """),
            {
                "url": url,
                "now": int(time.time()),
                "request_id": request_id,
            },
        )

        conn.execute(
            text("""
                DELETE FROM admin_state_v3
                WHERE admin_chat_id = :admin_chat_id
            """),
            {"admin_chat_id": int(ADMIN_CHAT_ID)},
        )

    try:
        await context.bot.send_message(
            chat_id=customer_chat_id,
            text=(
                "✅ LINK MUA HÀNG ĐÃ SẴN SÀNG!\n\n"
                f"🛍 {url}\n\n"
                "❤️ Cảm ơn bạn đã sử dụng bot."
            ),
            reply_markup=main_keyboard,
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Gửi khách thất bại:\n{e}"
        )
        return True

    await update.message.reply_text("✅ Đã gửi link cho khách.")
    return True


# =========================================================
# ADMIN DÁN MÃ QUÀ / VOUCHER
# =========================================================

async def handle_admin_reward_value(update, context, message_text):
    if not ADMIN_CHAT_ID:
        return False

    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        return False

    with engine.begin() as conn:
        state = conn.execute(
            text("""
                SELECT reward_id
                FROM admin_reward_state_v1
                WHERE admin_chat_id = :admin_chat_id
            """),
            {"admin_chat_id": int(ADMIN_CHAT_ID)},
        ).fetchone()

        if not state:
            return False

        reward_id = state[0]

        row = conn.execute(
            text("""
                SELECT chat_id, reward_name, status
                FROM reward_requests_v1
                WHERE reward_id = :reward_id
            """),
            {"reward_id": reward_id},
        ).fetchone()

        if not row:
            return False

        customer_chat_id, reward_name, status = row

        if status != "processing":
            conn.execute(
                text("""
                    DELETE FROM admin_reward_state_v1
                    WHERE admin_chat_id = :admin_chat_id
                """),
                {"admin_chat_id": int(ADMIN_CHAT_ID)},
            )
            return False

        conn.execute(
            text("""
                UPDATE reward_requests_v1
                SET
                    gift_value = :gift_value,
                    status = 'done',
                    updated_ts = :now
                WHERE reward_id = :reward_id
            """),
            {
                "gift_value": message_text,
                "now": int(time.time()),
                "reward_id": reward_id,
            },
        )

        conn.execute(
            text("""
                DELETE FROM admin_reward_state_v1
                WHERE admin_chat_id = :admin_chat_id
            """),
            {"admin_chat_id": int(ADMIN_CHAT_ID)},
        )

    try:
        await context.bot.send_message(
            chat_id=customer_chat_id,
            text=(
                "🎁 QUÀ CỦA BẠN ĐÃ SẴN SÀNG!\n\n"
                f"🎁 {reward_name}\n\n"
                "🔑 Mã / Link nhận quà:\n"
                f"{message_text}\n\n"
                "❤️ Cảm ơn bạn đã sử dụng bot."
            ),
            reply_markup=main_keyboard,
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Gửi mã quà cho khách thất bại:\n{e}"
        )
        return True

    await update.message.reply_text("✅ Đã gửi mã quà cho khách.")
    return True


# =========================================================
# BÁO CÁO TRONG NGÀY
# =========================================================

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_CHAT_ID:
        return

    now = datetime.now(TZ)

    start = datetime(
        now.year,
        now.month,
        now.day,
        0,
        0,
        0,
        tzinfo=TZ,
    )

    end = start + timedelta(days=1)
    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())

    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    r.request_id,
                    r.chat_id,
                    r.platform,
                    r.original_url,
                    r.affiliate_url,
                    r.status,
                    r.created_ts,
                    u.username,
                    u.full_name
                FROM requests_v3 r
                LEFT JOIN users_v3 u
                    ON r.chat_id = u.chat_id
                WHERE r.created_ts >= :start_ts
                AND r.created_ts < :end_ts
                ORDER BY r.created_ts ASC
            """),
            {
                "start_ts": start_ts,
                "end_ts": end_ts,
            },
        ).fetchall()

    if not rows:
        await context.bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=(
                f"📊 BÁO CÁO NGÀY {now.strftime('%d/%m/%Y')}\n\n"
                "Hôm nay chưa có yêu cầu nào."
            ),
        )
        return

    status_names = {
        "pending": "⏳ Chờ xử lý",
        "processing": "🔄 Đang xử lý",
        "done": "✅ Đã trả link",
    }

    total = len(rows)
    done_count = sum(1 for row in rows if row[5] == "done")
    processing_count = sum(1 for row in rows if row[5] == "processing")
    pending_count = sum(1 for row in rows if row[5] == "pending")

    parts = [
        f"📊 BÁO CÁO YÊU CẦU NGÀY {now.strftime('%d/%m/%Y')}\n"
    ]

    for index, row in enumerate(rows, start=1):
        request_id = row[0]
        chat_id = row[1]
        platform = row[2]
        original_url = row[3]
        affiliate_url = row[4]
        status = row[5]
        created_ts = row[6]
        username = row[7]
        full_name = row[8]

        created_time = datetime.fromtimestamp(
            created_ts,
            TZ,
        ).strftime("%H:%M")

        user_text = f"@{username}" if username else "Không có username"
        name_text = full_name if full_name else "Không có tên"
        returned_link = affiliate_url if affiliate_url else "Chưa có"

        parts.append(
            "\n"
            f"{index}.\n"
            f"🆔 Mã: {request_id}\n"
            f"👤 ID khách: {chat_id}\n"
            f"👤 Tên: {name_text}\n"
            f"📱 User: {user_text}\n"
            f"🏪 Nền tảng: {platform}\n"
            f"📅 Gửi lúc: {created_time}\n"
            f"🔗 Link khách gửi:\n{original_url}\n"
            f"🔗 Link đã trả:\n{returned_link}\n"
            f"{status_names.get(status, status)}\n"
        )

    parts.append(
        "\n----------------\n"
        f"📦 Tổng yêu cầu: {total}\n"
        f"✅ Đã trả link: {done_count}\n"
        f"🔄 Đang xử lý: {processing_count}\n"
        f"⏳ Chờ xử lý: {pending_count}"
    )

    report = "".join(parts)
    max_length = 3800

    while report:
        if len(report) <= max_length:
            chunk = report
            report = ""
        else:
            cut = report.rfind("\n", 0, max_length)
            if cut <= 0:
                cut = max_length

            chunk = report[:cut]
            report = report[cut:].lstrip()

        await context.bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=chunk,
        )


# =========================================================
# /REPORT
# =========================================================

async def report_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (
        not ADMIN_CHAT_ID
        or str(update.effective_chat.id) != str(ADMIN_CHAT_ID)
    ):
        await update.message.reply_text("⛔ Bạn không có quyền.")
        return

    await send_daily_report(context)


# =========================================================
# HANDLE MESSAGE
# =========================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    chat_id = update.effective_chat.id
    message_text = update.message.text.strip()

    # -----------------------------------------------------
    # Nếu admin đang chờ dán MÃ QUÀ thì ưu tiên xử lý trước.
    # Mã quà có thể là chữ, số hoặc URL.
    # -----------------------------------------------------
    handled_reward = await handle_admin_reward_value(
        update,
        context,
        message_text,
    )

    if handled_reward:
        return

    url = extract_url(message_text)

    # -----------------------------------------------------
    # Nếu admin đang chờ dán affiliate link
    # -----------------------------------------------------
    if url:
        handled_link = await handle_admin_link(
            update,
            context,
            url,
        )

        if handled_link:
            return

    # -----------------------------------------------------
    # MENU
    # -----------------------------------------------------
    if message_text == "👤 Thông tin tài khoản":
        await account_info(update, context)
        return

    if message_text == "🪙 Điểm của tôi":
        await my_points(update, context)
        return

    if message_text == "🎁 Đổi quà":
        await rewards_menu(update, context)
        return

    if message_text == "🛒 Gửi link Shopee":
        await update.message.reply_text(
            "🛒 Hãy dán link sản phẩm Shopee vào đây.",
            reply_markup=main_keyboard,
        )
        return

    if message_text == "🎵 Gửi link TikTok":
        await update.message.reply_text(
            "🎵 Hãy dán link sản phẩm TikTok vào đây.",
            reply_markup=main_keyboard,
        )
        return

    # -----------------------------------------------------
    # KHÔNG CÓ LINK
    # -----------------------------------------------------
    if not url:
        await update.message.reply_text(
            "❌ Mình chưa thấy link.\n\n"
            "Hãy gửi link Shopee hoặc TikTok.",
            reply_markup=main_keyboard,
        )
        return

    # -----------------------------------------------------
    # NHẬN DIỆN PLATFORM
    # -----------------------------------------------------
    platform = detect_platform(url)

    if not platform:
        await update.message.reply_text(
            "❌ Link này chưa được hỗ trợ.\n\n"
            "Hiện bot hỗ trợ Shopee và TikTok.",
            reply_markup=main_keyboard,
        )
        return

    # -----------------------------------------------------
    # CHỐNG LINK TRÙNG 5 PHÚT
    # -----------------------------------------------------
    duplicate = find_recent_duplicate(chat_id, url)

    if duplicate:
        request_id, status, affiliate_url = duplicate

        if status == "done" and affiliate_url:
            await update.message.reply_text(
                "✅ Link này vừa được xử lý.\n\n"
                f"🛍 Link mua hàng:\n{affiliate_url}",
                reply_markup=main_keyboard,
            )
            return

        await update.message.reply_text(
            "⏳ Link này đã được gửi trước đó.\n\n"
            f"🆔 Mã yêu cầu: {request_id}\n\n"
            "Vui lòng chờ xử lý.",
            reply_markup=main_keyboard,
        )
        return

    # -----------------------------------------------------
    # TẠO REQUEST
    # -----------------------------------------------------
    request_id = uuid.uuid4().hex[:8]
    now_ts = int(time.time())

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO requests_v3 (
                    request_id,
                    chat_id,
                    platform,
                    original_url,
                    affiliate_url,
                    status,
                    created_ts,
                    updated_ts
                )
                VALUES (
                    :request_id,
                    :chat_id,
                    :platform,
                    :url,
                    NULL,
                    'pending',
                    :created_ts,
                    :updated_ts
                )
            """),
            {
                "request_id": request_id,
                "chat_id": chat_id,
                "platform": platform,
                "url": url,
                "created_ts": now_ts,
                "updated_ts": now_ts,
            },
        )

    await update.message.reply_text(
        f"✅ Đã nhận link {platform}!\n\n"
        f"🆔 Mã yêu cầu: {request_id}\n"
        "⏳ Trạng thái: Chờ xử lý.\n\n"
        "Bot sẽ gửi lại link mua hàng sau khi hoàn tất.",
        reply_markup=main_keyboard,
    )

    # -----------------------------------------------------
    # GỬI CHO ADMIN
    # -----------------------------------------------------
    if ADMIN_CHAT_ID:
        username = f"@{user.username}" if user.username else "Không có username"
        now_text = datetime.now(TZ).strftime("%d/%m/%Y %H:%M")

        buttons = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(
                    "📤 Trả link cho khách",
                    callback_data=f"reply:{request_id}",
                )
            ]]
        )

        try:
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(
                    "🔔 YÊU CẦU MỚI\n\n"
                    f"🏪 Nền tảng: {platform}\n"
                    f"🆔 Mã: {request_id}\n"
                    f"👤 User: {username}\n"
                    f"💬 ID khách: {chat_id}\n"
                    f"📅 Thời gian: {now_text}\n\n"
                    f"🔗 Link khách gửi:\n{url}"
                ),
                reply_markup=buttons,
            )
        except Exception as e:
            print(f"Lỗi gửi admin: {e}")


# =========================================================
# MAIN
# =========================================================

def main():
    if not TOKEN:
        raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN")

    if not BASE_URL:
        raise RuntimeError(
            "Thiếu RENDER_EXTERNAL_URL hoặc WEBHOOK_BASE_URL"
        )

    init_db()

    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # BÁO CÁO TỰ ĐỘNG 23:30 HÀNG NGÀY
    # -----------------------------------------------------
    report_time = dt_time(
        hour=23,
        minute=30,
        tzinfo=TZ,
    )

    app.job_queue.run_daily(
        send_daily_report,
        time=report_time,
        name="daily_admin_report",
    )

    # -----------------------------------------------------
    # COMMANDS
    # -----------------------------------------------------
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("report", report_now))
    app.add_handler(CommandHandler("addpoints", add_points))
    app.add_handler(CommandHandler("approvepoints", approve_points))

    app.add_handler(CallbackQueryHandler(admin_callback))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    webhook_url = f"{BASE_URL.rstrip('/')}/telegram"
    print(f"Webhook URL: {webhook_url}")

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        url_path="telegram",
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
