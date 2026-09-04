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

keyboard = ReplyKeyboardMarkup(
    [
        ["🚀 Bắt đầu"],
        ["🛒 Gửi link Shopee", "🎵 Gửi link TikTok"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

# Lưu tạm yêu cầu trong lúc bot đang chạy
pending_requests = {}


def extract_url(text: str):
    match = re.search(r"https?://[^\s]+", text)
    if match:
        return match.group(0)
    return None


def detect_platform(url: str):
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào!\n\n"
        "🛍 Gửi link sản phẩm Shopee hoặc TikTok cho tôi.\n\n"
        "Sau khi nhận link, hệ thống sẽ xử lý và gửi link mua hàng lại cho bạn.",
        reply_markup=keyboard,
    )


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Telegram Chat ID của bạn:\n{update.effective_chat.id}"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "🚀 Bắt đầu":
        await start(update, context)
        return

    if text == "🛒 Gửi link Shopee":
        await update.message.reply_text(
            "🛒 Hãy dán link sản phẩm Shopee vào đây.",
            reply_markup=keyboard,
        )
        return

    if text == "🎵 Gửi link TikTok":
        await update.message.reply_text(
            "🎵 Hãy dán link sản phẩm TikTok Shop vào đây.",
            reply_markup=keyboard,
        )
        return

    url = extract_url(text)

    if not url:
        await update.message.reply_text(
            "❌ Mình chưa thấy đường link.\n\n"
            "Hãy gửi link Shopee hoặc TikTok nhé.",
            reply_markup=keyboard,
        )
        return

    platform = detect_platform(url)

    if not platform:
        await update.message.reply_text(
            "❌ Link này chưa được hỗ trợ.\n\n"
            "Hiện bot nhận link Shopee và TikTok.",
            reply_markup=keyboard,
        )
        return

    request_id = uuid.uuid4().hex[:8]

    user = update.effective_user
    user_id = update.effective_chat.id
    username = f"@{user.username}" if user.username else "Không có username"

    pending_requests[request_id] = {
        "user_id": user_id,
        "platform": platform,
        "original_url": url,
    }

    await update.message.reply_text(
        f"✅ Đã nhận link {platform} của bạn!\n\n"
        f"🆔 Mã yêu cầu: {request_id}\n"
        "⏳ Đang chờ xử lý link mua hàng...",
        reply_markup=keyboard,
    )

    if not ADMIN_CHAT_ID:
        print("Chưa cấu hình ADMIN_CHAT_ID")
        return

    try:
        await context.bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=(
                "🔔 CÓ YÊU CẦU MỚI\n\n"
                f"🏪 Nền tảng: {platform}\n"
                f"🆔 Mã: {request_id}\n"
                f"👤 User: {username}\n"
                f"💬 Chat ID: {user_id}\n\n"
                f"🔗 Link gốc:\n{url}\n\n"
                "Sau khi tạo affiliate link, gửi:\n\n"
                f"/reply {user_id} LINK_AFFILIATE"
            ),
        )
    except Exception as e:
        print(f"Lỗi gửi cho admin: {e}")


async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Chưa cấu hình ADMIN_CHAT_ID.")
        return

    if str(update.effective_chat.id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text("⛔ Bạn không có quyền dùng lệnh này.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Sai cú pháp.\n\n"
            "Dùng:\n"
            "/reply CHAT_ID LINK_AFFILIATE"
        )
        return

    target_chat_id = context.args[0]
    affiliate_link = context.args[1]

    if not affiliate_link.startswith("http"):
        await update.message.reply_text("❌ Affiliate link không hợp lệ.")
        return

    try:
        await context.bot.send_message(
            chat_id=int(target_chat_id),
            text=(
                "🎉 LINK CỦA BẠN ĐÃ SẴN SÀNG!\n\n"
                f"🛍 Mua hàng tại đây:\n{affiliate_link}\n\n"
                "❤️ Cảm ơn bạn đã sử dụng bot."
            ),
            reply_markup=keyboard,
        )

        await update.message.reply_text(
            "✅ Đã gửi affiliate link cho khách."
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Gửi thất bại:\n{e}"
        )


def main():
    if not TOKEN:
        raise RuntimeError("Chưa cấu hình TELEGRAM_BOT_TOKEN")

    if not RENDER_URL:
        raise RuntimeError("Không tìm thấy RENDER_EXTERNAL_URL")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("reply", admin_reply))

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
