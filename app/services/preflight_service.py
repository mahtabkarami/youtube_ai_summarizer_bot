import importlib.util
import os
import shutil
import sys
from datetime import datetime, timezone
from urllib.request import urlopen

from dotenv import load_dotenv

from .video_service import inspect_cookie_configuration

load_dotenv()


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def run_preflight(auto_fix: bool = False) -> dict:
    checks: list[dict[str, str]] = []
    errors: list[str] = []
    warnings: list[str] = []
    actions: list[str] = []

    def add_check(
        name: str,
        status: str,
        message: str,
        action: str | None = None,
    ) -> None:
        checks.append({"name": name, "status": status, "message": message})
        if status == "error":
            errors.append(f"{name}: {message}")
        elif status == "warning":
            warnings.append(f"{name}: {message}")
        if action:
            actions.append(action)

    add_check(
        "python",
        "ok",
        f"Python executable detected: {sys.executable}",
    )

    # Outbound IP check (useful to confirm VPS egress is different from a blocked network path).
    # Keep it best-effort and short timeout.
    outbound_ip = ""
    try:
        outbound_ip = (
            urlopen("https://api.ipify.org", timeout=5).read().decode("utf-8").strip()
        )
        if outbound_ip:
            add_check("outbound_ip", "ok", f"Detected outbound IP: {outbound_ip}")
        else:
            add_check("outbound_ip", "warning", "Could not determine outbound IP (empty response).")
    except Exception as exc:
        add_check(
            "outbound_ip",
            "warning",
            f"Could not determine outbound IP: {exc}",
        )

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if telegram_token:
        add_check("telegram_token", "ok", "Telegram bot token is set.")
    else:
        add_check(
            "telegram_token",
            "warning",
            "TELEGRAM_BOT_TOKEN / TELEGRAM_TOKEN is not set.",
            "Set TELEGRAM_BOT_TOKEN in .env before starting telegram_bot.py.",
        )

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_api_key:
        add_check("openrouter_api_key", "ok", "OPENROUTER_API_KEY is set.")
    else:
        add_check(
            "openrouter_api_key",
            "error",
            "OPENROUTER_API_KEY is not set.",
            "Set OPENROUTER_API_KEY in .env before processing links.",
        )

    required_modules = (
        ("yt_dlp", "Install with: .venv/bin/pip install yt-dlp"),
        (
            "youtube_transcript_api",
            "Install with: .venv/bin/pip install youtube-transcript-api",
        ),
        ("moviepy", "Install with: .venv/bin/pip install moviepy"),
        ("whisper", "Install with: .venv/bin/pip install openai-whisper"),
        ("torch", "Install with: .venv/bin/pip install torch"),
    )
    for module_name, install_hint in required_modules:
        if _module_available(module_name):
            add_check(module_name, "ok", f"Module '{module_name}' is available.")
        else:
            add_check(
                module_name,
                "error",
                f"Module '{module_name}' is missing.",
                install_hint,
            )

    if shutil.which("ffmpeg"):
        add_check("ffmpeg", "ok", "ffmpeg binary found in PATH.")
    else:
        add_check(
            "ffmpeg",
            "warning",
            "ffmpeg binary not found in PATH (moviepy may fail on some setups).",
            "Install ffmpeg and ensure it is available in PATH.",
        )

    node_bin = shutil.which("node") or shutil.which("nodejs")
    if node_bin:
        add_check("node", "ok", f"Node.js runtime found: {node_bin}")
    else:
        add_check(
            "node",
            "warning",
            "Node.js runtime not found in PATH. yt-dlp may fail to solve YouTube signatures (missing formats).",
            "Install nodejs inside the image/host (recommended for Docker builds).",
        )

    font_path = "fonts/Vazirmatn-Medium.ttf"
    if not os.path.exists(font_path):
        add_check(
            "pdf_unicode_font",
            "error",
            f"PDF Unicode font not found: {font_path}",
            "Place Vazirmatn-Medium.ttf under fonts/ to avoid '?' in PDF output.",
        )
    else:
        try:
            from fpdf import FPDF

            pdf = FPDF()
            pdf.add_page()
            pdf.add_font("Vazirmatn", "", font_path, uni=True)
            pdf.set_font("Vazirmatn", size=12)
            add_check(
                "pdf_unicode_font",
                "ok",
                "PDF Unicode font is available and loadable.",
            )
        except Exception as exc:
            add_check(
                "pdf_unicode_font",
                "error",
                f"Cannot load Unicode PDF font: {exc}",
                "Install/repair fpdf Unicode font support to avoid '?' in PDF output.",
            )

    # Refresh cookies if auto_fix is enabled and needed
    cookie_status = inspect_cookie_configuration(auto_fix=auto_fix)
    cookie_level = str(cookie_status.get("status", "error"))
    cookie_message = str(cookie_status.get("message", "Unknown cookie configuration error."))
    cookie_file = str(cookie_status.get("cookies_file", "")).strip()
    cookie_browser = str(cookie_status.get("cookies_browser", "")).strip()

    cookie_details = f"{cookie_message} (file='{cookie_file}', browser='{cookie_browser}')"
    if cookie_level == "ok":
        add_check("youtube_cookies", "ok", cookie_details)
    elif cookie_level == "warning":
        add_check(
            "youtube_cookies",
            "warning",
            cookie_details,
            "Prefer setting both YTDLP_COOKIES_FILE and YTDLP_COOKIES_FROM_BROWSER=chrome.",
        )
    else:
        add_check(
            "youtube_cookies",
            "error",
            cookie_details,
            "Set YTDLP_COOKIES_FROM_BROWSER=chrome and call GET /preflight?repair=true, "
            "or regenerate cookies file manually.",
        )

    # Proxy hint
    proxy = (os.getenv("YTDLP_PROXY") or "").strip()
    if proxy:
        add_check(
            "ytdlp_proxy",
            "ok",
            f"YTDLP_PROXY is set: {proxy}",
        )
    else:
        add_check(
            "ytdlp_proxy",
            "warning",
            "YTDLP_PROXY is not set. If YouTube blocks this VPS IP, set a proxy (HTTP/SOCKS5) and retry.",
            "Optional: set YTDLP_PROXY=socks5://user:pass@host:1080",
        )

    ok = len(errors) == 0
    status = "ok" if ok and not warnings else "warning" if ok else "error"

    return {
        "ok": ok,
        "status": status,
        "auto_fix": auto_fix,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "outbound_ip": outbound_ip,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "recommended_actions": actions,
    }

