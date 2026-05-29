"""Prompt suggestion via a local Qwen3.5-2B instruct model.

Turns a rough idea (any language) into a concise English sound-effect prompt
suitable for Stable Audio. The model is loaded lazily on first use and kept
resident in GPU memory (it shares the GPU with the Stable Audio model; with a
48GB card both fit comfortably). Generation is serialized by a lock.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_ROOT / "models" / "Qwen3.5-2B"

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
    "model": None,
    "tokenizer": None,
    "device": None,
}


def model_files_present() -> bool:
    """True if the Qwen model directory looks complete enough to load."""
    required = ["config.json", "tokenizer.json", "tokenizer_config.json"]
    if not all((MODEL_DIR / f).exists() for f in required):
        return False
    # The weights may be sharded or single-file.
    return any(MODEL_DIR.glob("*.safetensors")) or any(
        MODEL_DIR.glob("*.safetensors-*")
    )


def _select_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load(progress: Optional[Callable[[str], None]] = None):
    """Load the model once and keep it resident."""
    if _state["model"] is not None:
        return _state

    def log(msg: str) -> None:
        if progress:
            progress(msg)

    if not model_files_present():
        raise FileNotFoundError(f"Qwen model files not found in {MODEL_DIR}")

    import torch
    from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration

    device = _select_device()
    log(f"Loading suggestion model on {device} ...")
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    model = Qwen3_5ForConditionalGeneration.from_pretrained(
        str(MODEL_DIR),
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
    )
    model = model.to(device).eval()

    _state.update(model=model, tokenizer=tokenizer, device=device)
    log("Suggestion model ready.")
    return _state


def _clean(text: str) -> str:
    """Take the first non-empty line and strip wrapping quotes/labels."""
    line = next((l.strip() for l in text.splitlines() if l.strip()), text.strip())
    if len(line) >= 2 and line[0] in "\"'" and line[-1] == line[0]:
        line = line[1:-1].strip()
    return line


def _chat(system: str, user: str, max_new_tokens: int) -> str:
    """Run a single system+user turn and return the decoded reply text."""
    import torch

    with _lock:
        st = load()
        model = st["model"]
        tok = st["tokenizer"]

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        inputs = tok.apply_chat_template(
            messages,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        ).to(model.device)
        prompt_len = inputs["input_ids"].shape[1]

        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False
            )
        return tok.decode(out[0][prompt_len:], skip_special_tokens=True)


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
