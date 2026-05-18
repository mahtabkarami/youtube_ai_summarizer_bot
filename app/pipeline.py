from .services.youtube_service import get_transcript, extract_video_id
from .services.video_service import download_video, extract_keyframes
from .utils.audio_utils import extract_audio
from .services.ai_service import speech_to_text, translate_and_structure
from logger_config import logger

def process_video(video_url: str) -> dict:
    transcript = None
    language = "unknown"
    video_path = None

    # ۱. تست سریع یوتیوب
    if extract_video_id(video_url):
        try:
            logger.info("Trying YouTube transcript API first.")
            transcript = get_transcript(video_url)
            language = "fa (YouTube)"
            logger.info("YouTube transcript API succeeded.")
        except Exception as exc:
            logger.warning(
                "YouTube transcript API failed; switching to yt-dlp + Whisper. Reason: %s",
                exc,
            )

    # ۲. مسیر سنگین (Whisper)
    if not transcript:
        logger.info("Downloading video with yt-dlp.")
        video_path = download_video(video_url)
        logger.info("Extracting audio from downloaded video.")
        audio_path = extract_audio(video_path)
        logger.info("Transcribing audio with Whisper.")
        transcript, language = speech_to_text(audio_path)

    # ۳. خلاصه‌سازی
    logger.info("Generating structured summary.")
    structured_text = translate_and_structure(transcript)

    # ۴. فریم‌های کلیدی
    keyframes = []
    if video_path:
        logger.info("Extracting keyframes from downloaded video.")
        keyframes = extract_keyframes(video_path)

    return {
        "language": language,
        "structured_text": structured_text,
        "keyframes": keyframes
    }

