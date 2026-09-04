import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

keyboard = ReplyKeyboardMarkup(
    [
        ["🚀 Bắt đầu"],
        ["🛒 Gửi link Shopee", "🎵 Gửi link TikTok"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào!\n\n"
        "Hãy gửi link sản phẩm Shopee hoặc TikTok cho tôi.",
        reply_markup=keyboard,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    lower_text = text.lower()

    if text == "🚀 Bắt đầu":
        await start(update, context)
        return

    if text == "🛒 Gửi link Shopee":
        await update.message.reply_text(
            "📎 Hãy dán link sản phẩm Shopee vào đây.",
            reply_markup=keyboard,
        )
        return

    if text == "🎵 Gửi link TikTok":
        await update.message.reply_text(
            "📎 Hãy dán link sản phẩm TikTok Shop vào đây.",
            reply_markup=keyboard,
        )
        return

    if (
        "shopee.vn" in lower_text
        or "s.shopee.vn" in lower_text
        or "shp.ee" in lower_text
    ):
        await update.message.reply_text(
            "✅ Đã nhận link Shopee của bạn!\n\n"
            "⏳ Hiện bot chưa tự tạo affiliate link. "
            "Phần này mình sẽ thêm sau.",
            reply_markup=keyboard,
        )
        return

    if "tiktok.com" in lower_text:
        await update.message.reply_text(
            "✅ Đã nhận link TikTok của bạn!\n\n"
            "⏳ Hiện bot chưa tự tạo affiliate link. "
            "Phần này mình sẽ thêm sau.",
            reply_markup=keyboard,
        )
        return

    await update.message.reply_text(
        "❌ Mình chưa nhận ra link.\n\n"
        "Hãy gửi link Shopee hoặc TikTok nhé.",
        reply_markup=keyboard,
    )


def main():
    if not TOKEN:
        raise RuntimeError("Chưa cấu hình TELEGRAM_BOT_TOKEN")

    if not RENDER_URL:
        raise RuntimeError("Không tìm thấy RENDER_EXTERNAL_URL")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
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
