import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _read_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def create_job_workspace(user_id: int | None = None) -> dict[str, str]:
    jobs_root = Path("data/jobs")
    jobs_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    owner = str(user_id) if user_id is not None else "local"
    job_id = f"{ts}_{owner}_{uuid.uuid4().hex[:8]}"
    root = jobs_root / job_id

    videos_dir = root / "videos"
    audio_dir = root / "audio"
    keyframes_dir = root / "keyframes"
    output_dir = root / "output"

    for directory in (videos_dir, audio_dir, keyframes_dir, output_dir):
        directory.mkdir(parents=True, exist_ok=True)

    return {
        "job_id": job_id,
        "root": str(root),
        "videos_dir": str(videos_dir),
        "audio_dir": str(audio_dir),
        "keyframes_dir": str(keyframes_dir),
        "output_dir": str(output_dir),
    }


def cleanup_job_workspace(workspace_root: str | None) -> None:
    if not workspace_root:
        return
    path = Path(workspace_root)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _cleanup_old_job_workspaces() -> int:
    jobs_root = Path("data/jobs")
    if not jobs_root.exists():
        return 0

    max_age_hours = _read_int_env("JOB_ARTIFACT_MAX_AGE_HOURS", 12, minimum=1)
    now = datetime.now(timezone.utc).timestamp()
    max_age_seconds = max_age_hours * 3600
    removed = 0

    for item in jobs_root.iterdir():
        if not item.is_dir():
            continue
        age_seconds = now - item.stat().st_mtime
        if age_seconds >= max_age_seconds:
            shutil.rmtree(item, ignore_errors=True)
            removed += 1
    return removed


def _cleanup_summary_history() -> int:
    summary_dir = Path(os.getenv("SUMMARY_OUTPUT_DIR", "results/summaries"))
    summary_dir.mkdir(parents=True, exist_ok=True)

    max_files = _read_int_env("SUMMARY_KEEP_COUNT", 20, minimum=1)
    max_age_hours = _read_int_env("SUMMARY_MAX_AGE_HOURS", 168, minimum=1)
    now = datetime.now(timezone.utc).timestamp()
    max_age_seconds = max_age_hours * 3600
    removed = 0

    pdfs = [p for p in summary_dir.glob("*.pdf") if p.is_file()]
    pdfs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for idx, pdf in enumerate(pdfs):
        age_seconds = now - pdf.stat().st_mtime
        if idx >= max_files or age_seconds >= max_age_seconds:
            pdf.unlink(missing_ok=True)
            removed += 1

    return removed


def cleanup_old_artifacts() -> dict[str, int]:
    jobs_removed = _cleanup_old_job_workspaces()
    summaries_removed = _cleanup_summary_history()
    return {
        "jobs_removed": jobs_removed,
        "summaries_removed": summaries_removed,
    }

