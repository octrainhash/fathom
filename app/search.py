# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Search one file (of any kind) and report every match with a highlighted, circled picture."""
from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from PIL import Image

from app import extract
from app.annotate import annotate, crop_thumb, save_image, shrink_for_display, to_rgb, union_box
from app.paths import temp_dir
from app.query import compile_query, find_spans, make_snippet, span_to_box
from app.textsnap import render_snapshot

PDF_ZOOM = 2.0
MAX_ARCHIVE_DEPTH = 6


def _num(d: dict, key: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(d.get(key, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _bool(d: dict, key: str, default: bool) -> bool:
    v = d.get(key, default)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "on", "yes"}
    return bool(v)


@dataclass
class Options:
    query: str = ""
    mode: str = "text"          # "text" = words/numbers (incl. text inside pictures); "object" = the actual thing
    refs: tuple = ()            # object mode: paths of reference pictures to look for instead of a typed word
    ref_kind: str = "auto"      # "auto" | "same" (this exact item) | "like" (looks like it) | "person" (same face)
    case_sensitive: bool = False
    use_regex: bool = False
    whole_word: bool = False
    ocr: bool = True            # read text inside pictures / scans
    handwriting: bool = False   # also read handwriting in pictures / scans (and match it forgivingly)
    strictness: float = 0.6     # object mode: 0.2 loose ... 0.95 strict
    thorough: bool = True       # object mode on pictures: look at small details too
    scan_every: float = 0.0     # video: seconds between checks (0 = automatic)
    slowmo: float = 4.0         # video clip slow-down factor
    before: float = 2.0         # video clip: seconds before the match
    after: float = 2.0          # video clip: seconds after the match
    ramp: bool = True           # (older setting) slow down only while the match is on screen
    clipmode: str = "result"    # "result" = slow down while the result is on screen | "all" = slow the whole clip | "pause" = stop on the full result
    hold: float = 2.0           # seconds the picture stays frozen on the full result (0 = never)
    changes: bool = False       # video: also mark sudden changes (cuts, flashes)
    listen: bool = False        # audio/video: also search spoken words (same as media_speech)
    media_text: bool = True     # videos: look for the WORDS written on screen
    media_object: bool = False  # videos: look for the actual THING (a real butterfly, not the word)
    media_speech: bool = False  # videos and audio: look for SPOKEN words
    speech_model: str = "base"
    only: tuple = ()            # look only in these kinds of file: "documents", "pictures", "videos", "audio" (empty = everything)
    recursive: bool = True
    skip_junk: bool = True
    include_cloud: bool = False

    @staticmethod
    def from_dict(d: dict) -> "Options":
        model = str(d.get("speech_model", "base"))
        refs = tuple(str(x) for x in (d.get("refs") or []) if isinstance(x, str) and x.strip())[:12]
        query = str(d.get("query", "")).strip() or ("reference picture" if refs else "")
        return Options(
            query=query,
            refs=refs,
            ref_kind=str(d.get("ref_kind")) if str(d.get("ref_kind")) in ("auto", "same", "like", "person") else "auto",
            mode="object" if (refs or str(d.get("mode", "text")) == "object") else "text",
            case_sensitive=_bool(d, "case_sensitive", False),
            use_regex=_bool(d, "use_regex", False),
            whole_word=_bool(d, "whole_word", False),
            ocr=_bool(d, "ocr", True),
            handwriting=_bool(d, "handwriting", False),
            strictness=_num(d, "strictness", 0.6, 0.2, 0.97),
            thorough=_bool(d, "thorough", True),
            scan_every=_num(d, "scan_every", 0.0, 0.0, 600.0),
            slowmo=_num(d, "slowmo", 4.0, 1.0, 32.0),
            before=_num(d, "before", 2.0, 0.0, 120.0),
            after=_num(d, "after", 2.0, 0.0, 120.0),
            ramp=_bool(d, "ramp", True),
            clipmode=(str(d["clipmode"]) if str(d.get("clipmode")) in ("result", "all", "pause") else ("result" if _bool(d, "ramp", True) else "all")),
            hold=_num(d, "hold", 2.0, 0.0, 60.0),
            changes=_bool(d, "changes", False),
            listen=_bool(d, "media_speech", _bool(d, "listen", False)),
            media_text=_bool(d, "media_text", str(d.get("mode", "text")) != "object"),
            media_object=_bool(d, "media_object", str(d.get("mode", "text")) == "object"),
            media_speech=_bool(d, "media_speech", _bool(d, "listen", False)),
            speech_model=model if model in ("tiny", "base", "small") else "base",
            only=tuple(k for k in (d.get("only") or []) if k in ("documents", "pictures", "videos", "audio")) if isinstance(d.get("only"), (list, tuple)) else (),
            recursive=_bool(d, "recursive", True),
            skip_junk=_bool(d, "skip_junk", True),
            include_cloud=_bool(d, "include_cloud", False),
        )


class Context:
    """Everything one search job shares between files."""

    def __init__(self, opts: Options, out_dir: Path, url_prefix: str, emit: Callable[[dict], None],
                 error: Callable[[str, str], None], cancel: threading.Event,
                 status: Callable[[str], None] | None = None):
        self.opts = opts
        self.pattern = compile_query(opts.query, opts.case_sensitive, opts.use_regex, opts.whole_word) if opts.mode == "text" else None
        self.is_sub = False
        self.ref_objs: list = []
        self.ref_kind = "like"
        self.out_dir = out_dir
        self.url_prefix = url_prefix
        self._emit = emit
        self._error = error
        self._status = status
        self.cancel = cancel
        self._n = 0
        self._lock = threading.Lock()
        self.tmp_dir = temp_dir() / uuid.uuid4().hex[:10]

    @property
    def cancelled(self) -> bool:
        return self.cancel.is_set()

    def next_id(self) -> str:
        with self._lock:
            self._n += 1
            return f"{self._n:06d}"

    def url(self, name: str) -> str:
        return f"{self.url_prefix}/{name}"

    def emit(self, result: dict) -> None:
        result["id"] = result.get("id") or self.next_id()
        self._emit(result)

    def error(self, display: str, message: str) -> None:
        self._error(display, message)

    def status(self, message: str) -> None:
        if self._status:
            self._status(message)

    def save_thumb(self, annotated: Image.Image, box) -> str:
        name = f"{self.next_id()}_t.jpg"
        crop_thumb(annotated, box).save(self.out_dir / name, "JPEG", quality=84)
        return self.url(name)



class _Sub:
    """The same search job seen with a different 'what to look for' (words, objects or speech), so one video can be searched several ways."""

    def __init__(self, base: "Context", mode: str):
        self._base = base
        self.is_sub = True
        self.opts = replace(base.opts, mode=mode, ocr=True if mode == "text" else base.opts.ocr)
        self.pattern = None
        if mode == "text":
            self.pattern = compile_query(base.opts.query, base.opts.case_sensitive, base.opts.use_regex, base.opts.whole_word)

    def __getattr__(self, name):
        return getattr(self._base, name)


def media_targets(opts: Options) -> list[str]:
    out = []
    if opts.media_text:
        out.append("text")
    if opts.media_object:
        out.append("object")
    return out


# ------------------------------------------------------------------ text-like content (files, Office text, binary strings)
CTX_BEFORE, CTX_AFTER, MAX_ROWS, MAX_HITS = 2, 2, 40, 25


@dataclass
class _Cluster:
    rows: list
    hits: list
    after_left: int


def _flush(ctx: Context, cl: _Cluster, display: str, origin: Path) -> None:
    first_where = cl.hits[0][3]
    extra = f"   (+{len(cl.hits) - 1} more in this view)" if len(cl.hits) > 1 else ""
    image, boxes_per_hit = render_snapshot(cl.rows, [(r, s, e) for r, s, e, _ in cl.hits], title=f"{display}   -   {first_where}{extra}")
    annotated = annotate(image, [b for bl in boxes_per_hit for b in bl], "text")
    full = save_image(annotated, ctx.out_dir / f"{ctx.next_id()}_full", photo_like=False)
    for (ri, s, e, where), boxes in zip(cl.hits, boxes_per_hit):
        if not boxes:
            continue
        ctx.emit({
            "file": display, "path": str(origin), "where": where, "kind": "text",
            "snippet": make_snippet(cl.rows[ri][1], s, e),
            "thumb": ctx.save_thumb(annotated, union_box(boxes)),
            "image": ctx.url(full),
        })


def search_lines(ctx: Context, lines, display: str, origin: Path) -> None:
    before: collections.deque = collections.deque(maxlen=CTX_BEFORE)
    cluster: _Cluster | None = None
    for count, (label, where, text) in enumerate(lines, 1):
        if count % 2000 == 0 and ctx.cancelled:
            break
        spans = find_spans(ctx.pattern, text) if text else []
        if cluster is not None:
            cluster.rows.append((label, text))
            ri = len(cluster.rows) - 1
            if spans:
                cluster.hits.extend((ri, s, e, where) for s, e in spans)
                cluster.after_left = CTX_AFTER
            else:
                cluster.after_left -= 1
            if cluster.after_left <= 0 or len(cluster.rows) >= MAX_ROWS or len(cluster.hits) >= MAX_HITS:
                _flush(ctx, cluster, display, origin)
                cluster = None
                before.clear()
            continue
        if spans:
            rows = list(before) + [(label, text)]
            cluster = _Cluster(rows, [(len(rows) - 1, s, e, where) for s, e in spans], CTX_AFTER)
        else:
            before.append((label, text))
    if cluster is not None:
        _flush(ctx, cluster, display, origin)


# ------------------------------------------------------------------ pictures (photos, scans, screenshots, PDF pages)
def picture_hits(ctx: Context, image: Image.Image) -> list[dict]:
    """[{'box', 'snippet': [pre, match, post], 'score'}] for one picture, in text or object mode."""
    hits: list[dict] = []
    if ctx.opts.mode == "object" and ctx.opts.refs:
        from app.reference import find as find_reference

        for item in find_reference(ctx.ref_kind, image, ctx.ref_objs, ctx.opts.strictness, ctx.opts.thorough):
            hits.append({"box": item["bbox"], "snippet": ["", "reference picture", ""], "score": item["score"]})
        return hits
    if ctx.opts.mode == "object":
        from app.detect import find_objects

        for item in find_objects(image, ctx.opts.query, ctx.opts.strictness, ctx.opts.thorough):
            hits.append({"box": item["bbox"], "snippet": ["", ctx.opts.query, ""], "score": item["score"]})
        return hits
    if ctx.opts.ocr:
        from app.ocr import ocr_boxes

        for tok in ocr_boxes(image):
            x0, y0, x1, y1 = tok["bbox"]
            vertical = (y1 - y0) > 1.5 * (x1 - x0) and len(tok["text"]) >= 3
            for s, e in find_spans(ctx.pattern, tok["text"]):
                hits.append({"box": span_to_box(tok["text"], s, e, tok["bbox"], vertical), "snippet": make_snippet(tok["text"], s, e), "score": tok["score"]})
    if ctx.opts.handwriting and min(image.size) >= 120:
        hits += handwriting_hits(ctx, image, hits)
    return hits


def _overlap(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1.0, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


def handwriting_hits(ctx: Context, image: Image.Image, existing: list[dict]) -> list[dict]:
    """handwritten lines that contain the query (a word read one or two letters wrong still counts)"""
    from app import handwriting as hw

    res = hw.read(image, cancel=getattr(ctx, "cancel", None))
    out: list[dict] = []
    for ln in res["lines"]:
        text = ln["text"]
        spans = find_spans(ctx.pattern, text)
        if not spans and not ctx.opts.use_regex and ctx.opts.mode == "text":
            spans = hw.fuzzy_spans(text, ctx.opts.query)
        for s, e in spans:
            box = span_to_box(text, s, e, ln["bbox"], False)
            if any(_overlap(box, h["box"]) > 0.5 for h in existing):
                continue                                    # the normal reader already found this one
            out.append({"box": box, "snippet": make_snippet(text, s, e), "score": ln.get("score", 0.6), "hand": True})
    return out


def emit_picture_hits(ctx: Context, image: Image.Image, hits: list[dict], display: str, origin: Path, where: str, photo_like: bool) -> None:
    """hits: [{'box': (x0,y0,x1,y1), 'boxes': optional list (a match that wraps over lines), 'snippet', 'score'}]"""
    if not hits:
        return
    mode = "object" if ctx.opts.mode == "object" else "text"
    rgb = to_rgb(image)
    small, _ = shrink_for_display(rgb, [])
    k = small.width / rgb.width

    def sc(b):
        return (b[0] * k, b[1] * k, b[2] * k, b[3] * k)

    annotated = annotate(small, [sc(b) for h in hits for b in (h.get("boxes") or [h["box"]])], mode)
    full = save_image(annotated, ctx.out_dir / f"{ctx.next_id()}_full", photo_like=photo_like)
    for hit in hits:
        result = {
            "file": display, "path": str(origin), "where": (where or "picture") + (" · handwriting" if hit.get("hand") else ""),
            "kind": mode, "snippet": hit["snippet"],
            "thumb": ctx.save_thumb(annotated, sc(hit["box"])), "image": ctx.url(full),
        }
        if mode == "object":
            result["score"] = round(float(hit.get("score", 0)), 2)
        ctx.emit(result)


def search_picture(ctx: Context, image: Image.Image, display: str, origin: Path, where: str = "", photo_like: bool = True) -> None:
    emit_picture_hits(ctx, image, picture_hits(ctx, image), display, origin, where, photo_like)


def _search_image_file(ctx: Context, path: Path, display: str, origin: Path) -> None:
    if ctx.opts.mode == "text" and not ctx.opts.ocr and not ctx.opts.handwriting:
        return
    photo = path.suffix.lower() in {".jpg", ".jpeg", ".jpe", ".jfif", ".heic", ".heif", ".avif", ".webp", ".jp2"}
    for label, image in extract.iter_image_frames(path):
        if ctx.cancelled:
            return
        search_picture(ctx, image, display, origin, label, photo)


# ------------------------------------------------------------------ PDF
def _pdf_module():
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    return fitz


def _scale(box, z: float):
    return (box[0] * z, box[1] * z, box[2] * z, box[3] * z)


def _overlap(a, b) -> float:
    ix0, iy0, ix1, iy1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / small if small > 0 else 0.0


def _pdf_picture_regions(page, fitz):
    rects = []
    try:
        infos = page.get_image_info()
    except Exception:
        infos = []
    for info in infos:
        r = fitz.Rect(info["bbox"]) & page.rect
        if not r.is_empty and r.width >= 40 and r.height >= 40:
            rects.append(r)
    return rects


def _search_pdf(ctx: Context, path: Path, display: str, origin: Path) -> None:
    fitz = _pdf_module()
    doc = fitz.open(str(path))
    try:
        if doc.needs_pass:
            raise RuntimeError("This PDF is password-protected.")
        z = PDF_ZOOM
        for pno in range(doc.page_count):
            if ctx.cancelled:
                return
            page = doc[pno]
            hits: list[dict] = []
            if ctx.opts.mode == "text":
                for block in extract.pdf_blocks(page):
                    for s, e in find_spans(ctx.pattern, block[0]):
                        boxes = [_scale(b, z) for b in extract.pdf_match_boxes(block, s, e)]
                        if boxes:
                            hits.append({"box": union_box(boxes), "boxes": boxes, "snippet": make_snippet(block[0], s, e), "score": 1.0})
            if ctx.opts.mode == "object" or ctx.opts.ocr or ctx.opts.handwriting:
                for rect in _pdf_picture_regions(page, fitz):  # scanned pages and pictures inside the PDF
                    pix = page.get_pixmap(matrix=fitz.Matrix(z, z), clip=rect, alpha=False)
                    pic = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    ox, oy = rect.x0 * z, rect.y0 * z
                    for h in picture_hits(ctx, pic):
                        b = h["box"]
                        box = (b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy)
                        if any(_overlap(box, old["box"]) > 0.5 for old in hits):
                            continue  # the same words were already found in the text layer
                        hits.append({**h, "box": box})
            if not hits:
                continue
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            emit_picture_hits(ctx, image, hits, display, origin, f"page {pno + 1}", photo_like=False)
    finally:
        doc.close()


# ------------------------------------------------------------------ Office files, archives, everything else
def _search_office(ctx: Context, path: Path, display: str, origin: Path) -> None:
    if ctx.opts.mode == "text":
        try:
            search_lines(ctx, extract.iter_office_text(path), display, origin)
        except Exception as exc:
            ctx.error(display, f"Could not read the document text ({exc}); scanning its raw bytes instead.")
            search_lines(ctx, extract.iter_binary_strings(path), display, origin)
    if ctx.opts.mode == "object" or ctx.opts.ocr or ctx.opts.handwriting:
        try:
            for name, data in extract.iter_office_images(path):
                if ctx.cancelled:
                    return
                try:
                    pic = extract.image_from_bytes(data)
                except Exception:
                    continue
                search_picture(ctx, pic, f"{display} > {name}", origin, "embedded picture", photo_like=True)
        except Exception:
            pass


def _search_legacy_office(ctx: Context, path: Path, display: str, origin: Path, depth: int) -> None:
    """Old .doc / .xls / .ppt (and WordPerfect, Works, OpenOffice 1.x): converted with LibreOffice and searched like a modern file.
    Without LibreOffice the readable text inside the file is scanned instead."""
    target = extract.LEGACY_OFFICE.get(path.suffix.lower(), "docx")
    exe = None
    try:
        from app.convert.eng_docs import LO_LOCK, soffice_exe

        exe = soffice_exe()
    except Exception:
        LO_LOCK = None
    if exe:
        tmp = ctx.tmp_dir / uuid.uuid4().hex[:8]
        try:
            from app.paths import data_root
            from app.runtime import no_window_flags

            tmp.mkdir(parents=True, exist_ok=True)
            profile = data_root() / "lo_profile"
            profile.mkdir(parents=True, exist_ok=True)
            src = tmp / f"in{path.suffix.lower()}"
            try:
                os.link(path, src)
            except OSError:
                shutil.copy2(path, src)
            ctx.status(f"Opening {path.name} in LibreOffice…")
            cmd = [exe, "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nologo", "--nofirststartwizard",
                   f"-env:UserInstallation={profile.as_uri()}", "--convert-to", target, "--outdir", str(tmp), str(src)]
            with LO_LOCK:
                subprocess.run(cmd, capture_output=True, timeout=900, creationflags=no_window_flags())
            done = next((p for p in tmp.iterdir() if p.suffix.lower() == "." + target), None)
            if done is not None:
                search_file(ctx, done, display, depth + 1, origin)
                return
            ctx.error(display, "LibreOffice could not open this old Office file; scanning its raw text instead.")
        except Exception as exc:
            ctx.error(display, f"Could not convert this old Office file ({exc}); scanning its raw text instead.")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if ctx.opts.mode == "text":
        search_lines(ctx, extract.iter_binary_strings(path), display, origin)


def _search_email(ctx: Context, path: Path, display: str, origin: Path, depth: int) -> None:
    """.eml and .mbox: headers, body text, and every attachment (searched like any other file)."""
    if depth >= MAX_ARCHIVE_DEPTH:
        ctx.error(display, "E-mails are nested too deeply; stopped here.")
        return
    for n, msg in extract.iter_email(path):
        if ctx.cancelled:
            return
        if ctx.opts.mode == "text":
            search_lines(ctx, extract.email_text_lines(msg, n), display, origin)
        tmp = ctx.tmp_dir / uuid.uuid4().hex[:8]
        try:
            for name, data in extract.email_attachments(msg):
                if ctx.cancelled:
                    return
                tmp.mkdir(parents=True, exist_ok=True)
                safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:120] or "attachment"
                f = tmp / safe
                f.write_bytes(data)
                try:
                    search_file(ctx, f, f"{display} > message {n} > {name}", depth + 1, origin)
                except Exception as exc:
                    ctx.error(f"{display} > {name}", str(exc))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _search_archive(ctx: Context, path: Path, display: str, origin: Path, depth: int) -> None:
    if depth >= MAX_ARCHIVE_DEPTH:
        ctx.error(display, "Archives are nested too deeply; stopped here.")
        return
    tmp = ctx.tmp_dir / uuid.uuid4().hex[:8]
    try:
        for name, tmp_path in extract.iter_archive(path, tmp):
            if ctx.cancelled:
                break
            try:
                search_file(ctx, tmp_path, f"{display} > {name}", depth + 1, origin)
            except Exception as exc:
                ctx.error(f"{display} > {name}", str(exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_KIND_GROUP = {"video": "videos", "audio": "audio", "image": "pictures", "raw": "pictures"}


def _wanted(opts: Options, kind: str) -> bool:
    """The 'look in' choice: documents, pictures, videos, audio (nothing chosen = everything). Archives are always opened, their contents are checked the same way."""
    only = opts.only
    if not only or kind == "archive":
        return True
    group = _KIND_GROUP.get(kind, "documents")
    if group in only:
        return True
    # scanned PDF pages and slides are pictures when you look for objects
    return opts.mode == "object" and "pictures" in only and kind in ("pdf", "office")


def search_file(ctx: Context, path: Path, display: str, depth: int = 0, origin: Path | None = None) -> None:
    origin = origin or path
    kind = extract.classify(path)
    mode = ctx.opts.mode
    if kind == "empty":
        return
    if not _wanted(ctx.opts, kind):
        return
    if kind == "video":
        from app.video import search_video

        search_video(ctx, path, display, origin)
    elif kind == "audio":
        if ctx.opts.media_speech:
            from app.speech import search_audio

            search_audio(_Sub(ctx, "text"), path, display, origin)
        elif mode == "text":
            search_lines(ctx, extract.iter_binary_strings(path), display, origin)
    elif kind in ("image", "raw"):
        _search_image_file(ctx, path, display, origin)
    elif kind == "legacy":
        _search_legacy_office(ctx, path, display, origin, depth)
    elif kind == "email":
        _search_email(ctx, path, display, origin, depth)
    elif kind == "database":
        if mode == "text":
            search_lines(ctx, extract.iter_sqlite(path), display, origin)
    elif kind == "pdf":
        _search_pdf(ctx, path, display, origin)
    elif kind == "office":
        _search_office(ctx, path, display, origin)
    elif kind == "archive":
        _search_archive(ctx, path, display, origin, depth)
    elif mode == "text":
        lines = extract.iter_text_lines(path) if kind == "text" else extract.iter_binary_strings(path)
        search_lines(ctx, lines, display, origin)
