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
# DÙNG V3 ĐỂ KHÔNG XUNG ĐỘT BẢNG CŨ
# =========================================================

def init_db():

    with engine.begin() as conn:

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users_v3 (
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
            CREATE TABLE IF NOT EXISTS withdrawals_v3 (
                withdrawal_id TEXT PRIMARY KEY,

                chat_id BIGINT NOT NULL,

                amount BIGINT NOT NULL,

                bank_info TEXT NOT NULL,

                status TEXT NOT NULL,

                created_ts BIGINT NOT NULL
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS withdraw_state_v3 (
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
        ["👤 Thông tin tài khoản"],
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
# USER
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


def get_balances(chat_id):

    with engine.begin() as conn:

        row = conn.execute(
            text("""
                SELECT
                    available_balance,
                    pending_balance

                FROM users_v3

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
# LINK
# =========================================================

def extract_url(message):

    match = re.search(
        r"https?://[^\s]+",
        message,
    )

    if not match:
        return None

    url = match.group(0).strip()

    return url.rstrip(
        ".,);]}>\"'"
    )


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
        # Ví dụ:
        # shopee.vn
        # s.shopee.vn
        # vn.shp.ee
        # shp.ee

        if (
            host == "shopee.vn"
            or host.endswith(".shopee.vn")
            or host == "shp.ee"
            or host.endswith(".shp.ee")
        ):
            return "Shopee"

        # TIKTOK
        # Ví dụ:
        # tiktok.com
        # www.tiktok.com
        # vt.tiktok.com
        # vm.tiktok.com

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
# /ID
# =========================================================

async def get_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👤 Thông tin tài khoản của bạn\n\n"
        f"🆔 ID hội viên: "
        f"{update.effective_chat.id}"
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

        total = conn.execute(
            text("""
                SELECT COUNT(*)

                FROM requests_v3

                WHERE chat_id = :chat_id
            """),

            {
                "chat_id": chat_id
            },

        ).scalar() or 0

        completed = conn.execute(
            text("""
                SELECT COUNT(*)

                FROM requests_v3

                WHERE
                    chat_id = :chat_id

                AND
                    status = 'done'
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

        f"👤 Họ tên: "
        f"{user.full_name}\n"

        f"📱 Username: "
        f"{username}\n\n"

        f"💰 Số dư có thể rút: "
        f"{available:,}đ\n"

        f"⏳ Số dư chờ duyệt: "
        f"{pending:,}đ\n\n"

        f"📦 Tổng yêu cầu: "
        f"{total}\n"

        f"✅ Đã hoàn tất: "
        f"{completed}\n\n"

        "📜 Gõ /history để xem lịch sử.",

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

        f"💰 Số dư có thể rút: "
        f"{available:,}đ\n"

        f"⏳ Số dư chờ duyệt: "
        f"{pending:,}đ",

        reply_markup=main_keyboard,
    )


# =========================================================
# HISTORY
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

                FROM requests_v3

                WHERE
                    chat_id = :chat_id

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
                TZ
            )
            .strftime(
                "%d/%m/%Y %H:%M"
            )
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

def find_recent_duplicate(
    chat_id,
    url,
):

    five_minutes_ago = (
        int(time.time()) - 300
    )

    with engine.begin() as conn:

        return conn.execute(
            text("""
                SELECT
                    request_id,
                    status,
                    affiliate_url

                FROM requests_v3

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
                "limit_ts": five_minutes_ago,
            },

        ).fetchone()


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

    available, _ = get_balances(
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
                INSERT INTO withdraw_state_v3 (
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


def get_withdraw_state(chat_id):

    with engine.begin() as conn:

        return conn.execute(
            text("""
                SELECT
                    stage,
                    amount

                FROM withdraw_state_v3

                WHERE
                    chat_id = :chat_id
            """),

            {
                "chat_id": chat_id
            },

        ).fetchone()


def clear_withdraw_state(chat_id):

    with engine.begin() as conn:

        conn.execute(
            text("""
                DELETE FROM withdraw_state_v3

                WHERE
                    chat_id = :chat_id
            """),

            {
                "chat_id": chat_id
            },
        )


# =========================================================
# ADMIN: CỘNG TIỀN CHỜ DUYỆT
# =========================================================

async def add_pending(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        not ADMIN_CHAT_ID
        or str(update.effective_chat.id)
        != str(ADMIN_CHAT_ID)
    ):

        await update.message.reply_text(
            "⛔ Bạn không có quyền."
        )

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
                    :amount,
                    :created_ts
                )

                ON CONFLICT(chat_id)

                DO UPDATE SET
                    pending_balance =
                        users_v3.pending_balance
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
# ADMIN: DUYỆT HOA HỒNG
# CHỜ DUYỆT -> CÓ THỂ RÚT
# =========================================================

async def approve_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        not ADMIN_CHAT_ID
        or str(update.effective_chat.id)
        != str(ADMIN_CHAT_ID)
    ):

        await update.message.reply_text(
            "⛔ Bạn không có quyền."
        )

        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "Dùng:\n\n"
            "/approvebalance CHAT_ID SOTIEN"
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

                FROM users_v3

                WHERE chat_id = :chat_id
            """),

            {
                "chat_id": chat_id
            },

        ).fetchone()

        if not row:

            await update.message.reply_text(
                "❌ Không tìm thấy khách."
            )

            return

        pending = int(row[0])

        if amount > pending:

            await update.message.reply_text(
                f"❌ Khách chỉ có "
                f"{pending:,}đ "
                "đang chờ duyệt."
            )

            return

        conn.execute(
            text("""
                UPDATE users_v3

                SET
                    pending_balance =
                        pending_balance
                        - :amount,

                    available_balance =
                        available_balance
                        + :amount

                WHERE
                    chat_id = :chat_id
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

                f"💰 +{amount:,}đ\n"

                "Số tiền đã chuyển sang "
                "số dư có thể rút."
            ),
        )

    except Exception:
        pass


# =========================================================
# ADMIN CALLBACK BUTTONS
# =========================================================

async def admin_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if (
        not ADMIN_CHAT_ID
        or str(query.from_user.id)
        != str(ADMIN_CHAT_ID)
    ):

        await query.answer(
            "Bạn không có quyền.",
            show_alert=True,
        )

        return

    await query.answer()

    data = query.data


    # =====================================================
    # ADMIN BẤM TRẢ LINK
    # =====================================================

    if data.startswith("reply:"):

        request_id = (
            data.split(":", 1)[1]
        )

        with engine.begin() as conn:

            row = conn.execute(
                text("""
                    SELECT
                        chat_id,
                        status

                    FROM requests_v3

                    WHERE
                        request_id = :request_id
                """),

                {
                    "request_id": request_id
                },

            ).fetchone()

            if not row:

                await query.message.reply_text(
                    "❌ Không tìm thấy yêu cầu."
                )

                return

            customer_chat_id = row[0]
            status = row[1]

            if status == "done":

                await query.message.reply_text(
                    "✅ Yêu cầu này đã hoàn tất."
                )

                return

            conn.execute(
                text("""
                    UPDATE requests_v3

                    SET
                        status = 'processing',
                        updated_ts = :now

                    WHERE
                        request_id = :request_id
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
                        request_id =
                            excluded.request_id
                """),

                {
                    "admin_chat_id":
                        int(ADMIN_CHAT_ID),

                    "request_id":
                        request_id,
                },
            )

        await query.message.reply_text(
            f"📤 Đang xử lý mã "
            f"{request_id}\n\n"

            "👉 Bây giờ bạn chỉ cần "
            "dán LINK AFFILIATE vào bot.\n\n"

            "Bot sẽ tự gửi link "
            "đúng cho khách."
        )

        try:

            await context.bot.send_message(
                chat_id=customer_chat_id,

                text=(
                    "🔄 Yêu cầu của bạn "
                    "đang được xử lý.\n\n"

                    "Bot sẽ gửi link mua hàng "
                    "ngay khi hoàn tất."
                ),
            )

        except Exception:
            pass

        return


    # =====================================================
    # ADMIN DUYỆT RÚT TIỀN
    # =====================================================

    if data.startswith("wdapprove:"):

        withdrawal_id = (
            data.split(":", 1)[1]
        )

        with engine.begin() as conn:

            row = conn.execute(
                text("""
                    SELECT
                        chat_id,
                        amount,
                        status

                    FROM withdrawals_v3

                    WHERE
                        withdrawal_id = :wid
                """),

                {
                    "wid": withdrawal_id
                },

            ).fetchone()

            if not row:
                return

            chat_id = row[0]
            amount = int(row[1])
            status = row[2]

            if status != "pending":

                await query.message.reply_text(
                    "Yêu cầu này đã được xử lý."
                )

                return

            conn.execute(
                text("""
                    UPDATE withdrawals_v3

                    SET status = 'approved'

                    WHERE
                        withdrawal_id = :wid
                """),

                {
                    "wid": withdrawal_id
                },
            )

        try:

            await context.bot.send_message(
                chat_id=chat_id,

                text=(
                    "✅ YÊU CẦU RÚT TIỀN "
                    "ĐÃ ĐƯỢC DUYỆT\n\n"

                    f"💵 Số tiền: "
                    f"{amount:,}đ"
                ),
            )

        except Exception:
            pass

        await query.message.reply_text(
            f"✅ Đã duyệt rút "
            f"{amount:,}đ."
        )

        return


    # =====================================================
    # ADMIN TỪ CHỐI RÚT
    # =====================================================

    if data.startswith("wdreject:"):

        withdrawal_id = (
            data.split(":", 1)[1]
        )

        with engine.begin() as conn:

            row = conn.execute(
                text("""
                    SELECT
                        chat_id,
                        amount,
                        status

                    FROM withdrawals_v3

                    WHERE
                        withdrawal_id = :wid
                """),

                {
                    "wid": withdrawal_id
                },

            ).fetchone()

            if not row:
                return

            chat_id = row[0]
            amount = int(row[1])
            status = row[2]

            if status != "pending":

                await query.message.reply_text(
                    "Yêu cầu này đã được xử lý."
                )

                return

            conn.execute(
                text("""
                    UPDATE withdrawals_v3

                    SET status = 'rejected'

                    WHERE
                        withdrawal_id = :wid
                """),

                {
                    "wid": withdrawal_id
                },
            )

            # Hoàn lại tiền
            conn.execute(
                text("""
                    UPDATE users_v3

                    SET
                        available_balance =
                            available_balance
                            + :amount

                    WHERE
                        chat_id = :chat_id
                """),

                {
                    "amount": amount,
                    "chat_id": chat_id,
                },
            )

        try:

            await context.bot.send_message(
                chat_id=chat_id,

                text=(
                    "❌ Yêu cầu rút tiền "
                    "không được duyệt.\n\n"

                    f"💰 {amount:,}đ "
                    "đã được hoàn lại "
                    "vào số dư có thể rút."
                ),
            )

        except Exception:
            pass

        await query.message.reply_text(
            "❌ Đã từ chối và hoàn lại tiền."
        )

        return


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
        str(update.effective_chat.id)
        != str(ADMIN_CHAT_ID)
    ):
        return False

    with engine.begin() as conn:

        state = conn.execute(
            text("""
                SELECT request_id

                FROM admin_state_v3

                WHERE
                    admin_chat_id = :admin_chat_id
            """),

            {
                "admin_chat_id":
                    int(ADMIN_CHAT_ID)
            },

        ).fetchone()

        if not state:
            return False

        request_id = state[0]

        request = conn.execute(
            text("""
                SELECT
                    chat_id,
                    status

                FROM requests_v3

                WHERE
                    request_id = :request_id
            """),

            {
                "request_id": request_id
            },

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

                WHERE
                    request_id = :request_id
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

                WHERE
                    admin_chat_id = :admin_chat_id
            """),

            {
                "admin_chat_id":
                    int(ADMIN_CHAT_ID)
            },
        )

    try:

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

    except Exception as e:

        await update.message.reply_text(
            f"❌ Gửi khách thất bại:\n"
            f"{e}"
        )

        return True

    await update.message.reply_text(
        "✅ Đã gửi link cho khách."
    )

    return True


# =========================================================
# BÁO CÁO TRONG NGÀY
# =========================================================

async def send_daily_report(
    context: ContextTypes.DEFAULT_TYPE
):

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

                WHERE
                    r.created_ts >= :start_ts

                AND
                    r.created_ts < :end_ts

                ORDER BY
                    r.created_ts ASC
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
                f"📊 BÁO CÁO NGÀY "
                f"{now.strftime('%d/%m/%Y')}\n\n"

                "Hôm nay chưa có "
                "yêu cầu nào."
            ),
        )

        return

    status_names = {
        "pending": "⏳ Chờ xử lý",
        "processing": "🔄 Đang xử lý",
        "done": "✅ Đã trả link",
    }

    total = len(rows)

    done_count = sum(
        1
        for row in rows
        if row[5] == "done"
    )

    processing_count = sum(
        1
        for row in rows
        if row[5] == "processing"
    )

    pending_count = sum(
        1
        for row in rows
        if row[5] == "pending"
    )

    parts = [
        f"📊 BÁO CÁO YÊU CẦU "
        f"NGÀY {now.strftime('%d/%m/%Y')}\n"
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
        username = row[7]
        full_name = row[8]

        created_time = (
            datetime
            .fromtimestamp(
                created_ts,
                TZ
            )
            .strftime("%H:%M")
        )

        user_text = (
            f"@{username}"
            if username
            else "Không có username"
        )

        name_text = (
            full_name
            if full_name
            else "Không có tên"
        )

        returned_link = (
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

            f"👤 Tên: "
            f"{name_text}\n"

            f"📱 User: "
            f"{user_text}\n"

            f"🏪 Nền tảng: "
            f"{platform}\n"

            f"📅 Gửi lúc: "
            f"{created_time}\n"

            f"🔗 Link khách gửi:\n"
            f"{original_url}\n"

            f"🔗 Link đã trả:\n"
            f"{returned_link}\n"

            f"{status_names.get(status, status)}\n"
        )

    parts.append(
        "\n----------------\n"

        f"📦 Tổng yêu cầu: "
        f"{total}\n"

        f"✅ Đã trả link: "
        f"{done_count}\n"

        f"🔄 Đang xử lý: "
        f"{processing_count}\n"

        f"⏳ Chờ xử lý: "
        f"{pending_count}"
    )

    report = "".join(parts)

    # Telegram giới hạn khoảng 4096 ký tự
    # Chia thành nhiều tin nhỏ
    max_length = 3800

    while report:

        if len(report) <= max_length:
            chunk = report
            report = ""

        else:
            cut = report.rfind(
                "\n",
                0,
                max_length,
            )

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
# ADMIN XEM BÁO CÁO NGAY
# =========================================================

async def report_now(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        not ADMIN_CHAT_ID
        or str(update.effective_chat.id)
        != str(ADMIN_CHAT_ID)
    ):

        await update.message.reply_text(
            "⛔ Bạn không có quyền."
        )

        return

    await send_daily_report(
        context
    )


# =========================================================
# XỬ LÝ TIN NHẮN
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
    # NẾU ADMIN ĐANG CHỜ DÁN AFFILIATE LINK
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
    # NẾU USER ĐANG TRONG QUY TRÌNH RÚT TIỀN
    # =====================================================

    withdraw_state = (
        get_withdraw_state(
            chat_id
        )
    )

    if withdraw_state:

        stage = withdraw_state[0]
        stored_amount = int(
            withdraw_state[1]
        )


        # =================================================
        # BƯỚC NHẬP SỐ TIỀN
        # =================================================

        if stage == "amount":

            amount_text = (
                message_text
                .replace(".", "")
                .replace(",", "")
                .replace("đ", "")
                .replace("₫", "")
                .strip()
            )

            try:

                amount = int(
                    amount_text
                )

            except ValueError:

                await update.message.reply_text(
                    "❌ Vui lòng nhập "
                    "số tiền bằng số.\n\n"

                    "Ví dụ:\n"
                    "50000"
                )

                return

            available, _ = get_balances(
                chat_id
            )

            if amount <= 0:

                await update.message.reply_text(
                    "❌ Số tiền không hợp lệ."
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
                        UPDATE withdraw_state_v3

                        SET
                            stage = 'bank',
                            amount = :amount

                        WHERE
                            chat_id = :chat_id
                    """),

                    {
                        "amount": amount,
                        "chat_id": chat_id,
                    },
                )

            await update.message.reply_text(
                "🏦 Nhập thông tin nhận tiền.\n\n"

                "Ví dụ:\n"

                "Vietcombank - "
                "0123456789 - "
                "NGUYEN VAN A"
            )

            return


        # =================================================
        # BƯỚC NHẬP NGÂN HÀNG
        # =================================================

        if stage == "bank":

            bank_info = message_text

            amount = stored_amount

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

                            FROM users_v3

                            WHERE
                                chat_id = :chat_id
                        """),

                        {
                            "chat_id": chat_id
                        },

                    ).scalar()
                    or 0
                )

                available = int(
                    available
                )

                if amount > available:

                    conn.execute(
                        text("""
                            DELETE FROM withdraw_state_v3

                            WHERE
                                chat_id = :chat_id
                        """),

                        {
                            "chat_id": chat_id
                        },
                    )

                    await update.message.reply_text(
                        "❌ Số dư hiện tại "
                        "không còn đủ."
                    )

                    return

                # Trừ tiền ngay khi tạo yêu cầu
                # Nếu admin từ chối thì hoàn lại
                conn.execute(
                    text("""
                        UPDATE users_v3

                        SET
                            available_balance =
                                available_balance
                                - :amount

                        WHERE
                            chat_id = :chat_id
                    """),

                    {
                        "amount": amount,
                        "chat_id": chat_id,
                    },
                )

                conn.execute(
                    text("""
                        INSERT INTO withdrawals_v3 (
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
                        "wid": withdrawal_id,
                        "chat_id": chat_id,
                        "amount": amount,
                        "bank_info": bank_info,
                        "created_ts":
                            int(time.time()),
                    },
                )

                conn.execute(
                    text("""
                        DELETE FROM withdraw_state_v3

                        WHERE
                            chat_id = :chat_id
                    """),

                    {
                        "chat_id": chat_id
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

                buttons = InlineKeyboardMarkup(
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

                try:

                    await context.bot.send_message(
                        chat_id=int(
                            ADMIN_CHAT_ID
                        ),

                        text=(
                            "💳 YÊU CẦU RÚT TIỀN\n\n"

                            f"🆔 Mã: "
                            f"{withdrawal_id}\n"

                            f"👤 Chat ID: "
                            f"{chat_id}\n"

                            f"💵 Số tiền: "
                            f"{amount:,}đ\n"

                            f"🏦 Nhận tiền:\n"
                            f"{bank_info}"
                        ),

                        reply_markup=buttons,
                    )

                except Exception as e:

                    print(
                        f"Lỗi gửi yêu cầu rút "
                        f"cho admin: {e}"
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
            "🛒 Hãy dán link sản phẩm "
            "Shopee vào đây.",

            reply_markup=main_keyboard,
        )

        return


    if message_text == (
        "🎵 Gửi link TikTok"
    ):

        await update.message.reply_text(
            "🎵 Hãy dán link sản phẩm "
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
            "❌ Link này chưa được hỗ trợ.\n\n"

            "Hiện bot hỗ trợ "
            "Shopee và TikTok.",

            reply_markup=main_keyboard,
        )

        return


    # =====================================================
    # CHỐNG LINK TRÙNG TRONG 5 PHÚT
    # =====================================================

    duplicate = find_recent_duplicate(
        chat_id,
        url,
    )

    if duplicate:

        request_id = duplicate[0]
        status = duplicate[1]
        affiliate_url = duplicate[2]

        if (
            status == "done"
            and affiliate_url
        ):

            await update.message.reply_text(
                "✅ Link này vừa được xử lý.\n\n"

                f"🛍 Link mua hàng:\n"
                f"{affiliate_url}",

                reply_markup=main_keyboard,
            )

            return

        await update.message.reply_text(
            "⏳ Link này đã được gửi "
            "trước đó.\n\n"

            f"🆔 Mã yêu cầu: "
            f"{request_id}\n\n"

            "Vui lòng chờ xử lý.",

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

    now_ts = int(
        time.time()
    )

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

        "Bot sẽ gửi lại link mua hàng "
        "sau khi hoàn tất.",

        reply_markup=main_keyboard,
    )


    # =====================================================
    # GỬI YÊU CẦU CHO ADMIN
    # =====================================================

    if ADMIN_CHAT_ID:

        username = (
            f"@{user.username}"

            if user.username

            else "Không có username"
        )

        now_text = (
            datetime
            .now(TZ)
            .strftime(
                "%d/%m/%Y %H:%M"
            )
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

        try:

            await context.bot.send_message(
                chat_id=int(
                    ADMIN_CHAT_ID
                ),

                text=(
                    "🔔 YÊU CẦU MỚI\n\n"

                    f"🏪 Nền tảng: "
                    f"{platform}\n"

                    f"🆔 Mã: "
                    f"{request_id}\n"

                    f"👤 User: "
                    f"{username}\n"

                    f"💬 ID khách: "
                    f"{chat_id}\n"

                    f"📅 Thời gian: "
                    f"{now_text}\n\n"

                    f"🔗 Link khách gửi:\n"
                    f"{url}"
                ),

                reply_markup=buttons,
            )

        except Exception as e:

            print(
                f"Lỗi gửi admin: {e}"
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
            "Thiếu RENDER_EXTERNAL_URL "
            "hoặc WEBHOOK_BASE_URL"
        )

    init_db()

    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )


    # =====================================================
    # JOB QUEUE
    # 23:30 HÀNG NGÀY
    # =====================================================

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


    # =====================================================
    # COMMAND HANDLERS
    # =====================================================

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "id",
            get_id,
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
