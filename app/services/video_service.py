import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

import cv2
import numpy as np

_COOKIE_EXPORT_TEST_URL = "https://www.youtube.com/watch?v=BaW_jenozKc"
_COOKIE_FILE_HEADER = "# Netscape HTTP Cookie File"
_PROBE_DEFAULT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Cache for cookie refresh timestamp to avoid repeated refreshes
_cookie_refreshed_at: float | None = None


def _read_yt_dlp_settings() -> tuple[str, int, int, int]:
    # Prefer smaller/progressive formats for transcript and keyframe extraction.
    fmt = (
        os.getenv("YTDLP_FORMAT")
        or "b[height<=720]/bv*[height<=720]+ba/b"
    ).strip()

    retries_raw = (os.getenv("YTDLP_RETRIES") or "").strip()
    timeout_raw = (os.getenv("YTDLP_SOCKET_TIMEOUT") or "").strip()
    process_timeout_raw = (os.getenv("YTDLP_PROCESS_TIMEOUT") or "").strip()

    try:
        retries = max(1, int(retries_raw)) if retries_raw else 3
    except ValueError:
        retries = 3

    try:
        socket_timeout = max(5, int(timeout_raw)) if timeout_raw else 15
    except ValueError:
        socket_timeout = 15

    try:
        process_timeout = max(30, int(process_timeout_raw)) if process_timeout_raw else 240
    except ValueError:
        process_timeout = 240

    return fmt, retries, socket_timeout, process_timeout


def _read_proxy_settings() -> str | None:
    """Read optional proxy setting for yt-dlp.

    Useful when a VPS/datacenter egress IP gets blocked by YouTube.
    Example:
        YTDLP_PROXY=socks5://user:pass@host:1080
        YTDLP_PROXY=http://user:pass@host:8080
    """
    proxy = (os.getenv("YTDLP_PROXY") or "").strip()
    return proxy or None


def _read_js_runtime_settings() -> str | None:
    """Read JS runtime configuration for yt-dlp EJS/signature solving.

    Newer yt-dlp versions default to enabling only "deno"; in minimal Docker
    images deno is usually missing, so you must explicitly enable node.

    Example:
        YTDLP_JS_RUNTIMES=node
        YTDLP_JS_RUNTIMES=node:/usr/bin/node
    """
    value = (os.getenv("YTDLP_JS_RUNTIMES") or "").strip()
    if value:
        return value

    # Reasonable default when nodejs is installed in the image.
    return "node"


def _read_cookie_settings() -> tuple[str | None, str | None, bool]:
    """Returns tuple of (cookies_file, cookies_browser, auto_refresh)"""
    cookies_file = (os.getenv("YTDLP_COOKIES_FILE") or "").strip() or None
    cookies_browser = (os.getenv("YTDLP_COOKIES_FROM_BROWSER") or "").strip() or None
    auto_refresh = os.getenv("YTDLP_AUTO_REFRESH_COOKIES", "").strip().lower() in ("true", "1", "yes")

    if cookies_file:
        cookies_file = os.path.abspath(os.path.expanduser(cookies_file))

    return cookies_file, cookies_browser, auto_refresh


def _get_cookie_expiry_timestamp(cookies_file: str) -> float | None:
    """Extract the earliest cookie expiry timestamp from the cookie file."""
    if not os.path.exists(cookies_file):
        return None
    
    try:
        with open(cookies_file, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 5:
                    # Field 4 is the expiry timestamp
                    try:
                        expiry = int(parts[4])
                        if expiry > 0:
                            return float(expiry)
                    except (ValueError, IndexError):
                        continue
    except Exception:
        pass
    return None


def _should_refresh_cookies(cookies_file: str, cookies_browser: str | None) -> bool:
    """Determine if cookies should be refreshed based on expiry time or age."""
    global _cookie_refreshed_at
    
    # If auto-refresh is disabled, never auto-refresh
    cookies_file, cookies_browser, auto_refresh = _read_cookie_settings()
    if not auto_refresh:
        return False
    
    # If no browser configured, can't auto-refresh
    if not cookies_browser:
        return False
    
    # If cookie file doesn't exist, always refresh
    if not os.path.exists(cookies_file):
        return True
    
    # Check if we refreshed recently (within last 5 minutes)
    if _cookie_refreshed_at is not None:
        import time as time_module
        if time_module.time() - _cookie_refreshed_at < 300:  # 5 minutes cache
            return False
    
    # Check cookie expiry
    expiry_timestamp = _get_cookie_expiry_timestamp(cookies_file)
    if expiry_timestamp is not None:
        import time as time_module
        current_time = time_module.time()
        warning_hours = int(os.getenv("YTDLP_COOKIE_EXPIRY_WARNING_HOURS", "24").strip() or 24)
        warning_seconds = warning_hours * 3600
        
        # Refresh if expiring within warning period
        if expiry_timestamp - current_time < warning_seconds:
            return True
    
    # Check file age (if no expiry found)
    file_age = os.path.getmtime(cookies_file)
    import time as time_module
    max_age = 6 * 3600  # 6 hours default max age
    if time_module.time() - file_age > max_age:
        return True
    
    return False


def _force_refresh_cookies() -> tuple[bool, str]:
    """Force refresh cookies from browser. Returns (success, message)."""
    global _cookie_refreshed_at
    
    cookies_file, cookies_browser, _ = _read_cookie_settings()
    
    if not cookies_browser:
        return False, "No browser configured for cookie extraction"
    
    if not cookies_file:
        return False, "No cookie file path configured"
    
    # Export cookies from browser
    success, message = _export_cookies_from_browser(cookies_browser, cookies_file)
    
    if success:
        import time as time_module
        _cookie_refreshed_at = time_module.time()
    
    return success, message


def _truncate(text: str | None, max_chars: int = 1500) -> str:
    value = (text or "").strip()
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars]} ...(truncated)"


def _run_command(command: list[str], timeout: int) -> dict[str, object]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_sec = round(time.monotonic() - started, 2)
        stdout = _truncate(result.stdout)
        stderr = _truncate(result.stderr)
        summary_source = stderr or stdout
        summary = (
            summary_source.splitlines()[-1].strip()
            if summary_source
            else ("Success" if result.returncode == 0 else "No output")
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "timed_out": False,
            "duration_sec": duration_sec,
            "stdout": stdout,
            "stderr": stderr,
            "summary": _truncate(summary, max_chars=300),
        }
    except subprocess.TimeoutExpired as exc:
        duration_sec = round(time.monotonic() - started, 2)
        err = ""
        if isinstance(exc.stderr, str):
            err = exc.stderr
        elif isinstance(exc.stdout, str):
            err = exc.stdout
        return {
            "ok": False,
            "exit_code": None,
            "timed_out": True,
            "duration_sec": duration_sec,
            "stdout": _truncate(exc.stdout if isinstance(exc.stdout, str) else ""),
            "stderr": _truncate(err),
            "summary": f"Command timed out after {timeout}s",
        }


def _diagnose_ytdlp_error(error_text: str) -> dict[str, object]:
    text = error_text.lower()

    if "failed to resolve" in text:
        return {
            "category": "dns_resolution",
            "message": "Failed to resolve YouTube/CDN domains.",
            "recommendations": [
                "Check DNS/network connectivity from the host.",
                "Disable VPN/proxy temporarily and retry.",
            ],
        }
    if "read timed out" in text or "timed out" in text:
        return {
            "category": "network_timeout",
            "message": "YouTube media requests timed out.",
            "recommendations": [
                "Try a more stable network path.",
                "Lower YTDLP_FORMAT (example: 18) for smaller downloads.",
                "Tune YTDLP_RETRIES / YTDLP_SOCKET_TIMEOUT in .env.",
            ],
        }
    if "video unavailable" in text:
        return {
            "category": "video_unavailable",
            "message": "The video is unavailable (private/removed/region restricted).",
            "recommendations": [
                "Retry with another public video URL.",
                "Open the URL in browser to confirm availability.",
            ],
        }
    if "sign in to confirm you're not a bot" in text or "sign in to confirm you’re not a bot" in text:
        return {
            "category": "anti_bot_challenge",
            "message": "YouTube anti-bot challenge was triggered.",
            "recommendations": [
                "Refresh cookies via /preflight?repair=true.",
                "Keep YTDLP_COOKIES_FILE and YTDLP_COOKIES_FROM_BROWSER configured.",
            ],
        }
    if "does not look like a netscape format cookies file" in text:
        return {
            "category": "invalid_cookie_file",
            "message": "Cookie file is not valid Netscape format.",
            "recommendations": [
                "Regenerate cookies file with yt-dlp --cookies-from-browser ... --cookies ...",
                "Ensure first line contains 'HTTP Cookie File'.",
            ],
        }
    if "find-generic-password failed" in text or "cannot decrypt v10 cookies" in text:
        return {
            "category": "keychain_cookie_access",
            "message": "Could not read/decrypt browser cookies from keychain.",
            "recommendations": [
                "Allow keychain access prompt for terminal/python.",
                "Use YTDLP_COOKIES_FILE as primary source after manual export.",
            ],
        }
    return {
        "category": "unknown_error",
        "message": "yt-dlp probe failed with an unknown error.",
        "recommendations": [
            "Inspect probe attempt stderr.",
            "Run /preflight and verify environment dependencies.",
        ],
    }


def _inspect_cookie_file(cookies_file: str) -> tuple[bool, str]:
    if not os.path.exists(cookies_file):
        return False, f"file does not exist: {cookies_file}"

    if not os.path.isfile(cookies_file):
        return False, f"path is not a file: {cookies_file}"

    if os.path.getsize(cookies_file) == 0:
        return False, f"file is empty: {cookies_file}"

    with open(cookies_file, "r", encoding="utf-8", errors="ignore") as fh:
        lines = [line.rstrip("\n") for line in fh]

    if not lines:
        return False, f"file is empty: {cookies_file}"

    header = lines[0].strip()
    if "HTTP Cookie File" not in header:
        return False, (
            "invalid Netscape header. First line should contain "
            "'HTTP Cookie File'."
        )

    cookie_rows = sum(
        1
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    )
    if cookie_rows == 0:
        return False, "file has no cookie rows."

    return True, f"valid Netscape cookies file ({cookie_rows} cookie rows)."


def _export_cookies_from_browser(
    cookies_browser: str,
    cookies_file: str,
) -> tuple[bool, str]:
    os.makedirs(str(Path(cookies_file).parent), exist_ok=True)

    # yt-dlp may fail if an empty/invalid file already exists at --cookies path.
    if os.path.exists(cookies_file):
        os.remove(cookies_file)

    export_cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--cookies-from-browser",
        cookies_browser,
        "--cookies",
        cookies_file,
        "--skip-download",
        _COOKIE_EXPORT_TEST_URL,
    ]
    result = subprocess.run(export_cmd, capture_output=True, text=True)
    details = (result.stderr or result.stdout or "").strip()
    if result.returncode != 0:
        return False, details or "yt-dlp cookie export command failed."

    valid, reason = _inspect_cookie_file(cookies_file)
    if not valid:
        return False, reason

    return True, reason


def inspect_cookie_configuration(auto_fix: bool = False) -> dict[str, str | bool]:
    cookies_file, cookies_browser, _ = _read_cookie_settings()

    if not cookies_file and not cookies_browser:
        return {
            "status": "warning",
            "cookies_file": "",
            "cookies_browser": "",
            "message": (
                "No YouTube cookie source is configured. Set YTDLP_COOKIES_FILE "
                "or YTDLP_COOKIES_FROM_BROWSER to reduce anti-bot failures."
            ),
        }

    if cookies_file:
        valid, reason = _inspect_cookie_file(cookies_file)
        if valid:
            # Check if cookies need refresh based on expiry/age
            needs_refresh = _should_refresh_cookies(cookies_file, cookies_browser)
            refresh_msg = ""
            if needs_refresh and cookies_browser:
                success, msg = _force_refresh_cookies()
                if success:
                    refresh_msg = f" (auto-refreshed: {msg})"
                    valid, reason = _inspect_cookie_file(cookies_file)
                else:
                    refresh_msg = f" (refresh failed: {msg})"
            
            status_msg = f"Cookie file is ready: {reason}{refresh_msg}"
            return {
                "status": "ok",
                "cookies_file": cookies_file,
                "cookies_browser": cookies_browser or "",
                "message": status_msg,
            }

        if auto_fix and cookies_browser:
            fixed, fix_reason = _export_cookies_from_browser(
                cookies_browser,
                cookies_file,
            )
            if fixed:
                return {
                    "status": "ok",
                    "cookies_file": cookies_file,
                    "cookies_browser": cookies_browser,
                    "message": f"Cookie file auto-refreshed from browser: {fix_reason}",
                }
            return {
                "status": "error",
                "cookies_file": cookies_file,
                "cookies_browser": cookies_browser,
                "message": (
                    f"YTDLP_COOKIES_FILE is invalid ({reason}) and auto-refresh "
                    f"from browser '{cookies_browser}' failed. Details: {fix_reason}"
                ),
            }

        if cookies_browser:
            return {
                "status": "error",
                "cookies_file": cookies_file,
                "cookies_browser": cookies_browser,
                "message": (
                    f"YTDLP_COOKIES_FILE is invalid ({reason}). "
                    "Call GET /preflight?repair=true to auto-refresh from browser, "
                    "or regenerate the file manually."
                ),
            }

        return {
            "status": "error",
            "cookies_file": cookies_file,
            "cookies_browser": "",
            "message": (
                f"YTDLP_COOKIES_FILE is invalid ({reason}). Re-export cookies in "
                "Netscape format or set YTDLP_COOKIES_FROM_BROWSER."
            ),
        }

    return {
        "status": "warning",
        "cookies_file": "",
        "cookies_browser": cookies_browser or "",
        "message": (
            "Using browser cookies only (YTDLP_COOKIES_FROM_BROWSER). This works "
            "if the process can access browser keychain cookies."
        ),
    }


def run_download_probe(url: str | None = None, run_download: bool = False) -> dict[str, object]:
    target_url = (url or _PROBE_DEFAULT_URL).strip()
    if not target_url.startswith(("http://", "https://")):
        return {
            "ok": False,
            "status": "error",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "url": target_url,
            "message": "Invalid URL. Provide a full http(s) URL.",
        }

    format_selector, retries, socket_timeout, process_timeout = _read_yt_dlp_settings()
    cookie_status = inspect_cookie_configuration(auto_fix=True)
    cookies_file, cookies_browser, _ = _read_cookie_settings()

    proxy = _read_proxy_settings()
    js_runtimes = _read_js_runtime_settings()

    # Keep probe minimal: never inherit global -f/format selector here.
    base_cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--js-runtimes",
        js_runtimes,
        "--skip-download",
        "--no-playlist",
        "--retries",
        str(retries),
        "--socket-timeout",
        str(socket_timeout),
        "--print",
        "%(id)s|%(title)s",
    ]

    if proxy:
        base_cmd += ["--proxy", proxy]

    attempt_commands: list[list[str]] = []
    if cookies_file:
        attempt_commands.append(base_cmd + ["--cookies", cookies_file, target_url])
    if cookies_browser:
        attempt_commands.append(
            base_cmd + ["--cookies-from-browser", cookies_browser, target_url]
        )
    # Android clients do not support cookies; keep these as explicit no-cookie fallbacks.
    attempt_commands.append(
        base_cmd
        + ["--extractor-args", "youtube:player_client=android,web_embedded", target_url]
    )
    attempt_commands.append(
        base_cmd + ["--extractor-args", "youtube:player_client=android", target_url]
    )
    attempt_commands.append(base_cmd + [target_url])

    probe_timeout = min(process_timeout, 120)
    attempts: list[dict[str, object]] = []
    metadata_ok = False
    metadata_result = ""
    metadata_errors: list[str] = []

    for command in attempt_commands:
        command_result = _run_command(command, timeout=probe_timeout)
        attempts.append(
            {
                "command": " ".join(command),
                "ok": command_result["ok"],
                "exit_code": command_result["exit_code"],
                "timed_out": command_result["timed_out"],
                "duration_sec": command_result["duration_sec"],
                "summary": command_result["summary"],
            }
        )

        if command_result["ok"]:
            metadata_ok = True
            lines = str(command_result.get("stdout", "")).splitlines()
            metadata_result = lines[-1] if lines else str(command_result.get("summary", ""))
            break

        combined_text = "\n".join(
            filter(
                None,
                [
                    str(command_result.get("stderr", "")),
                    str(command_result.get("stdout", "")),
                ],
            )
        )
        metadata_errors.append(_truncate(combined_text, max_chars=1200))

    diagnosis = (
        {"category": "ok", "message": "Metadata probe succeeded.", "recommendations": []}
        if metadata_ok
        else _diagnose_ytdlp_error("\n".join(metadata_errors))
    )

    report: dict[str, object] = {
        "ok": metadata_ok,
        "status": "ok" if metadata_ok else "error",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "url": target_url,
        "settings": {
            "format": format_selector,
            "retries": retries,
            "socket_timeout": socket_timeout,
            "process_timeout": process_timeout,
        },
        "cookie_status": cookie_status,
        "metadata_probe": {
            "ok": metadata_ok,
            "attempts": attempts,
            "result": metadata_result,
            "diagnosis": diagnosis,
            "errors": metadata_errors,
        },
    }

    if not run_download:
        return report

    probe_output = str(Path("/tmp") / f"yt_probe_{int(time.time())}.mp4")
    probe_format = (os.getenv("YTDLP_PROBE_FORMAT") or "best[ext=mp4]/best").strip()

    # For download probe: avoid format selection issues by defaulting to best.
    # (Hardcoding an itag like 18 can fail with "Requested format is not available".)
    download_base_cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--js-runtimes",
        js_runtimes,
        "-f",
        probe_format,
        "--no-playlist",
        "--retries",
        str(retries),
        "--fragment-retries",
        str(retries),
        "--socket-timeout",
        str(socket_timeout),
        "--merge-output-format",
        "mp4",
        "--force-overwrites",
        "-o",
        probe_output,
    ]

    if proxy:
        download_base_cmd += ["--proxy", proxy]

    cookie_args: list[str] = []
    if cookies_file:
        cookie_args = ["--cookies", cookies_file]
    elif cookies_browser:
        cookie_args = ["--cookies-from-browser", cookies_browser]

    download_attempts: list[dict[str, object]] = []
    download_errors: list[str] = []
    download_ok = False
    download_size = 0
    download_summary = ""
    download_timed_out = False
    download_duration = 0.0

    # Mirror the same strategy list used in download_video(), because some YouTube
    # endpoints work while others fail (signature solving / anti-bot).
    attempt_cmds: list[list[str]] = [
        # Try cookie-backed default web client first.
        download_base_cmd + cookie_args + [target_url],
        # Then use Android fallback clients without cookies.
        download_base_cmd
        + [
            "--extractor-args",
            "youtube:player_client=android,web_embedded",
            target_url,
        ],
        download_base_cmd
        + ["--extractor-args", "youtube:player_client=android", target_url],
        download_base_cmd + [target_url],
    ]

    for attempt in attempt_cmds:
        # Ensure no stale probe output.
        if os.path.exists(probe_output):
            os.remove(probe_output)

        attempt_result = _run_command(attempt, timeout=min(process_timeout, 240))
        file_ok = bool(attempt_result["ok"]) and os.path.exists(probe_output)
        file_size = os.path.getsize(probe_output) if file_ok else 0

        download_attempts.append(
            {
                "command": " ".join(attempt),
                "ok": file_ok,
                "exit_code": attempt_result["exit_code"],
                "timed_out": attempt_result["timed_out"],
                "duration_sec": attempt_result["duration_sec"],
                "summary": attempt_result["summary"],
                "downloaded_bytes": file_size,
            }
        )

        if file_ok:
            download_ok = True
            download_size = file_size
            download_summary = str(attempt_result["summary"])
            download_timed_out = bool(attempt_result["timed_out"])
            download_duration = float(attempt_result["duration_sec"])
            break

        combined = "\n".join(
            filter(
                None,
                [
                    str(attempt_result.get("stderr", "")),
                    str(attempt_result.get("stdout", "")),
                ],
            )
        )
        if combined.strip():
            download_errors.append(_truncate(combined, max_chars=1200))

    if os.path.exists(probe_output):
        os.remove(probe_output)

    download_text = "\n".join(download_errors)
    download_diag = (
        {"category": "ok", "message": "Download smoke test succeeded.", "recommendations": []}
        if download_ok
        else _diagnose_ytdlp_error(download_text)
    )

    report["download_probe"] = {
        "ok": download_ok,
        "format": probe_format,
        "attempts": download_attempts,
        "duration_sec": download_duration,
        "timed_out": download_timed_out,
        "summary": download_summary,
        "downloaded_bytes": download_size,
        "diagnosis": download_diag,
        "errors": download_errors,
    }
    report["ok"] = bool(report["ok"]) and download_ok
    report["status"] = "ok" if report["ok"] else "error"

    return report


def download_video(url: str, output_path="data/video.mp4") -> str:
    os.makedirs(os.path.dirname(output_path) or "data", exist_ok=True)
    format_selector, retries, socket_timeout, process_timeout = _read_yt_dlp_settings()

    # Read cookie configuration for actual downloads as well.
    # (Previously only /probe-download used cookies; downloads ignored them.)
    cookies_file, cookies_browser, _ = _read_cookie_settings()

    proxy = _read_proxy_settings()
    js_runtimes = _read_js_runtime_settings()

    base_cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--js-runtimes",
        js_runtimes,
        "-f",
        format_selector,
        "--retries",
        str(retries),
        "--fragment-retries",
        str(retries),
        "--socket-timeout",
        str(socket_timeout),
        "--merge-output-format",
        "mp4",
        "-o",
        output_path,
        "--no-playlist",
    ]

    if proxy:
        base_cmd += ["--proxy", proxy]

    # Cookie args should be included before URL.
    # In Docker/VPS environments, a cookies file is usually the only viable option.
    cookie_args: list[str] = []
    if cookies_file:
        cookie_args = ["--cookies", cookies_file]
    elif cookies_browser:
        cookie_args = ["--cookies-from-browser", cookies_browser]

    # Multiple strategies to reduce frequent YouTube anti-bot failures.
    # Also include a final "no cookies" attempt: occasionally cookie state itself can
    # trigger harsher challenges and a clean request works better.
    attempt_commands: list[list[str]] = []

    # Try cookie-backed default web client first.
    attempt_commands.append(base_cmd + cookie_args + [url])

    # Android clients do not support cookies; keep them as no-cookie fallbacks.
    attempt_commands.append(
        base_cmd + ["--extractor-args", "youtube:player_client=android,web_embedded", url]
    )
    attempt_commands.append(base_cmd + ["--extractor-args", "youtube:player_client=android", url])
    attempt_commands.append(base_cmd + [url])

    errors: list[str] = []
    for attempt_cmd in attempt_commands:
        try:
            result = subprocess.run(
                attempt_cmd,
                capture_output=True,
                text=True,
                timeout=process_timeout,
            )
        except subprocess.TimeoutExpired:
            errors.append(
                "yt-dlp attempt timed out after "
                f"{process_timeout}s for command: {' '.join(attempt_cmd)}"
            )
            continue

        if result.returncode == 0:
            return output_path
        errors.append((result.stderr or result.stdout or "").strip())

    joined_errors = "\n\n---\n\n".join(error for error in errors if error)
    bot_check_messages = (
        "Sign in to confirm you're not a bot",
        "Sign in to confirm you’re not a bot",
    )

    if any(message in joined_errors for message in bot_check_messages):
        raise RuntimeError(
            "Download failed due to YouTube anti-bot check after multiple strategies. "
            "Set YTDLP_COOKIES_FROM_BROWSER (example: chrome) or YTDLP_COOKIES_FILE "
            "in .env, then restart uvicorn/bot and retry.\n"
            f"yt-dlp details:\n{joined_errors}"
        )
    if "does not look like a Netscape format cookies file" in joined_errors:
        raise RuntimeError(
            "Download failed because YTDLP_COOKIES_FILE is not in Netscape format. "
            "Export a valid cookies.txt file and retry.\n"
            f"yt-dlp details:\n{joined_errors}"
        )
    keychain_messages = (
        "cannot decrypt v10 cookies",
        "find-generic-password failed",
    )
    if any(message in joined_errors for message in keychain_messages):
        raise RuntimeError(
            "Download failed while reading browser cookies from keychain. "
            "Allow terminal/python keychain access, or export a cookies file "
            "manually and set YTDLP_COOKIES_FILE.\n"
            f"yt-dlp details:\n{joined_errors}"
        )

    raise RuntimeError(f"Download failed after multiple strategies:\n{joined_errors}")


def extract_keyframes(video_path: str, threshold=30, max_frames=5):
    """Extract keyframes from video and return list of image paths.
    
    Returns:
        List of strings (file paths) to the extracted keyframe images,
        sorted by frame number (frame_0.jpg, frame_1.jpg, etc.).
    """
    os.makedirs("data/keyframes", exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0: fps = 24
    keyframes = []
    prev_gray = None
    count = 0
    while cap.isOpened() and len(keyframes) < max_frames:
        ok, frame = cap.read()
        if not ok: break
        count += 1
        if count % int(fps) != 0: continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev_gray is not None:
            diff = np.mean(cv2.absdiff(prev_gray, gray))
            if diff > threshold:
                path = f"data/keyframes/frame_{len(keyframes)}.jpg"
                cv2.imwrite(path, frame)
                # Return just the path string, not a dictionary
                keyframes.append(path)
        prev_gray = gray
    cap.release()
    # Sort by frame number to ensure consistent ordering
    keyframes.sort(key=lambda x: int(x.split('_')[-1].replace('.jpg', '')))
    return keyframes

