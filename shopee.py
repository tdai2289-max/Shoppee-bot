import os
import re
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
        connect_args={
            "check_same_thread": False
        },
    )

else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
    )


# =========================================================
# TẠO DATABASE
# =========================================================

def init_db():

    with engine.begin() as conn:

        # USER
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,

                available_balance BIGINT
                    NOT NULL DEFAULT 0,

                pending_balance BIGINT
                    NOT NULL DEFAULT 0,

                created_ts BIGINT NOT NULL
            )
        """))

        # REQUEST
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS requests (
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

        # ADMIN ĐANG TRẢ LINK CHO AI
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_state (
                admin_chat_id BIGINT PRIMARY KEY,

                request_id TEXT
            )
        """))

        # RÚT TIỀN
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                withdrawal_id TEXT PRIMARY KEY,

                chat_id BIGINT NOT NULL,

                amount BIGINT NOT NULL,

                bank_info TEXT NOT NULL,

                status TEXT NOT NULL,

                created_ts BIGINT NOT NULL
            )
        """))

        # STATE NHẬP RÚT TIỀN
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS withdraw_state (
                chat_id BIGINT PRIMARY KEY,

                stage TEXT NOT NULL,

                amount BIGINT NOT NULL DEFAULT 0
            )
        """))


# =========================================================
# MENU
# =========================================================

main_keyboard = ReplyKeyboardMarkup(
    [
        [
            "👤 Thông tin tài khoản"
        ],
        [
            "🛒 Gửi link Shopee",
            "🎵 Gửi link TikTok",
        ],
        [
            "💳 Rút tiền",
            "💰 Thu nhập",
        ],
    ],

    resize_keyboard=True,

    is_persistent=True,
)


# =========================================================
# SAVE USER
# =========================================================

def save_user(user):

    now = int(time.time())

    username = user.username or ""

    full_name = user.full_name or ""

    with engine.begin() as conn:

        conn.execute(
            text("""
                INSERT INTO users (
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

                    username =
                        excluded.username,

                    full_name =
                        excluded.full_name
            """),

            {
                "chat_id": user.id,

                "username": username,

                "full_name": full_name,

                "created_ts": now,
            },
        )


# =========================================================
# LẤY SỐ DƯ
# =========================================================

def get_balances(chat_id):

    with engine.begin() as conn:

        row = conn.execute(
            text("""
                SELECT
                    available_balance,
                    pending_balance

                FROM users

                WHERE chat_id = :chat_id
            """),

            {
                "chat_id": chat_id
            },

        ).fetchone()

    if not row:
        return 0, 0

    return (
        int(row[0]),
        int(row[1]),
    )


# =========================================================
# LẤY LINK
# =========================================================

def extract_url(message):

    match = re.search(
        r"https?://[^\s]+",
        message,
    )

    if not match:
        return None

    url = match.group(0).strip()

    url = url.rstrip(
        ".,);]}>\"'"
    )

    return url


# =========================================================
# NHẬN DIỆN SHOPEE / TIKTOK
# =========================================================

def detect_platform(url):

    try:

        parsed = urlparse(url)

        host = (
            parsed.netloc
            .lower()
            .split(":")[0]
        )

        if host.startswith("www."):

            host = host[4:]

        # SHOPEE
        if (
            host == "shopee.vn"

            or host.endswith(
                ".shopee.vn"
            )

            or host == "shp.ee"

            or host.endswith(
                ".shp.ee"
            )
        ):
            return "Shopee"

        # TIKTOK
        if (
            host == "tiktok.com"

            or host.endswith(
                ".tiktok.com"
            )
        ):
            return "TikTok"

        return None

    except Exception:

        return None


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    save_user(user)

    name = (
        user.first_name
        or "bạn"
    )

    await update.message.reply_text(
        f"👋 Xin chào {name}!\n\n"

        "🎉 Chào mừng bạn đến với Shopee Tích Xu.\n\n"

        "🛍 Hãy gửi link sản phẩm Shopee hoặc TikTok.\n"

        "Hệ thống sẽ tiếp nhận và xử lý link cho bạn.\n\n"

        "👇 Chọn chức năng bên dưới:",

        reply_markup=main_keyboard,
    )


# =========================================================
# THÔNG TIN TÀI KHOẢN
# =========================================================

async def account_info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    save_user(user)

    chat_id = user.id

    available, pending = get_balances(
        chat_id
    )

    with engine.begin() as conn:

        total_requests = conn.execute(
            text("""
                SELECT COUNT(*)

                FROM requests

                WHERE chat_id = :chat_id
            """),

            {
                "chat_id": chat_id
            },

        ).scalar() or 0

        completed = conn.execute(
            text("""
                SELECT COUNT(*)

                FROM requests

                WHERE
                    chat_id = :chat_id

                AND status = 'done'
            """),

            {
                "chat_id": chat_id
            },

        ).scalar() or 0

    username = (
        f"@{user.username}"

        if user.username

        else "Chưa có"
    )

    await update.message.reply_text(
        "👤 THÔNG TIN TÀI KHOẢN\n\n"

        f"🆔 ID hội viên: {chat_id}\n"

        f"👤 Họ tên: {user.full_name}\n"

        f"📱 Username: {username}\n\n"

        f"💰 Số dư có thể rút: "
        f"{available:,}đ\n"

        f"⏳ Số dư chờ duyệt: "
        f"{pending:,}đ\n\n"

        f"📦 Tổng yêu cầu: "
        f"{total_requests}\n"

        f"✅ Đã hoàn tất: "
        f"{completed}\n\n"

        "📜 Xem lịch sử bằng /history",

        reply_markup=main_keyboard,
    )


# =========================================================
# THU NHẬP
# =========================================================

async def income(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = (
        update.effective_chat.id
    )

    available, pending = get_balances(
        chat_id
    )

    await update.message.reply_text(
        "💰 THU NHẬP\n\n"

        f"💰 Có thể rút: "
        f"{available:,}đ\n"

        f"⏳ Chờ duyệt: "
        f"{pending:,}đ",

        reply_markup=main_keyboard,
    )


# =========================================================
# LỊCH SỬ KHÁCH
# =========================================================

async def history(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = (
        update.effective_chat.id
    )

    with engine.begin() as conn:

        rows = conn.execute(
            text("""
                SELECT
                    request_id,
                    platform,
                    status,
                    created_ts

                FROM requests

                WHERE chat_id = :chat_id

                ORDER BY
                    created_ts DESC

                LIMIT 10
            """),

            {
                "chat_id": chat_id
            },

        ).fetchall()

    if not rows:

        await update.message.reply_text(
            "📜 Bạn chưa có yêu cầu nào."
        )

        return

    status_names = {

        "pending":
            "⏳ Chờ xử lý",

        "processing":
            "🔄 Đang xử lý",

        "done":
            "✅ Hoàn tất",
    }

    tz = ZoneInfo(
        "Asia/Ho_Chi_Minh"
    )

    lines = [
        "📜 LỊCH SỬ YÊU CẦU\n"
    ]

    for row in rows:

        request_id = row[0]

        platform = row[1]

        status = row[2]

        created_ts = row[3]

        created_time = (
            datetime
            .fromtimestamp(
                created_ts,
                tz
            )
            .strftime(
                "%d/%m/%Y %H:%M"
            )
        )

        lines.append(
            "\n"
            f"🆔 {request_id}\n"

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

def find_recent_duplicate(
    chat_id,
    url,
):

    five_minutes_ago = (
        int(time.time()) - 300
    )

    with engine.begin() as conn:

        row = conn.execute(
            text("""
                SELECT
                    request_id,
                    status,
                    affiliate_url

                FROM requests

                WHERE
                    chat_id = :chat_id

                AND
                    original_url = :url

                AND
                    created_ts >= :limit_ts

                ORDER BY
                    created_ts DESC

                LIMIT 1
            """),

            {
                "chat_id": chat_id,

                "url": url,

                "limit_ts":
                    five_minutes_ago,
            },

        ).fetchone()

    return row


# =========================================================
# RÚT TIỀN
# =========================================================

async def withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = (
        update.effective_chat.id
    )

    available, pending = get_balances(
        chat_id
    )

    if available <= 0:

        await update.message.reply_text(
            "💳 RÚT TIỀN\n\n"

            f"💰 Số dư có thể rút: "
            f"{available:,}đ\n\n"

            "❌ Hiện tại bạn chưa có "
            "số dư có thể rút.",

            reply_markup=main_keyboard,
        )

        return

    with engine.begin() as conn:

        conn.execute(
            text("""
                INSERT INTO withdraw_state (
                    chat_id,
                    stage,
                    amount
                )

                VALUES (
                    :chat_id,
                    'amount',
                    0
                )

                ON CONFLICT(chat_id)

                DO UPDATE SET
                    stage = 'amount',
                    amount = 0
            """),

            {
                "chat_id": chat_id
            },
        )

    await update.message.reply_text(
        "💳 RÚT TIỀN\n\n"

        f"💰 Số dư có thể rút: "
        f"{available:,}đ\n\n"

        "👉 Nhập số tiền muốn rút.\n\n"

        "Ví dụ:\n"
        "50000"
    )


# =========================================================
# WITHDRAW STATE
# =========================================================

def get_withdraw_state(chat_id):

    with engine.begin() as conn:

        return conn.execute(
            text("""
                SELECT
                    stage,
                    amount

                FROM withdraw_state

                WHERE chat_id = :chat_id
            """),

            {
                "chat_id": chat_id
            },

        ).fetchone()


def clear_withdraw_state(chat_id):

    with engine.begin() as conn:

        conn.execute(
            text("""
                DELETE FROM withdraw_state

                WHERE chat_id = :chat_id
            """),

            {
                "chat_id": chat_id
            },
        )


# =========================================================
# ADMIN CỘNG TIỀN CHỜ DUYỆT
# =========================================================

async def add_pending(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        not ADMIN_CHAT_ID

        or str(
            update.effective_chat.id
        )
        != str(
            ADMIN_CHAT_ID
        )
    ):
        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "Dùng:\n\n"

            "/addpending CHAT_ID SOTIEN"
        )

        return

    try:

        chat_id = int(
            context.args[0]
        )

        amount = int(
            context.args[1]
        )

        if amount <= 0:
            raise ValueError()

    except ValueError:

        await update.message.reply_text(
            "❌ Số tiền không hợp lệ."
        )

        return

    now = int(time.time())

    with engine.begin() as conn:

        conn.execute(
            text("""
                INSERT INTO users (
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
                    :amount,
                    :created_ts
                )

                ON CONFLICT(chat_id)

                DO UPDATE SET

                    pending_balance =
                        users.pending_balance
                        + :amount
            """),

            {
                "chat_id": chat_id,

                "amount": amount,

                "created_ts": now,
            },
        )

    await update.message.reply_text(
        f"✅ Đã cộng "
        f"{amount:,}đ "
        "vào số dư chờ duyệt."
    )

    try:

        await context.bot.send_message(
            chat_id=chat_id,

            text=(
                "⏳ HOA HỒNG CHỜ DUYỆT\n\n"

                f"➕ +{amount:,}đ"
            ),
        )

    except Exception:

        pass


# =========================================================
# ADMIN DUYỆT HOA HỒNG
# CHUYỂN CHỜ DUYỆT -> CÓ THỂ RÚT
# =========================================================

async def approve_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        not ADMIN_CHAT_ID

        or str(
            update.effective_chat.id
        )
        != str(
            ADMIN_CHAT_ID
        )
    ):
        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "Dùng:\n\n"

            "/approvebalance "
            "CHAT_ID SOTIEN"
        )

        return

    try:

        chat_id = int(
            context.args[0]
        )

        amount = int(
            context.args[1]
        )

        if amount <= 0:
            raise ValueError()

    except ValueError:

        await update.message.reply_text(
            "❌ Số tiền không hợp lệ."
        )

        return

    with engine.begin() as conn:

        row = conn.execute(
            text("""
                SELECT pending_balance

                FROM users

                WHERE chat_id = :chat_id
            """),

            {
                "chat_id": chat_id
            },

        ).fetchone()

        if not row:

            await update.message.reply_text(
                "❌ Không tìm thấy user."
            )

            return

        pending = int(
            row[0]
        )

        if amount > pending:

            await update.message.reply_text(
                f"❌ User chỉ có "
                f"{pending:,}đ "
                "đang chờ duyệt."
            )

            return

        conn.execute(
            text("""
                UPDATE users

                SET

                    pending_balance =
                        pending_balance
                        - :amount,

                    available_balance =
                        available_balance
                        + :amount

                WHERE chat_id = :chat_id
            """),

            {
                "amount": amount,

                "chat_id": chat_id,
            },
        )

    await update.message.reply_text(
        f"✅ Đã duyệt "
        f"{amount:,}đ."
    )

    try:

        await context.bot.send_message(
            chat_id=chat_id,

            text=(
                "✅ HOA HỒNG ĐÃ ĐƯỢC DUYỆT\n\n"

                f"💰 +{amount:,}đ "
                "vào số dư có thể rút."
            ),
        )

    except Exception:

        pass


# =========================================================
# ADMIN CALLBACK
# =========================================================

async def admin_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if (
        not ADMIN_CHAT_ID

        or str(
            query.from_user.id
        )
        != str(
            ADMIN_CHAT_ID
        )
    ):

        await query.answer(
            "Bạn không có quyền.",
            show_alert=True,
        )

        return

    data = query.data


    # =====================================================
    # TRẢ LINK
    # =====================================================

    if data.startswith(
        "reply:"
    ):

        request_id = (
            data.split(
                ":",
                1
            )[1]
        )

        with engine.begin() as conn:

            row = conn.execute(
                text("""
                    SELECT
                        chat_id,
                        status

                    FROM requests

                    WHERE
                        request_id =
                        :request_id
                """),

                {
                    "request_id":
                        request_id
                },

            ).fetchone()

            if not row:

                await query.message.reply_text(
                    "❌ Không tìm thấy "
                    "yêu cầu."
                )

                return

            customer_chat_id = row[0]

            status = row[1]

            if status == "done":

                await query.message.reply_text(
                    "✅ Yêu cầu này "
                    "đã hoàn tất."
                )

                return

            conn.execute(
                text("""
                    UPDATE requests

                    SET
                        status = 'processing',

                        updated_ts = :now

                    WHERE
                        request_id =
                        :request_id
                """),

                {
                    "now":
                        int(time.time()),

                    "request_id":
                        request_id,
                },
            )

            conn.execute(
                text("""
                    INSERT INTO admin_state (
                        admin_chat_id,
                        request_id
                    )

                    VALUES (
                        :admin_chat_id,
                        :request_id
                    )

                    ON CONFLICT(
                        admin_chat_id
                    )

                    DO UPDATE SET

                        request_id =
                            excluded.request_id
                """),

                {
                    "admin_chat_id":
                        int(
                            ADMIN_CHAT_ID
                        ),

                    "request_id":
                        request_id,
                },
            )

        await query.message.reply_text(
            f"📤 Yêu cầu "
            f"{request_id}\n\n"

            "👉 Bây giờ chỉ cần "
            "dán link affiliate "
            "vào bot."
        )

        try:

            await context.bot.send_message(
                chat_id=
                    customer_chat_id,

                text=(
                    "🔄 Yêu cầu của bạn "
                    "đang được xử lý.\n\n"

                    "Bot sẽ gửi link "
                    "ngay khi hoàn tất."
                ),
            )

        except Exception:

            pass

        return


    # =====================================================
    # DUYỆT RÚT
    # =====================================================

    if data.startswith(
        "wdapprove:"
    ):

        withdrawal_id = (
            data.split(
                ":",
                1
            )[1]
        )

        with engine.begin() as conn:

            row = conn.execute(
                text("""
                    SELECT
                        chat_id,
                        amount,
                        status

                    FROM withdrawals

                    WHERE
                        withdrawal_id =
                        :wid
                """),

                {
                    "wid":
                        withdrawal_id
                },

            ).fetchone()

            if not row:
                return

            chat_id = row[0]

            amount = row[1]

            status = row[2]

            if status != "pending":

                await query.message.reply_text(
                    "Yêu cầu này "
                    "đã được xử lý."
                )

                return

            conn.execute(
                text("""
                    UPDATE withdrawals

                    SET status =
                        'approved'

                    WHERE withdrawal_id =
                        :wid
                """),

                {
                    "wid":
                        withdrawal_id
                },
            )

        await context.bot.send_message(
            chat_id=chat_id,

            text=(
                "✅ YÊU CẦU RÚT TIỀN "
                "ĐÃ ĐƯỢC DUYỆT\n\n"

                f"💵 Số tiền: "
                f"{amount:,}đ"
            ),
        )

        await query.message.reply_text(
            f"✅ Đã duyệt rút "
            f"{amount:,}đ."
        )

        return


    # =====================================================
    # TỪ CHỐI RÚT
    # =====================================================

    if data.startswith(
        "wdreject:"
    ):

        withdrawal_id = (
            data.split(
                ":",
                1
            )[1]
        )

        with engine.begin() as conn:

            row = conn.execute(
                text("""
                    SELECT
                        chat_id,
                        amount,
                        status

                    FROM withdrawals

                    WHERE
                        withdrawal_id =
                        :wid
                """),

                {
                    "wid":
                        withdrawal_id
                },

            ).fetchone()

            if not row:
                return

            chat_id = row[0]

            amount = row[1]

            status = row[2]

            if status != "pending":

                await query.message.reply_text(
                    "Yêu cầu này "
                    "đã được xử lý."
                )

                return

            conn.execute(
                text("""
                    UPDATE withdrawals

                    SET status =
                        'rejected'

                    WHERE
                        withdrawal_id =
                        :wid
                """),

                {
                    "wid":
                        withdrawal_id
                },
            )

            # Hoàn số dư
            conn.execute(
                text("""
                    UPDATE users

                    SET
                        available_balance =
                            available_balance
                            + :amount

                    WHERE
                        chat_id = :chat_id
                """),

                {
                    "amount":
                        amount,

                    "chat_id":
                        chat_id,
                },
            )

        await context.bot.send_message(
            chat_id=chat_id,

            text=(
                "❌ Yêu cầu rút tiền "
                "không được duyệt.\n\n"

                f"💰 {amount:,}đ "
                "đã được hoàn lại."
            ),
        )

        await query.message.reply_text(
            "❌ Đã từ chối "
            "và hoàn số dư."
        )


# =========================================================
# ADMIN DÁN AFFILIATE LINK
# =========================================================

async def handle_admin_link(
    update,
    context,
    url,
):

    if not ADMIN_CHAT_ID:
        return False

    if (
        str(
            update.effective_chat.id
        )
        != str(
            ADMIN_CHAT_ID
        )
    ):

        return False

    with engine.begin() as conn:

        state = conn.execute(
            text("""
                SELECT request_id

                FROM admin_state

                WHERE
                    admin_chat_id =
                    :admin_chat_id
            """),

            {
                "admin_chat_id":
                    int(
                        ADMIN_CHAT_ID
                    )
            },

        ).fetchone()

        if not state:

            return False

        request_id = (
            state[0]
        )

        request = conn.execute(
            text("""
                SELECT chat_id

                FROM requests

                WHERE
                    request_id =
                    :request_id
            """),

            {
                "request_id":
                    request_id
            },

        ).fetchone()

        if not request:

            return False

        customer_chat_id = (
            request[0]
        )

        conn.execute(
            text("""
                UPDATE requests

                SET
                    affiliate_url = :url,

                    status = 'done',

                    updated_ts = :now

                WHERE
                    request_id =
                    :request_id
            """),

            {
                "url": url,

                "now":
                    int(time.time()),

                "request_id":
                    request_id,
            },
        )

        conn.execute(
            text("""
                DELETE FROM admin_state

                WHERE
                    admin_chat_id =
                    :admin_chat_id
            """),

            {
                "admin_chat_id":
                    int(
                        ADMIN_CHAT_ID
                    )
            },
        )

    await context.bot.send_message(
        chat_id=customer_chat_id,

        text=(
            "✅ LINK MUA HÀNG "
            "ĐÃ SẴN SÀNG!\n\n"

            f"🛍 {url}\n\n"

            "❤️ Cảm ơn bạn "
            "đã sử dụng bot."
        ),

        reply_markup=main_keyboard,
    )

    await update.message.reply_text(
        "✅ Đã gửi link "
        "cho khách."
    )

    return True


# =========================================================
# BÁO CÁO CUỐI NGÀY
# =========================================================

async def send_daily_report(
    app
):

    if not ADMIN_CHAT_ID:
        return

    tz = ZoneInfo(
        "Asia/Ho_Chi_Minh"
    )

    now = datetime.now(tz)

    start = datetime(
        now.year,
        now.month,
        now.day,
        0,
        0,
        0,
        tzinfo=tz,
    )

    end = (
        start
        + timedelta(days=1)
    )

    start_ts = int(
        start.timestamp()
    )

    end_ts = int(
        end.timestamp()
    )

    with engine.begin() as conn:

        rows = conn.execute(
            text("""
                SELECT
                    request_id,
                    chat_id,
                    platform,
                    original_url,
                    affiliate_url,
                    status,
                    created_ts

                FROM requests

                WHERE
                    created_ts >=
                        :start_ts

                AND
                    created_ts <
                        :end_ts

                ORDER BY
                    created_ts ASC
            """),

            {
                "start_ts":
                    start_ts,

                "end_ts":
                    end_ts,
            },

        ).fetchall()

    if not rows:

        await app.bot.send_message(
            chat_id=int(
                ADMIN_CHAT_ID
            ),

            text=(
                f"📊 BÁO CÁO NGÀY "
                f"{now.strftime('%d/%m/%Y')}\n\n"

                "Hôm nay chưa có "
                "yêu cầu nào."
            ),
        )

        return

    status_names = {

        "pending":
            "⏳ Chờ xử lý",

        "processing":
            "🔄 Đang xử lý",

        "done":
            "✅ Đã trả link",
    }

    total = len(rows)

    done_count = sum(
        1
        for row in rows

        if row[5] == "done"
    )

    unfinished = (
        total - done_count
    )

    parts = [
        f"📊 BÁO CÁO YÊU CẦU "
        f"NGÀY "
        f"{now.strftime('%d/%m/%Y')}\n"
    ]

    for index, row in enumerate(
        rows,
        start=1
    ):

        request_id = row[0]

        chat_id = row[1]

        platform = row[2]

        original_url = row[3]

        affiliate_url = row[4]

        status = row[5]

        created_ts = row[6]

        created_time = (
            datetime
            .fromtimestamp(
                created_ts,
                tz
            )
            .strftime(
                "%H:%M"
            )
        )

        affiliate_text = (
            affiliate_url
            if affiliate_url
            else "Chưa có"
        )

        parts.append(
            "\n"
            f"{index}.\n"

            f"🆔 Mã: "
            f"{request_id}\n"

            f"👤 ID khách: "
            f"{chat_id}\n"

            f"🏪 {platform}\n"

            f"📅 Gửi lúc: "
            f"{created_time}\n"

            f"🔗 Link gốc:\n"
            f"{original_url}\n"

            f"🔗 Link đã trả:\n"
            f"{affiliate_text}\n"

            f"{status_names.get(status, status)}\n"
        )

    parts.append(
        "\n----------------\n"

        f"📦 Tổng yêu cầu: "
        f"{total}\n"

        f"✅ Đã trả link: "
        f"{done_count}\n"

        f"⏳ Chưa hoàn tất: "
        f"{unfinished}"
    )

    report = "".join(parts)

    max_length = 3800

    while report:

        chunk = report[
            :max_length
        ]

        report = report[
            max_length:
        ]

        await app.bot.send_message(
            chat_id=int(
                ADMIN_CHAT_ID
            ),

            text=chunk,
        )


# =========================================================
# /REPORT - ADMIN XEM NGAY
# =========================================================

async def report_now(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        not ADMIN_CHAT_ID

        or str(
            update.effective_chat.id
        )
        != str(
            ADMIN_CHAT_ID
        )
    ):

        await update.message.reply_text(
            "⛔ Bạn không có quyền."
        )

        return

    await send_daily_report(
        context.application
    )


# =========================================================
# HANDLE MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    save_user(user)

    chat_id = (
        update.effective_chat.id
    )

    message_text = (
        update.message.text.strip()
    )

    url = extract_url(
        message_text
    )


    # =====================================================
    # ADMIN ĐANG CHỜ DÁN LINK
    # =====================================================

    if url:

        handled = await handle_admin_link(
            update,
            context,
            url,
        )

        if handled:
            return


    # =====================================================
    # ĐANG RÚT TIỀN
    # =====================================================

    withdraw_state = (
        get_withdraw_state(
            chat_id
        )
    )

    if withdraw_state:

        stage = withdraw_state[0]

        stored_amount = (
            withdraw_state[1]
        )


        # =================================================
        # NHẬP SỐ TIỀN
        # =================================================

        if stage == "amount":

            amount_text = (
                message_text
                .replace(
                    ".",
                    ""
                )
                .replace(
                    ",",
                    ""
                )
                .replace(
                    "đ",
                    ""
                )
                .strip()
            )

            try:

                amount = int(
                    amount_text
                )

            except ValueError:

                await update.message.reply_text(
                    "❌ Vui lòng nhập "
                    "số tiền.\n\n"

                    "Ví dụ:\n"
                    "50000"
                )

                return

            available, pending = (
                get_balances(
                    chat_id
                )
            )

            if amount <= 0:

                await update.message.reply_text(
                    "❌ Số tiền "
                    "không hợp lệ."
                )

                return

            if amount > available:

                await update.message.reply_text(
                    f"❌ Số dư có thể rút "
                    f"của bạn chỉ có "
                    f"{available:,}đ."
                )

                return

            with engine.begin() as conn:

                conn.execute(
                    text("""
                        UPDATE withdraw_state

                        SET
                            stage = 'bank',

                            amount = :amount

                        WHERE
                            chat_id =
                            :chat_id
                    """),

                    {
                        "amount":
                            amount,

                        "chat_id":
                            chat_id,
                    },
                )

            await update.message.reply_text(
                "🏦 Nhập thông tin "
                "nhận tiền.\n\n"

                "Ví dụ:\n"

                "Vietcombank - "
                "0123456789 - "
                "NGUYEN VAN A"
            )

            return


        # =================================================
        # NHẬP TÀI KHOẢN
        # =================================================

        if stage == "bank":

            bank_info = (
                message_text
            )

            amount = int(
                stored_amount
            )

            withdrawal_id = (
                uuid.uuid4()
                .hex[:8]
            )

            with engine.begin() as conn:

                available = (
                    conn.execute(
                        text("""
                            SELECT
                                available_balance

                            FROM users

                            WHERE
                                chat_id =
                                :chat_id
                        """),

                        {
                            "chat_id":
                                chat_id
                        },

                    ).scalar()
                    or 0
                )

                if amount > available:

                    clear_withdraw_state(
                        chat_id
                    )

                    await update.message.reply_text(
                        "❌ Số dư "
                        "không còn đủ."
                    )

                    return

                conn.execute(
                    text("""
                        UPDATE users

                        SET
                            available_balance =
                                available_balance
                                - :amount

                        WHERE
                            chat_id =
                            :chat_id
                    """),

                    {
                        "amount":
                            amount,

                        "chat_id":
                            chat_id,
                    },
                )

                conn.execute(
                    text("""
                        INSERT INTO withdrawals (
                            withdrawal_id,
                            chat_id,
                            amount,
                            bank_info,
                            status,
                            created_ts
                        )

                        VALUES (
                            :wid,
                            :chat_id,
                            :amount,
                            :bank_info,
                            'pending',
                            :created_ts
                        )
                    """),

                    {
                        "wid":
                            withdrawal_id,

                        "chat_id":
                            chat_id,

                        "amount":
                            amount,

                        "bank_info":
                            bank_info,

                        "created_ts":
                            int(
                                time.time()
                            ),
                    },
                )

                conn.execute(
                    text("""
                        DELETE FROM withdraw_state

                        WHERE
                            chat_id =
                            :chat_id
                    """),

                    {
                        "chat_id":
                            chat_id
                    },
                )

            await update.message.reply_text(
                "✅ Đã tạo yêu cầu "
                "rút tiền.\n\n"

                f"🆔 Mã: "
                f"{withdrawal_id}\n"

                f"💵 Số tiền: "
                f"{amount:,}đ\n\n"

                "⏳ Đang chờ admin duyệt.",

                reply_markup=main_keyboard,
            )

            if ADMIN_CHAT_ID:

                buttons = (
                    InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton(
                                "✅ Duyệt",

                                callback_data=(
                                    "wdapprove:"
                                    f"{withdrawal_id}"
                                ),
                            ),

                            InlineKeyboardButton(
                                "❌ Từ chối",

                                callback_data=(
                                    "wdreject:"
                                    f"{withdrawal_id}"
                                ),
                            ),
                        ]]
                    )
                )

                await context.bot.send_message(
                    chat_id=int(
                        ADMIN_CHAT_ID
                    ),

                    text=(
                        "💳 YÊU CẦU RÚT TIỀN\n\n"

                        f"🆔 "
                        f"{withdrawal_id}\n"

                        f"👤 Chat ID: "
                        f"{chat_id}\n"

                        f"💵 "
                        f"{amount:,}đ\n"

                        f"🏦 "
                        f"{bank_info}"
                    ),

                    reply_markup=buttons,
                )

            return


    # =====================================================
    # MENU
    # =====================================================

    if message_text == (
        "👤 Thông tin tài khoản"
    ):

        await account_info(
            update,
            context,
        )

        return


    if message_text == (
        "💰 Thu nhập"
    ):

        await income(
            update,
            context,
        )

        return


    if message_text == (
        "💳 Rút tiền"
    ):

        await withdraw(
            update,
            context,
        )

        return


    if message_text == (
        "🛒 Gửi link Shopee"
    ):

        await update.message.reply_text(
            "🛒 Hãy dán link "
            "Shopee vào đây.",

            reply_markup=main_keyboard,
        )

        return


    if message_text == (
        "🎵 Gửi link TikTok"
    ):

        await update.message.reply_text(
            "🎵 Hãy dán link "
            "TikTok vào đây.",

            reply_markup=main_keyboard,
        )

        return


    # =====================================================
    # KHÔNG CÓ LINK
    # =====================================================

    if not url:

        await update.message.reply_text(
            "❌ Mình chưa thấy link.\n\n"

            "Hãy gửi link Shopee "
            "hoặc TikTok.",

            reply_markup=main_keyboard,
        )

        return


    # =====================================================
    # NHẬN DIỆN PLATFORM
    # =====================================================

    platform = detect_platform(
        url
    )

    if not platform:

        await update.message.reply_text(
            "❌ Link chưa được hỗ trợ.\n\n"

            "Hiện bot chỉ hỗ trợ "
            "Shopee và TikTok.",

            reply_markup=main_keyboard,
        )

        return


    # =====================================================
    # CHỐNG LINK TRÙNG
    # =====================================================

    duplicate = find_recent_duplicate(
        chat_id,
        url,
    )

    if duplicate:

        request_id = (
            duplicate[0]
        )

        status = (
            duplicate[1]
        )

        affiliate_url = (
            duplicate[2]
        )

        if (
            status == "done"

            and affiliate_url
        ):

            await update.message.reply_text(
                "✅ Link này "
                "vừa được xử lý.\n\n"

                f"🛍 "
                f"{affiliate_url}",

                reply_markup=main_keyboard,
            )

            return

        await update.message.reply_text(
            "⏳ Link này đã được gửi "
            "trước đó.\n\n"

            f"🆔 Mã yêu cầu: "
            f"{request_id}\n\n"

            "Vui lòng chờ bot xử lý.",

            reply_markup=main_keyboard,
        )

        return


    # =====================================================
    # TẠO REQUEST
    # =====================================================

    request_id = (
        uuid.uuid4()
        .hex[:8]
    )

    now = int(
        time.time()
    )

    with engine.begin() as conn:

        conn.execute(
            text("""
                INSERT INTO requests (
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
                "request_id":
                    request_id,

                "chat_id":
                    chat_id,

                "platform":
                    platform,

                "url":
                    url,

                "created_ts":
                    now,

                "updated_ts":
                    now,
            },
        )


    # =====================================================
    # TRẢ LỜI KHÁCH
    # =====================================================

    await update.message.reply_text(
        f"✅ Đã nhận link "
        f"{platform}!\n\n"

        f"🆔 Mã yêu cầu: "
        f"{request_id}\n"

        "⏳ Trạng thái: "
        "Chờ xử lý.\n\n"

        "Bot sẽ gửi link "
        "sau khi hoàn tất.",

        reply_markup=main_keyboard,
    )


    # =====================================================
    # GỬI ADMIN
    # =====================================================

    if ADMIN_CHAT_ID:

        username = (
            f"@{user.username}"

            if user.username

            else "Không có username"
        )

        buttons = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(
                    "📤 Trả link cho khách",

                    callback_data=(
                        f"reply:"
                        f"{request_id}"
                    ),
                )
            ]]
        )

        await context.bot.send_message(
            chat_id=int(
                ADMIN_CHAT_ID
            ),

            text=(
                "🔔 YÊU CẦU MỚI\n\n"

                f"🏪 "
                f"{platform}\n"

                f"🆔 Mã: "
                f"{request_id}\n"

                f"👤 User: "
                f"{username}\n"

                f"💬 Chat ID: "
                f"{chat_id}\n\n"

                f"📅 Thời gian: "
                f"{datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%d/%m/%Y %H:%M')}\n\n"

                f"🔗 Link khách gửi:\n"
                f"{url}"
            ),

            reply_markup=buttons,
        )


# =========================================================
# MAIN
# =========================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "Thiếu TELEGRAM_BOT_TOKEN"
        )

    if not BASE_URL:

        raise RuntimeError(
            "Thiếu WEBHOOK BASE URL"
        )

    init_db()

    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )


    # =====================================================
    # SCHEDULER
    # =====================================================

    scheduler = AsyncIOScheduler(
        timezone="Asia/Ho_Chi_Minh"
    )

    scheduler.add_job(
        send_daily_report,

        trigger="cron",

        hour=23,

        minute=30,

        args=[app],
    )

    scheduler.start()


    # =====================================================
    # COMMAND
    # =====================================================

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "history",
            history,
        )
    )

    app.add_handler(
        CommandHandler(
            "report",
            report_now,
        )
    )

    app.add_handler(
        CommandHandler(
            "addpending",
            add_pending,
        )
    )

    app.add_handler(
        CommandHandler(
            "approvebalance",
            approve_balance,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_callback
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,

            handle_message,
        )
    )


    # =====================================================
    # WEBHOOK
    # =====================================================

    webhook_url = (
        f"{BASE_URL.rstrip('/')}"
        "/telegram"
    )

    print(
        f"Webhook URL: "
        f"{webhook_url}"
    )

    app.run_webhook(
        listen="0.0.0.0",

        port=int(
            os.getenv(
                "PORT",
                "10000",
            )
        ),

        url_path="telegram",

        webhook_url=webhook_url,

        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
