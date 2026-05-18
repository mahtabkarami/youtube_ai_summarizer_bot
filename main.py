from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from app.message_handler import process_and_send
from app.services.preflight_service import run_preflight
from app.services.video_service import run_download_probe
from logger_config import logger

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    report = run_preflight(auto_fix=False)
    app.state.preflight_report = report
    if report["ok"]:
        logger.info(
            "Startup preflight passed (warnings=%s).",
            len(report["warnings"]),
        )
    else:
        logger.error(
            "Startup preflight failed (errors=%s). Check GET /preflight.",
            len(report["errors"]),
        )
    yield


app = FastAPI(lifespan=lifespan)


class VideoRequest(BaseModel):
    link: str
    user_id: int | None = None
    status_msg_id: int | None = None
    notify_telegram: bool = True


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Telegram Summarizer API is running.",
        "docs": "/docs",
        "health": "/health",
        "preflight": "/preflight",
        "probe_download": "/probe-download",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/preflight")
async def preflight(repair: bool = False):
    report = run_preflight(auto_fix=repair)
    app.state.preflight_report = report
    return report


@app.get("/probe-download")
async def probe_download(url: str | None = None, download: bool = False):
    report = run_download_probe(url=url, run_download=download)
    status_code = 200 if report.get("ok") else 503
    return JSONResponse(status_code=status_code, content=report)


@app.post("/process-link")
async def handle_request(request: VideoRequest, background_tasks: BackgroundTasks):
    preflight_report = run_preflight(auto_fix=True)
    app.state.preflight_report = preflight_report
    if not preflight_report["ok"]:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": "Server preflight failed. Fix configuration before processing links.",
                "preflight": preflight_report,
            },
        )

    background_tasks.add_task(
        process_and_send,
        request.link,
        request.user_id,
        request.status_msg_id,
        request.notify_telegram,
    )
    return {"status": "ok"}

