# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Pictures: every image format Pillow can read or write (plus HEIC, AVIF and camera RAW when their packages are present),
and reading the text out of a picture (OCR)."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageFile, ImageOps, ImageSequence

from app.convert import adjust
from app.convert.core import ConvertError, Ctx, Edge, Engine, Opts, safe_stem
from app.convert.formats import FORMATS, known_fmt

Image.MAX_IMAGE_PIXELS = None
ImageFile.LOAD_TRUNCATED_IMAGES = True

HEIF = False
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    try:
        pillow_heif.register_avif_opener()
    except Exception:
        pass
    HEIF = True
except Exception:
    pass

try:
    import rawpy  # type: ignore

    HAVE_RAW = True
except Exception:
    HAVE_RAW = False

# format id -> Pillow format name used to save it
SAVE_NAME = {"png": "PNG", "jpg": "JPEG", "gif": "GIF", "bmp": "BMP", "tif": "TIFF", "webp": "WEBP", "ico": "ICO", "icns": "ICNS",
             "tga": "TGA", "ppm": "PPM", "pgm": "PPM", "pbm": "PPM", "pcx": "PCX", "sgi": "SGI", "dds": "DDS", "jp2": "JPEG2000",
             "avif": "AVIF", "heic": "HEIF", "eps": "EPS", "pdf": "PDF", "xbm": "XBM", "apng": "PNG",
             "qoi": "QOI", "im": "IM"}
ANIMATED_OUT = {"gif", "webp", "apng", "tif", "pdf"}


def _gs_present() -> bool:
    import shutil

    return bool(shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs"))


def _tables() -> tuple[set[str], set[str]]:
    Image.init()
    reg = Image.registered_extensions()
    reads: set[str] = set()
    writes: set[str] = set()
    for ext, fmt in reg.items():
        fid = known_fmt(ext)
        if not fid or FORMATS[fid][1] != "image":
            continue
        if fmt in Image.OPEN:
            reads.add(fid)
    for fid, name in SAVE_NAME.items():
        if name in Image.SAVE:
            writes.add(fid)
    if "eps" in reads and not _gs_present():
        reads.discard("eps")
    if HAVE_RAW:
        reads.add("raw")
    if sys.platform != "win32":
        reads.discard("emf")
        reads.discard("wmf")
    reads.discard("svg")
    if "png" in reads:
        reads.add("apng")
    if "heic" in writes and not HEIF:
        writes.discard("heic")
    return reads, writes


_RW: tuple[set[str], set[str]] | None = None


def rw() -> tuple[set[str], set[str]]:
    global _RW
    if _RW is None:
        _RW = _tables()
    return _RW


# ---------------------------------------------------------------- loading and saving
def load_frames(path: Path, fmt: str, all_frames: bool = True, upright: bool = True) -> tuple[list[Image.Image], list[int], Image.Image]:
    """Returns (frames, durations in ms, the first image object (for its metadata))."""
    if fmt == "raw":
        if not HAVE_RAW:
            raise ConvertError("Camera RAW photos need the 'rawpy' package (run Fathom.bat repair with internet).")
        with rawpy.imread(str(path)) as raw:  # type: ignore[name-defined]
            rgb = raw.postprocess(use_camera_wb=True)
        img = Image.fromarray(rgb)
        return [img], [0], img
    try:
        im = Image.open(path)
    except Exception as exc:
        raise ConvertError(f"This picture could not be opened ({type(exc).__name__}: {exc}).")
    frames: list[Image.Image] = []
    durations: list[int] = []
    n = getattr(im, "n_frames", 1)
    if n > 1 and all_frames:
        for frame in ImageSequence.Iterator(im):
            durations.append(int(frame.info.get("duration", 100) or 100))
            frames.append(frame.copy())
    else:
        im.seek(0)
        frames.append(im.copy())
        durations.append(int(im.info.get("duration", 100) or 100))
    if upright and len(frames) == 1:
        try:
            frames[0] = ImageOps.exif_transpose(frames[0])
        except Exception:
            pass
    return frames, durations, im


def to_8bit(im: Image.Image) -> Image.Image:
    if im.mode in ("I;16", "I;16L", "I;16B", "I", "F"):
        import numpy as np

        arr = np.asarray(im).astype("float64")
        top = arr.max() if arr.size else 1
        scale = 255.0 / (65535.0 if top > 255 else max(top, 1))
        return Image.fromarray(np.clip(arr * scale, 0, 255).astype("uint8"), "L")
    return im


def has_alpha(im: Image.Image) -> bool:
    return im.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (im.mode == "P" and "transparency" in im.info)


def flatten(im: Image.Image, bg: str) -> Image.Image:
    im = to_8bit(im)
    if has_alpha(im):
        rgba = im.convert("RGBA")
        base = Image.new("RGBA", rgba.size, ImageColor.getrgb(bg) + (255,))
        base.alpha_composite(rgba)
        return base.convert("RGB")
    if im.mode in ("RGB", "L"):
        return im
    return im.convert("RGB")


def resized(im: Image.Image, o: Opts) -> Image.Image:
    w, h = im.size
    if o.resize == "percent" and o.resize_percent and o.resize_percent != 100:
        nw, nh = max(1, round(w * o.resize_percent / 100)), max(1, round(h * o.resize_percent / 100))
    elif o.resize == "fit" and (o.max_width or o.max_height):
        k = min((o.max_width / w) if o.max_width else 1e9, (o.max_height / h) if o.max_height else 1e9)
        if k >= 1:
            return im
        nw, nh = max(1, round(w * k)), max(1, round(h * k))
    else:
        return im
    if im.mode in ("P", "1"):
        im = im.convert("RGBA" if has_alpha(im) else "RGB")
    method = {"bicubic": Image.BICUBIC, "bilinear": Image.BILINEAR, "nearest": Image.NEAREST}.get(str(o.img_resample), Image.LANCZOS)
    return im.resize((nw, nh), method)


def _autotrim(im: Image.Image) -> Image.Image:
    """Cuts off edges that are all one colour (or fully see-through)."""
    if has_alpha(im):
        box = im.convert("RGBA").getchannel("A").getbbox()
        if box and box != (0, 0, *im.size):
            return im.crop(box)
    rgb = to_8bit(im).convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, rgb.getpixel((0, 0))))
    diff = ImageChops.add(diff, diff, 2.0, -10)
    box = diff.getbbox()
    return im.crop(box) if box and box != (0, 0, *im.size) else im


def _crop_aspect(im: Image.Image, ratio: tuple[int, int]) -> Image.Image:
    w, h = im.size
    n, d = ratio
    if w * d > h * n:                      # too wide: cut the sides
        nw, nh = max(1, round(h * n / d)), h
    else:                                  # too tall: cut top and bottom
        nw, nh = w, max(1, round(w * d / n))
    left, top = (w - nw) // 2, (h - nh) // 2
    return im.crop((left, top, left + nw, top + nh))


def shaped(im: Image.Image, o: Opts) -> Image.Image:
    """Cut empty edges and crop to a new shape. Done before resizing, so the size limits apply to the result."""
    if not adjust.image_shape_active(o):
        return im
    if im.mode in ("P", "1"):
        im = im.convert("RGBA" if has_alpha(im) else "RGB")
    if o.img_autotrim:
        im = _autotrim(im)
    ratio = adjust.ASPECTS.get(str(o.img_aspect))
    if ratio:
        im = _crop_aspect(im, ratio)
    return im


def _quantize(im: Image.Image, colors: int) -> Image.Image:
    Q = getattr(Image, "Quantize", Image)
    if has_alpha(im):
        return im.convert("RGBA").quantize(colors=colors, method=Q.FASTOCTREE)
    return im.convert("RGB").quantize(colors=colors, method=Q.MEDIANCUT)


def finished(im: Image.Image, o: Opts) -> Image.Image:
    """Fewer colours, then a border. Done last."""
    if not adjust.image_finish_active(o):
        return im
    n = int(o.img_palette)
    if n > 0:
        im = _quantize(to_8bit(im), max(2, min(256, n)))
    b = max(0, min(2000, int(o.img_border)))
    if b:
        try:
            fill = ImageColor.getrgb(o.img_border_color or "#ffffff")
        except ValueError:
            fill = (255, 255, 255)
        if im.mode == "P":
            im = im.convert("RGBA" if has_alpha(im) else "RGB")
        if im.mode == "RGBA" and len(fill) == 3:
            fill = fill + (255,)
        elif im.mode == "L":
            fill = fill[0]
        im = ImageOps.expand(im, border=b, fill=fill)
    return im


def adjusted(im: Image.Image, o: Opts) -> Image.Image:
    """Turn, flip, lighting, colour, sharpness and blur (see the picture options). Transparent areas stay transparent."""
    if not adjust.image_active(o):
        return im
    from PIL import ImageEnhance, ImageFilter

    T = getattr(Image, "Transpose", Image)
    im = to_8bit(im)
    alpha = None
    if has_alpha(im):
        rgba = im.convert("RGBA")
        alpha = rgba.getchannel("A")
        im = rgba.convert("RGB")
    elif im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    # turn and flip (the see-through mask follows the picture)
    turn = {"90": T.ROTATE_270, "180": T.ROTATE_180, "270": T.ROTATE_90}.get(str(o.img_rotate))
    flips = []
    if o.img_flip in ("h", "both"):
        flips.append(T.FLIP_LEFT_RIGHT)
    if o.img_flip in ("v", "both"):
        flips.append(T.FLIP_TOP_BOTTOM)
    for op in ([turn] if turn is not None else []) + flips:
        im = im.transpose(op)
        if alpha is not None:
            alpha = alpha.transpose(op)
    if o.img_auto_levels:
        im = ImageOps.autocontrast(im, cutoff=1)
    if int(o.img_brightness) != 100:
        im = ImageEnhance.Brightness(im).enhance(max(0, int(o.img_brightness)) / 100)
    if int(o.img_contrast) != 100:
        im = ImageEnhance.Contrast(im).enhance(max(0, int(o.img_contrast)) / 100)
    if int(o.img_saturation) != 100 and im.mode == "RGB":
        im = ImageEnhance.Color(im).enhance(max(0, int(o.img_saturation)) / 100)
    if int(o.img_sharpness) != 100:
        im = ImageEnhance.Sharpness(im).enhance(max(0, int(o.img_sharpness)) / 100)
    if o.img_blur and o.img_blur > 0:
        im = im.filter(ImageFilter.GaussianBlur(radius=min(100.0, float(o.img_blur))))
    if o.img_grayscale:
        im = im.convert("L").convert("RGB")
    if o.img_invert:
        im = ImageOps.invert(im.convert("RGB"))
    if alpha is not None:
        im = im.convert("RGBA")
        im.putalpha(alpha)
    return im


def _prep(im: Image.Image, t: str, o: Opts) -> Image.Image:
    im = to_8bit(im)
    if t in ("jpg", "bmp", "pcx", "eps", "pdf", "ppm", "xbm", "pgm", "pbm") or (t == "tif" and im.mode == "P"):
        im = flatten(im, o.background)
    if t == "jpg" and im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if t == "pgm":
        im = im.convert("L")
    elif t in ("pbm", "xbm"):
        im = im.convert("1")
    elif t == "ppm":
        im = im.convert("RGB")
    elif t in ("png", "tga", "webp", "avif", "heic", "sgi", "dds", "jp2", "icns", "tif", "apng"):
        if im.mode in ("CMYK", "YCbCr", "LAB", "HSV") and t != "tif":
            im = im.convert("RGB")
        elif im.mode == "P" and not (o.img_palette and t in ("png", "apng")):
            im = im.convert("RGBA" if has_alpha(im) else "RGB")
        elif im.mode == "1" and t in ("webp", "avif", "heic", "jp2", "icns", "dds"):
            im = im.convert("L")
    return im


def _square(im: Image.Image, size: int) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    k = size / max(w, h)
    im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    return canvas


def save_pil(frames: list[Image.Image], durations: list[int], dst: Path, t: str, o: Opts, src_img: Image.Image | None = None) -> None:
    """Saves one or more frames as format t."""
    fmt = SAVE_NAME[t]
    frames = [_prep(finished(adjusted(resized(shaped(f, o), o), o), o), t, o) for f in frames]
    first = frames[0]
    kw: dict = {}
    q = max(1, min(100, int(o.image_quality)))
    if not o.strip_metadata and src_img is not None and t in ("jpg", "png", "webp", "tif", "avif", "heic", "apng"):
        try:
            exif = src_img.getexif()
            if exif:
                exif.pop(0x0112, None)  # orientation was already applied
                kw["exif"] = exif.tobytes()
        except Exception:
            pass
        icc = (src_img.info or {}).get("icc_profile")
        if icc and t in ("jpg", "png", "webp", "tif", "apng"):
            kw["icc_profile"] = icc
    if t == "jpg":
        kw.update(quality=q, optimize=True, progressive=q < 100, subsampling=0 if q >= 92 else -1)
    elif t == "webp":
        kw.update(quality=q, method=4, lossless=q >= 100)
    elif t in ("avif", "heic"):
        kw.update(quality=q)
    elif t in ("png", "apng"):
        kw.update(optimize=True)
    elif t == "tif":
        kw.update(compression="tiff_lzw")
    elif t == "jp2":
        kw.update(quality_mode="rates", quality_layers=[max(1.0, (101 - q) / 5)], irreversible=q < 100)
    elif t == "ico":
        first = _square(first, 256)
        wanted = []
        for tok in (o.ico_sizes or "").split(","):
            tok = tok.strip()
            if tok.isdigit() and 8 <= int(tok) <= 256:
                wanted.append((int(tok), int(tok)))
        kw["sizes"] = wanted or [(32, 32), (256, 256)]
        frames = [first]
    elif t == "icns":
        first = _square(first, 512)
        frames = [first]
    elif t == "pdf":
        kw["resolution"] = float(o.pdf_dpi or 150)
    elif t == "gif":
        kw.update(optimize=True)
    if int(o.img_dpi) > 0 and t in ("jpg", "png", "apng", "tif", "bmp"):
        kw["dpi"] = (int(o.img_dpi), int(o.img_dpi))
    if o.strip_metadata:
        kw.pop("exif", None)
        kw.pop("icc_profile", None)
    animated = len(frames) > 1 and t in ANIMATED_OUT
    try:
        if animated:
            extra: dict = dict(save_all=True, append_images=frames[1:])
            if t in ("gif", "webp", "apng"):
                extra.update(duration=durations, loop=0)
            first.save(dst, fmt, **{**kw, **extra})
        else:
            first.save(dst, fmt, **kw)
    except OSError as exc:
        if "cannot write mode" in str(exc):
            first.convert("RGB").save(dst, fmt, **kw)
        else:
            raise ConvertError(f"Could not write {t.upper()}: {exc}")
    except (ValueError, KeyError, NotImplementedError) as exc:
        raise ConvertError(f"Could not write {t.upper()}: {exc}")


class ImageEngine(Engine):
    name = "image"
    label = "Pictures"
    cost = 1.0
    same_ok = True

    def can(self, s: str, t: str) -> Edge | None:
        if s == t:
            r, w = rw()
            if s in r and s in w and s not in ("apng", "gif", "ico", "icns"):
                return Edge(s, t, self, 2.6, "Same type: only your adjustments are applied (quality, size, colours, turn...).")
            return None
        return super().can(s, t)

    def reads(self) -> set[str]:
        return rw()[0]

    def writes(self) -> set[str]:
        return rw()[1]

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        ctx.check()
        if s == t and not adjust.image_changes(o):
            raise ConvertError("Nothing to change. Pick a setting first (quality, size, brightness, turn...) or choose a different type.")
        animated_target = t in ANIMATED_OUT
        frames, durations, first = load_frames(src, s, all_frames=animated_target or o.all_frames)
        stem = safe_stem(src)
        out_dir.mkdir(parents=True, exist_ok=True)
        if len(frames) > 1 and not animated_target:
            if o.all_frames:
                outs = []
                for i, fr in enumerate(frames, 1):
                    dst = out_dir / f"{stem}_frame{i:04d}.{t}"
                    save_pil([fr], durations[i - 1:i], dst, t, o, first)
                    outs.append(dst)
                    ctx.progress(i / len(frames))
                return outs
            frames, durations = frames[:1], durations[:1]
        dst = out_dir / f"{stem}.{t}"
        save_pil(frames, durations, dst, t, o, first)
        return [dst]


class OcrEngine(Engine):
    name = "ocr"
    label = "Read text from pictures (OCR)"
    cost = 2.2
    heavy = True
    needs = "the text reader (OCR)"

    def available(self) -> bool:
        try:
            import importlib.util

            return importlib.util.find_spec("rapidocr_onnxruntime") is not None
        except Exception:
            return False

    def reads(self) -> set[str]:
        return {f for f in rw()[0] if f != "apng"}

    def writes(self) -> set[str]:
        return {"txt"}

    def can(self, s: str, t: str) -> Edge | None:
        e = super().can(s, t)
        if e:
            e.note = "The text is read from the picture by OCR, so it can contain mistakes."
        return e

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        from app.ocr import ocr_boxes
        from app.runtime import ML_LOCK

        frames, _d, _f = load_frames(src, s, all_frames=True)
        parts: list[str] = []
        for i, fr in enumerate(frames[:200], 1):
            ctx.check()
            with ML_LOCK:
                toks = ocr_boxes(fr)
            parts.append(lines_from_tokens(toks))
            ctx.progress(i / len(frames))
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / f"{safe_stem(src)}.txt"
        dst.write_text("\n\n".join(p for p in parts if p) or "", encoding="utf-8")
        return [dst]


def lines_from_tokens(tokens: list[dict]) -> str:
    """Turns OCR boxes into reading-order text lines."""
    toks = [t for t in tokens if t.get("text", "").strip()]
    if not toks:
        return ""
    toks.sort(key=lambda t: ((t["bbox"][1] + t["bbox"][3]) / 2, t["bbox"][0]))
    lines: list[list[dict]] = []
    for t in toks:
        cy = (t["bbox"][1] + t["bbox"][3]) / 2
        h = max(1.0, t["bbox"][3] - t["bbox"][1])
        if lines:
            last = lines[-1]
            ly = sum((x["bbox"][1] + x["bbox"][3]) / 2 for x in last) / len(last)
            lh = sum(x["bbox"][3] - x["bbox"][1] for x in last) / len(last)
            if abs(cy - ly) < 0.6 * min(h, lh):
                last.append(t)
                continue
        lines.append([t])
    return "\n".join(" ".join(x["text"].strip() for x in sorted(line, key=lambda x: x["bbox"][0])) for line in lines)
