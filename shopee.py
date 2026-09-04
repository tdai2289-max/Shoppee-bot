import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Shopee bot is running".encode())

    def log_message(self, format, *args):
        pass


def run_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"Web server running on port {PORT}")
    server.serve_forever()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Xin chào 👋\n"
        "Hãy gửi link sản phẩm Shopee cho tôi."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    lower_text = text.lower()

    if (
        "shopee.vn" in lower_text
        or "s.shopee.vn" in lower_text
        or "shp.ee" in lower_text
    ):
        await update.message.reply_text(
            "✅ Đã nhận link Shopee của bạn!\n\n"
            f"{text}"
        )
    else:
        await update.message.reply_text(
            "❌ Hãy gửi một đường link Shopee hợp lệ nhé!"
        )


def main():
    if not TOKEN:
        print("Chưa cấu hình TELEGRAM_BOT_TOKEN")
        return

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("Bot đang chạy...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
