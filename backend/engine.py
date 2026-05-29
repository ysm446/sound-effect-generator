"""Stable Audio 3 Medium inference engine.

Loads the locally-stored model (under ``models/stable-audio-3-medium``) and
generates audio from a text prompt. The model is loaded lazily on first use and
kept resident in GPU memory. Generation is guarded by a lock because a single
GPU processes one request at a time.
"""
from __future__ import annotations

import gc
import json
import random
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# Project layout
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_ROOT / "models" / "stable-audio-3-medium"
MODEL_CONFIG_PATH = MODEL_DIR / "model_config.json"
MODEL_WEIGHTS_PATH = MODEL_DIR / "model.safetensors"
TEXT_ENCODER_DIR = MODEL_DIR / "t5gemma-b-b-ul2"

_lock = threading.Lock()
_state = {
    "model": None,
    "config": None,
    "sample_rate": None,
    "sample_size": None,
    "device": None,
}


def _select_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def model_files_present() -> tuple[bool, list[str]]:
    """Return (ok, missing_files) for a quick pre-flight check."""
    required = {
        "model_config.json": MODEL_CONFIG_PATH,
        "model.safetensors": MODEL_WEIGHTS_PATH,
        "t5gemma-b-b-ul2/config.json": TEXT_ENCODER_DIR / "config.json",
        "t5gemma-b-b-ul2/model.safetensors": TEXT_ENCODER_DIR / "model.safetensors",
        "t5gemma-b-b-ul2/tokenizer.json": TEXT_ENCODER_DIR / "tokenizer.json",
        "t5gemma-b-b-ul2/tokenizer_config.json": TEXT_ENCODER_DIR / "tokenizer_config.json",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    return (len(missing) == 0, missing)


def _patch_text_encoder_paths(config: dict) -> dict:
    """Point the t5gemma text-encoder conditioner at our local folder.

    The stable-audio-3 ``model_config.json`` loads the text encoder from a
    gated Hugging Face repo via ``repo_id`` + ``subfolder``. The
    ``T5GemmaConditioner`` prefers a ``model_path`` over ``repo_id``, and calls
    ``AutoTokenizer/AutoConfig/T5GemmaEncoderModel.from_pretrained(load_from,
    subfolder=subfolder)``. We set ``model_path`` to the local encoder folder
    and clear ``subfolder``/``repo_id`` so everything loads fully offline.
    """
    local = str(TEXT_ENCODER_DIR)
    conditioning = config.get("model", {}).get("conditioning", {})
    for cond in conditioning.get("configs", []):
        if cond.get("type") == "t5gemma":
            cfg = cond.setdefault("config", {})
            cfg["model_path"] = local
            cfg["subfolder"] = None
            cfg.pop("repo_id", None)
    return config


def load_model(progress: Optional[Callable[[str], None]] = None):
    """Load (once) and return (model, config, sample_rate, sample_size, device)."""
    if _state["model"] is not None:
        return _state

    def log(msg: str) -> None:
        if progress:
            progress(msg)

    ok, missing = model_files_present()
    if not ok:
        raise FileNotFoundError(
            "Missing model files:\n  - " + "\n  - ".join(missing)
        )

    import torch
    from stable_audio_tools.models.factory import create_model_from_config
    from stable_audio_tools.models.utils import load_ckpt_state_dict

    # Triton isn't available on Windows, so torch.compile of flex_attention
    # cannot lower to a Triton kernel. Fall back to eager silently instead of
    # spewing a multi-page "WON'T CONVERT" traceback on every generation.
    import torch._dynamo
    torch._dynamo.config.suppress_errors = True

    device = _select_device()
    log(f"Using device: {device}")

    log("Reading model_config.json ...")
    with open(MODEL_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    config = _patch_text_encoder_paths(config)

    log("Building model from config ...")
    model = create_model_from_config(config)

    log("Loading weights (model.safetensors) ...")
    state_dict = load_ckpt_state_dict(str(MODEL_WEIGHTS_PATH))
    model.load_state_dict(state_dict, strict=False)
    del state_dict
    gc.collect()

    log("Moving model to device ...")
    model = model.to(device).eval().requires_grad_(False)
    if device == "cuda":
        model = model.to(torch.float16)

    _state.update(
        model=model,
        config=config,
        sample_rate=config["sample_rate"],
        sample_size=config["sample_size"],
        device=device,
    )
    log("Model ready.")
    return _state


def generate(
    prompt: str,
    seconds: float = 8.0,
    steps: int = 8,
    cfg_scale: float = 1.0,
    negative_prompt: Optional[str] = None,
    seed: int = -1,
    out_path: Optional[Path] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> Path:
    """Generate audio for ``prompt`` and write a WAV file to ``out_path``.

    Returns the path to the written WAV file. Thread-safe: serialized by a lock
    so concurrent jobs run one at a time on the GPU.
    """
    import torch
    import soundfile as sf
    from einops import rearrange

    with _lock:
        st = load_model(progress)
        model = st["model"]
        sample_rate = st["sample_rate"]
        sample_size = st["sample_size"]
        device = st["device"]

        # Clamp requested duration to the model's max sample window.
        max_seconds = sample_size / sample_rate
        seconds = max(1.0, min(float(seconds), max_seconds))

        conditioning = [{"prompt": prompt, "seconds_total": seconds}]
        negative_conditioning = (
            [{"prompt": negative_prompt, "seconds_total": seconds}]
            if negative_prompt
            else None
        )

        if progress:
            progress(f"Generating {seconds:.1f}s, {steps} steps ...")

        # stable-audio-tools >=0.0.20 ships the inpaint-capable sampler which
        # also performs plain conditional generation.
        try:
            from stable_audio_tools.inference.generation import (
                generate_diffusion_cond_inpaint as _gen,
            )
        except ImportError:  # older fallback
            from stable_audio_tools.inference.generation import (
                generate_diffusion_cond as _gen,
            )

        # Always pass an explicit, valid seed. stable-audio-tools' own random
        # path uses ``np.random.randint(0, 2**32 - 1)``, which raises
        # "high is out of bounds for int32" on Windows (NumPy's default int is
        # int32 there). Picking the seed ourselves avoids that broken path and
        # lets seed=-1 mean "random".
        if seed is None or seed < 0:
            seed = random.randint(0, 2**31 - 1)

        gen_kwargs = dict(
            steps=steps,
            cfg_scale=cfg_scale,
            conditioning=conditioning,
            negative_conditioning=negative_conditioning,
            sample_size=int(seconds * sample_rate),
            sampler_type="pingpong",
            device=device,
            seed=int(seed),
        )

        t0 = time.time()
        with torch.no_grad():
            audio = _gen(model, **gen_kwargs)
        elapsed = time.time() - t0

        # (batch, channels, samples) -> (channels, samples)
        audio = rearrange(audio, "b d n -> d (b n)")
        audio = (
            audio.to(torch.float32)
            .div(torch.max(torch.abs(audio)).clamp(min=1e-8))
            .clamp(-1, 1)
            .cpu()
        )

        if out_path is None:
            out_path = PROJECT_ROOT / "data" / f"sfx_{int(time.time())}.wav"
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # soundfile expects (frames, channels); our tensor is (channels, frames).
        sf.write(str(out_path), audio.transpose(0, 1).numpy(), sample_rate, subtype="PCM_16")

        if progress:
            progress(f"Done in {elapsed:.1f}s -> {out_path.name}")
        return out_path
