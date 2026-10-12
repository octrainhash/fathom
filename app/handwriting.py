"""Reading handwriting.

Pipeline for one picture:
  1. clean it up: even out the lighting, straighten a tilted page, remove ruled lines and margin lines, drop specks
  2. cut it into lines of writing (so every line has an exact position for highlighting)
  3. read each line with the best reader that is available:
        ai       your AI model looks at the whole page AND each line close up (best for messy writing; sends the picture to that service)
        trocr    an offline handwriting model on this PC (nothing leaves the PC; needs a one-time install in Assistant > Settings)
        enhanced the normal text reader on a cleaned-up copy (works for neat writing only)
  4. hard lines (low confidence, [?]) get a second, closer look with the context of the whole page
Matching in Search is forgiving: a word that was misread by a letter or two still matches."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from PIL import Image

from app.ai import store
from app.paths import data_root, models_dir
from app.service import UserError, _has

TROCR_NAME = "microsoft/trocr-large-handwritten"
TROCR_SMALL = "microsoft/trocr-base-handwritten"
_LOCK = threading.RLock()


# ================================================================== availability
def trocr_ready() -> bool:
    if not (_has("transformers") and _has("torch")):
        return False
    d = models_dir() / "trocr"
    return d.exists() and any(d.glob("models--microsoft--trocr-*"))


def ai_ready() -> bool:
    cfg = store.load()
    p = cfg["provider"]
    return p == "ollama" or bool(store.get_secret(p))


def info() -> dict:
    cfg = store.load()
    return {"setting": cfg.get("handwriting", "auto"), "ai": ai_ready(), "trocr": trocr_ready(), "trocr_installable": True, "chosen": choose_engine(), "provider": cfg["provider"], "model": cfg["models"][cfg["provider"]]}


def choose_engine(pref: str | None = None) -> str:
    pref = pref or store.load().get("handwriting", "auto")
    if pref == "off":
        return "enhanced"
    if pref == "trocr":
        return "trocr" if trocr_ready() else ("enhanced")
    if pref == "ai":
        return "ai" if ai_ready() else ("trocr" if trocr_ready() else "enhanced")
    if ai_ready():
        return "ai"
    return "trocr" if trocr_ready() else "enhanced"


# ================================================================== cleaning and cutting into lines
def _gray(image: Image.Image) -> np.ndarray:
    import cv2
    rgb = np.asarray(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def flatten_light(gray: np.ndarray) -> np.ndarray:
    """removes shadows and uneven light: divide by a heavily blurred copy"""
    import cv2
    k = max(31, (min(gray.shape) // 8) | 1)
    bg = cv2.medianBlur(gray, k if k % 2 else k + 1) if max(gray.shape) < 2500 else cv2.GaussianBlur(gray, (0, 0), k / 3)
    out = cv2.divide(gray, np.maximum(bg, 1), scale=235)
    return np.clip(out, 0, 255).astype(np.uint8)


def raw_ink(gray: np.ndarray) -> np.ndarray:
    import cv2
    flat = flatten_light(gray)
    h, w = flat.shape
    blur = cv2.GaussianBlur(flat, (3, 3), 0)
    block = max(15, (min(h, w) // 30) | 1)
    return cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 12)


def remove_rules(ink: np.ndarray) -> np.ndarray:
    """takes out ruled lines and margin lines (the page must already be level), then specks; strokes that crossed a rule are rejoined"""
    import cv2
    h, w = ink.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 12), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, h // 4)))
    hl = cv2.morphologyEx(ink, cv2.MORPH_OPEN, hk)
    vl = cv2.morphologyEx(ink, cv2.MORPH_OPEN, vk)
    lines = cv2.dilate(cv2.bitwise_or(hl, vl), np.ones((3, 3), np.uint8))
    clean = cv2.bitwise_and(ink, cv2.bitwise_not(lines))
    clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(clean, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= max(8, (h * w) // 400000)
    return np.where(keep[lab], 255, 0).astype(np.uint8)


def ink_mask(gray: np.ndarray) -> np.ndarray:
    return remove_rules(raw_ink(gray))


def estimate_skew(mask: np.ndarray) -> float:
    """degrees to rotate so the writing is level (the angle whose row profile is sharpest)"""
    import cv2
    h, w = mask.shape
    s = 600 / max(h, w)
    small = cv2.resize(mask, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA) if s < 1 else mask
    sh, sw = small.shape
    best, best_a = -1.0, 0.0
    for a in np.arange(-10, 10.01, 0.5):
        M = cv2.getRotationMatrix2D((sw / 2, sh / 2), a, 1.0)
        r = cv2.warpAffine(small, M, (sw, sh), flags=cv2.INTER_NEAREST)
        prof = r.sum(axis=1).astype(float)
        score = float(np.sum(np.diff(prof) ** 2))
        if score > best:
            best, best_a = score, float(a)
    return best_a



def _smooth(v: np.ndarray, sigma: float) -> np.ndarray:
    r = max(1, int(sigma * 3))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(v, r, mode="edge"), k, mode="valid")


def _split_rows(p: np.ndarray, rows_raw: np.ndarray, glyph_h: float) -> list[tuple[int, int]]:
    """cut the row profile into lines at the valleys between the rows of writing"""
    h = len(p)
    if p.max() <= 0:
        return []
    q = p - p.mean()
    ac = np.correlate(q, q, "full")[h - 1:]
    lo, hi = int(glyph_h * 0.9), min(h - 1, int(glyph_h * 6))
    pitch = glyph_h * 1.8
    if hi > lo + 2 and ac[0] > 0:
        seg = ac[lo:hi]
        k = int(np.argmax(seg))
        if seg[k] > 0.25 * ac[0]:
            pitch = float(lo + k)
    r = max(2, int(pitch * 0.42))
    peaks = [i for i in range(h) if p[i] > 0.16 * p.max() and p[i] >= p[max(0, i - r):i + r + 1].max() and (i == 0 or p[i] > p[i - 1] or p[i] > 0)]
    # plateaus give several equal maxima: keep one per window
    uniq: list[int] = []
    for i in peaks:
        if uniq and i - uniq[-1] <= r:
            if p[i] > p[uniq[-1]]:
                uniq[-1] = i
            continue
        uniq.append(i)
    if not uniq:
        return []
    cuts = [0]
    for a_, b_ in zip(uniq[:-1], uniq[1:]):
        cuts.append(a_ + int(np.argmin(p[a_:b_ + 1])))
    cuts.append(h)
    out = []
    for k, pk in enumerate(uniq):
        y0, y1 = cuts[k], cuts[k + 1]
        y0, y1 = max(y0, int(pk - pitch * 0.95)), min(y1, int(pk + pitch * 0.95))
        seg = rows_raw[y0:y1]
        if seg.size == 0 or seg.max() <= 0:
            continue
        on = np.where(seg > 0.03 * seg.max())[0]
        if len(on) == 0:
            continue
        out.append((y0 + int(on[0]), y0 + int(on[-1]) + 1))
    return out


def segment_lines(image: Image.Image, max_lines: int = 120) -> dict:
    """{'lines': [bbox in the ORIGINAL picture], 'angle': skew, 'size': (w, h)}; lines are top to bottom"""
    import cv2
    gray = _gray(image)
    H, W = gray.shape
    scale = 1.0
    if max(H, W) > 2400:
        scale = 2400 / max(H, W)
        gray = cv2.resize(gray, (int(W * scale), int(H * scale)), interpolation=cv2.INTER_AREA)
    raw = raw_ink(gray)
    h, w = raw.shape
    if raw.sum() < 255 * 40:
        return {"lines": [], "angle": 0.0, "size": (W, H)}
    angle = estimate_skew(raw)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rot = remove_rules(cv2.warpAffine(raw, M, (w, h), flags=cv2.INTER_NEAREST))
    if rot.sum() < 255 * 40:
        return {"lines": [], "angle": angle, "size": (W, H)}
    # join letters of a line sideways so each line becomes one band
    comp = [stat for stat in cv2.connectedComponentsWithStats(rot, connectivity=8)[2][1:]]
    heights = sorted(int(s[cv2.CC_STAT_HEIGHT]) for s in comp) or [12]
    glyph_h = max(8, heights[int(len(heights) * 0.6)])                  # typical letter height
    smear = cv2.dilate(rot, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, int(glyph_h * 2.2)), 1)))
    prof = smear.sum(axis=1).astype(float) / 255.0
    sig = max(1.0, glyph_h * 0.22)
    p = _smooth(prof, sig)
    rows_raw = rot.sum(axis=1).astype(float) / 255.0
    bands = _split_rows(p, rows_raw, glyph_h)
    out = []
    inv = cv2.invertAffineTransform(M)
    gap = int(glyph_h * 4)
    for y0, y1 in bands:
        if y1 - y0 < max(6, glyph_h * 0.45):
            continue
        cols = cv2.dilate(rot[y0:y1], cv2.getStructuringElement(cv2.MORPH_RECT, (int(glyph_h * 1.2) | 1, 1))).sum(axis=0).astype(float) / 255.0
        xs = np.where(cols > 0)[0]
        if len(xs) < 4:
            continue
        # runs of writing separated by wide gaps; tiny isolated runs (page edges, stray marks) are dropped
        splits = np.where(np.diff(xs) > gap)[0]
        runs = [(xs[a_], xs[b_]) for a_, b_ in zip(np.r_[0, splits + 1], np.r_[splits, len(xs) - 1])]
        ink = [float(cols[r0:r1 + 1].sum()) for r0, r1 in runs]
        keep = [r for r, i in zip(runs, ink) if i >= 0.08 * max(ink)]
        x0, x1 = int(keep[0][0]), int(keep[-1][1])
        if x1 - x0 < glyph_h * 0.8:
            continue
        pad = glyph_h * 0.2
        ys_, xs_ = np.nonzero(rot[y0:y1, x0:x1 + 1])
        if len(xs_) < 6:
            continue
        pts = np.stack([xs_ + x0, ys_ + y0], axis=1).astype(np.float32)
        back = (inv[:, :2] @ pts.T).T + inv[:, 2]
        bx0, by0 = np.percentile(back, 0.3, axis=0) / scale - pad
        bx1, by1 = np.percentile(back, 99.7, axis=0) / scale + pad
        out.append((max(0.0, float(bx0)), max(0.0, float(by0)), min(float(W), float(bx1)), min(float(H), float(by1))))
    out.sort(key=lambda b: (b[1] + b[3]) / 2)
    return {"lines": out[:max_lines], "angle": angle, "size": (W, H), "glyph_h": glyph_h / scale}


def line_crop(image: Image.Image, box, enhance: bool = True, min_h: int = 90, max_w: int = 1800) -> Image.Image:
    x0, y0, x1, y1 = [int(v) for v in box]
    crop = image.convert("RGB").crop((x0, y0, x1, y1))
    if enhance:
        g = flatten_light(_gray(crop))
        import cv2
        g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(g)
        crop = Image.fromarray(g).convert("RGB")
    w, h = crop.size
    s = max(1.0, min_h / max(1, h))
    s = min(s, max_w / max(1, w)) if w * s > max_w else s
    if abs(s - 1) > 0.05:
        crop = crop.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    return crop


def _jpeg_b64(im: Image.Image, q: int = 90) -> str:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=q)
    return base64.b64encode(buf.getvalue()).decode()


def _page_for_ai(image: Image.Image, side: int = 1800) -> Image.Image:
    im = image.convert("RGB")
    if max(im.size) > side:
        s = side / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    return im


# ================================================================== the readers
SYSTEM = ("You are an expert at reading handwriting, including very messy, rushed, slanted or faded handwriting, cursive, mixed print and cursive, and abbreviations. "
          "You transcribe exactly what is written: keep the writer's spelling, punctuation, capitals and numbers; do not correct, translate, summarise or add anything. "
          "Use the whole page for context (topic, names, repeated words, the writer's letter shapes) to decide between similar-looking letters. "
          "When a word cannot be read even with that context, write your best guess followed by [?], or [?] alone if there is no guess. Answer with JSON only.")


def _ai_json(text: str) -> dict:
    t = text.strip()
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(t[i:j + 1])
        except Exception:
            pass
    lines = {}
    for m in re.finditer(r"^\s*(?:line\s*)?(\d+)\s*[.:)\-]\s*(.*)$", t, re.I | re.M):
        lines[int(m.group(1))] = m.group(2).strip()
    return {"lines": [{"n": k, "text": v, "confidence": 0.6} for k, v in lines.items()]}


def _ai_ask(content: list, cancel, max_tokens: int = 6000) -> str:
    from app.ai import llm
    return llm.complete(SYSTEM, [{"role": "user", "content": content}], cancel, max_tokens)


def _img_block(b64: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}


def read_with_ai(image: Image.Image, boxes: list, cancel=None, progress=None, careful: bool = True) -> list[dict]:
    page = _page_for_ai(image)
    page_b64 = _jpeg_b64(page)
    out: list[dict] = []
    if not boxes:                                           # no usable lines: read the page as a whole (long pages in strips)
        H = page.height
        strips = [(0, H)] if H <= 2600 or page.width * 1.0 > H else [(y, min(H, y + 1500)) for y in range(0, H, 1300)]
        for y0, y1 in strips:
            crop = page.crop((0, y0, page.width, y1))
            txt = _ai_ask([_img_block(_jpeg_b64(crop)), {"type": "text", "text": 'Transcribe all the handwriting in this picture, line by line, top to bottom. Return {"lines":[{"n":1,"text":"...","confidence":0.0-1.0}, ...]}.'}], cancel)
            for l in _ai_json(txt).get("lines", []):
                if str(l.get("text", "")).strip():
                    out.append({"text": str(l["text"]).strip(), "bbox": (0, y0 * image.height / H, image.width, y1 * image.height / H), "score": float(l.get("confidence", 0.6))})
        return out
    N = 22
    for start in range(0, len(boxes), N):
        group = boxes[start:start + N]
        content: list = [{"type": "text", "text": "Full page for context:"}, _img_block(page_b64)]
        for k, b in enumerate(group, start + 1):
            content += [{"type": "text", "text": f"Line {k}:"}, _img_block(_jpeg_b64(line_crop(image, b)))]
        content.append({"type": "text", "text": f'Transcribe each numbered line crop exactly (lines {start + 1} to {start + len(group)}). Return {{"lines":[{{"n":<number>,"text":"<exact text>","confidence":<0.0-1.0>}}, ...]}} with one entry per line, including lines that are only a number, a date or a doodle ("" if there is no writing).'})
        res = {int(l.get("n", 0)): l for l in _ai_json(_ai_ask(content, cancel)).get("lines", []) if str(l.get("n", "")).strip().lstrip("-").isdigit()}
        for k, b in enumerate(group, start + 1):
            l = res.get(k) or {}
            out.append({"text": str(l.get("text", "")).strip(), "bbox": tuple(b), "score": float(l.get("confidence", 0.5) or 0.5), "n": k})
        if progress:
            progress(min(1.0, (start + len(group)) / len(boxes)) * 0.8)
    if careful:                                             # a closer second look at the hard lines, with what was read around them as context
        hard = [l for l in out if l["text"] and (l["score"] < 0.72 or "[?]" in l["text"])]
        for chunk_start in range(0, len(hard), 10):
            chunk = hard[chunk_start:chunk_start + 10]
            content = [{"type": "text", "text": "Full page for context:"}, _img_block(page_b64), {"type": "text", "text": "The text read so far for the whole page:\n" + "\n".join(f"{l.get('n', i + 1)}: {l['text']}" for i, l in enumerate(out) if l['text'])[:6000]}]
            for l in chunk:
                content += [{"type": "text", "text": f"Look again at line {l['n']} (first reading: {l['text']!r}). Larger view:"}, _img_block(_jpeg_b64(line_crop(image, l['bbox'], min_h=160)))]
            content.append({"type": "text", "text": 'Re-read these lines very carefully, letter by letter, using the surrounding text for context. Return {"lines":[{"n":<number>,"text":"...","confidence":<0.0-1.0>}]}.'})
            try:
                res = {int(x.get("n", 0)): x for x in _ai_json(_ai_ask(content, cancel)).get("lines", []) if str(x.get("n", "")).strip().lstrip("-").isdigit()}
            except Exception:
                res = {}
            for l in chunk:
                r = res.get(l["n"])
                if r and str(r.get("text", "")).strip():
                    l["text"], l["score"] = str(r["text"]).strip(), max(l["score"], float(r.get("confidence", 0.6) or 0.6))
    if progress:
        progress(1.0)
    return [l for l in out if l["text"]]


_TROCR: dict = {}


def read_with_trocr(image: Image.Image, boxes: list, cancel=None, progress=None) -> list[dict]:
    if not trocr_ready():
        raise UserError("The offline handwriting reader is not installed yet. Open Assistant > Settings > Handwriting and press Install.")
    import torch
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    with _LOCK:
        if "m" not in _TROCR:
            name = TROCR_NAME if any((models_dir() / "trocr").glob("models--microsoft--trocr-large*")) else TROCR_SMALL
            _TROCR["p"] = TrOCRProcessor.from_pretrained(name, cache_dir=str(models_dir() / "trocr"), local_files_only=True)
            _TROCR["m"] = VisionEncoderDecoderModel.from_pretrained(name, cache_dir=str(models_dir() / "trocr"), local_files_only=True).eval()
    proc, model = _TROCR["p"], _TROCR["m"]
    if not boxes:
        boxes = [(0, 0, image.width, image.height)]
    out = []
    B = 6
    for s in range(0, len(boxes), B):
        if cancel is not None and cancel.is_set():
            break
        crops = [line_crop(image, b, min_h=64, max_w=1400) for b in boxes[s:s + B]]
        with torch.no_grad():
            pix = proc(images=crops, return_tensors="pt").pixel_values
            ids = model.generate(pix, max_new_tokens=96, num_beams=4)
        for b, t in zip(boxes[s:s + B], proc.batch_decode(ids, skip_special_tokens=True)):
            out.append({"text": t.strip(), "bbox": tuple(b), "score": 0.7})
        if progress:
            progress(min(1.0, (s + B) / len(boxes)))
    return [l for l in out if l["text"]]


def read_enhanced(image: Image.Image, boxes: list, cancel=None, progress=None) -> list[dict]:
    """the normal text reader on cleaned-up line crops (and the whole page); good for neat writing only"""
    from app.ocr import ocr_boxes
    out = []
    todo = boxes or [(0, 0, image.width, image.height)]
    for i, b in enumerate(todo):
        crop = line_crop(image, b, min_h=110)
        toks = ocr_boxes(crop)
        toks.sort(key=lambda t: t["bbox"][0])
        text = " ".join(t["text"] for t in toks).strip()
        if text:
            out.append({"text": text, "bbox": tuple(b), "score": float(np.mean([t["score"] for t in toks])) if toks else 0.3})
        if progress:
            progress((i + 1) / len(todo))
    return out


# ================================================================== the one entry point (with a cache)
def _cache_path(key: str) -> Path:
    d = data_root() / "handwriting_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / (key + ".json")


def read(image: Image.Image, engine: str | None = None, cancel=None, progress=None, careful: bool = True, use_cache: bool = True) -> dict:
    """{'engine', 'lines': [{'text','bbox','score'}], 'text': 'all lines joined', 'size': (w, h)}"""
    eng = choose_engine() if not engine or engine == "auto" else engine
    cfg = store.load()
    thumb = image.convert("L").resize((64, 64))
    key = hashlib.sha1(thumb.tobytes() + str(image.size).encode() + eng.encode() + (cfg["models"][cfg["provider"]] if eng == "ai" else "").encode()).hexdigest()
    cp = _cache_path(key)
    if use_cache and cp.exists():
        try:
            d = json.loads(cp.read_text("utf-8"))
            d["lines"] = [{**l, "bbox": tuple(l["bbox"])} for l in d["lines"]]
            return d
        except Exception:
            pass
    seg = segment_lines(image)
    boxes = seg["lines"]
    if eng == "ai":
        lines = read_with_ai(image, boxes, cancel, progress, careful)
    elif eng == "trocr":
        lines = read_with_trocr(image, boxes, cancel, progress)
    else:
        lines = read_enhanced(image, boxes, cancel, progress)
    res = {"engine": eng, "lines": lines, "text": "\n".join(l["text"] for l in lines), "size": tuple(seg["size"]), "angle": seg["angle"]}
    if lines and (cancel is None or not cancel.is_set()):
        try:
            cp.write_text(json.dumps(res), encoding="utf-8")
        except OSError:
            pass
    return res


# ================================================================== forgiving matching for Search
def fuzzy_spans(text: str, query: str, min_ratio: float = 0.8) -> list[tuple[int, int]]:
    """places in text that look like the query, allowing a letter or two to be misread (words are compared one run of words at a time)"""
    q = re.sub(r"\s+", " ", query.strip().lower())
    if len(q) < 3:
        return []
    words = [(m.start(), m.end(), m.group().lower()) for m in re.finditer(r"\S+", text)]
    n = len(q.split())
    cand = []
    need = min_ratio if len(q) >= 5 else 0.9
    for i in range(len(words)):
        for k in (n, n + 1, max(1, n - 1)):
            seg = words[i:i + k]
            if len(seg) != k:
                continue
            s = " ".join(w[2] for w in seg)
            s2 = re.sub(r"[^\w\s]", "", s)
            r = max(SequenceMatcher(None, q, s).ratio(), SequenceMatcher(None, q, s2).ratio())
            if r >= need:
                cand.append((r, -(seg[-1][1] - seg[0][0]), seg[0][0], seg[-1][1]))
    cand.sort(reverse=True)                                  # best matches first; a worse overlapping window is dropped
    taken: list[tuple[int, int]] = []
    for r, _l, s_, e_ in cand:
        if all(e_ <= a_ or s_ >= b_ for a_, b_ in taken):
            taken.append((s_, e_))
    return sorted(taken)


# ================================================================== one-time install of the offline reader
def install_start() -> dict:
    import subprocess
    import sys

    from app import ops
    from app.convert.core import ConvertError
    from app.ops import Output, Task
    from app.runtime import no_window_flags

    def fn(ctx, task):
        def run(args, label):
            ctx.status(label)
            p = subprocess.Popen([sys.executable, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=no_window_flags())
            tail = []
            for line in p.stdout:  # type: ignore[union-attr]
                tail.append(line.strip())
                del tail[:-8]
                ctx.check() if not ctx.cancel.is_set() else p.kill()
            if p.wait() != 0:
                raise ConvertError(f"{label} failed: " + " | ".join(tail[-3:]))
        if not _has("torch"):
            run(["-m", "pip", "install", "--disable-pip-version-check", "torch", "--index-url", "https://download.pytorch.org/whl/cpu"], "Installing the reading engine (about 200 MB)…")
        if not _has("transformers"):
            run(["-m", "pip", "install", "--disable-pip-version-check", "transformers", "sentencepiece"], "Installing the model loader…")
        ctx.progress(0.5)
        code = ("from huggingface_hub import snapshot_download as s;import sys;"
                f"s('{TROCR_NAME}',cache_dir=r'{models_dir() / 'trocr'}')")
        try:
            run(["-c", code], "Downloading the handwriting model (about 2 GB)…")
        except ConvertError:
            code = code.replace(TROCR_NAME, TROCR_SMALL)
            run(["-c", code], "Downloading the smaller handwriting model…")
        return Output([], "The offline handwriting reader is ready.")

    return {"job": ops.start("hw-install", "Installing the handwriting reader", [Task("Offline handwriting reader", fn)], workers=1).id}


# ================================================================== the "Read handwriting" tool
def _annotated(image: Image.Image, lines: list[dict]) -> Image.Image:
    from PIL import ImageDraw
    im = image.convert("RGB")
    k = min(1.0, 1500 / max(im.size))
    if k < 1:
        im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for i, l in enumerate(lines, 1):
        x0, y0, x1, y1 = [v * k for v in l["bbox"]]
        d.rectangle((x0, y0, x1, y1), fill=(255, 235, 59, 70), outline=(226, 60, 40, 255), width=3)
        d.ellipse((x0 - 4, y0 - 12, x0 + 20, y0 + 12), fill=(226, 60, 40, 255))
        d.text((x0 + 3, y0 - 9), str(i), fill=(255, 255, 255, 255))
    out = im.convert("RGBA")
    out.alpha_composite(ov)
    return out.convert("RGB")


def read_start(paths: list[str], recursive: bool, options: dict, output: dict) -> dict:
    from app import ops, pagesel, pdfview, proof
    from app.convert.core import ConvertError
    from app.opsvc import expand_sources
    from app.ops import Output, Task

    engine = str(options.get("engine") or "auto")
    careful = options.get("careful", True) is not False
    fmt = str(options.get("format") or "txt")
    if fmt not in ("txt", "md", "docx", "html"):
        fmt = "txt"
    pages_spec = str(options.get("pages") or "")
    pol = ops.OutputPolicy.from_dict(output)
    IMG = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".gif", ".heic", ".avif", ".jp2"}
    tasks = []
    for src, rel in expand_sources(paths, recursive):
        ext = src.suffix.lower()
        if ext not in IMG and ext != ".pdf":
            continue

        def fn(ctx, task, src=src, rel=rel, ext=ext):
            frames: list[tuple[str, Image.Image]] = []
            if ext == ".pdf":
                n = int(pdfview.info(str(src)).get("pages", 1) or 1)
                for pg in (pagesel.parse(pages_spec, n) if pages_spec else range(1, n + 1)):
                    ctx.check()
                    data, _m = pdfview.page_png(str(src), pg - 1, 2400)
                    frames.append((f"Page {pg}", Image.open(io.BytesIO(data)).convert("RGB")))
            else:
                from app import extract
                for label, im in extract.iter_image_frames(src):
                    frames.append((label or "Picture", im))
            if not frames:
                raise ConvertError("Nothing to read in this file.")
            P = proof.Proofs(proof.new_sid(), limit=3)
            parts, total_lines, engines = [], 0, set()
            for i, (label, im) in enumerate(frames):
                ctx.check()
                ctx.status(f"{src.name}: {label}")
                ctx.span = (i / len(frames), (i + 1) / len(frames))
                res = read(im, engine, ctx.cancel, ctx.progress, careful)
                engines.add(res["engine"])
                total_lines += len(res["lines"])
                parts.append((label, res["text"]))
                if not P.full() and res["lines"]:
                    P.add("Handwriting read", f"{src.name} · {label}", proof.framed(im), _annotated(im, res["lines"]), "\n".join(f"{n}. {l['text']}" for n, l in enumerate(res["lines"][:6], 1)))
            ctx.span = (0.0, 1.0)
            multi = len(parts) > 1
            if fmt == "txt":
                body = "\n\n".join((f"--- {lab} ---\n" if multi else "") + t for lab, t in parts)
            else:
                body = "\n\n".join((f"## {lab}\n\n" if multi else "") + t.replace("\n", "  \n") for lab, t in parts)
            work = ctx.scratch_dir()
            outp = work / f"{src.stem} (handwriting).{fmt}"
            if fmt in ("txt", "md"):
                outp.write_text(body, encoding="utf-8")
            elif fmt == "docx":
                from app.ai import docs
                docs.make_docx(f"# {src.stem}\n\n" + body, outp, "")
            else:
                from app.ai import docs
                docs.make_html(f"# {src.stem}\n\n" + body, outp, src.stem)
            final = pol.place([outp], src, rel)
            note = (f"{total_lines} line{'s' if total_lines != 1 else ''} read" if total_lines else "No handwriting was found") + f" · reader: {', '.join(sorted(engines))}"
            return Output(final, note, extra={"proof": P.result(), "lines": total_lines, "preview": parts[0][1][:600]})

        tasks.append(Task(src.name, fn, src, heavy=False, rel=rel))
    if not tasks:
        raise UserError("Add pictures, scans or PDFs with handwriting on them first.")
    return {"job": ops.start("handwriting", "Reading handwriting", tasks, workers=1).id}
