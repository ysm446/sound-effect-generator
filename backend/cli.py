"""Command-line front-end for the Sound Effect Generator.

Talks to the same local HTTP API the Electron UI uses (``backend/server.py`` on
``127.0.0.1:8765``). If the backend is not running it is started in the
background with the project's ``.venv`` Python and left running afterwards, so
a sequence of calls only pays the model-load cost once. It exits on its own
after ``SFX_IDLE_TIMEOUT`` seconds (default 600) without requests or jobs;
``sfx stop`` shuts it down immediately.

Only the standard library is used so this file can be imported by the MCP
server (``mcp_server.py``) and run on its own.

Examples::

    sfx generate "glass shattering on a tile floor" --seconds 4
    sfx generate "door creak" --json
    sfx list --limit 5
    sfx status
    sfx stop
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
SERVER_SCRIPT = PROJECT_ROOT / "backend" / "server.py"
SERVER_LOG = PROJECT_ROOT / "cli-server.log"

HOST = os.environ.get("SFX_HOST", "127.0.0.1")
PORT = int(os.environ.get("SFX_PORT", "8765"))
BASE = f"http://{HOST}:{PORT}"

# A backend we spawn exits by itself after this many idle seconds (no requests,
# no jobs) so the model does not sit in VRAM forever. 0 disables.
IDLE_TIMEOUT = float(os.environ.get("SFX_IDLE_TIMEOUT", "600"))
START_TIMEOUT = 120.0  # seconds to wait for /api/health after spawning
POLL_INTERVAL = 0.5


class CliError(RuntimeError):
    """A user-facing failure (backend refused, timeout, ...)."""


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _request(method: str, path: str, body: Optional[dict] = None, timeout: float = 10.0) -> Any:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw).get("detail", raw.decode("utf-8", "replace"))
        except (ValueError, AttributeError):
            detail = raw.decode("utf-8", "replace")
        raise CliError(f"HTTP {exc.code} {path}: {detail}") from None
    return json.loads(raw) if raw else None


def backend_alive() -> bool:
    try:
        _request("GET", "/api/health", timeout=2.0)
        return True
    except (CliError, urllib.error.URLError, OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Backend lifecycle
# ---------------------------------------------------------------------------
def start_backend() -> None:
    """Spawn ``server.py`` detached so it outlives this CLI process."""
    if not PYTHON_EXE.exists():
        raise CliError(f"venv Python not found: {PYTHON_EXE}")
    log = open(SERVER_LOG, "ab")  # noqa: SIM115 - handed to the child
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [
            str(PYTHON_EXE), str(SERVER_SCRIPT),
            "--host", HOST, "--port", str(PORT),
            "--idle-timeout", str(IDLE_TIMEOUT),
        ],
        cwd=str(SERVER_SCRIPT.parent),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        close_fds=True,
        **kwargs,
    )


def ensure_backend(log=None) -> bool:
    """Return True if the backend was already running, False if we started it."""
    if backend_alive():
        return True
    if log:
        log("backend not running; starting it...")
    start_backend()
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        if backend_alive():
            return False
        time.sleep(POLL_INTERVAL)
    raise CliError(f"backend did not answer within {START_TIMEOUT:.0f}s (see {SERVER_LOG})")


def stop_backend() -> bool:
    """Ask the backend to exit. Returns False if it was not running."""
    if not backend_alive():
        return False
    _request("POST", "/api/shutdown")
    deadline = time.time() + 15
    while time.time() < deadline:
        if not backend_alive():
            return True
        time.sleep(POLL_INTERVAL)
    raise CliError("backend acknowledged shutdown but is still answering")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
def _resolve_path(job: dict) -> Optional[str]:
    if not job.get("filename"):
        return None
    health = _request("GET", "/api/health")
    return str(Path(health["data_dir"]) / job["filename"])


def generate(
    prompt: str,
    seconds: float = 8.0,
    steps: int = 8,
    cfg_scale: float = 1.0,
    negative_prompt: Optional[str] = None,
    seed: int = -1,
    timeout: float = 600.0,
    log=None,
) -> dict:
    """Queue a job, wait for it to finish and return the job dict with ``path``."""
    ensure_backend(log)
    job = _request(
        "POST",
        "/api/generate",
        {
            "prompt": prompt,
            "seconds": seconds,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "negative_prompt": negative_prompt or None,
            "seed": seed,
        },
    )
    job_id = job["id"]
    if log:
        log(f"queued job {job_id}")
    last_msg = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = _request("GET", f"/api/jobs/{job_id}")
        msg = job.get("message")
        if log and msg and msg != last_msg:
            log(f"[{job['status']}] {msg}")
            last_msg = msg
        if job["status"] == "done":
            job["path"] = _resolve_path(job)
            return job
        if job["status"] == "error":
            raise CliError(f"generation failed: {job.get('message')}")
        time.sleep(POLL_INTERVAL)
    raise CliError(f"job {job_id} did not finish within {timeout:.0f}s")


def get_job(job_id: str) -> dict:
    job = _request("GET", f"/api/jobs/{job_id}")
    job["path"] = _resolve_path(job)
    return job


def list_jobs(limit: int = 20) -> list[dict]:
    jobs = _request("GET", "/api/jobs")[:limit]
    if jobs:
        data_dir = Path(_request("GET", "/api/health")["data_dir"])
        for j in jobs:
            j["path"] = str(data_dir / j["filename"]) if j.get("filename") else None
    return jobs


def status() -> dict:
    if not backend_alive():
        return {"running": False}
    return {"running": True, **_request("GET", "/api/health")}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _print(obj: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(obj)


def main(argv: Optional[list[str]] = None) -> int:
    # ``--json`` is defined on a parent parser so it is accepted both before and
    # after the sub-command (``sfx --json list`` / ``sfx list --json``).
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS so a sub-command's copy of the flag never overwrites the
    # top-level one with its default.
    common.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS,
        help="print machine-readable JSON",
    )
    parser = argparse.ArgumentParser(
        prog="sfx", parents=[common], description=__doc__.split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name: str, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    g = add("generate", help="generate a sound effect and print the WAV path")
    g.add_argument("prompt")
    g.add_argument("--seconds", type=float, default=8.0)
    g.add_argument("--steps", type=int, default=8)
    g.add_argument("--cfg-scale", type=float, default=1.0)
    g.add_argument("--negative", default=None, help="negative prompt")
    g.add_argument("--seed", type=int, default=-1, help="-1 = random")
    g.add_argument("--timeout", type=float, default=600.0)

    add("status", help="show whether the backend is running")
    add("start", help="start the backend if it is not running")
    add("stop", help="shut the backend down")
    ls = add("list", help="list recent jobs")
    ls.add_argument("--limit", type=int, default=20)
    gj = add("get", help="show one job")
    gj.add_argument("job_id")

    args = parser.parse_args(argv)
    args.json = getattr(args, "json", False)
    try:
        if args.cmd == "generate":
            job = generate(
                args.prompt,
                seconds=args.seconds,
                steps=args.steps,
                cfg_scale=args.cfg_scale,
                negative_prompt=args.negative,
                seed=args.seed,
                timeout=args.timeout,
                log=None if args.json else _log,
            )
            _print(job if args.json else job["path"], args.json)
        elif args.cmd == "status":
            st = status()
            _print(st if args.json else ("running" if st["running"] else "stopped"), args.json)
        elif args.cmd == "start":
            was_running = ensure_backend(None if args.json else _log)
            _print({"running": True, "started": not was_running} if args.json
                   else ("already running" if was_running else "started"), args.json)
        elif args.cmd == "stop":
            stopped = stop_backend()
            _print({"stopped": stopped} if args.json
                   else ("stopped" if stopped else "not running"), args.json)
        elif args.cmd == "list":
            jobs = list_jobs(args.limit)
            if args.json:
                _print(jobs, True)
            else:
                for j in jobs:
                    print(f"{j['id']}  {j['status']:7}  {j['seconds']:>5.1f}s  {j['prompt']}")
        elif args.cmd == "get":
            _print(get_job(args.job_id), True)
    except CliError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}), file=sys.stdout)
        else:
            _log(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
