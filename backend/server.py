"""FastAPI backend for the Sound Effect Generator.

Exposes a small HTTP API the Electron front-end talks to. Generation requests
are placed on an in-process queue and handled by a single background worker
(one job at a time, matching the single GPU). Job state is kept in memory and
the resulting WAV files are written to ``outputs/``.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------
@dataclass
class Job:
    id: str
    prompt: str
    seconds: float
    steps: int
    cfg_scale: float
    negative_prompt: Optional[str]
    seed: int
    status: str = "queued"  # queued | running | done | error
    message: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    filename: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
WORK_QUEUE: "queue.Queue[str]" = queue.Queue()


def _worker() -> None:
    """Background thread: pull job ids and run generation sequentially."""
    while True:
        job_id = WORK_QUEUE.get()
        job = JOBS.get(job_id)
        if job is None:
            WORK_QUEUE.task_done()
            continue
        try:
            with JOBS_LOCK:
                job.status = "running"
                job.started_at = time.time()
                job.message = "Starting..."

            def progress(msg: str, _job=job) -> None:
                with JOBS_LOCK:
                    _job.message = msg

            out_path = OUTPUT_DIR / f"{job.id}.wav"
            engine.generate(
                prompt=job.prompt,
                seconds=job.seconds,
                steps=job.steps,
                cfg_scale=job.cfg_scale,
                negative_prompt=job.negative_prompt,
                seed=job.seed,
                out_path=out_path,
                progress=progress,
            )
            with JOBS_LOCK:
                job.status = "done"
                job.filename = out_path.name
                job.finished_at = time.time()
                job.message = "Completed"
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            with JOBS_LOCK:
                job.status = "error"
                job.message = f"{type(exc).__name__}: {exc}"
                job.finished_at = time.time()
        finally:
            WORK_QUEUE.task_done()


worker_thread = threading.Thread(target=_worker, daemon=True)
worker_thread.start()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
app = FastAPI(title="Sound Effect Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    seconds: float = Field(8.0, gt=0, le=300)
    steps: int = Field(8, ge=1, le=100)
    cfg_scale: float = Field(1.0, ge=0, le=20)
    negative_prompt: Optional[str] = None
    seed: int = -1


@app.get("/api/health")
def health() -> dict:
    ok, missing = engine.model_files_present()
    return {
        "status": "ok",
        "model_ready": ok,
        "missing_files": missing,
        "queue_size": WORK_QUEUE.qsize(),
        "model_loaded": engine._state["model"] is not None,
        "device": engine._state["device"],
    }


@app.post("/api/generate")
def create_job(req: GenerateRequest) -> dict:
    ok, missing = engine.model_files_present()
    if not ok:
        raise HTTPException(
            status_code=409,
            detail={"error": "model_files_missing", "missing": missing},
        )
    job = Job(
        id=uuid.uuid4().hex[:12],
        prompt=req.prompt,
        seconds=req.seconds,
        steps=req.steps,
        cfg_scale=req.cfg_scale,
        negative_prompt=req.negative_prompt or None,
        seed=req.seed,
    )
    with JOBS_LOCK:
        JOBS[job.id] = job
    WORK_QUEUE.put(job.id)
    return job.to_dict()


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    with JOBS_LOCK:
        jobs = sorted(JOBS.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.to_dict()


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    with JOBS_LOCK:
        job = JOBS.pop(job_id, None)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.filename:
        f = OUTPUT_DIR / job.filename
        if f.exists():
            f.unlink()
    return {"deleted": job_id}


@app.get("/api/audio/{job_id}")
def get_audio(job_id: str):
    job = JOBS.get(job_id)
    if job is None or not job.filename:
        raise HTTPException(status_code=404, detail="audio not found")
    f = OUTPUT_DIR / job.filename
    if not f.exists():
        raise HTTPException(status_code=404, detail="audio file missing")
    return FileResponse(f, media_type="audio/wav", filename=f"{job_id}.wav")


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
