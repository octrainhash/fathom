"""Read text out of pictures (screenshots, scans, photos, video frames) with RapidOCR."""
from __future__ import annotations

import threading

import numpy as np
from PIL import Image

from app.annotate import to_rgb
from app.runtime import ML_LOCK

_engine = None
_engine_lock = threading.Lock()

TILE = 2000        # pixels per OCR tile for very large pictures
OVERLAP = 400
TILE_ABOVE = 2600  # pictures with a side longer than this are read in tiles


def get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        return _engine


def _parse(result, dx: int = 0, dy: int = 0) -> list[dict]:
    items: list[dict] = []
    for row in result or []:
        box, text, score = row[0], row[1], row[2]
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        text = str(text)
        if not text.strip():
            continue
        try:
            sc = float(score)
        except (TypeError, ValueError):
            sc = 0.0
        items.append({"text": text, "score": sc, "bbox": (min(xs) + dx, min(ys) + dy, max(xs) + dx, max(ys) + dy)})
    return items


def _once(arr: np.ndarray, dx: int = 0, dy: int = 0) -> list[dict]:
    with ML_LOCK:
        result, _ = get_engine()(arr)
    return _parse(result, dx, dy)


def _iou(a, b) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def dedupe(tokens: list[dict]) -> list[dict]:
    """Tiles overlap, so the same line can be read twice. Keep the better read, and drop fragments
    that were cut off at a tile edge when another tile read the whole line."""
    kept: list[dict] = []
    for tok in sorted(tokens, key=lambda t: -t["score"]):
        same = any(_iou(tok["bbox"], k["bbox"]) > 0.3 and (tok["text"] in k["text"] or k["text"] in tok["text"]) for k in kept)
        if not same:
            kept.append(tok)

    def is_fragment(a: dict) -> bool:
        cx, cy = (a["bbox"][0] + a["bbox"][2]) / 2, (a["bbox"][1] + a["bbox"][3]) / 2
        aw = a["bbox"][2] - a["bbox"][0]
        for b in kept:
            if b is a or b.get("tile") == a.get("tile"):
                continue
            bb = b["bbox"]
            if (bb[2] - bb[0]) > aw and bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]:
                return True
        return False

    kept = [t for t in kept if not is_fragment(t)]
    for tok in kept:
        tok.pop("tile", None)
    kept.sort(key=lambda t: (round(t["bbox"][1] / 12), t["bbox"][0]))
    return kept


def ocr_boxes(image: Image.Image) -> list[dict]:
    """Returns [{'text', 'score', 'bbox': (x0, y0, x1, y1)}] in the picture's own pixel coordinates."""
    arr = np.asarray(to_rgb(image))
    h, w = arr.shape[:2]
    if h < 8 or w < 8:
        return []
    if max(h, w) <= TILE_ABOVE:
        return _once(arr)
    tokens: list[dict] = []
    step = TILE - OVERLAP
    for y in range(0, max(1, h - OVERLAP), step):
        for x in range(0, max(1, w - OVERLAP), step):
            tile = arr[y:y + TILE, x:x + TILE]
            if tile.shape[0] < 16 or tile.shape[1] < 16:
                continue
            for tok in _once(np.ascontiguousarray(tile), x, y):
                tok["tile"] = (x, y)
                tokens.append(tok)
    return dedupe(tokens)
