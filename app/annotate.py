"""Draw the yellow highlight + circle on pictures, and make thumbnails."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # no size limits

YELLOW = (255, 235, 59)
RED = (232, 62, 40)
Box = tuple[float, float, float, float]


def to_rgb(image: Image.Image) -> Image.Image:
    """Any PIL image -> plain RGB (transparency goes onto white, 16-bit scaled down)."""
    im = image
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        return bg.convert("RGB")
    if im.mode in ("I;16", "I;16L", "I;16B", "I", "F"):
        arr = np.asarray(im).astype(np.float32)
        top = float(arr.max()) or 1.0
        return Image.fromarray((arr / top * 255.0).astype(np.uint8)).convert("RGB")
    return im.convert("RGB")


def _clamp_box(raw, width: int, height: int, min_size: float = 8.0) -> Box | None:
    x0, y0, x1, y1 = [float(v) for v in raw]
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    if x1 - x0 < min_size:
        mid = (x0 + x1) / 2
        x0, x1 = mid - min_size / 2, mid + min_size / 2
    if y1 - y0 < min_size:
        mid = (y0 + y1) / 2
        y0, y1 = mid - min_size / 2, mid + min_size / 2
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(float(width), x1), min(float(height), y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _arrow_for(cx: float, cy: float, rx: float, ry: float, width: int, height: int, taken: list, scale: float):
    """Tail and tip of an arrow that points at the circle from the free side (inside the picture, away from other arrows)."""
    length = 70.0 * scale
    best, best_score = None, -1e9
    for deg in (225, 315, 135, 45, 270, 180, 0, 90, 202, 248, 292, 338, 158, 112, 68, 22):
        dx, dy = float(np.cos(np.radians(deg))), float(-np.sin(np.radians(deg)))
        # tip touches the circle edge, tail is `length` further out
        tip = (cx + dx * (rx + 4 * scale), cy + dy * (ry + 4 * scale))
        tail = (tip[0] + dx * length, tip[1] + dy * length)
        inside = min(tail[0], width - tail[0], tail[1], height - tail[1])
        crowd = min([np.hypot(tail[0] - t[0], tail[1] - t[1]) for t in taken] or [1e9])
        score = min(inside, 0.0) * 4 + min(crowd, 200.0) * 0.5 + (4 if deg == 225 else 0)
        if score > best_score:
            best, best_score = (tail, tip), score
    tail, tip = best
    tail = (min(max(tail[0], 4), width - 5), min(max(tail[1], 4), height - 5))
    taken.append(tail)
    return tail, tip


def annotate_array(arr: np.ndarray, boxes, mode: str = "text", arrows: bool = False) -> np.ndarray:
    """arr is an RGB uint8 array. Returns a new array with highlight + circle drawn (and an arrow to each one when asked)."""
    out = arr.copy()
    height, width = out.shape[:2]
    scale = max(1.0, max(width, height) / 1100.0)
    thick = max(2, int(round(2.6 * scale)))
    taken: list = []
    for raw in boxes:
        box = _clamp_box(raw, width, height)
        if box is None:
            continue
        x0, y0, x1, y1 = [int(round(v)) for v in box]
        x1, y1 = max(x1, x0 + 1), max(y1, y0 + 1)
        region = out[y0:y1, x0:x1].astype(np.float32)
        if mode == "text" and region.mean() > 110:
            # real highlighter look: black text stays black, white paper turns yellow
            region = region * (np.array(YELLOW, dtype=np.float32) / 255.0)
        else:
            alpha = 0.50 if mode == "text" else 0.30
            region = region * (1 - alpha) + np.array(YELLOW, dtype=np.float32) * alpha
        out[y0:y1, x0:x1] = np.clip(region, 0, 255).astype(np.uint8)
        if mode == "object":
            cv2.rectangle(out, (x0, y0), (x1, y1), YELLOW, thick, cv2.LINE_AA)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        pad = 6.0 * scale
        rx = (x1 - x0) / 2.0 * 1.45 + pad
        ry = (y1 - y0) / 2.0 * 1.45 + pad
        cv2.ellipse(out, (int(round(cx)), int(round(cy))), (int(round(rx)), int(round(ry))), 0, 0, 360, RED, thick, cv2.LINE_AA)
        if arrows:
            tail, tip = _arrow_for(cx, cy, rx, ry, width, height, taken, scale)
            p0, p1 = (int(tail[0]), int(tail[1])), (int(tip[0]), int(tip[1]))
            tipl = 0.38
            cv2.arrowedLine(out, p0, p1, YELLOW, thick * 3, cv2.LINE_AA, tipLength=tipl)
            cv2.arrowedLine(out, p0, p1, RED, thick * 3 - max(2, thick), cv2.LINE_AA, tipLength=tipl)
    return out


def annotate(image: Image.Image, boxes, mode: str = "text", arrows: bool = False) -> Image.Image:
    arr = np.asarray(to_rgb(image))
    return Image.fromarray(annotate_array(arr, boxes, mode, arrows))


def union_box(boxes) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def crop_thumb(image: Image.Image, box: Box, max_side: int = 520) -> Image.Image:
    """Crop around the match with generous padding (so the circle is fully visible), shaped about 16:10."""
    x0, y0, x1, y1 = [float(v) for v in box]
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    pad_x = max(90.0, w * 0.9)
    pad_y = max(70.0, h * 1.6)
    left, right = x0 - pad_x, x1 + pad_x
    top, bottom = y0 - pad_y, y1 + pad_y
    aspect = 1.6
    cw, ch = right - left, bottom - top
    if cw / ch > aspect:                    # too wide: show more rows above and below
        extra = (cw / aspect - ch) / 2
        top, bottom = top - extra, bottom + extra
    elif cw / ch < 1.0:                     # very tall: show more width
        extra = (ch - cw) / 2
        left, right = left - extra, right + extra
    cw, ch = right - left, bottom - top     # slide the window back inside the picture instead of squashing it
    if cw <= image.width:
        left = min(max(0.0, left), image.width - cw)
        right = left + cw
    if ch <= image.height:
        top = min(max(0.0, top), image.height - ch)
        bottom = top + ch
    crop = to_rgb(image.crop((int(max(0, left)), int(max(0, top)), int(min(image.width, right)), int(min(image.height, bottom)))))
    scale = max_side / max(crop.width, crop.height)
    if scale < 1:
        crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))), Image.Resampling.LANCZOS)
    return crop


def shrink_for_display(image: Image.Image, boxes, max_side: int = 4096):
    """Huge pictures are scaled down for viewing; boxes are scaled with them."""
    longest = max(image.width, image.height)
    if longest <= max_side:
        return image, list(boxes)
    s = max_side / longest
    small = image.resize((max(1, int(image.width * s)), max(1, int(image.height * s))), Image.Resampling.LANCZOS)
    return small, [(b[0] * s, b[1] * s, b[2] * s, b[3] * s) for b in boxes]


def save_image(image: Image.Image, path_no_ext, photo_like: bool) -> str:
    """Save as JPEG for photos / big images, PNG for text-like pictures. Returns the file name used."""
    base = Path(path_no_ext)
    rgb = to_rgb(image)
    if photo_like or rgb.width * rgb.height > 6_000_000:
        target = base.with_suffix(".jpg")
        rgb.save(target, "JPEG", quality=90, optimize=True)
    else:
        target = base.with_suffix(".png")
        rgb.save(target, "PNG")
    return target.name
