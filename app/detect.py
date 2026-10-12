"""'Find the actual thing, not the word': CLIP image/text matching over sliding windows.

Model: Xenova/clip-vit-base-patch32 (ONNX). Scoring compares each picture window with the
query *and* with a set of generic 'something else' prompts, so unrelated pictures do not match."""
from __future__ import annotations

import os
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from app.annotate import to_rgb
from app.paths import models_dir
from app.runtime import ML_LOCK, cpu_threads

REPO = "Xenova/clip-vit-base-patch32"
FILES_FULL = {"vision": "onnx/vision_model.onnx", "text": "onnx/text_model.onnx", "tok": "tokenizer.json"}
FILES_QUANT = {"vision": "onnx/vision_model_quantized.onnx", "text": "onnx/text_model_quantized.onnx", "tok": "tokenizer.json"}

TEMPLATES = ["{}", "a photo of {}", "a picture of {}", "a close-up photo of {}"]
NEGATIVES = [
    "a photo", "a blurry photo", "a plain background", "a close-up of a texture", "a screenshot",
    "a document with text", "a person", "an animal", "a building", "a landscape", "furniture",
    "a vehicle", "food", "a plant", "a drawing", "the sky", "a wall", "a table",
]
LOGIT_SCALE = 100.0
MIN_COSINE = 0.19
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
PAD_COLOR = (123, 117, 104)

_lock = threading.Lock()
_state: dict = {}


def _download(variant_files: dict, local_only: bool) -> dict[str, Path]:
    from huggingface_hub import hf_hub_download

    out = {}
    for key, name in variant_files.items():
        out[key] = Path(hf_hub_download(REPO, name, cache_dir=str(models_dir() / "hf"), local_files_only=local_only))
    return out


def model_paths(download: bool = True) -> dict[str, Path]:
    """Locate (and if needed download) the CLIP files. Raises with a readable message on failure."""
    prefer_quant = os.environ.get("FATHOM_CLIP", "").lower().startswith("quant")
    order = [FILES_QUANT, FILES_FULL] if prefer_quant else [FILES_FULL, FILES_QUANT]
    for files in order:  # already on disk? no network needed
        try:
            return _download(files, True)
        except Exception:
            continue
    if not download:
        raise RuntimeError("The object-search model is not downloaded yet.")
    last: Exception | None = None
    for files in order:
        try:
            return _download(files, False)
        except Exception as exc:  # network down, disk full...
            last = exc
    raise RuntimeError(f"Could not download the object-search model ({last}). Check the internet connection and try again.")


def models_ready() -> bool:
    try:
        model_paths(download=False)
        return True
    except Exception:
        return False


def _load():
    with _lock:
        if _state:
            return _state
        import onnxruntime as ort
        from tokenizers import Tokenizer

        paths = model_paths(download=True)
        so = ort.SessionOptions()
        so.intra_op_num_threads = cpu_threads()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        prov = ["CPUExecutionProvider"]
        vision = ort.InferenceSession(str(paths["vision"]), so, providers=prov)
        text = ort.InferenceSession(str(paths["text"]), so, providers=prov)
        tok = Tokenizer.from_file(str(paths["tok"]))
        tok.enable_truncation(max_length=77)
        tok.enable_padding(length=77, pad_id=0, pad_token="!")
        _state.update(vision=vision, text=text, tok=tok)
        return _state


def _pick_output(session) -> int:
    for i, out in enumerate(session.get_outputs()):
        if "embeds" in out.name.lower():
            return i
    return 0


def _norm(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-8)


def preprocess(image: Image.Image) -> np.ndarray:
    img = ImageOps.pad(to_rgb(image), (224, 224), method=Image.Resampling.BICUBIC, color=PAD_COLOR)
    arr = (np.asarray(img).astype(np.float32) / 255.0 - MEAN) / STD
    return np.transpose(arr, (2, 0, 1))


def embed_images(images: list[Image.Image], batch: int = 32) -> np.ndarray:
    st = _load()
    sess = st["vision"]
    name = sess.get_inputs()[0].name
    idx = _pick_output(sess)
    outs = []
    for i in range(0, len(images), batch):
        chunk = np.stack([preprocess(im) for im in images[i:i + batch]]).astype(np.float32)
        with ML_LOCK:
            res = sess.run(None, {name: chunk})[idx]
        outs.append(res.reshape(len(chunk), -1))
    return _norm(np.concatenate(outs, axis=0).astype(np.float32))


def embed_texts(texts: list[str]) -> np.ndarray:
    st = _load()
    sess, tok = st["text"], st["tok"]
    enc = tok.encode_batch(texts)
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    feeds = {inp.name: (mask if "mask" in inp.name.lower() else ids) for inp in sess.get_inputs()}
    with ML_LOCK:
        res = sess.run(None, feeds)[_pick_output(sess)]
    return _norm(res.reshape(len(texts), -1).astype(np.float32))


@lru_cache(maxsize=64)
def query_embeddings(query: str):
    """(query vector, matrix of 'something else' vectors)."""
    q = " ".join(query.split())
    prompts = [t.format(q) for t in TEMPLATES]
    vecs = embed_texts(prompts + NEGATIVES)
    qv = _norm(vecs[: len(prompts)].mean(axis=0, keepdims=True))[0]
    negs = vecs[len(prompts):]
    keep = [i for i in range(len(negs)) if float(negs[i] @ qv) < 0.88]  # drop negatives that mean the same as the query
    return qv, negs[keep] if keep else negs


def score_embeddings(embs: np.ndarray, qv: np.ndarray, negs: np.ndarray):
    """-> (probability the window shows the query, cosine to the query)"""
    cos_q = embs @ qv
    logits = np.concatenate([cos_q[:, None], embs @ negs.T], axis=1) * LOGIT_SCALE
    logits -= logits.max(axis=1, keepdims=True)
    e = np.exp(logits)
    return e[:, 0] / e.sum(axis=1), cos_q


def make_windows(width: int, height: int, levels, max_windows: int = 420):
    wins = [(0, 0, width, height)]
    short = min(width, height)
    for frac in levels:
        size = max(48, int(short * frac))
        if size >= short * 0.97:
            continue
        step = max(16, size // 2 if frac >= 0.3 else int(size * 0.7))
        xs = list(range(0, max(1, width - size) + 1, step))
        ys = list(range(0, max(1, height - size) + 1, step))
        if xs[-1] != max(0, width - size):
            xs.append(max(0, width - size))
        if ys[-1] != max(0, height - size):
            ys.append(max(0, height - size))
        for y in ys:
            for x in xs:
                wins.append((x, y, min(width, x + size), min(height, y + size)))
    uniq = list(dict.fromkeys(wins))
    if len(uniq) > max_windows:  # panoramas: thin out evenly instead of refusing
        keep = np.linspace(0, len(uniq) - 1, max_windows).astype(int)
        uniq = [uniq[i] for i in keep]
    return uniq


def _iou(a, b) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def nms(cands: list[dict], iou_thresh: float = 0.30) -> list[dict]:
    """Keep the best box per object: drop overlaps, boxes inside a better box, and bigger boxes that
    only contain a better small one (they are the same object seen with extra background)."""
    def inside(a, b) -> float:  # fraction of a that lies inside b
        ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
        ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
        area = (a[2] - a[0]) * (a[3] - a[1])
        return (max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)) / area if area > 0 else 0.0

    kept: list[dict] = []
    for c in sorted(cands, key=lambda r: -r["score"]):
        if any(_iou(c["bbox"], k["bbox"]) >= iou_thresh or inside(c["bbox"], k["bbox"]) >= 0.85 or inside(k["bbox"], c["bbox"]) >= 0.85 for k in kept):
            continue
        kept.append(c)
    return kept


FAST_LEVELS = (0.6, 0.4, 0.27)
THOROUGH_LEVELS = (0.7, 0.5, 0.35, 0.24, 0.16)


def find_objects(image: Image.Image, query: str, threshold: float = 0.6, thorough: bool = True) -> list[dict]:
    """[{'text', 'score', 'bbox'}] in the picture's own pixel coordinates."""
    if not query.strip():
        return []
    rgb = to_rgb(image)
    max_side = 1280 if thorough else 800
    scale = min(1.0, max_side / max(rgb.width, rgb.height))
    work = rgb.resize((max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))), Image.Resampling.BILINEAR) if scale < 1 else rgb
    wins = make_windows(work.width, work.height, THOROUGH_LEVELS if thorough else FAST_LEVELS)
    qv, negs = query_embeddings(query)
    embs = embed_images([work.crop(w) for w in wins])
    prob, cos_q = score_embeddings(embs, qv, negs)
    inv = 1.0 / scale
    cands = [
        {"text": query, "score": float(prob[i]), "bbox": (w[0] * inv, w[1] * inv, w[2] * inv, w[3] * inv)}
        for i, w in enumerate(wins)
        if prob[i] >= threshold and cos_q[i] >= MIN_COSINE
    ]
    return nms(cands)[:50]
