# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Download everything Fathom needs once, so searches never stall waiting for a model."""
from __future__ import annotations

import sys


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_ocr() -> None:
    from app.ocr import get_engine

    get_engine()
    log("  Text-in-pictures reader (OCR) ready.")


def ensure_object_model() -> None:
    from app.detect import model_paths

    log("  Downloading the object-search model (about 600 MB, one time only)...")
    paths = model_paths(download=True)
    log("  Object-search model ready: " + ", ".join(p.name for p in paths.values()))


def _whisper_sizes() -> list[str]:
    import os

    raw = os.environ.get("FATHOM_WHISPER", "").strip().lower()
    from app.speech import WHISPER_SIZES

    if raw == "all":
        return list(WHISPER_SIZES)
    if raw:
        return [x for x in (t.strip() for t in raw.replace(";", ",").split(",")) if x in WHISPER_SIZES]
    if os.environ.get("FATHOM_LITE") == "1":
        return ["tiny", "base", "small"]
    return list(WHISPER_SIZES)   # Full install: every speech model, so nothing ever says "downloading the speech model" later


def ensure_speech(size: str = "") -> None:
    from app import speech

    if not speech.available():
        log("  Spoken-word search not installed (optional) - skipped.")
        return
    sizes = [size] if size else _whisper_sizes()
    bad = []
    for sz in sizes:
        log(f"  Downloading the speech model '{sz}' (one time only)...")
        try:
            speech._model(sz)
        except Exception as exc:
            bad.append(sz)
            log(f"  !! speech model '{sz}' failed: {type(exc).__name__}: {exc}")
    log("  Speech models ready: " + ", ".join(x for x in sizes if x not in bad))
    if bad:
        raise RuntimeError("some speech models did not download: " + ", ".join(bad))


def ensure_faces() -> None:
    from app import reference

    if not reference.faces_supported():
        log("  Face finder not supported by this OpenCV - skipped.")
        return
    log("  Downloading the face models (about 39 MB)...")
    reference.ensure_face_models(lambda m: log("  " + m))
    log("  Face models ready.")


def ensure_handwriting() -> None:
    import importlib.util
    import os
    import subprocess

    from app.paths import models_dir

    if os.environ.get("FATHOM_LITE") == "1":
        log("  Offline handwriting reader skipped (Lite).")
        return

    def has(m):
        return importlib.util.find_spec(m) is not None

    def pip(*args):
        subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *args], check=True)

    if not has("torch"):
        log("  Installing the handwriting engine (torch, about 200 MB)...")
        pip("torch", "--index-url", "https://download.pytorch.org/whl/cpu")
    if not has("transformers") or not has("sentencepiece"):
        log("  Installing the handwriting model loader...")
        pip("transformers", "sentencepiece")
    from huggingface_hub import snapshot_download

    from app.handwriting import TROCR_NAME, TROCR_SMALL

    for name in (TROCR_NAME, TROCR_SMALL):
        log(f"  Downloading the handwriting model {name} ...")
        try:
            snapshot_download(name, cache_dir=str(models_dir() / "trocr"))
            break
        except Exception as exc:
            log(f"  !! {name}: {exc}")
    else:
        raise RuntimeError("handwriting model did not download")
    log("  Offline handwriting reader ready.")


def make_icon(path: str) -> None:
    """A little magnifier: yellow lens, red ring (the same colours Fathom uses to mark matches)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.line([(168, 168), (228, 228)], fill=(34, 38, 46, 255), width=30)
    d.ellipse([20, 20, 200, 200], fill=(255, 235, 59, 255), outline=(232, 62, 40, 255), width=18)
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--icon":
        make_icon(argv[1])
        return 0
    failed = False
    for name, step in (("ocr", ensure_ocr), ("objects", ensure_object_model), ("faces", ensure_faces), ("speech", ensure_speech), ("handwriting", ensure_handwriting)):
        if argv and name not in argv:
            continue
        try:
            step()
        except Exception as exc:
            failed = failed or name not in ("speech", "handwriting")
            log(f"  !! {name}: {type(exc).__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
