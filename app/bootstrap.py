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


def ensure_speech(size: str = "base") -> None:
    from app import speech

    if not speech.available():
        log("  Spoken-word search not installed (optional) - skipped.")
        return
    log(f"  Downloading the speech model '{size}' (about 150 MB, optional)...")
    speech._model(size)
    # the assistant's Talk button uses the more accurate 'small' model: fetch it now so the first Talk does not wait for a download
    log("  Downloading the speech model for the Talk button 'small' (about 480 MB, one time only)...")
    speech._model("small")
    log("  Speech models ready.")


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
    for name, step in (("ocr", ensure_ocr), ("objects", ensure_object_model), ("speech", ensure_speech)):
        if argv and name not in argv:
            continue
        try:
            step()
        except Exception as exc:
            failed = failed or name != "speech"
            log(f"  !! {name}: {type(exc).__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
