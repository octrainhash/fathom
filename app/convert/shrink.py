"""Make a file smaller or bigger while keeping its format: pictures, video, audio, PDF, Office files, archives and anything else."""
from __future__ import annotations

import io
import math
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.convert.core import ConvertError, Ctx, Opts, safe_stem, file_bytes
from app.convert.eng_data import _enc
from app.convert.formats import category

LOSSY_PICTURES = {"jpg", "webp", "avif", "heic", "jp2"}
ZIP_FAMILY = {"docx", "pptx", "xlsx", "odt", "ods", "odp", "epub", "zip", "jar", "cbz", "xlsm", "dotx", "potx", "xltx", "ppsx", "odg", "ott"}
PCM_AUDIO = {"wav", "aiff", "au", "caf"}
LOSSY_AUDIO = {"mp3", "m4a", "aac", "ogg", "opus", "wma", "ac3", "mp2", "mka", "amr"}
PRESETS = {"light": dict(q=85, side=0, dpi=200, thr=250, crf="balanced", vh=0, ak=192, quant=False),
           "medium": dict(q=72, side=3000, dpi=150, thr=180, crf="balanced", vh=1080, ak=128, quant=False),
           "strong": dict(q=55, side=1920, dpi=100, thr=130, crf="small", vh=720, ak=96, quant=True)}


@dataclass
class SizeSpec:
    mode: str = "smaller"         # smaller | bigger
    level: str = "medium"         # light | medium | strong
    target_bytes: int = 0         # smaller: at most this big; bigger: at least this big (0 = use the level / factor)
    factor: float = 2.0           # bigger: pictures and video are enlarged by this much
    zip_fallback: bool = True     # a format that cannot shrink on its own gets zipped instead
    exact: bool = True            # bigger with a target: add filler so the file is exactly that size
    fill: str = "zero"            # filler kind: zero (fast, compresses to nothing) | random (looks like real data, does not compress)

    @staticmethod
    def from_dict(d: dict) -> "SizeSpec":
        def num(k, default):
            try:
                return float(d.get(k, default))
            except (TypeError, ValueError):
                return default

        unit = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}.get(str(d.get("target_unit", "MB")).upper(), 1024 ** 2)
        target = int(max(0.0, num("target_value", 0)) * unit)
        return SizeSpec(mode="bigger" if d.get("mode") == "bigger" else "smaller",
                        level=d.get("level") if d.get("level") in PRESETS else "medium", target_bytes=target,
                        factor=max(1.1, min(16.0, num("factor", 2))), zip_fallback=bool(d.get("zip_fallback", True)), exact=bool(d.get("exact", True)), fill="random" if d.get("fill") == "random" else "zero")


class Result:
    def __init__(self, path: Path | None = None, note: str = ""):
        self.path, self.note = path, note


def _scratch_file(ctx: Ctx, name: str) -> Path:
    d = ctx.scratch_dir()
    return d / name


# ---------------------------------------------------------------- pictures
def _fit_side(im: Image.Image, side: int) -> Image.Image:
    if not side or max(im.size) <= side:
        return im
    k = side / max(im.size)
    return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)


def _picture_try(frames, durs, first, fmt: str, o: Opts, dst: Path, quant: bool = False) -> int:
    from app.convert.eng_image import save_pil

    if quant and fmt == "png":
        frames = [f.convert("RGBA").quantize(colors=256, method=Image.Quantize.FASTOCTREE) if f.mode in ("RGB", "RGBA") else f for f in frames]
    save_pil(frames, durs, dst, fmt, o, first)
    return file_bytes(dst)


def picture(src: Path, fmt: str, spec: SizeSpec, ctx: Ctx) -> Result:
    from app.convert.eng_image import load_frames

    animated = fmt in ("gif", "webp", "tif", "apng")
    frames, durs, first = load_frames(src, fmt, all_frames=animated)
    orig = file_bytes(src)
    dst = _scratch_file(ctx, f"{safe_stem(src)}.{fmt}")
    o = Opts(strip_metadata=False)
    if spec.mode == "bigger":
        return _picture_bigger(src, fmt, frames, durs, first, spec, ctx, dst, o)
    p = PRESETS[spec.level]
    lossy = fmt in LOSSY_PICTURES
    if not spec.target_bytes:
        o.image_quality = p["q"]
        small = [_fit_side(f, p["side"]) for f in frames]
        size = _picture_try(small, durs, first, fmt, o, dst, quant=p["quant"])
        note = f"Quality {p['q']}%" if lossy else ("Optimised" if fmt in ("png", "gif", "tif") else "")
        if p["side"] and small[0].size != frames[0].size:
            note += f", longest side limited to {p['side']} px"
        if size >= orig:
            if fmt not in LOSSY_PICTURES and fmt not in ("png", "gif", "tif") and not p["side"]:
                return Result(None, "This picture format cannot be compressed without making it smaller in pixels. Try Medium or Strong.")
            return Result(None, "Already as small as it gets in this format.")
        return Result(dst, note.strip(", "))
    # a size to hit
    target = spec.target_bytes
    scales = [1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2, 0.12, 0.07]
    best_path, best_size, best_note = None, None, ""
    for sc in scales:
        ctx.check()
        sized = [f if sc == 1.0 else f.resize((max(1, round(f.width * sc)), max(1, round(f.height * sc))), Image.LANCZOS) for f in frames]
        trial = _scratch_file(ctx, f"t_{safe_stem(src)}.{fmt}")
        if lossy:
            lo, hi, found = 45, 95, None
            o.image_quality = hi
            if _picture_try(sized, durs, first, fmt, o, trial) <= target:
                found = hi
            else:
                while lo <= hi:
                    mid = (lo + hi) // 2
                    o.image_quality = mid
                    if _picture_try(sized, durs, first, fmt, o, trial) <= target:
                        found, lo = mid, mid + 1
                    else:
                        hi = mid - 1
            if found:
                o.image_quality = found
                size = _picture_try(sized, durs, first, fmt, o, dst)
                return Result(dst, f"Quality {found}%" + (f", {round(sc * 100)}% of the original width and height" if sc < 1 else ""))
        else:
            size = _picture_try(sized, durs, first, fmt, o, trial, quant=(sc < 1 and fmt == "png"))
            if size <= target:
                shutil.move(str(trial), str(dst))
                return Result(dst, "Optimised" + (f", {round(sc * 100)}% of the original width and height" if sc < 1 else ""))
        if best_size is None or file_bytes(trial) < best_size:
            if trial.exists():
                best_size = file_bytes(trial)
                best_path = trial
    if best_path is not None and best_size is not None and best_size < orig:
        shutil.move(str(best_path), str(dst))
        return Result(dst, f"Could not reach that size; this is the smallest it can get ({best_size // 1024} KB).")
    return Result(None, "Could not make this picture that small.")


def _picture_bigger(src, fmt, frames, durs, first, spec: SizeSpec, ctx: Ctx, dst: Path, o: Opts) -> Result:
    o.image_quality = 100
    o.level = 6
    w, h = frames[0].size
    cap = 60000

    def make(k: float) -> int:
        k = min(k, cap / max(w, h))
        big = [f.resize((max(1, round(f.width * k)), max(1, round(f.height * k))), Image.LANCZOS) for f in frames]
        return _picture_try(big, durs, first, fmt, o, dst)

    if spec.target_bytes:
        k = max(1.0, math.sqrt(spec.target_bytes / max(1, file_bytes(src))))
        for _ in range(5):
            ctx.check()
            size = make(k)
            if size >= spec.target_bytes or k * max(w, h) >= cap:
                break
            k *= max(1.05, math.sqrt(spec.target_bytes / max(1, size)) * 1.02)
        return Result(dst, f"Enlarged {k:.1f}× (Lanczos) at the highest quality; no new detail is created.")
    make(spec.factor)
    return Result(dst, f"Enlarged {spec.factor:g}× (Lanczos) at the highest quality; no new detail is created.")


# ---------------------------------------------------------------- video and audio
def _strip_quality(args: list[str]) -> list[str]:
    out, i = [], 0
    while i < len(args):
        if args[i] in ("-crf", "-q:v", "-b:v") and i + 1 < len(args):
            i += 2
            continue
        out.append(args[i])
        i += 1
    return out


def video(src: Path, fmt: str, spec: SizeSpec, ctx: Ctx) -> Result:
    from app.convert.eng_media import VIDEO_OUT, _ok, probe, run_ffmpeg, video_args

    if fmt not in VIDEO_OUT or fmt == "gif" or not _ok(VIDEO_OUT[fmt]):
        raise ConvertError(f"Fathom cannot re-encode .{fmt} video here.")
    info = probe(ctx, src)
    dur = info["duration"]
    orig = file_bytes(src)
    dst = _scratch_file(ctx, f"{safe_stem(src)}.{fmt}")
    p = PRESETS[spec.level]
    if spec.mode == "bigger":
        o = Opts(video_quality="high", audio_kbps=256)
        args = video_args(fmt, o, info["audio"])
        vf = f"scale=trunc(iw*{spec.factor:g}/2)*2:trunc(ih*{spec.factor:g}/2)*2"
        if spec.target_bytes and dur:
            vk = int(spec.target_bytes * 8 * 0.96 / dur / 1000) - 256
            args = _strip_quality(args) + ["-b:v", f"{max(200, vk)}k", "-minrate", f"{max(200, vk)}k", "-maxrate", f"{max(200, vk)}k", "-bufsize", f"{max(400, vk * 2)}k"]
            vf = "null"
        if "-vf" in args:
            i = args.index("-vf")
            args[i + 1] = vf + "," + args[i + 1] if vf != "null" else args[i + 1]
        elif vf != "null":
            args = ["-vf", vf] + args
        run_ffmpeg(ctx, ["-i", src, *args, dst], dur, "enlarge")
        return Result(dst, "Re-encoded at higher quality" + ("" if vf == "null" else f" and enlarged {spec.factor:g}×") + "; no new detail is created.")
    if spec.target_bytes and dur:
        ak = 96 if info["audio"] else 0
        for attempt in range(3):
            ctx.check()
            total_k = spec.target_bytes * 8 * (0.94 - 0.04 * attempt) / dur / 1000
            vk = max(60, int(total_k - ak))
            fps = info["fps"] or 25
            cap = 0
            for h_try in (2160, 1440, 1080, 720, 480, 360, 240):
                if info["h"] and h_try > info["h"]:
                    continue
                w_try = (info["w"] / info["h"]) * h_try if info["h"] else h_try * 16 / 9
                if vk * 1000 / (w_try * h_try * fps) >= 0.06 or h_try == 240:
                    cap = h_try
                    break
            o = Opts(video_quality="balanced", video_height=cap, audio_kbps=ak or 96)
            args = _strip_quality(video_args(fmt, o, info["audio"])) + ["-b:v", f"{vk}k", "-maxrate", f"{int(vk * 1.3)}k", "-bufsize", f"{vk * 2}k"]
            run_ffmpeg(ctx, ["-i", src, *args, dst], dur, "shrink")
            if file_bytes(dst) <= spec.target_bytes:
                break
        note = f"Re-encoded at about {vk} kbps" + (f", limited to {cap}p" if cap else "")
        if file_bytes(dst) > spec.target_bytes:
            note += f" (came out {file_bytes(dst) // 1024 // 1024} MB, a little over the target)"
    else:
        o = Opts(video_quality=p["crf"], video_height=p["vh"], audio_kbps=p["ak"])
        run_ffmpeg(ctx, ["-i", src, *video_args(fmt, o, info["audio"]), dst], dur, "shrink")
        note = f"Re-encoded ({spec.level})" + (f", limited to {p['vh']}p" if p["vh"] else "")
    if file_bytes(dst) >= orig:
        return Result(None, "This video is already compressed more efficiently than Fathom can do; re-encoding would make it bigger.")
    return Result(dst, note)


def audio(src: Path, fmt: str, spec: SizeSpec, ctx: Ctx) -> Result:
    from app.convert.eng_media import AUDIO_OUT, _ok, audio_args, probe, run_ffmpeg

    if fmt not in AUDIO_OUT or not _ok(AUDIO_OUT[fmt]):
        raise ConvertError(f"Fathom cannot re-encode .{fmt} audio here.")
    info = probe(ctx, src)
    dur = info["duration"]
    orig = file_bytes(src)
    dst = _scratch_file(ctx, f"{safe_stem(src)}.{fmt}")
    p = PRESETS[spec.level]
    extra: list = []
    if fmt in PCM_AUDIO or fmt == "flac":
        rates = [44100, 32000, 22050, 16000, 11025, 8000]
        if spec.mode == "bigger":
            return Result(None, "Lossless sound cannot be made bigger in any useful way. Use the Pad option with a target size.")
        if spec.target_bytes and dur:
            choice = None
            for mono in (False, True):
                for r in rates:
                    est = dur * r * (1 if mono else 2) * 2 * (0.6 if fmt == "flac" else 1)
                    if est <= spec.target_bytes:
                        choice = (r, mono)
                        break
                if choice:
                    break
            r, mono = choice or (8000, True)
        else:
            r, mono = {"light": (44100, False), "medium": (32000, False), "strong": (22050, True)}[spec.level]
        extra = ["-ar", str(r)] + (["-ac", "1"] if mono else [])
        o = Opts(audio_kbps=192)
        run_ffmpeg(ctx, ["-i", src, "-vn", *extra, *audio_args(fmt, o), dst], dur, "shrink")
        note = f"Re-sampled to {r // 1000 if r % 1000 == 0 else r / 1000:g} kHz" + (" mono" if mono else "")
    else:
        if spec.mode == "bigger":
            kb = 320
        elif spec.target_bytes and dur:
            kb = int(max(24, min(320, spec.target_bytes * 8 * 0.95 / dur / 1000)))
        else:
            kb = p["ak"] if spec.level != "light" else 160
        o = Opts(audio_kbps=kb)
        run_ffmpeg(ctx, ["-i", src, "-vn", *audio_args(fmt, o), dst], dur, "re-encode")
        note = f"Re-encoded at {kb} kbps" + ("; a lossy sound cannot gain real quality." if spec.mode == "bigger" else "")
    if spec.mode == "smaller" and file_bytes(dst) >= orig:
        return Result(None, "Already compressed as much as it can be.")
    return Result(dst, note)


# ---------------------------------------------------------------- PDF
def pdf(src: Path, fmt: str, spec: SizeSpec, ctx: Ctx) -> Result:
    from app.convert.eng_docs import get_fitz, open_doc

    if spec.mode == "bigger":
        return Result(None, "PDFs cannot be made bigger in a useful way. Use the Pad option with a target size.")
    fitz = get_fitz()
    if fitz is None:
        raise ConvertError("PDF tools are not installed.")
    orig = file_bytes(src)
    dst = _scratch_file(ctx, f"{safe_stem(src)}.pdf")
    levels = [spec.level] if not spec.target_bytes else ["light", "medium", "strong", "ultra"]
    chosen = None
    for lv in levels:
        ctx.check()
        doc = open_doc(src, Opts())
        try:
            p = PRESETS.get(lv, dict(q=35, dpi=72, thr=90))
            if hasattr(doc, "rewrite_images"):
                try:
                    doc.rewrite_images(dpi_threshold=p["thr"], dpi_target=p["dpi"], quality=p["q"])
                except Exception:
                    pass
            kw = dict(garbage=4, deflate=True, clean=True)
            try:
                doc.save(str(dst), use_objstms=1, deflate_images=True, deflate_fonts=True, **kw)
            except TypeError:
                doc.save(str(dst), **kw)
        finally:
            doc.close()
        chosen = lv
        if not spec.target_bytes or file_bytes(dst) <= spec.target_bytes:
            break
    size = file_bytes(dst)
    if size >= orig:
        return Result(None, "This PDF is already compressed as much as it can be.")
    note = f"Pictures inside were reduced ({chosen})."
    if spec.target_bytes and size > spec.target_bytes:
        note = f"Could not reach that size; this is the smallest it can get ({size // 1024} KB)."
    return Result(dst, note)


# ---------------------------------------------------------------- Office files, e-books and ZIP archives
def zip_family(src: Path, fmt: str, spec: SizeSpec, ctx: Ctx) -> Result:
    if spec.mode == "bigger":
        return Result(None, "Use the Pad option to make this file bigger.")
    orig = file_bytes(src)
    levels = [spec.level] if not spec.target_bytes else ["light", "medium", "strong"]
    dst = _scratch_file(ctx, src.name)
    for lv in levels:
        ctx.check()
        p = PRESETS[lv]
        _recompress_zip(src, dst, p["q"], p["side"] or 4000, p["quant"], ctx)
        if not spec.target_bytes or file_bytes(dst) <= spec.target_bytes:
            break
    size = file_bytes(dst)
    if size >= orig:
        return Result(None, "Nothing inside could be compressed any further.")
    return Result(dst, "Pictures inside were recompressed" + (f" ({lv})" if len(levels) > 1 else f" ({spec.level})") + ".")


def _recompress_zip(src: Path, dst: Path, quality: int, side: int, quant: bool, ctx: Ctx) -> None:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", allowZip64=True) as zout:
        infos = zin.infolist()
        for n, info in enumerate(infos, 1):
            ctx.check()
            if info.is_dir():
                zout.writestr(info, b"")
                continue
            ext = info.filename.lower().rsplit(".", 1)[-1] if "." in info.filename else ""
            new = zipfile.ZipInfo(info.filename, info.date_time)
            new.external_attr = info.external_attr
            new.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            if ext in ("jpg", "jpeg", "png") and info.file_size > 20000:
                data = zin.read(info)
                try:
                    im = Image.open(io.BytesIO(data))
                    im.load()
                    im = _fit_side(im, side)
                    buf = io.BytesIO()
                    if ext == "png":
                        if quant and im.mode in ("RGB", "RGBA"):
                            im = im.convert("RGBA" if im.mode == "RGBA" else "RGB").quantize(colors=256, method=Image.Quantize.FASTOCTREE)
                        im.save(buf, "PNG", optimize=True)
                    else:
                        im.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
                    if len(buf.getvalue()) < len(data):
                        data = buf.getvalue()
                except Exception:
                    pass
                zout.writestr(new, data, compresslevel=9)
            else:
                with zin.open(info) as fin, zout.open(new, "w", force_zip64=True) as fout:
                    shutil.copyfileobj(fin, fout, 1 << 20)
            ctx.progress(n / len(infos))


# ---------------------------------------------------------------- archives and everything else
def archive(src: Path, fmt: str, spec: SizeSpec, ctx: Ctx) -> Result:
    from app.convert.eng_misc import extract_to, pack_from

    if spec.mode == "bigger":
        return Result(None, "Use the Pad option to make this file bigger.")
    work = ctx.scratch_dir()
    o = Opts(level=9)
    extract_to(src, fmt, work, o, ctx)
    dst = _scratch_file(ctx, src.name)
    pack_from(work, dst, fmt, o, ctx)
    if file_bytes(dst) >= file_bytes(src):
        return Result(None, "This archive is already compressed as much as it can be.")
    return Result(dst, "Re-packed with the strongest compression.")


def text_minify(src: Path, fmt: str, spec: SizeSpec, ctx: Ctx) -> Result | None:
    if fmt == "json" and spec.mode == "smaller":
        import json

        try:
            data = json.loads(src.read_text(encoding=_enc(src)))
        except ValueError:
            return None
        dst = _scratch_file(ctx, src.name)
        dst.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if file_bytes(dst) < file_bytes(src):
            return Result(dst, "Extra spaces and line breaks removed (the data is unchanged).")
    return None


def pad(src: Path, spec: SizeSpec, ctx: Ctx) -> Result:
    """Adds filler bytes at the end until the file has the wanted size (most programs ignore them)."""
    if not spec.target_bytes:
        return Result(None, "Enter the size you want to reach.")
    cur = file_bytes(src)
    if cur >= spec.target_bytes:
        return Result(None, "The file is already at least that big.")
    from app.convert.formats import detect

    text_like = category(detect(src)) in ("text", "data", "subtitle")
    dst = _scratch_file(ctx, src.name)
    shutil.copyfile(src, dst)
    remaining = spec.target_bytes - cur
    rnd = spec.fill == "random"
    block = (b" " * 1023 + b"\n") if text_like else bytes(1 << 20)
    with open(dst, "ab") as fh:
        while remaining > 0:
            ctx.check()
            if rnd:
                block = os.urandom(min(1 << 20, remaining))
            chunk = block[: min(len(block), remaining)]
            fh.write(chunk)
            remaining -= len(chunk)
            if remaining % (64 << 20) < len(chunk):
                ctx.progress(1 - remaining / (spec.target_bytes - cur))
    return Result(dst, "Filler (" + ("random data" if rnd else "blank space" if text_like else "zero bytes") + ") was added at the end. Most programs ignore it, but a few strict ones may complain.")


def zip_it(src: Path, ctx: Ctx) -> Result:
    from app.convert.eng_misc import pack_from

    work = ctx.scratch_dir()
    try:
        os.link(src, work / src.name)
    except OSError:
        shutil.copy2(src, work / src.name)
    dst = _scratch_file(ctx, src.name + ".zip")
    pack_from(work, dst, "zip", Opts(level=9), ctx)
    if file_bytes(dst) >= file_bytes(src):
        return Result(None, "Compressing it would not make it any smaller.")
    return Result(dst, "This format cannot shrink on its own, so it was zipped instead.")


def resize_file(src: Path, fmt: str, spec: SizeSpec, ctx: Ctx) -> Result:
    """Picks the right method for the file's format."""
    from app.convert.eng_image import rw
    from app.convert.eng_media import AUDIO_IN, VIDEO_IN

    cat = category(fmt)
    if spec.mode == "bigger" and spec.target_bytes and not (fmt in rw()[1] or fmt in VIDEO_IN or fmt in AUDIO_IN):
        return pad(src, spec, ctx)
    res: Result | None = None
    if fmt in rw()[0] and fmt in rw()[1] and fmt not in ("pdf",):
        res = picture(src, fmt, spec, ctx)
    elif fmt in VIDEO_IN and fmt != "gif":
        res = video(src, fmt, spec, ctx)
    elif fmt == "gif":
        res = picture(src, fmt, spec, ctx)
    elif fmt in AUDIO_IN:
        res = audio(src, fmt, spec, ctx)
    elif fmt == "pdf":
        res = pdf(src, fmt, spec, ctx)
    elif fmt in ZIP_FAMILY:
        res = zip_family(src, fmt, spec, ctx)
    elif fmt in ("tar", "tar.gz", "tar.bz2", "tar.xz", "7z", "gz", "bz2", "xz"):
        res = archive(src, fmt, spec, ctx)
    else:
        res = text_minify(src, fmt, spec, ctx)
    if res is None:
        res = Result(None, "")
    if res.path is None and spec.mode == "smaller" and spec.zip_fallback and fmt not in ZIP_FAMILY and fmt not in ("tar.gz", "tar.bz2", "tar.xz", "7z", "gz", "bz2", "xz") \
            and "already" not in res.note.lower():
        z = zip_it(src, ctx)
        if z.path is not None:
            return z
        return Result(None, z.note)
    if res.path is None and not res.note:
        res.note = "Nothing to do for this kind of file."
    # bigger with a target: top up with filler so the size is exact
    if spec.mode == "bigger" and spec.target_bytes and spec.exact and res.path is not None and file_bytes(res.path) < spec.target_bytes:
        padded = pad(res.path, spec, ctx)
        if padded.path is not None:
            res = Result(padded.path, res.note + " " + padded.note)
    elif spec.mode == "bigger" and res.path is not None and file_bytes(res.path) <= file_bytes(src):
        return Result(None, "That did not make the file any bigger.")
    return res
