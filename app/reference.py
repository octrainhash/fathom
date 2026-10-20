# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Find things by showing Fathom a picture of them ("reference pictures").

Three ways to match, chosen by the user:
  same    this exact item (a logo, a product, a painting, a poster): SIFT feature matching + RANSAC.
          Needs no download. Finds it small, rotated, partly hidden, in any photo or video frame.
  like    things that look like the reference (any object, animal, scene): CLIP picture-to-picture matching.
  person  the same person's face: YuNet face finder + SFace recogniser (OpenCV model zoo, Apache-2.0).

Everything runs on this PC. Nothing is uploaded and no face data is kept after the search."""
from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.annotate import to_rgb
from app.paths import models_dir
from app.runtime import ML_LOCK

log = logging.getLogger("fathom.reference")

KINDS = ("auto", "same", "like", "person")
REF_QUERY = "reference picture"

# ---------------------------------------------------------------------------------------------- helpers


def load_reference(path: str | Path) -> Image.Image:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    return to_rgb(im)


def _bgr(image: Image.Image, max_side: int | None = None) -> tuple[np.ndarray, float]:
    rgb = to_rgb(image)
    scale = 1.0
    if max_side and max(rgb.size) > max_side:
        scale = max_side / max(rgb.size)
        rgb = rgb.resize((max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))), Image.Resampling.LANCZOS)
    return cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR), scale


def _iou(a, b) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _dedupe(cands: list[dict], thresh: float = 0.4) -> list[dict]:
    out: list[dict] = []
    for c in sorted(cands, key=lambda c: -c["score"]):
        if all(_iou(c["bbox"], o["bbox"]) < thresh for o in out):
            out.append(c)
    return out


# ------------------------------------------------------------------------------------------- "same": SIFT

_sift_local = threading.local()


def _sift():
    s = getattr(_sift_local, "sift", None)
    if s is None:
        s = cv2.SIFT_create(nfeatures=4000)
        _sift_local.sift = s
    return s


def _gray_features(bgr: np.ndarray, mask=None):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    kps, desc = _sift().detectAndCompute(gray, mask)
    return kps, desc


class SameRef:
    def __init__(self, image: Image.Image):
        bgr, _ = _bgr(image, 900)
        self.size = (bgr.shape[1], bgr.shape[0])
        self.kps, self.desc = _gray_features(bgr)
        self.n = 0 if self.desc is None else len(self.desc)
        # the reference's outline, used to draw the box around each find
        w, h = self.size
        self.outline = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)

    @property
    def usable(self) -> bool:
        return self.n >= 12


def find_same(image: Image.Image, refs: list[SameRef], strictness: float, thorough: bool = True) -> list[dict]:
    """Every place where one of the reference items appears in the picture."""
    refs = [r for r in refs if r.usable]
    if not refs:
        return []
    bgr, scale = _bgr(image, 1800 if thorough else 1100)
    kps, desc = _gray_features(bgr)
    if desc is None or len(desc) < 8:
        return []
    inv = 1.0 / scale
    need = int(round(10 + 22 * float(strictness)))  # confirmed (RANSAC) matching points needed: 12 loose ... 31 strict
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    out: list[dict] = []
    for ref in refs:
        pts_img = np.float32([k.pt for k in kps])
        remaining = np.ones(len(kps), dtype=bool)
        for _ in range(6 if thorough else 2):  # the same item can appear more than once
            idx = np.nonzero(remaining)[0]
            if len(idx) < max(8, need):
                break
            pairs = matcher.knnMatch(ref.desc, desc[idx], k=2)
            good = [m for p in pairs if len(p) == 2 for m, n in [p] if m.distance < 0.75 * n.distance]
            if len(good) < need:
                break
            src = np.float32([ref.kps[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            dst = np.float32([pts_img[idx[m.trainIdx]] for m in good]).reshape(-1, 1, 2)
            H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
            if H is None or mask is None:
                break
            inliers = int(mask.sum())
            if inliers < need:
                break
            quad = cv2.perspectiveTransform(ref.outline, H).reshape(-1, 2)
            area = abs(cv2.contourArea(quad.astype(np.float32)))
            img_area = bgr.shape[0] * bgr.shape[1]
            hull_ok = cv2.isContourConvex(quad.astype(np.float32)) and 0.0004 * img_area < area < 1.6 * img_area
            inl_pts = dst[mask.ravel().astype(bool)].reshape(-1, 2)
            if hull_ok:
                x0, y0 = np.clip(inl_pts.min(axis=0), 0, [bgr.shape[1], bgr.shape[0]])
                x1, y1 = np.clip(inl_pts.max(axis=0), 0, [bgr.shape[1], bgr.shape[0]])
                if x1 - x0 > 8 and y1 - y0 > 8:
                    score = float(min(1.0, 0.5 + inliers / (2.0 * max(need, 1) + 20)))
                    out.append({"text": REF_QUERY, "score": score, "bbox": (x0 * inv, y0 * inv, x1 * inv, y1 * inv), "inliers": inliers})
            # remove the points that explained this find, then look for another copy
            keep = np.ones(len(idx), dtype=bool)
            used = {good[i].trainIdx for i in np.nonzero(mask.ravel())[0]}
            for t in used:
                keep[t] = False
            remaining[idx[~keep]] = False
    return _dedupe(out)[:30]


# ------------------------------------------------------------------------------------------ "like": CLIP


class LikeRef:
    def __init__(self, image: Image.Image):
        from app.detect import _norm, embed_images

        rgb = to_rgb(image)
        views = [rgb]
        w, h = rgb.size  # the middle of the reference counts too, because the thing is usually in the middle
        if min(w, h) >= 96:
            views.append(rgb.crop((int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85))))
        embs = embed_images(views)
        self.vec = _norm(embs.mean(axis=0, keepdims=True))[0]


def find_like(image: Image.Image, refs: list[LikeRef], strictness: float, thorough: bool = True) -> list[dict]:
    from app.detect import FAST_LEVELS, THOROUGH_LEVELS, embed_images, make_windows, nms

    if not refs:
        return []
    rgb = to_rgb(image)
    max_side = 1280 if thorough else 800
    scale = min(1.0, max_side / max(rgb.width, rgb.height))
    work = rgb.resize((max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))), Image.Resampling.BILINEAR) if scale < 1 else rgb
    wins = make_windows(work.width, work.height, THOROUGH_LEVELS if thorough else FAST_LEVELS)
    embs = embed_images([work.crop(w) for w in wins])
    mat = np.stack([r.vec for r in refs])
    cos = (embs @ mat.T).max(axis=1)
    thr = 0.50 + 0.40 * float(strictness)  # picture-to-picture similarity: 0.58 loose ... 0.88 strict
    inv = 1.0 / scale
    cands = [
        {"text": REF_QUERY, "score": float(min(1.0, max(0.0, (cos[i] - 0.4) / 0.5))), "bbox": (w[0] * inv, w[1] * inv, w[2] * inv, w[3] * inv)}
        for i, w in enumerate(wins)
        if cos[i] >= thr
    ]
    return nms(cands)[:50]


# --------------------------------------------------------------------------------------- "person": faces

FACE_MODELS = {
    "detector": (
        "face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        ["https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
         "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx"],
    ),
    "recognizer": (
        "face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        ["https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
         "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx"],
    ),
}


def _face_dir() -> Path:
    d = models_dir() / "faces"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def face_models_ready() -> bool:
    for name, sha, _urls in FACE_MODELS.values():
        p = _face_dir() / name
        if not p.is_file() or p.stat().st_size < 100_000:
            return False
    return True


def faces_supported() -> bool:
    return hasattr(cv2, "FaceDetectorYN") and hasattr(cv2, "FaceRecognizerSF")


def ensure_face_models(progress=None) -> None:
    """Download the two small face models once (about 39 MB), verifying their fingerprints."""
    import urllib.request

    for key, (name, sha, urls) in FACE_MODELS.items():
        dest = _face_dir() / name
        if dest.is_file() and dest.stat().st_size > 100_000 and _sha(dest) == sha:
            continue
        last: Exception | None = None
        for url in urls:
            tmp = dest.with_suffix(".part")
            try:
                if progress:
                    progress(f"Downloading the face model ({name}, one time only)…")
                req = urllib.request.Request(url, headers={"User-Agent": "Fathom"})
                with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                if _sha(tmp) != sha:
                    raise RuntimeError("the downloaded file did not match its fingerprint")
                tmp.replace(dest)
                last = None
                break
            except Exception as exc:  # try the next address
                last = exc
                tmp.unlink(missing_ok=True)
        if last is not None:
            raise RuntimeError(f"Could not download the face model: {last}. Check your internet connection and try again.")


class _Faces:
    _inst: "_Faces | None" = None
    _lock = threading.Lock()

    def __init__(self):
        d = _face_dir()
        self.det = cv2.FaceDetectorYN.create(str(d / FACE_MODELS["detector"][0]), "", (320, 320), 0.7, 0.3, 500)
        self.rec = cv2.FaceRecognizerSF.create(str(d / FACE_MODELS["recognizer"][0]), "")

    @classmethod
    def get(cls) -> "_Faces":
        with cls._lock:
            if cls._inst is None:
                cls._inst = cls()
            return cls._inst


def _detect(eng: _Faces, bgr: np.ndarray) -> np.ndarray:
    h, w = bgr.shape[:2]
    eng.det.setInputSize((w, h))
    _ok, faces = eng.det.detect(bgr)
    return faces if faces is not None else np.zeros((0, 15), dtype=np.float32)


def _faces_in(bgr: np.ndarray, thorough: bool) -> list[tuple[np.ndarray, np.ndarray]]:
    """[(face row in bgr coordinates, feature vector)]. Big pictures are also searched in overlapping tiles so small faces are found."""
    eng = _Faces.get()
    found: list[np.ndarray] = []
    with ML_LOCK:
        found += list(_detect(eng, bgr))
        H, W = bgr.shape[:2]
        if thorough and max(H, W) > 1400:
            tile, step = 1000, 700
            for y in range(0, max(1, H - tile + step), step):
                for x in range(0, max(1, W - tile + step), step):
                    crop = bgr[y:y + tile, x:x + tile]
                    if min(crop.shape[:2]) < 120:
                        continue
                    for f in _detect(eng, crop):
                        f = f.copy()
                        f[[0, 4, 6, 8, 10, 12]] += x
                        f[[1, 5, 7, 9, 11, 13]] += y
                        found.append(f)
        uniq: list[np.ndarray] = []
        for f in sorted(found, key=lambda r: -float(r[14])):
            b = (f[0], f[1], f[0] + f[2], f[1] + f[3])
            if all(_iou(b, (u[0], u[1], u[0] + u[2], u[1] + u[3])) < 0.4 for u in uniq):
                uniq.append(f)
        out = []
        for f in uniq:
            if min(f[2], f[3]) < 24:  # too small to tell people apart
                continue
            try:
                aligned = eng.rec.alignCrop(bgr, f)
                feat = eng.rec.feature(aligned)
            except cv2.error:
                continue
            out.append((f, feat))
        return out


class PersonRef:
    def __init__(self, image: Image.Image):
        bgr, _ = _bgr(image, 1600)
        faces = _faces_in(bgr, thorough=False)
        if not faces and min(bgr.shape[:2]) < 700:  # a small screenshot: look again, bigger
            k = 2.0 if min(bgr.shape[:2]) >= 300 else 3.0
            faces = _faces_in(cv2.resize(bgr, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC), thorough=False)
            bgr = cv2.resize(bgr, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        self.count = len(faces)
        self.feats: list[np.ndarray] = []
        self.share = 0.0  # how much of the picture the face fills (a profile picture: a lot)
        if faces:  # when the reference shows several people the biggest face is the one to look for
            big = max(faces, key=lambda t: float(t[0][2] * t[0][3]))
            self.feats.append(big[1])
            self.share = float(big[0][2] * big[0][3]) / float(bgr.shape[0] * bgr.shape[1])

    @property
    def usable(self) -> bool:
        return bool(self.feats)


def face_threshold(strictness: float) -> float:
    """SFace cosine threshold: the model's recommended 0.363 sits at 60% strictness."""
    return 0.20 + 0.28 * float(strictness)


def find_person(image: Image.Image, refs: list[PersonRef], strictness: float, thorough: bool = True) -> list[dict]:
    feats = [f for r in refs for f in r.feats]
    if not feats:
        return []
    bgr, scale = _bgr(image, 2600 if thorough else 1600)
    inv = 1.0 / scale
    thr = face_threshold(strictness)
    eng = _Faces.get()
    out = []
    for row, feat in _faces_in(bgr, thorough):
        with ML_LOCK:
            cos = max(float(eng.rec.match(feat, f, cv2.FaceRecognizerSF_FR_COSINE)) for f in feats)
        if cos >= thr:
            x, y, w, h = (float(v) for v in row[:4])
            pad = 0.15 * max(w, h)
            out.append({"text": REF_QUERY, "score": float(min(1.0, max(0.0, 0.5 + (cos - thr) * 1.6))), "cos": cos,
                        "bbox": ((x - pad) * inv, (y - pad) * inv, (x + w + pad) * inv, (y + h + pad) * inv)})
    return _dedupe(out)


# ------------------------------------------------------------------------------------------- front door

_cache: dict = {}
_cache_lock = threading.Lock()


def _key(kind: str, paths: tuple) -> tuple:
    stamp = []
    for p in paths:
        try:
            st = Path(p).stat()
            stamp.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            stamp.append((str(p), 0, 0))
    return (kind, tuple(stamp))


def _guess_kind(paths: tuple, progress=None) -> str:
    """Auto: if every reference picture is mostly one clear face (profile pictures, portraits) look for that person; otherwise look for the thing."""
    if not faces_supported():
        return "like"
    try:
        ensure_face_models(progress)
    except Exception:
        return "like"
    shares = []
    for p in paths:
        try:
            r = PersonRef(load_reference(p))
        except Exception:
            continue
        shares.append(r.share if r.usable else 0.0)
    return "person" if shares and min(shares) >= 0.06 else "like"


def prepare(kind: str, paths: tuple, progress=None):
    """Reads the reference pictures once and returns (references, notes). Returns (references, notes, kind actually used). Raises ValueError with a readable message."""
    if kind not in KINDS:
        kind = "auto"
    if not paths:
        raise ValueError("Add at least one reference picture first.")
    key = _key(kind, paths)
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    if kind == "auto":
        kind = _guess_kind(paths, progress)
    refs, notes = [], []
    if kind == "person":
        if not faces_supported():
            raise ValueError("Face search needs OpenCV 4.9 or newer. Run Fathom.bat again to update it.")
        ensure_face_models(progress)
    for p in paths:
        name = Path(p).name
        try:
            im = load_reference(p)
        except Exception:
            notes.append(f"{name}: could not be opened as a picture, skipped.")
            continue
        if kind == "same":
            r = SameRef(im)
            if not r.usable:
                notes.append(f"{name}: too plain or too small to recognise (needs texture, edges or text). Use “Looks like” instead.")
                continue
        elif kind == "like":
            r = LikeRef(im)
        else:
            r = PersonRef(im)
            if not r.usable:
                notes.append(f"{name}: no clear face found, skipped.")
                continue
            if r.count > 1:
                notes.append(f"{name}: shows {r.count} faces; the biggest one is used.")
        refs.append(r)
    if not refs:
        raise ValueError(" ".join(notes) or "None of the reference pictures could be used.")
    with _cache_lock:
        if len(_cache) > 8:
            _cache.clear()
        _cache[key] = (refs, notes, kind)
    return refs, notes, kind


def find(kind: str, image: Image.Image, refs, strictness: float, thorough: bool = True) -> list[dict]:
    if kind == "same":
        return find_same(image, refs, strictness, thorough)
    if kind == "person":
        return find_person(image, refs, strictness, thorough)
    return find_like(image, refs, strictness, thorough)
