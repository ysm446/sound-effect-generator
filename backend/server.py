"""FastAPI backend for the Sound Effect Generator.

Exposes a small HTTP API the Electron front-end talks to. Generation requests
are placed on an in-process queue and handled by a single background worker
(one job at a time, matching the single GPU). Job metadata is persisted to
``data/jobs.json`` (and restored on startup) so the result list survives app
restarts; the WAV files live next to it in ``data/``.
"""
from __future__ import annotations

import json
import os
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
import suggest

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
    title: Optional[str] = None  # short Qwen-generated name for the card
    status: str = "queued"  # queued | running | done | error
    message: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    filename: Optional[str] = None
    model: Optional[str] = None  # which model produced/produces this job

    def to_dict(self) -> dict:
        return asdict(self)


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
WORK_QUEUE: "queue.Queue[str]" = queue.Queue()

# Persistence: job metadata is stored alongside the WAV files so the result
# list survives app restarts.
JOBS_FILE = OUTPUT_DIR / "jobs.json"
_SAVE_LOCK = threading.Lock()


def save_jobs() -> None:
    """Atomically write all jobs to disk. Call outside JOBS_LOCK."""
    with JOBS_LOCK:
        data = [j.to_dict() for j in JOBS.values()]
    with _SAVE_LOCK:
        tmp = JOBS_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, JOBS_FILE)


def load_jobs() -> None:
    """Restore jobs from disk on startup."""
    if not JOBS_FILE.exists():
        return
    try:
        data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    fields = Job.__dataclass_fields__
    for d in data:
        try:
            job = Job(**{k: d.get(k) for k in fields})
        except TypeError:
            continue
        # Jobs that were mid-flight when the app closed can't be resumed.
        if job.status in ("queued", "running"):
            job.status = "error"
            job.message = "Interrupted by app shutdown"
        # Drop completed jobs whose audio file is gone.
        if job.status == "done" and (
            not job.filename or not (OUTPUT_DIR / job.filename).exists()
        ):
            continue
        JOBS[job.id] = job


load_jobs()


# ---------------------------------------------------------------------------
# Selected model (persisted so it auto-loads next launch)
# ---------------------------------------------------------------------------
CONFIG_FILE = OUTPUT_DIR / "config.json"


def load_selected_model() -> str:
    key = engine.DEFAULT_MODEL
    if CONFIG_FILE.exists():
        try:
            key = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("model", key)
        except (json.JSONDecodeError, OSError):
            pass
    return key if key in engine.MODELS else engine.DEFAULT_MODEL


def save_selected_model(key: str) -> None:
    with _SAVE_LOCK:
        tmp = CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"model": key}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_FILE)


SELECTED_MODEL = load_selected_model()


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
            save_jobs()

            def progress(msg: str, _job=job) -> None:
                with JOBS_LOCK:
                    _job.message = msg

            # Give the card a short, readable name derived from the prompt.
            # Best-effort: a failure here must not block audio generation.
            if not job.title and suggest.model_files_present():
                try:
                    title = suggest.make_title(job.prompt)
                    if title:
                        with JOBS_LOCK:
                            job.title = title
                        save_jobs()
                except Exception:  # noqa: BLE001
                    pass

            out_path = OUTPUT_DIR / f"{job.id}.wav"
            _, used_seed = engine.generate(
                prompt=job.prompt,
                seconds=job.seconds,
                steps=job.steps,
                cfg_scale=job.cfg_scale,
                negative_prompt=job.negative_prompt,
                seed=job.seed,
                out_path=out_path,
                progress=progress,
                model_key=job.model or SELECTED_MODEL,
            )
            with JOBS_LOCK:
                job.status = "done"
                job.filename = out_path.name
                job.seed = used_seed  # record the actual seed (resolves -1)
                job.finished_at = time.time()
                job.message = "Completed"
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            with JOBS_LOCK:
                job.status = "error"
                job.message = f"{type(exc).__name__}: {exc}"
                job.finished_at = time.time()
        finally:
            save_jobs()
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
    ok, missing = engine.model_files_present(SELECTED_MODEL)
    return {
        "status": "ok",
        "model_ready": ok,
        "missing_files": missing,
        "queue_size": WORK_QUEUE.qsize(),
        "model_loaded": engine._state["model"] is not None,
        "loaded_model": engine._state["key"],
        "device": engine._state["device"],
        "selected_model": SELECTED_MODEL,
    }


@app.get("/api/models")
def list_models() -> dict:
    return {"models": engine.available_models(), "selected": SELECTED_MODEL}


class ModelRequest(BaseModel):
    model: str


@app.post("/api/model")
def set_model(req: ModelRequest) -> dict:
    global SELECTED_MODEL
    if req.model not in engine.MODELS:
        raise HTTPException(status_code=400, detail="unknown model")
    SELECTED_MODEL = req.model
    save_selected_model(SELECTED_MODEL)
    ok, missing = engine.model_files_present(SELECTED_MODEL)
    return {"selected": SELECTED_MODEL, "model_ready": ok, "missing_files": missing}


@app.post("/api/generate")
def create_job(req: GenerateRequest) -> dict:
    ok, missing = engine.model_files_present(SELECTED_MODEL)
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
        model=SELECTED_MODEL,
    )
    with JOBS_LOCK:
        JOBS[job.id] = job
    WORK_QUEUE.put(job.id)
    save_jobs()
    return job.to_dict()


class SuggestRequest(BaseModel):
    idea: str = Field(..., min_length=1)


@app.post("/api/suggest")
def suggest_prompt(req: SuggestRequest) -> dict:
    if not suggest.model_files_present():
        raise HTTPException(status_code=409, detail="suggestion model not available")
    try:
        text = suggest.suggest(req.idea)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
    return {"prompt": text}


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
    # Remove the WAV from data/. Try the recorded filename and the conventional
    # "<id>.wav" so the audio file never lingers after a card is deleted.
    candidates = {job.filename, f"{job_id}.wav"}
    for name in candidates:
        if not name:
            continue
        f = OUTPUT_DIR / name
        if f.exists():
            f.unlink()
    save_jobs()
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
