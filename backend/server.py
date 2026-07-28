"""FastAPI backend for the Sound Effect Generator.

Exposes a small HTTP API the Electron front-end talks to. Generation requests
are placed on an in-process queue and handled by a single background worker
(one job at a time, matching the single GPU). Job metadata is persisted to
``<data dir>/jobs.json`` (and restored on startup) so the result list survives
app restarts; the WAV files live next to it in the same folder.

The data folder is user-configurable (``/api/datadir``) so generated results can
be kept away from the application itself; it defaults to ``data/`` in the
project root. Where it points is an *app* setting, so it is stored in
``app-config.json`` next to the code -- never inside the data folder.
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
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data"

# ---------------------------------------------------------------------------
# App settings (data folder, selected model)
# ---------------------------------------------------------------------------
# Kept next to the code rather than in the data folder: it records *where* that
# folder is, so it has to be readable before the folder is known. The selected
# model used to live in ``data/config.json``; that file is still read once as a
# fallback so existing installs keep their choice.
APP_CONFIG_FILE = PROJECT_ROOT / "app-config.json"
LEGACY_CONFIG_FILE = DEFAULT_OUTPUT_DIR / "config.json"

_SAVE_LOCK = threading.Lock()


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def load_app_config() -> dict:
    if APP_CONFIG_FILE.exists():
        return _read_json(APP_CONFIG_FILE)
    return _read_json(LEGACY_CONFIG_FILE)  # migrate the old model setting


APP_CONFIG = load_app_config()


def save_app_config() -> None:
    with _SAVE_LOCK:
        tmp = APP_CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(APP_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, APP_CONFIG_FILE)


def resolve_data_dir(raw: Optional[str]) -> Path:
    """Turn a configured/requested path into an absolute data folder path."""
    if not raw or not str(raw).strip():
        return DEFAULT_OUTPUT_DIR
    p = Path(str(raw).strip()).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return Path(os.path.normpath(p))


def _init_data_dir() -> Path:
    """Use the configured folder, falling back to ``data/`` if unusable.

    The configured folder can live on a drive that is not present right now, so
    a failure here must not stop the server from starting.
    """
    configured = resolve_data_dir(APP_CONFIG.get("data_dir"))
    try:
        configured.mkdir(parents=True, exist_ok=True)
        return configured
    except OSError as exc:
        print(f"[data] cannot use {configured} ({exc}); falling back to default")
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        return DEFAULT_OUTPUT_DIR


OUTPUT_DIR = _init_data_dir()


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
# list survives app restarts. Both follow the (switchable) data folder, hence
# the function rather than a constant.
def jobs_file() -> Path:
    return OUTPUT_DIR / "jobs.json"


def save_jobs() -> None:
    """Atomically write all jobs to disk. Call outside JOBS_LOCK."""
    with JOBS_LOCK:
        data = [j.to_dict() for j in JOBS.values()]
    with _SAVE_LOCK:
        target = jobs_file()
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, target)


def load_jobs() -> None:
    """Replace the in-memory job list with the one in the data folder."""
    restored: dict[str, Job] = {}
    src = jobs_file()
    data = _read_list(src) if src.exists() else []
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
        restored[job.id] = job
    with JOBS_LOCK:
        JOBS.clear()
        JOBS.update(restored)


def _read_list(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


load_jobs()


# ---------------------------------------------------------------------------
# Selected model (persisted so it auto-loads next launch)
# ---------------------------------------------------------------------------
def load_selected_model() -> str:
    key = APP_CONFIG.get("model", engine.DEFAULT_MODEL)
    return key if key in engine.MODELS else engine.DEFAULT_MODEL


def save_selected_model(key: str) -> None:
    APP_CONFIG["model"] = key
    save_app_config()


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
            # If the card was deleted while this job was generating, delete()
            # couldn't remove the not-yet-written WAV. Clean it up here so no
            # orphaned audio lingers in data/.
            with JOBS_LOCK:
                removed = job.id not in JOBS
            if removed:
                f = OUTPUT_DIR / f"{job.id}.wav"
                if f.exists():
                    f.unlink()
            save_jobs()
            WORK_QUEUE.task_done()


worker_thread = threading.Thread(target=_worker, daemon=True)
worker_thread.start()


# ---------------------------------------------------------------------------
# On-demand engine load/unload (driven by the UI toggles)
# ---------------------------------------------------------------------------
# Loading a model takes several seconds, so the load/unload endpoints kick the
# work off on a background thread and report progress via the ``loading`` flags
# below; the front-end polls /api/health to see the resulting state.
ENGINE_STATE_LOCK = threading.Lock()
ENGINE_LOADING = {"audio": False, "llm": False}


def _run_engine_task(name: str, fn) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 - a failed load just leaves it "off"
        pass
    finally:
        with ENGINE_STATE_LOCK:
            ENGINE_LOADING[name] = False


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
    with ENGINE_STATE_LOCK:
        audio_loading = ENGINE_LOADING["audio"]
        llm_loading = ENGINE_LOADING["llm"]
    return {
        "status": "ok",
        "model_ready": ok,
        "missing_files": missing,
        "queue_size": WORK_QUEUE.qsize(),
        "data_dir": str(OUTPUT_DIR),
        "model_loaded": engine._state["model"] is not None,
        "loaded_model": engine._state["key"],
        "device": engine._state["device"],
        "selected_model": SELECTED_MODEL,
        # Per-engine state for the UI on/off toggles.
        "audio_loaded": engine.is_loaded(),
        "audio_loading": audio_loading,
        "audio_present": ok,
        "llm_loaded": suggest.is_loaded(),
        "llm_loading": llm_loading,
        "llm_present": suggest.model_files_present(),
    }


def _data_dir_state() -> dict:
    return {
        "path": str(OUTPUT_DIR),
        "default": str(DEFAULT_OUTPUT_DIR),
        "is_default": OUTPUT_DIR == DEFAULT_OUTPUT_DIR,
    }


@app.get("/api/datadir")
def get_data_dir() -> dict:
    return _data_dir_state()


class DataDirRequest(BaseModel):
    # Empty/None means "go back to the default data/ folder".
    path: Optional[str] = None


@app.post("/api/datadir")
def set_data_dir(req: DataDirRequest) -> dict:
    """Point the app at another data folder.

    Nothing is moved or copied: the new folder is read as-is (its own
    ``jobs.json`` + WAVs become the visible result list), and the old one is
    left untouched.
    """
    global OUTPUT_DIR
    new_dir = resolve_data_dir(req.path)
    if new_dir == OUTPUT_DIR:
        return _data_dir_state()

    # Switching under a running/queued job would orphan its WAV in the old
    # folder, so require an idle queue.
    with JOBS_LOCK:
        busy = any(j.status in ("queued", "running") for j in JOBS.values())
    if busy:
        raise HTTPException(status_code=409, detail="jobs_in_progress")

    try:
        new_dir.mkdir(parents=True, exist_ok=True)
        probe = new_dir / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}")

    OUTPUT_DIR = new_dir
    APP_CONFIG["data_dir"] = "" if new_dir == DEFAULT_OUTPUT_DIR else str(new_dir)
    save_app_config()
    load_jobs()  # show whatever the new folder already holds
    return _data_dir_state()


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


class EngineRequest(BaseModel):
    action: str  # "load" | "unload"


@app.post("/api/engine/{name}")
def set_engine(name: str, req: EngineRequest) -> dict:
    """Load or unload one of the resident models on demand ("audio" | "llm")."""
    if name not in ("audio", "llm"):
        raise HTTPException(status_code=404, detail="unknown engine")
    if req.action not in ("load", "unload"):
        raise HTTPException(status_code=400, detail="unknown action")

    if req.action == "load":
        with ENGINE_STATE_LOCK:
            if ENGINE_LOADING[name]:
                return {"ok": True, "loading": True}
            ENGINE_LOADING[name] = True
        fn = (
            (lambda: engine.preload(SELECTED_MODEL))
            if name == "audio"
            else suggest.preload
        )
        threading.Thread(
            target=_run_engine_task, args=(name, fn), daemon=True
        ).start()
    else:  # unload — run off-thread so a busy GPU lock doesn't block the request
        fn = engine.unload if name == "audio" else suggest.unload
        threading.Thread(target=fn, daemon=True).start()
    return {"ok": True}


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
