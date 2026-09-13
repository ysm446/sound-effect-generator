"""MCP (Model Context Protocol) server exposing the Sound Effect Generator.

Lets an LLM client (Claude Code, Claude Desktop, ...) call
``generate_sound_effect`` as a tool. The heavy lifting is delegated to
``cli.py``: the HTTP backend is started on demand, the job is polled until it
finishes and the resulting WAV path is returned. Transport is stdio. Requires ``mcp>=2`` (``MCPServer`` API).

Register in Claude Code from the project root (``.mcp.json`` already does this):

    claude mcp add sfx -- .venv/Scripts/python.exe backend/mcp_server.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from mcp.server.mcpserver import MCPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cli  # noqa: E402

mcp = MCPServer(
    "sound-effect-generator",
    instructions=(
        "Generates sound effects locally from a text description with Stable Audio 3. "
        "The first call may take a minute while the backend starts and loads the model; "
        "it then stays resident and shuts itself down after 10 idle minutes. "
        "Write prompts in English, concrete and sensory (material, action, space), e.g. "
        "'heavy wooden door slamming shut in a stone hallway'."
    ),
)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


@mcp.tool()
def generate_sound_effect(
    prompt: str,
    seconds: float = 8.0,
    steps: int = 8,
    cfg_scale: float = 1.0,
    negative_prompt: Optional[str] = None,
    seed: int = -1,
) -> dict:
    """Generate a sound effect and return the absolute path of the WAV file.

    Blocks until generation finishes (typically a few seconds once the model is
    loaded). Starts the local backend if it is not running. ``seed=-1`` picks a
    random seed; the seed actually used is returned so the result can be
    reproduced. ``seconds`` is capped by the model (about 47 s).
    """
    try:
        job = cli.generate(
            prompt,
            seconds=seconds,
            steps=steps,
            cfg_scale=cfg_scale,
            negative_prompt=negative_prompt,
            seed=seed,
            log=_log,
        )
    except cli.CliError as exc:
        return {"error": str(exc)}
    return {
        "job_id": job["id"],
        "path": job["path"],
        "prompt": job["prompt"],
        "seconds": job["seconds"],
        "seed": job["seed"],
        "title": job.get("title"),
    }


@mcp.tool()
def list_sound_effects(limit: int = 20) -> list[dict]:
    """List recently generated sound effects (newest first) with their WAV paths."""
    try:
        cli.ensure_backend(_log)
        jobs = cli.list_jobs(limit)
    except cli.CliError as exc:
        return [{"error": str(exc)}]
    return [
        {
            "job_id": j["id"],
            "status": j["status"],
            "prompt": j["prompt"],
            "seconds": j["seconds"],
            "seed": j["seed"],
            "title": j.get("title"),
            "path": j.get("path"),
        }
        for j in jobs
    ]


@mcp.tool()
def backend_status() -> dict:
    """Report whether the local generation backend is running and which model is loaded."""
    try:
        return cli.status()
    except cli.CliError as exc:
        return {"error": str(exc)}


@mcp.tool()
def stop_backend() -> dict:
    """Shut down the local generation backend now to free GPU memory.

    Not required: the backend exits by itself after 10 idle minutes. Refused
    while a job is still queued or running.
    """
    try:
        return {"stopped": cli.stop_backend()}
    except cli.CliError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
