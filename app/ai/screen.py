"""Live screen watching for the assistant. Off until the user presses "Watch my screen".

While it is on, every message the user sends carries a fresh picture of the screen, and the assistant
may call look_at_screen whenever it wants to see what is happening (for example while a job runs).
Nothing is recorded or saved: pictures are held in memory only for the chat.
"""
from __future__ import annotations

import base64
import io
import threading
import time

_state = {"on": False, "since": 0.0}
_lock = threading.Lock()


def is_on() -> bool:
    return _state["on"]


def set_on(on: bool) -> dict:
    with _lock:
        _state["on"] = bool(on)
        _state["since"] = time.time() if on else 0.0
    return state()


def state() -> dict:
    ok, why = available()
    return {"on": _state["on"], "available": ok, "why": why}


def available() -> tuple[bool, str]:
    try:
        from PIL import ImageGrab  # noqa: F401
    except Exception:
        return False, "Screen capture needs the Pillow package."
    import os, sys
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False, "No screen is available on this system."
    return True, ""


def grab(max_side: int = 1568, quality: int = 72) -> dict:
    """{'media_type','data'(base64 jpeg),'width','height'} of the whole desktop (every monitor)."""
    ok, why = available()
    if not ok:
        raise RuntimeError(why)
    from PIL import Image, ImageGrab
    try:
        im = ImageGrab.grab(all_screens=True)
    except TypeError:
        im = ImageGrab.grab()
    except Exception as exc:
        raise RuntimeError(f"Could not capture the screen ({exc}).")
    im = im.convert("RGB")
    w, h = im.size
    s = max_side / max(w, h)
    if s < 1:
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return {"media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode(), "width": im.width, "height": im.height}
