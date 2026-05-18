import os
import time

import requests
import telebot
from dotenv import load_dotenv

load_dotenv()


def register_handlers(bot: telebot.TeleBot) -> None:
    @bot.message_handler(func=lambda m: True)
    def on_message(message) -> None:
        link = message.text.strip()
        if not link.startswith("http"):
            bot.reply_to(message, "❌ لینک معتبر نیست.")
            return

        status_msg = bot.reply_to(
            message, "🚀 دریافت شد! در حال ارسال به سرور هوش مصنوعی..."
        )

        try:
            response = requests.post(
                "http://api:8000/process-link",
                json={
                    "link": link,
                    "user_id": message.chat.id,
                    "status_msg_id": status_msg.message_id,
                },
                timeout=300,
            )
            if response.status_code >= 400:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                server_message = body.get("message") or "Server returned an error."
                bot.edit_message_text(
                    f"❌ {server_message} (see /preflight in FastAPI).",
                    message.chat.id,
                    status_msg.message_id,
                )
        except requests.RequestException:
            bot.edit_message_text(
                "❌ سرور در دسترس نیست.", message.chat.id, status_msg.message_id
            )


def run_bot() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN is not set.")

    bot = telebot.TeleBot(token)
    register_handlers(bot)
    print("Bot is running...")
    try:
        bot.polling(none_stop=True, interval=0, timeout=20)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(5)
        bot.polling(none_stop=True, interval=0, timeout=20)


if __name__ == "__main__":
    run_bot()

