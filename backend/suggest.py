"""Prompt suggestion via a local GGUF model served by llama.cpp.

Turns a rough idea (any language) into a concise English sound-effect prompt
suitable for Stable Audio, and writes short card titles. The model is a
user-selected ``.gguf`` file (see ``configure()``) that we run in a
``llama-server.exe`` child process from ``runtime/llama_cpp``; this module
talks to it over its OpenAI-compatible HTTP API on localhost. "Loading" the
LLM therefore means spawning that server and waiting for it to report ready;
"unloading" kills it (which also frees the VRAM it held).
"""
from __future__ import annotations

import atexit
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models"
LLAMA_ROOT = PROJECT_ROOT / "runtime" / "llama_cpp" / "versions"

HOST = "127.0.0.1"
PORT = int(os.environ.get("LLAMA_SERVER_PORT", "8766"))
READY_TIMEOUT = 180  # seconds to wait for the server to load the model
CONTEXT_SIZE = 4096

SYSTEM_PROMPT = (
    "You help a user write prompts for a text-to-audio sound-effect generator "
    "(Stable Audio). Given a short, possibly vague idea in any language, reply "
    "with a single concise English prompt describing the sound. Be concrete "
    "about the source, material and acoustic qualities. Reply with only the "
    "prompt text on one line - no quotes, no labels, no explanation."
)

TITLE_SYSTEM_PROMPT = (
    "You write a very short title for a sound effect, given its (possibly long) "
    "description in any language. The title must be 2-4 words in English Title "
    "Case, naming the sound. Reply with only the title - no quotes, no period, "
    "no explanation."
)

_lock = threading.Lock()
_state = {
    "proc": None,  # subprocess.Popen of llama-server, or None
    "model_path": None,  # Path of the GGUF the running server was started with
    "ready": False,
}

# User configuration (set by the server from app-config.json).
_config = {
    "dir": None,  # Path or None (= DEFAULT_MODEL_DIR)
    "model": None,  # str (path relative to dir, or absolute) or None
}


# ---------------------------------------------------------------------------
# Configuration / model discovery
# ---------------------------------------------------------------------------
def resolve_dir(raw: Optional[str]) -> Path:
    """Turn a configured folder into an absolute path (empty = default)."""
    if not raw or not str(raw).strip():
        return DEFAULT_MODEL_DIR
    p = Path(str(raw).strip()).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return Path(os.path.normpath(p))


def configure(dir_: Optional[str], model: Optional[str]) -> None:
    """Set the GGUF folder and selected file. Does not touch a running server."""
    _config["dir"] = resolve_dir(dir_)
    _config["model"] = (model or "").strip() or None


def model_dir() -> Path:
    return _config["dir"] or DEFAULT_MODEL_DIR


def list_models() -> list[dict]:
    """All ``*.gguf`` files under the model folder (recursive), sorted by path.

    Multimodal projector files (``mmproj-*``) are not language models, so they
    are skipped.
    """
    root = model_dir()
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.rglob("*.gguf")):
        if "mmproj" in p.name.lower():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append(
            {
                "path": p.relative_to(root).as_posix(),
                "name": p.name,
                "size": size,
            }
        )
    return out


def _resolve_model(raw: str) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else model_dir() / p


def selected_model() -> Optional[str]:
    """The configured GGUF (relative to the folder), or the first one found."""
    if _config["model"]:
        return _config["model"]
    models = list_models()
    return models[0]["path"] if models else None


def selected_model_path() -> Optional[Path]:
    sel = selected_model()
    return _resolve_model(sel) if sel else None


def model_files_present() -> bool:
    """True if a GGUF file is selected/available and llama-server exists."""
    p = selected_model_path()
    return bool(p and p.is_file() and llama_server_exe() is not None)


def llama_server_exe() -> Optional[Path]:
    """Newest ``llama-server.exe`` under runtime/llama_cpp/versions/."""
    if not LLAMA_ROOT.is_dir():
        return None
    best: tuple[int, Optional[Path]] = (-1, None)
    for d in LLAMA_ROOT.iterdir():
        exe = d / "llama-server.exe"
        if not exe.is_file():
            continue
        m = re.match(r"b(\d+)", d.name)
        build = int(m.group(1)) if m else 0
        if build > best[0]:
            best = (build, exe)
    return best[1]


# ---------------------------------------------------------------------------
# Server process lifecycle
# ---------------------------------------------------------------------------
# Electron stops the backend with a hard kill (TerminateProcess), which skips
# ``atexit``. To make sure llama-server never outlives us, every child is put
# in a Windows Job Object flagged "kill on job close": the job handle dies
# with this process, and the OS then terminates the child for us.
_job_handle = None


def _make_job():
    global _job_handle
    if os.name != "nt" or _job_handle is not None:
        return _job_handle
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMIT),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JobObjectExtendedLimitInformation = 9
    h = k32.CreateJobObjectW(None, None)
    if not h:
        return None
    info = EXTENDED_LIMIT()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(
        h, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    ):
        k32.CloseHandle(h)
        return None
    _job_handle = h
    return h


def _attach_to_job(proc: subprocess.Popen) -> None:
    h = _make_job()
    if h is None:
        return
    import ctypes

    ctypes.windll.kernel32.AssignProcessToJobObject(h, int(proc._handle))


def _alive() -> bool:
    proc = _state["proc"]
    return proc is not None and proc.poll() is None


def _base_url() -> str:
    return f"http://{HOST}:{PORT}"


def _http(path: str, payload: Optional[dict] = None, timeout: float = 5.0):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        _base_url() + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def _server_ready() -> bool:
    try:
        return _http("/health", timeout=2).get("status") == "ok"
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return False


def load(progress: Optional[Callable[[str], None]] = None):
    """Start llama-server with the selected GGUF (once) and wait until ready."""
    if _alive() and _state["ready"]:
        return _state

    def log(msg: str) -> None:
        if progress:
            progress(msg)

    exe = llama_server_exe()
    if exe is None:
        raise FileNotFoundError(f"llama-server.exe not found under {LLAMA_ROOT}")
    model = selected_model_path()
    if model is None or not model.is_file():
        raise FileNotFoundError(f"No GGUF model file selected in {model_dir()}")

    _kill()  # a stale/dead process from a previous attempt

    log(f"Starting llama-server ({exe.parent.name}) with {model.name} ...")
    args = [
        str(exe),
        "-m", str(model),
        "--host", HOST,
        "--port", str(PORT),
        "-ngl", "99",
        "-c", str(CONTEXT_SIZE),
        "--no-webui",
    ]
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        args,
        cwd=str(exe.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation,
    )
    _attach_to_job(proc)
    _state.update(proc=proc, model_path=model, ready=False)

    deadline = time.time() + READY_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            _state.update(proc=None, model_path=None, ready=False)
            raise RuntimeError(
                f"llama-server exited with code {proc.returncode} while loading {model.name}"
            )
        if _server_ready():
            _state["ready"] = True
            log("Suggestion model ready.")
            return _state
        time.sleep(0.5)

    _kill()
    raise TimeoutError(f"llama-server did not become ready within {READY_TIMEOUT}s")


def _kill() -> None:
    proc = _state["proc"]
    _state.update(proc=None, model_path=None, ready=False)
    if proc is None:
        return
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


def is_loaded() -> bool:
    """True if the llama-server process is running and ready."""
    return _alive() and _state["ready"]


def loaded_model() -> Optional[str]:
    return _state["model_path"].name if _state["model_path"] else None


def preload(progress: Optional[Callable[[str], None]] = None):
    """Eagerly start the server (thread-safe), e.g. from a UI toggle."""
    with _lock:
        return load(progress)


def unload() -> None:
    """Stop the server, freeing its VRAM (thread-safe)."""
    with _lock:
        _kill()


atexit.register(_kill)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _clean(text: str) -> str:
    """Drop reasoning blocks, take the first non-empty line, strip quotes."""
    text = _THINK_RE.sub("", text or "")
    line = next((l.strip() for l in text.splitlines() if l.strip()), text.strip())
    if len(line) >= 2 and line[0] in "\"'" and line[-1] == line[0]:
        line = line[1:-1].strip()
    return line


def _chat(system: str, user: str, max_new_tokens: int) -> str:
    """Run a single system+user turn and return the reply text."""
    with _lock:
        load()
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_new_tokens,
            "temperature": 0,
            # Qwen3-style models think by default; we want the answer only.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        res = _http("/v1/chat/completions", payload, timeout=120)
        return res["choices"][0]["message"].get("content") or ""


def suggest(idea: str, max_new_tokens: int = 64) -> str:
    """Return a single English sound-effect prompt for ``idea``."""
    idea = (idea or "").strip()
    if not idea:
        return ""
    return _clean(_chat(SYSTEM_PROMPT, idea, max_new_tokens))


def make_title(prompt: str, max_new_tokens: int = 16) -> str:
    """Return a short English title summarizing ``prompt``."""
    prompt = (prompt or "").strip()
    if not prompt:
        return ""
    title = _clean(_chat(TITLE_SYSTEM_PROMPT, prompt, max_new_tokens))
    return title.rstrip(".")
