import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "shopee.vn" in text or "sp.shp.ee" in text:
        await update.message.reply_text("Đã nhận link Shopee của bạn!")
    else:
        await update.message.reply_text("Hãy gửi một đường link Shopee hợp lệ nhé!")

def main():
    if not TOKEN:
        print("Chưa cấu hình TELEGRAM_BOT_TOKEN!")
        return
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("Bot đang chạy...")
    app.run_polling()

if __name__ == "__main__":
    main()
