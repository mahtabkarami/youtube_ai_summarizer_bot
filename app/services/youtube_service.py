import re


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video id from common URL formats."""
    patterns = [
        r"(?:v=|\/videos\/|embed\/|youtu\.be\/)([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _parse_preferred_languages() -> list[str]:
    """Read preferred transcript languages from env or use a broad default."""
    import os

    env_value = os.getenv("YOUTUBE_TRANSCRIPT_LANGUAGES")
    if env_value:
        languages = [item.strip() for item in env_value.split(",") if item.strip()]
        if languages:
            return languages

    # Broad default to avoid falling back to video download for non-English videos.
    return [
        "fa",
        "en",
        "ar",
        "tr",
        "ur",
        "hi",
        "es",
        "fr",
        "de",
        "it",
        "pt",
        "ru",
        "id",
        "ms",
        "nl",
        "ja",
        "ko",
    ]


def get_transcript(video_url: str) -> str:
    """Fetch video transcript text from YouTube."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import TranscriptsDisabled
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The 'youtube-transcript-api' package is not installed. Install dependencies first."
        ) from exc

    video_id = extract_video_id(video_url)
    if not video_id:
        raise ValueError("Invalid YouTube URL")

    preferred_languages = _parse_preferred_languages()
    transcript_entries = None

    try:
        # First try direct get_transcript with broad language preference.
        transcript_entries = YouTubeTranscriptApi.get_transcript(
            video_id, languages=preferred_languages
        )
    except TranscriptsDisabled as exc:
        raise RuntimeError(
            "No YouTube subtitles are available for this video (subtitles disabled)."
        ) from exc
    except Exception:
        # Fallback: inspect available transcripts and choose the best possible one.
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        selected_transcript = None

        try:
            selected_transcript = transcript_list.find_transcript(preferred_languages)
        except Exception:
            try:
                selected_transcript = transcript_list.find_generated_transcript(
                    preferred_languages
                )
            except Exception:
                # Last resort: use the first available transcript track.
                for item in transcript_list:
                    selected_transcript = item
                    break

        if selected_transcript is None:
            raise RuntimeError("No transcript tracks are available for this video.")

        transcript_entries = selected_transcript.fetch()

    text = " ".join(chunk.get("text", "").strip() for chunk in transcript_entries).strip()
    if not text:
        raise ValueError("Transcript is empty")

    return text

