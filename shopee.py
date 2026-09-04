import os
import re
import uuid

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")


# =========================
# MENU
# =========================

main_keyboard = ReplyKeyboardMarkup(
    [
        ["👤 Thông tin tài khoản"],
        ["🛒 Gửi link Shopee", "🎵 Gửi link TikTok"],
        ["💳 Rút tiền", "💰 Thu nhập"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


# =========================
# DỮ LIỆU TẠM
# =========================

user_balances = {}


def get_balance(user_id):
    return user_balances.get(user_id, 0)


# =========================
# XỬ LÝ LINK
# =========================

def extract_url(text):
    match = re.search(r"https?://[^\s]+", text)

    if match:
        return match.group(0)

    return None


def detect_platform(url):
    lower = url.lower()

    if (
        "shopee.vn" in lower
        or "s.shopee.vn" in lower
        or "shp.ee" in lower
    ):
        return "Shopee"

    if (
        "tiktok.com" in lower
        or "vt.tiktok.com" in lower
        or "vm.tiktok.com" in lower
    ):
        return "TikTok"

    return None


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or "bạn"

    await update.message.reply_text(
        f"👋 Xin chào {name}!\n\n"
        "🎉 Chào mừng bạn đến với Shopee Tích Xu.\n\n"
        "🛍 Hãy gửi link sản phẩm Shopee hoặc TikTok.\n"
        "Bot sẽ tiếp nhận và xử lý link cho bạn.\n\n"
        "👇 Chọn chức năng bên dưới:",
        reply_markup=main_keyboard,
    )


# =========================
# THÔNG TIN TÀI KHOẢN
# =========================

async def account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = update.effective_chat.id

    name = user.full_name or "Chưa cập nhật"

    username = (
        f"@{user.username}"
        if user.username
        else "Chưa có"
    )

    balance = get_balance(user_id)

    await update.message.reply_text(
        "👤 THÔNG TIN TÀI KHOẢN\n\n"
        f"🆔 ID hội viên: {user_id}\n"
        f"👤 Họ tên: {name}\n"
        f"📱 Username: {username}\n"
        f"💰 Số dư: {balance:,}đ",
        reply_markup=main_keyboard,
    )


# =========================
# RÚT TIỀN
# =========================

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    balance = get_balance(user_id)

    await update.message.reply_text(
        "💳 RÚT TIỀN\n\n"
        f"💰 Số dư hiện tại: {balance:,}đ\n\n"
        "⏳ Chức năng rút tiền đang được hoàn thiện.",
        reply_markup=main_keyboard,
    )


# =========================
# THU NHẬP
# =========================

async def income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    balance = get_balance(user_id)

    await update.message.reply_text(
        "💰 THU NHẬP\n\n"
        f"💵 Số dư hiện tại: {balance:,}đ\n"
        "📦 Hoa hồng chờ duyệt: 0đ\n"
        "✅ Hoa hồng đã duyệt: 0đ",
        reply_markup=main_keyboard,
    )


# =========================
# LẤY CHAT ID
# =========================

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Chat ID của bạn:\n{update.effective_chat.id}"
    )


# =========================
# ADMIN GỬI LINK CHO KHÁCH
# =========================

async def admin_send(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not ADMIN_CHAT_ID:
        await update.message.reply_text(
            "❌ Chưa cấu hình ADMIN_CHAT_ID."
        )
        return

    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text(
            "⛔ Bạn không có quyền dùng lệnh này."
        )
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Sai cú pháp.\n\n"
            "Dùng:\n"
            "/send CHAT_ID LINK"
        )
        return

    target_chat_id = context.args[0]
    link = context.args[1]

    if not link.startswith("http"):
        await update.message.reply_text(
            "❌ Link không hợp lệ."
        )
        return

    try:
        await context.bot.send_message(
            chat_id=int(target_chat_id),
            text=(
                "🎉 Link mua hàng của bạn đã sẵn sàng!\n\n"
                f"🛍 Link:\n{link}\n\n"
                "❤️ Cảm ơn bạn đã sử dụng bot."
            ),
            reply_markup=main_keyboard,
        )

        await update.message.reply_text(
            "✅ Đã gửi link cho khách."
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Không gửi được:\n{e}"
        )


# =========================
# XỬ LÝ TIN NHẮN
# =========================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text.strip()

    # MENU

    if text == "👤 Thông tin tài khoản":
        await account_info(update, context)
        return

    if text == "💳 Rút tiền":
        await withdraw(update, context)
        return

    if text == "💰 Thu nhập":
        await income(update, context)
        return

    if text == "🛒 Gửi link Shopee":
        await update.message.reply_text(
            "🛒 Hãy dán link sản phẩm Shopee vào đây.",
            reply_markup=main_keyboard,
        )
        return

    if text == "🎵 Gửi link TikTok":
        await update.message.reply_text(
            "🎵 Hãy dán link sản phẩm TikTok vào đây.",
            reply_markup=main_keyboard,
        )
        return

    # NHẬN LINK

    url = extract_url(text)

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
            "❌ Link này chưa được hỗ trợ.\n\n"
            "Hiện bot hỗ trợ Shopee và TikTok.",
            reply_markup=main_keyboard,
        )
        return

    request_id = uuid.uuid4().hex[:8]

    user = update.effective_user
    user_id = update.effective_chat.id

    username = (
        f"@{user.username}"
        if user.username
        else "Không có username"
    )

    await update.message.reply_text(
        f"✅ Đã nhận link {platform}!\n\n"
        f"🆔 Mã yêu cầu: {request_id}\n"
        "⏳ Đang xử lý link cho bạn.",
        reply_markup=main_keyboard,
    )

    # GỬI THÔNG BÁO CHO ADMIN

    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(
                    "🔔 YÊU CẦU MỚI\n\n"
                    f"🏪 Nền tảng: {platform}\n"
                    f"🆔 Mã: {request_id}\n"
                    f"👤 User: {username}\n"
                    f"💬 Chat ID: {user_id}\n\n"
                    "🔗 Link khách gửi:\n"
                    f"{url}\n\n"
                    "📤 Trả link cho khách bằng:\n\n"
                    f"/send {user_id} LINK_AFFILIATE"
                ),
            )

        except Exception as e:
            print(f"Lỗi gửi admin: {e}")


# =========================
# MAIN
# =========================

def main():

    if not TOKEN:
        raise RuntimeError(
            "Chưa cấu hình TELEGRAM_BOT_TOKEN"
        )

    if not RENDER_URL:
        raise RuntimeError(
            "Không tìm thấy RENDER_EXTERNAL_URL"
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("id", get_id)
    )

    app.add_handler(
        CommandHandler("send", admin_send)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    webhook_url = f"{RENDER_URL}/telegram"

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
