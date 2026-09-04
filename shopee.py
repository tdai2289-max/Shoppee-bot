import os
import re
import time
import uuid
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
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

# Render/Supabase đôi lúc trả URL dạng postgres://
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
# DATABASE
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


def init_db():
    with engine.begin() as conn:

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance BIGINT NOT NULL DEFAULT 0,
                created_ts BIGINT NOT NULL
            )
        """))

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

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_state (
                admin_chat_id BIGINT PRIMARY KEY,
                request_id TEXT
            )
        """))

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
        ["👤 Thông tin tài khoản"],
        ["🛒 Gửi link Shopee", "🎵 Gửi link TikTok"],
        ["💳 Rút tiền", "💰 Thu nhập"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


# =========================================================
# USER DATABASE
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
                    balance,
                    created_ts
                )
                VALUES (
                    :chat_id,
                    :username,
                    :full_name,
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
                "username": username,
                "full_name": full_name,
                "created_ts": now,
            },
        )


def get_balance(chat_id):
    with engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT balance
                FROM users
                WHERE chat_id = :chat_id
            """),
            {"chat_id": chat_id},
        ).fetchone()

    if not row:
        return 0

    return int(row[0])


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
        host = parsed.netloc.lower().split(":")[0]

        if host.startswith("www."):
            host = host[4:]

        # Shopee
        if (
            host == "shopee.vn"
            or host.endswith(".shopee.vn")
            or host == "shp.ee"
            or host.endswith(".shp.ee")
        ):
            return "Shopee"

        # TikTok
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

    name = user.first_name or "bạn"

    await update.message.reply_text(
        f"👋 Xin chào {name}!\n\n"
        "🎉 Chào mừng bạn đến với Shopee Tích Xu.\n\n"
        "🛍 Hãy gửi link sản phẩm Shopee hoặc TikTok.\n"
        "Bot sẽ tiếp nhận và xử lý link mua hàng cho bạn.\n\n"
        "👇 Chọn chức năng bên dưới:",
        reply_markup=main_keyboard,
    )


# =========================================================
# TÀI KHOẢN + LỊCH SỬ
# =========================================================

async def account_info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    save_user(user)

    chat_id = user.id
    balance = get_balance(chat_id)

    with engine.begin() as conn:
        total = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM requests
                WHERE chat_id = :chat_id
            """),
            {"chat_id": chat_id},
        ).scalar() or 0

        completed = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM requests
                WHERE chat_id = :chat_id
                AND status = 'done'
            """),
            {"chat_id": chat_id},
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
        f"💰 Số dư: {balance:,}đ\n"
        f"📦 Tổng yêu cầu: {total}\n"
        f"✅ Đã hoàn tất: {completed}\n\n"
        "📜 Xem lịch sử bằng /history",
        reply_markup=main_keyboard,
    )


async def history(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id

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
                ORDER BY created_ts DESC
                LIMIT 5
            """),
            {"chat_id": chat_id},
        ).fetchall()

    if not rows:
        await update.message.reply_text(
            "📜 Bạn chưa có yêu cầu nào."
        )
        return

    status_names = {
        "pending": "⏳ Chờ xử lý",
        "processing": "🔄 Đang xử lý",
        "done": "✅ Hoàn tất",
    }

    lines = ["📜 5 YÊU CẦU GẦN NHẤT\n"]

    for row in rows:
        rid, platform, status, ts = row

        date = time.strftime(
            "%d/%m %H:%M",
            time.localtime(ts),
        )

        lines.append(
            f"\n🆔 {rid}"
            f"\n🏪 {platform}"
            f"\n{status_names.get(status, status)}"
            f"\n🕐 {date}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=main_keyboard,
    )


# =========================================================
# THU NHẬP
# =========================================================

async def income(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    balance = get_balance(
        update.effective_chat.id
    )

    await update.message.reply_text(
        "💰 THU NHẬP\n\n"
        f"💵 Số dư khả dụng: {balance:,}đ\n\n"
        "ℹ️ Hiện hoa hồng được admin cập nhật "
        "sau khi đối soát.",
        reply_markup=main_keyboard,
    )


# =========================================================
# RÚT TIỀN
# =========================================================

async def withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id

    balance = get_balance(chat_id)

    if balance <= 0:
        await update.message.reply_text(
            "💳 RÚT TIỀN\n\n"
            "❌ Hiện tại số dư của bạn là 0đ.",
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
            {"chat_id": chat_id},
        )

    await update.message.reply_text(
        "💳 RÚT TIỀN\n\n"
        f"💰 Số dư khả dụng: {balance:,}đ\n\n"
        "Nhập số tiền bạn muốn rút.\n\n"
        "Ví dụ:\n"
        "50000"
    )


def get_withdraw_state(chat_id):
    with engine.begin() as conn:
        return conn.execute(
            text("""
                SELECT stage, amount
                FROM withdraw_state
                WHERE chat_id = :chat_id
            """),
            {"chat_id": chat_id},
        ).fetchone()


def clear_withdraw_state(chat_id):
    with engine.begin() as conn:
        conn.execute(
            text("""
                DELETE FROM withdraw_state
                WHERE chat_id = :chat_id
            """),
            {"chat_id": chat_id},
        )


# =========================================================
# ADMIN: CỘNG SỐ DƯ
# =========================================================

async def add_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if (
        not ADMIN_CHAT_ID
        or str(update.effective_chat.id)
        != str(ADMIN_CHAT_ID)
    ):
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Dùng:\n"
            "/addbalance CHAT_ID SOTIEN"
        )
        return

    try:
        chat_id = int(context.args[0])
        amount = int(context.args[1])

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
                    balance,
                    created_ts
                )
                VALUES (
                    :chat_id,
                    '',
                    '',
                    :amount,
                    :created_ts
                )
                ON CONFLICT(chat_id)
                DO UPDATE SET
                    balance = users.balance + :amount
            """),
            {
                "chat_id": chat_id,
                "amount": amount,
                "created_ts": now,
            },
        )

    await update.message.reply_text(
        f"✅ Đã cộng {amount:,}đ "
        f"cho {chat_id}."
    )

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "💰 SỐ DƯ ĐÃ ĐƯỢC CẬP NHẬT\n\n"
                f"➕ +{amount:,}đ"
            ),
        )
    except Exception:
        pass


# =========================================================
# REQUEST DATABASE
# =========================================================

def find_recent_duplicate(
    chat_id,
    url,
):
    limit_ts = int(time.time()) - 300

    with engine.begin() as conn:
        return conn.execute(
            text("""
                SELECT
                    request_id,
                    status,
                    affiliate_url
                FROM requests
                WHERE chat_id = :chat_id
                AND original_url = :url
                AND created_ts >= :limit_ts
                ORDER BY created_ts DESC
                LIMIT 1
            """),
            {
                "chat_id": chat_id,
                "url": url,
                "limit_ts": limit_ts,
            },
        ).fetchone()


# =========================================================
# ADMIN BUTTON: TRẢ LINK
# =========================================================

async def admin_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

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

    data = query.data

    # -----------------------------------------
    # TRẢ LINK AFFILIATE
    # -----------------------------------------

    if data.startswith("reply:"):
        request_id = data.split(":", 1)[1]

        with engine.begin() as conn:

            row = conn.execute(
                text("""
                    SELECT chat_id, status
                    FROM requests
                    WHERE request_id = :request_id
                """),
                {"request_id": request_id},
            ).fetchone()

            if not row:
                await query.message.reply_text(
                    "❌ Không tìm thấy yêu cầu."
                )
                return

            chat_id, status = row

            if status == "done":
                await query.message.reply_text(
                    "✅ Yêu cầu này đã hoàn tất."
                )
                return

            conn.execute(
                text("""
                    UPDATE requests
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
                    INSERT INTO admin_state (
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
                    "admin_chat_id": int(
                        ADMIN_CHAT_ID
                    ),
                    "request_id": request_id,
                },
            )

        await query.message.reply_text(
            f"📤 Đang trả yêu cầu {request_id}.\n\n"
            "👉 Bây giờ chỉ cần dán "
            "affiliate link vào bot."
        )

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🔄 Yêu cầu của bạn đang được xử lý.\n\n"
                    "Bot sẽ gửi link mua hàng "
                    "ngay khi hoàn tất."
                ),
            )
        except Exception:
            pass

        return

    # -----------------------------------------
    # DUYỆT RÚT TIỀN
    # -----------------------------------------

    if data.startswith("wdapprove:"):
        wid = data.split(":", 1)[1]

        with engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT chat_id, amount, status
                    FROM withdrawals
                    WHERE withdrawal_id = :wid
                """),
                {"wid": wid},
            ).fetchone()

            if not row:
                return

            chat_id, amount, status = row

            if status != "pending":
                await query.message.reply_text(
                    "Yêu cầu này đã được xử lý."
                )
                return

            conn.execute(
                text("""
                    UPDATE withdrawals
                    SET status = 'approved'
                    WHERE withdrawal_id = :wid
                """),
                {"wid": wid},
            )

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ YÊU CẦU RÚT TIỀN ĐÃ ĐƯỢC DUYỆT\n\n"
                f"💵 Số tiền: {amount:,}đ"
            ),
        )

        await query.message.reply_text(
            f"✅ Đã duyệt rút {amount:,}đ."
        )

        return

    # -----------------------------------------
    # TỪ CHỐI RÚT TIỀN
    # -----------------------------------------

    if data.startswith("wdreject:"):
        wid = data.split(":", 1)[1]

        with engine.begin() as conn:

            row = conn.execute(
                text("""
                    SELECT chat_id, amount, status
                    FROM withdrawals
                    WHERE withdrawal_id = :wid
                """),
                {"wid": wid},
            ).fetchone()

            if not row:
                return

            chat_id, amount, status = row

            if status != "pending":
                await query.message.reply_text(
                    "Yêu cầu này đã được xử lý."
                )
                return

            conn.execute(
                text("""
                    UPDATE withdrawals
                    SET status = 'rejected'
                    WHERE withdrawal_id = :wid
                """),
                {"wid": wid},
            )

            conn.execute(
                text("""
                    UPDATE users
                    SET balance = balance + :amount
                    WHERE chat_id = :chat_id
                """),
                {
                    "amount": amount,
                    "chat_id": chat_id,
                },
            )

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ Yêu cầu rút tiền không được duyệt.\n\n"
                f"💰 {amount:,}đ đã được "
                "hoàn lại vào số dư."
            ),
        )

        await query.message.reply_text(
            "❌ Đã từ chối và hoàn lại số dư."
        )


# =========================================================
# ADMIN GỬI LINK CHỈ BẰNG CÁCH DÁN LINK
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
                FROM admin_state
                WHERE admin_chat_id = :admin_chat_id
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
                SELECT chat_id
                FROM requests
                WHERE request_id = :request_id
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
                UPDATE requests
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
                DELETE FROM admin_state
                WHERE admin_chat_id = :admin_chat_id
            """),
            {
                "admin_chat_id":
                    int(ADMIN_CHAT_ID)
            },
        )

    await context.bot.send_message(
        chat_id=customer_chat_id,
        text=(
            "✅ LINK MUA HÀNG ĐÃ SẴN SÀNG!\n\n"
            f"🛍 {url}\n\n"
            "❤️ Cảm ơn bạn đã sử dụng bot."
        ),
        reply_markup=main_keyboard,
    )

    await update.message.reply_text(
        "✅ Đã gửi link cho khách."
    )

    return True


# =========================================================
# HANDLE MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    save_user(user)

    chat_id = update.effective_chat.id
    text_message = update.message.text.strip()

    # -----------------------------------------------------
    # ADMIN đang trả affiliate link
    # -----------------------------------------------------

    url = extract_url(text_message)

    if url:
        handled = await handle_admin_link(
            update,
            context,
            url,
        )

        if handled:
            return

    # -----------------------------------------------------
    # USER đang thực hiện rút tiền
    # -----------------------------------------------------

    wd_state = get_withdraw_state(chat_id)

    if wd_state:

        stage, stored_amount = wd_state

        if stage == "amount":

            amount_text = (
                text_message
                .replace(".", "")
                .replace(",", "")
                .replace("đ", "")
                .strip()
            )

            try:
                amount = int(amount_text)

            except ValueError:
                await update.message.reply_text(
                    "❌ Vui lòng nhập số tiền.\n\n"
                    "Ví dụ: 50000"
                )
                return

            balance = get_balance(chat_id)

            if amount <= 0:
                await update.message.reply_text(
                    "❌ Số tiền không hợp lệ."
                )
                return

            if amount > balance:
                await update.message.reply_text(
                    f"❌ Số dư của bạn chỉ có "
                    f"{balance:,}đ."
                )
                return

            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE withdraw_state
                        SET
                            stage = 'bank',
                            amount = :amount
                        WHERE chat_id = :chat_id
                    """),
                    {
                        "amount": amount,
                        "chat_id": chat_id,
                    },
                )

            await update.message.reply_text(
                "🏦 Nhập thông tin nhận tiền.\n\n"
                "Ví dụ:\n"
                "Vietcombank - 0123456789 "
                "- NGUYEN VAN A"
            )
            return

        if stage == "bank":

            bank_info = text_message
            amount = int(stored_amount)

            withdrawal_id = (
                uuid.uuid4().hex[:8]
            )

            with engine.begin() as conn:

                balance = conn.execute(
                    text("""
                        SELECT balance
                        FROM users
                        WHERE chat_id = :chat_id
                    """),
                    {
                        "chat_id": chat_id
                    },
                ).scalar() or 0

                if amount > balance:
                    clear_withdraw_state(chat_id)

                    await update.message.reply_text(
                        "❌ Số dư không còn đủ."
                    )
                    return

                conn.execute(
                    text("""
                        UPDATE users
                        SET balance = balance - :amount
                        WHERE chat_id = :chat_id
                    """),
                    {
                        "amount": amount,
                        "chat_id": chat_id,
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
                        DELETE FROM withdraw_state
                        WHERE chat_id = :chat_id
                    """),
                    {
                        "chat_id": chat_id
                    },
                )

            await update.message.reply_text(
                "✅ Đã tạo yêu cầu rút tiền.\n\n"
                f"🆔 Mã: {withdrawal_id}\n"
                f"💵 Số tiền: {amount:,}đ\n"
                "⏳ Đang chờ admin duyệt.",
                reply_markup=main_keyboard,
            )

            if ADMIN_CHAT_ID:
                buttons = InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(
                            "✅ Duyệt",
                            callback_data=(
                                f"wdapprove:"
                                f"{withdrawal_id}"
                            ),
                        ),
                        InlineKeyboardButton(
                            "❌ Từ chối",
                            callback_data=(
                                f"wdreject:"
                                f"{withdrawal_id}"
                            ),
                        ),
                    ]]
                )

                await context.bot.send_message(
                    chat_id=int(
                        ADMIN_CHAT_ID
                    ),
                    text=(
                        "💳 YÊU CẦU RÚT TIỀN\n\n"
                        f"🆔 {withdrawal_id}\n"
                        f"👤 Chat ID: {chat_id}\n"
                        f"💵 {amount:,}đ\n"
                        f"🏦 {bank_info}"
                    ),
                    reply_markup=buttons,
                )

            return

    # -----------------------------------------------------
    # MENU
    # -----------------------------------------------------

    if text_message == "👤 Thông tin tài khoản":
        await account_info(
            update,
            context,
        )
        return

    if text_message == "💰 Thu nhập":
        await income(
            update,
            context,
        )
        return

    if text_message == "💳 Rút tiền":
        await withdraw(
            update,
            context,
        )
        return

    if text_message == "🛒 Gửi link Shopee":
        await update.message.reply_text(
            "🛒 Hãy dán link Shopee vào đây.",
            reply_markup=main_keyboard,
        )
        return

    if text_message == "🎵 Gửi link TikTok":
        await update.message.reply_text(
            "🎵 Hãy dán link TikTok vào đây.",
            reply_markup=main_keyboard,
        )
        return

    # -----------------------------------------------------
    # LINK KHÁCH
    # -----------------------------------------------------

    if not url:
        await update.message.reply_text(
            "❌ Mình chưa thấy link.\n\n"
            "Hãy gửi link Shopee hoặc TikTok.",
            reply_markup=main_keyboard,
        )
        return

    platform = detect_platform(url)

    if not platform:
        await update.message.reply_text(
            "❌ Link chưa được hỗ trợ.\n\n"
            "Hiện bot hỗ trợ Shopee và TikTok.",
            reply_markup=main_keyboard,
        )
        return

    # -----------------------------------------------------
    # CHỐNG SPAM / LINK TRÙNG 5 PHÚT
    # -----------------------------------------------------

    duplicate = find_recent_duplicate(
        chat_id,
        url,
    )

    if duplicate:

        rid, status, affiliate_url = duplicate

        if (
            status == "done"
            and affiliate_url
        ):
            await update.message.reply_text(
                "✅ Link này vừa được xử lý.\n\n"
                f"🛍 {affiliate_url}",
                reply_markup=main_keyboard,
            )
            return

        await update.message.reply_text(
            "⏳ Link này đã được gửi trước đó.\n\n"
            f"🆔 Mã yêu cầu: {rid}\n"
            "Vui lòng chờ bot xử lý.",
            reply_markup=main_keyboard,
        )
        return

    # -----------------------------------------------------
    # TẠO REQUEST
    # -----------------------------------------------------

    request_id = uuid.uuid4().hex[:8]
    now = int(time.time())

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
                "request_id": request_id,
                "chat_id": chat_id,
                "platform": platform,
                "url": url,
                "created_ts": now,
                "updated_ts": now,
            },
        )

    await update.message.reply_text(
        f"✅ Đã nhận link {platform}!\n\n"
        f"🆔 Mã yêu cầu: {request_id}\n"
        "⏳ Trạng thái: Chờ xử lý.\n\n"
        "Bot sẽ thông báo khi link "
        "đang được xử lý và khi hoàn tất.",
        reply_markup=main_keyboard,
    )

    # -----------------------------------------------------
    # GỬI ADMIN + NÚT TRẢ LINK
    # -----------------------------------------------------

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
                        f"reply:{request_id}"
                    ),
                )
            ]]
        )

        await context.bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=(
                "🔔 YÊU CẦU MỚI\n\n"
                f"🏪 {platform}\n"
                f"🆔 {request_id}\n"
                f"👤 {username}\n"
                f"💬 Chat ID: {chat_id}\n\n"
                f"🔗 {url}"
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
            "addbalance",
            add_balance,
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

    webhook_url = (
        f"{BASE_URL.rstrip('/')}/telegram"
    )

    print(
        f"Webhook URL: {webhook_url}"
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
