import os

import requests

from .pipeline import process_video
from .services.pdf_service import create_pdf
from logger_config import logger


def _build_user_facing_error(error: Exception) -> str:
    text = str(error)
    if "cookies" in text.lower() or "YTDLP_COOKIES_FILE" in text:
        return (
            "❌ مشکل کوکی یوتیوب. لطفا تنظیمات سرور را بررسی کنید: "
            "GET /preflight یا GET /preflight?repair=true"
        )
    return "❌ خطایی رخ داد. لطفا لینک را چک کنید."


def update_telegram_status(chat_id: int, message_id: int, text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    requests.post(
        url,
        json={"chat_id": chat_id, "message_id": message_id, "text": text},
        timeout=15,
    )


def send_pdf_to_telegram(chat_id: int, file_path: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with open(file_path, "rb") as f:
        requests.post(
            url,
            data={"chat_id": chat_id},
            files={"document": f},
            timeout=30,
        )


def process_and_send(
    link: str,
    user_id: int | None,
    status_msg_id: int | None,
    notify_telegram: bool = True,
) -> None:
    can_notify = notify_telegram and user_id is not None and status_msg_id is not None

    try:
        logger.info(f"Processing started for {user_id}")
        if can_notify:
            update_telegram_status(
                user_id,
                status_msg_id,
                "⏳ در حال پردازش ویدیو و استخراج متن...",
            )

        result = process_video(link)

        if can_notify:
            update_telegram_status(user_id, status_msg_id, "📝 در حال تولید فایل PDF...")

        suffix = user_id if user_id is not None else "local"
        pdf_path = f"data/summary_{suffix}.pdf"
        keyframes = result.get("keyframes", [])
        create_pdf(result["structured_text"], pdf_path, images=keyframes)

        if can_notify:
            update_telegram_status(
                user_id,
                status_msg_id,
                "✅ پردازش تکمیل شد. در حال ارسال...",
            )
            send_pdf_to_telegram(user_id, pdf_path)

    except Exception as e:
        logger.error(f"Pipeline Error: {e}", exc_info=True)
        if can_notify:
            update_telegram_status(
                user_id,
                status_msg_id,
                _build_user_facing_error(e),
            )

