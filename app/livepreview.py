"""'See it before you do it': the same picture-processing the tools use, run on ONE page or picture the user chose, shown as BEFORE and AFTER."""
from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from app.service import UserError


def _png(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _load(path: str, page: int, size: int) -> tuple[Image.Image, tuple[int, int]]:
    """the chosen page/picture as an RGB picture about `size` pixels wide, and its real size"""
    from app import pdfview
    p = Path(path)
    if not p.is_file():
        raise UserError("That file was not found.")
    try:
        full = Image.open(p).size
    except Exception:
        full = (0, 0)
    data, meta = pdfview.page_png(path, page, size)
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if not full[0]:
        full = (meta.get("w", im.width), meta.get("h", im.height))
    return im, full


def make(tool: str, path: str, page: int, options: dict, size: int = 800) -> dict:
    im, full = _load(path, page, max(300, min(size, 1400)))
    k = im.width / max(1, full[0]) if full[0] else 1.0
    if tool == "touchup":
        from app.extras import touchup_image
        o = dict(options)
        if o.get("border"):
            o["border"] = max(0, round(float(o["border"]) * min(1.0, k)))
        out = touchup_image(im, o)
        if out.mode == "RGBA":
            bg = Image.new("RGB", out.size, (255, 255, 255))
            bg.paste(out, mask=out.getchannel("A"))
            out = bg
    elif tool == "scan":
        import cv2
        import numpy as np
        from app.filetools3 import clean_page, find_page_quad, flatten_page
        bgr = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
        note = "whole picture kept"
        if options.get("crop"):
            q = find_page_quad(bgr)
            if q is not None:
                bgr = flatten_page(bgr, q)
                note = "page found and straightened"
            else:
                note = "no page edges found: the whole picture is kept"
        res = clean_page(bgr, str(options.get("mode") or "magic"), bool(options.get("sharpen", True)))
        out = Image.fromarray(cv2.cvtColor(res, cv2.COLOR_GRAY2RGB) if res.ndim == 2 else cv2.cvtColor(res, cv2.COLOR_BGR2RGB))
        return {"before": _png(im), "after": _png(out), "note": note}
    else:
        raise UserError("There is no preview for this tool.")
    return {"before": _png(im), "after": _png(out), "note": ""}
