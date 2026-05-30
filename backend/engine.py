"""Stable Audio 3 inference engine (multi-model).

Loads one of the locally-stored Stable Audio 3 models (medium / small-sfx) and
generates audio from a text prompt. All models share the same t5gemma text
encoder, so only one copy of it is needed on disk. The selected model is loaded
lazily on first use and kept resident in GPU memory; switching to another model
frees the previous one. Generation is serialized by a lock (single GPU).
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
MODELS_DIR = PROJECT_ROOT / "models"

# Selectable models. All variants use the same t5gemma-b-b-ul2 text encoder,
# which we share from whichever model directory has it (no need to duplicate).
MODELS: dict[str, dict] = {
    "stable-audio-3-medium": {
        "label": "Medium (general, 2B)",
        "dir": MODELS_DIR / "stable-audio-3-medium",
    },
    "stable-audio-3-small-music": {
        "label": "Small Music (music, 0.6B)",
        "dir": MODELS_DIR / "stable-audio-3-small-music",
    },
    "stable-audio-3-small-sfx": {
        "label": "Small SFX (sound-effects, 0.6B)",
        "dir": MODELS_DIR / "stable-audio-3-small-sfx",
    },
}
DEFAULT_MODEL = "stable-audio-3-medium"

_lock = threading.Lock()
_state = {
    "model": None,
    "key": None,
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


def _model_dir(key: str) -> Path:
    return MODELS[key]["dir"]


def _resolve_text_encoder(model_dir: Path) -> Path:
    """Find a usable t5gemma-b-b-ul2 folder. Prefer the model's own subfolder,
    otherwise reuse one from any sibling model (or a shared top-level folder),
    so the encoder doesn't have to be downloaded/duplicated per model."""
    candidates = [model_dir / "t5gemma-b-b-ul2"]
    candidates += [m["dir"] / "t5gemma-b-b-ul2" for m in MODELS.values()]
    candidates.append(MODELS_DIR / "t5gemma-b-b-ul2")
    for c in candidates:
        if (c / "config.json").exists():
            return c
    return model_dir / "t5gemma-b-b-ul2"


def available_models() -> list[dict]:
    """List registered models and whether each one's files are present."""
    out = []
    for key, info in MODELS.items():
        ok, _ = model_files_present(key)
        out.append({"key": key, "label": info["label"], "present": ok})
    return out


def model_files_present(key: str) -> tuple[bool, list[str]]:
    """Return (ok, missing_files) for the given model key."""
    if key not in MODELS:
        return (False, [f"unknown model: {key}"])
    mdir = _model_dir(key)
    te = _resolve_text_encoder(mdir)
    required = {
        "model_config.json": mdir / "model_config.json",
        "model.safetensors": mdir / "model.safetensors",
        "t5gemma-b-b-ul2/config.json": te / "config.json",
        "t5gemma-b-b-ul2/model.safetensors": te / "model.safetensors",
        "t5gemma-b-b-ul2/tokenizer.json": te / "tokenizer.json",
        "t5gemma-b-b-ul2/tokenizer_config.json": te / "tokenizer_config.json",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    return (len(missing) == 0, missing)


def _patch_text_encoder_paths(config: dict, model_dir: Path) -> dict:
    """Point the t5gemma text-encoder conditioner at our local (shared) folder.

    The stable-audio-3 ``model_config.json`` loads the text encoder from a
    gated Hugging Face repo via ``repo_id`` + ``subfolder``. The
    ``T5GemmaConditioner`` prefers a ``model_path`` over ``repo_id``, and calls
    ``from_pretrained(load_from, subfolder=subfolder)``. We set ``model_path``
    to the resolved local encoder folder and clear ``subfolder``/``repo_id`` so
    everything loads fully offline.
    """
    local = str(_resolve_text_encoder(model_dir))
    conditioning = config.get("model", {}).get("conditioning", {})
    for cond in conditioning.get("configs", []):
        if cond.get("type") == "t5gemma":
            cfg = cond.setdefault("config", {})
            cfg["model_path"] = local
            cfg["subfolder"] = None
            cfg.pop("repo_id", None)
    return config


def _free_model() -> None:
    """Release the currently loaded model from memory / VRAM."""
    if _state["model"] is None:
        return
    _state["model"] = None
    _state["key"] = None
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def is_loaded() -> bool:
    """True if a Stable Audio model is currently resident in memory."""
    return _state["model"] is not None


def unload() -> None:
    """Free the currently loaded model (thread-safe)."""
    with _lock:
        _free_model()


def load_model(key: str, progress: Optional[Callable[[str], None]] = None):
    """Load (once) the requested model, swapping out any other loaded model."""
    if _state["model"] is not None and _state["key"] == key:
        return _state

    def log(msg: str) -> None:
        if progress:
            progress(msg)

    if key not in MODELS:
        raise ValueError(f"unknown model: {key}")

    ok, missing = model_files_present(key)
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

    # Free any previously loaded (different) model before loading the new one.
    if _state["model"] is not None:
        log(f"Unloading {_state['key']} ...")
        _free_model()

    mdir = _model_dir(key)
    device = _select_device()
    log(f"Using device: {device}")

    log("Reading model_config.json ...")
    with open(mdir / "model_config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    config = _patch_text_encoder_paths(config, mdir)

    log("Building model from config ...")
    model = create_model_from_config(config)

    log("Loading weights (model.safetensors) ...")
    state_dict = load_ckpt_state_dict(str(mdir / "model.safetensors"))
    model.load_state_dict(state_dict, strict=False)
    del state_dict
    gc.collect()

    log("Moving model to device ...")
    model = model.to(device).eval().requires_grad_(False)
    if device == "cuda":
        model = model.to(torch.float16)

    _state.update(
        model=model,
        key=key,
        config=config,
        sample_rate=config["sample_rate"],
        sample_size=config["sample_size"],
        device=device,
    )
    log("Model ready.")
    return _state


def preload(key: str, progress: Optional[Callable[[str], None]] = None):
    """Eagerly load ``key`` into memory (thread-safe), e.g. from a UI toggle."""
    with _lock:
        return load_model(key, progress)


def generate(
    prompt: str,
    seconds: float = 8.0,
    steps: int = 8,
    cfg_scale: float = 1.0,
    negative_prompt: Optional[str] = None,
    seed: int = -1,
    out_path: Optional[Path] = None,
    progress: Optional[Callable[[str], None]] = None,
    model_key: str = DEFAULT_MODEL,
) -> tuple[Path, int]:
    """Generate audio for ``prompt`` and write a WAV file to ``out_path``.

    Returns ``(path, seed)`` where ``seed`` is the actual seed used (a real
    value even when -1/random was requested). Thread-safe: serialized by a lock
    so concurrent jobs run one at a time on the GPU.
    """
    import torch
    import soundfile as sf
    from einops import rearrange

    with _lock:
        st = load_model(model_key, progress)
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
        return out_path, int(seed)
