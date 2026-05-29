"""Quick end-to-end check: load the model and generate one short sound effect."""
import sys
import time

import engine


def main():
    ok, missing = engine.model_files_present()
    print("model_files_present:", ok, "missing:", missing)
    if not ok:
        sys.exit(1)

    t0 = time.time()
    out = engine.generate(
        prompt="Heavy wooden door creaking open slowly",
        seconds=5.0,
        steps=8,
        cfg_scale=1.0,
        seed=42,
        progress=lambda m: print(f"[progress] {m}  (+{time.time()-t0:.1f}s)"),
    )
    print("WROTE:", out, "exists:", out.exists(), "bytes:", out.stat().st_size)


if __name__ == "__main__":
    main()
