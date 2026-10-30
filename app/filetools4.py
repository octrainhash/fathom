"""File tools, part 4 (the "more tools" batch): crop PDF pages, flatten PDFs, PDF to Markdown, make a PDF fillable, blur faces,
meme maker, video to GIF, change speed, even out loudness, mute a video. Same plumbing as the other file tools: a job of tasks,
one bad file never stops the others, originals are never changed."""
from __future__ import annotations

import re
from pathlib import Path

from app import ops
from app.convert import formats
from app.convert.core import ConvertError, Ctx, Opts
from app.ops import Output, OutputPolicy, Task
from app.opsvc import expand_sources
from app.service import UserError


def _batch(kind: str, title: str, paths: list[str], recursive: bool, output: dict, accept, work, empty: str, heavy: bool = False) -> dict:
    """work(src, fmt, scratch_dir, ctx) -> (list_of_output_files, note)"""
    policy = OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in expand_sources(paths, recursive):
        fmt = formats.detect(src)
        if not accept(fmt):
            continue

        def fn(ctx: Ctx, task: Task, src=src, fmt=fmt, rel=rel) -> Output:
            outs, note = work(src, fmt, ctx.scratch_dir(), ctx)
            return Output(policy.place(outs, src, rel), note)

        tasks.append(Task(src.name, fn, src, heavy=heavy, rel=rel))
    if not tasks:
        raise UserError(empty)
    return {"job": ops.start(kind, title, tasks).id, "count": len(tasks)}


def _is_pdf(fmt: str) -> bool:
    return fmt == "pdf"


def _open_pdf(src: Path, password: str = ""):
    from app.convert.eng_docs import get_fitz

    fitz = get_fitz()
    doc = fitz.open(str(src))
    if doc.needs_pass and not doc.authenticate(password or ""):
        doc.close()
        raise ConvertError("This PDF is locked with a password. Remove the password first (Protect > PDF password).")
    return fitz, doc


def _f(v, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


# ---------------------------------------------------------------- crop PDF
UNITS = {"mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72.0, "pt": 1.0}


def crop_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    mode = str(o.get("mode") or "margins")
    unit = str(o.get("unit") or "mm")
    k = UNITS.get(unit, UNITS["mm"])
    top, right, bottom, left = (_f(o.get(n)) * k for n in ("top", "right", "bottom", "left"))
    pad = _f(o.get("pad"), 5.0) * UNITS["mm"]
    pages = str(o.get("pages") or "")
    same = bool(o.get("same", True))
    if mode == "margins" and not (top or right or bottom or left):
        raise UserError("Enter how much to cut off at least one side, or choose 'Trim the white margins by itself'.")
    if min(top, right, bottom, left) < 0:
        raise UserError("Margins cannot be negative.")

    def work(src, fmt, d, ctx):
        from app import pagesel

        fitz, doc = _open_pdf(src)
        try:
            chosen = pagesel.need(pages, doc.page_count)
            rects: dict[int, object] = {}
            for i in chosen:
                pg = doc[i]
                r = pg.rect                                  # as shown (rotation applied)
                if mode == "auto":
                    box = _content_box(fitz, pg)
                    if box is None:
                        continue
                    rects[i] = fitz.Rect(box.x0 - pad, box.y0 - pad, box.x1 + pad, box.y1 + pad) & r
                else:
                    nr = fitz.Rect(r.x0 + left, r.y0 + top, r.x1 - right, r.y1 - bottom)
                    if nr.width < 20 or nr.height < 20:
                        raise ConvertError(f"Page {i + 1} would be almost empty. Use smaller margins.")
                    rects[i] = nr
            if mode == "auto" and same and rects:           # one common window per page direction, so pages keep the same size
                groups: dict[int, list[int]] = {}
                for i in rects:
                    groups.setdefault(doc[i].rotation, []).append(i)
                for idxs in groups.values():
                    u = fitz.Rect(rects[idxs[0]])
                    for i in idxs:
                        u |= rects[i]
                    for i in idxs:
                        rects[i] = u & doc[i].rect
            if not rects:
                raise ConvertError("Nothing to crop: these pages are empty.")
            for i, rr in rects.items():
                pg = doc[i]
                pg.set_cropbox(rr * pg.derotation_matrix)
            dst = d / f"{src.stem} (cropped).pdf"
            doc.save(str(dst), garbage=3, deflate=True)
        finally:
            doc.close()
        return [dst], f"Cropped {len(rects)} page{'s' if len(rects) != 1 else ''}. The cut-off parts are hidden, not erased (use Redact to remove content for good)."

    return _batch("pdfcrop", "Cropping PDFs", paths, recursive, output, _is_pdf, work, "Add a PDF to crop.")


def _content_box(fitz, pg):
    """the smallest box around everything visible on a page (text, pictures, drawings); None when the page is blank"""
    box = fitz.Rect()
    empty = True
    try:
        for b in pg.get_text("blocks"):
            if len(b) > 6 and b[6] == 0 and str(b[4]).strip():
                box |= fitz.Rect(b[:4]); empty = False
    except Exception:
        pass
    try:
        for im in pg.get_image_info():
            box |= fitz.Rect(im["bbox"]); empty = False
    except Exception:
        pass
    try:
        for dr in pg.get_drawings():
            r = dr.get("rect")
            if r is not None and r.width < pg.rect.width * 1.01 and r.height < pg.rect.height * 1.01 and not (r.width < 0.5 and r.height < 0.5):
                box |= fitz.Rect(r); empty = False
    except Exception:
        pass
    if empty or box.is_empty:
        return None
    return box & pg.rect


# ---------------------------------------------------------------- flatten PDF
def flatten_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    what = str(o.get("what") or "all")

    def work(src, fmt, d, ctx):
        fitz, doc = _open_pdf(src)
        try:
            n_annot = n_wid = 0
            for pg in doc:
                if what in ("all", "notes"):
                    n_annot += len(list(pg.annots() or []))
                if what in ("all", "forms"):
                    n_wid += len(list(pg.widgets() or []))
            doc.bake(annots=what in ("all", "notes"), widgets=what in ("all", "forms"))
            dst = d / f"{src.stem} (flattened).pdf"
            doc.save(str(dst), garbage=3, deflate=True)
        finally:
            doc.close()
        return [dst], f"Flattened {n_annot} note{'s' if n_annot != 1 else ''} and {n_wid} form field{'s' if n_wid != 1 else ''} into the pages. They can no longer be edited or removed."

    return _batch("pdfflat", "Flattening PDFs", paths, recursive, output, _is_pdf, work, "Add a PDF to flatten.")


# ---------------------------------------------------------------- PDF to Markdown
def _md_escape_cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def pdf_to_markdown_text(doc, fitz, pages: list[int], tables: bool = True, strip_repeats: bool = True) -> tuple[str, dict]:
    """Headings from font sizes, bullet and numbered lists, bold and italic, links and tables."""
    # body font size = the most used size by characters
    counts: dict[float, int] = {}
    for i in pages:
        for b in doc[i].get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    sz = round(sp["size"] * 2) / 2
                    counts[sz] = counts.get(sz, 0) + len(sp["text"].strip())
    body = max(counts, key=counts.get) if counts else 11.0
    sizes = sorted({s for s in counts if s >= body * 1.15}, reverse=True)[:4]
    level = {s: n + 1 for n, s in enumerate(sizes)}
    # lines repeated on most pages are headers and footers
    repeats: set[str] = set()
    if strip_repeats and len(pages) >= 4:
        seen: dict[str, int] = {}
        for i in pages:
            h = doc[i].rect.height
            for b in doc[i].get_text("blocks"):
                if b[1] < h * 0.08 or b[3] > h * 0.92:
                    t = re.sub(r"\d+", "#", str(b[4]).strip())
                    if t:
                        seen[t] = seen.get(t, 0) + 1
        repeats = {t for t, c in seen.items() if c >= max(3, int(len(pages) * 0.6))}
    out: list[str] = []
    stats = {"headings": 0, "tables": 0, "lists": 0, "links": 0}
    bullet = re.compile(r"^\s*([•●▪◦·\-–*])\s+")
    numbered = re.compile(r"^\s*(\d{1,3}[.)])\s+")
    for i in pages:
        pg = doc[i]
        table_rects = []
        table_md: list[tuple[float, str]] = []
        if tables:
            try:
                for t in pg.find_tables().tables:
                    rows = t.extract()
                    if not rows or len(rows) < 2 or max(len(r) for r in rows) < 2:
                        continue
                    width = max(len(r) for r in rows)
                    rows = [[_md_escape_cell(c if c is not None else "") for c in r] + [""] * (width - len(r)) for r in rows]
                    keep = [j for j in range(width) if any(r[j] for r in rows)]       # drop columns that are empty in every row
                    rows = [[r[j] for j in keep] for r in rows]
                    width = len(keep)
                    if width < 2:
                        continue
                    md = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width] + ["| " + " | ".join(r) + " |" for r in rows[1:]]
                    table_rects.append(fitz.Rect(t.bbox))
                    table_md.append((t.bbox[1], "\n".join(md)))
                    stats["tables"] += 1
            except Exception:
                table_rects, table_md = [], []
        items: list[tuple[float, str]] = list(table_md)
        links = []
        try:
            links = [(fitz.Rect(lk["from"]), lk.get("uri")) for lk in pg.get_links() if lk.get("uri")]
        except Exception:
            pass
        for b in pg.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            br = fitz.Rect(b["bbox"])
            if any((br & tr).get_area() > br.get_area() * 0.5 for tr in table_rects if br.get_area() > 0):
                continue
            lines_md = []
            for ln in b["lines"]:
                parts = []
                big = 0.0
                for sp in ln["spans"]:
                    t = sp["text"]
                    if not t.strip():
                        parts.append(t); continue
                    big = max(big, round(sp["size"] * 2) / 2)
                    bold = bool(sp["flags"] & 16) or "bold" in sp["font"].lower()
                    ital = bool(sp["flags"] & 2) or "italic" in sp["font"].lower()
                    core = t.strip()
                    lead, trail = t[: len(t) - len(t.lstrip())], t[len(t.rstrip()):]
                    uri = next((u for r, u in links if (fitz.Rect(sp["bbox"]) & r).get_area() > fitz.Rect(sp["bbox"]).get_area() * 0.5), None)
                    if uri:
                        core = f"[{core}]({uri})"; stats["links"] += 1
                    if bold and ital and big < body * 1.15:
                        core = f"***{core}***"
                    elif bold and big < body * 1.15:
                        core = f"**{core}**"
                    elif ital:
                        core = f"*{core}*"
                    parts.append(lead + core + trail)
                text = "".join(parts).strip()
                if text:
                    lines_md.append((text, big))
            if not lines_md:
                continue
            plain = " ".join(re.sub(r"[*_\[\]]|\(http[^)]*\)", "", t) for t, _ in lines_md).strip()
            if re.sub(r"\d+", "#", plain) in repeats:
                continue
            size = max(s for _, s in lines_md)
            if size in level and len(plain) < 160:
                out_text = "#" * level[size] + " " + re.sub(r"^\*+|\*+$", "", " ".join(t for t, _ in lines_md)).strip()
                stats["headings"] += 1
            else:
                rows = []
                for t, _ in lines_md:
                    if bullet.match(t):
                        rows.append("- " + bullet.sub("", t)); stats["lists"] += 1
                    elif numbered.match(t):
                        rows.append(t)
                    else:
                        rows.append(t)
                if any(r.startswith("- ") or numbered.match(r) for r in rows):
                    out_text = "\n".join(rows)
                else:
                    out_text = " ".join(rows)
                    out_text = re.sub(r"(\w)- (\w)", r"\1\2", out_text)   # join words split over two lines
            items.append((b["bbox"][1], out_text))
        items.sort(key=lambda x: x[0])
        out.extend(t for _, t in items)
    return "\n\n".join(out).strip() + "\n", stats


def pdf_markdown_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    pages = str(o.get("pages") or "")
    tables = bool(o.get("tables", True))

    def work(src, fmt, d, ctx):
        from app import pagesel

        fitz, doc = _open_pdf(src)
        try:
            chosen = pagesel.need(pages, doc.page_count)
            text, st = pdf_to_markdown_text(doc, fitz, chosen, tables)
        finally:
            doc.close()
        if len(text.strip()) < 5:
            raise ConvertError("No text found. This looks like a scan: run Searchable PDF (OCR) first, then try again.")
        dst = d / f"{src.stem}.md"
        dst.write_text(text, encoding="utf-8")
        return [dst], f"{st['headings']} headings, {st['tables']} tables, {st['lists']} list items, {st['links']} links."

    return _batch("pdfmd", "PDF to Markdown", paths, recursive, output, _is_pdf, work, "Add a PDF to turn into Markdown.")


# ---------------------------------------------------------------- make a PDF fillable
_BLANK = re.compile(r"(_{3,}|\.{6,}|-{6,})")
_BOX = re.compile(r"[\u2610\u25a1\u25a2\u2751\u2752]|\[\s\]")


def fillable_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    checks = bool(o.get("checks", True))
    boxes = bool(o.get("boxes", True))

    def work(src, fmt, d, ctx):
        fitz, doc = _open_pdf(src)
        n_text = n_check = 0
        try:
            for pg in doc:
                have = [w.rect for w in (pg.widgets() or [])]
                taken = lambda r: any((r & h).get_area() > r.get_area() * 0.3 for h in have)
                for b in pg.get_text("dict")["blocks"]:
                    for ln in b.get("lines", []):
                        for sp in ln["spans"]:
                            t = sp["text"]
                            if checks and _BOX.search(t):
                                for m in _BOX.finditer(t):
                                    x0, y0, x1, y1 = sp["bbox"]
                                    cw = (x1 - x0) / max(1, len(t))
                                    r = fitz.Rect(x0 + m.start() * cw, y0 + 1, x0 + m.start() * cw + max(10.0, (y1 - y0) * 0.9), y1 - 1)
                                    if taken(r):
                                        continue
                                    w = fitz.Widget(); w.rect = r; w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
                                    w.field_name = f"check_{pg.number + 1}_{n_check + 1}"; w.field_value = False
                                    pg.add_widget(w); have.append(r); n_check += 1
                            m = _BLANK.search(t)
                            if m:
                                x0, y0, x1, y1 = sp["bbox"]
                                cw = (x1 - x0) / max(1, len(t))
                                a, z = x0 + m.start() * cw, x0 + m.end() * cw
                                if z - a < 24:
                                    continue
                                r = fitz.Rect(a, y0 - 1, z, y1 + 1)
                                if taken(r):
                                    continue
                                w = fitz.Widget(); w.rect = r; w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                                w.field_name = f"text_{pg.number + 1}_{n_text + 1}"; w.text_fontsize = min(12, max(8, (y1 - y0) * 0.8))
                                w.border_width = 0; w.fill_color = None
                                pg.add_widget(w); have.append(r); n_text += 1
                if boxes:                                    # empty rectangles (a table cell or a box to write in) with no text inside
                    try:
                        for dr in pg.get_drawings():
                            r = dr.get("rect")
                            if r is None or dr.get("fill") is not None:
                                continue
                            if 60 <= r.width <= pg.rect.width * 0.9 and 12 <= r.height <= 40 and len(dr.get("items", [])) in (1, 4, 5) \
                                    and not pg.get_text("text", clip=r).strip() and not taken(r):
                                w = fitz.Widget(); w.rect = fitz.Rect(r.x0 + 1, r.y0 + 1, r.x1 - 1, r.y1 - 1); w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                                w.field_name = f"box_{pg.number + 1}_{n_text + 1}"; w.text_fontsize = min(12, max(8, r.height * 0.6))
                                w.border_width = 0; w.fill_color = None
                                pg.add_widget(w); have.append(r); n_text += 1
                    except Exception:
                        pass
            if not (n_text or n_check):
                raise ConvertError("No blank lines (____), empty boxes or check squares were found to turn into fields.")
            dst = d / f"{src.stem} (fillable).pdf"
            doc.save(str(dst), garbage=3, deflate=True)
        finally:
            doc.close()
        return [dst], f"Added {n_text} text field{'s' if n_text != 1 else ''} and {n_check} check box{'es' if n_check != 1 else ''}. Fill it in any PDF reader, or with Fathom's Fill a PDF form."

    return _batch("pdffillable", "Making PDFs fillable", paths, recursive, output, _is_pdf, work, "Add a PDF to make fillable.")


# ---------------------------------------------------------------- blur faces
def blur_faces_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    style = str(o.get("style") or "blur")
    grow = max(0.0, min(1.0, _f(o.get("grow"), 0.25)))
    strength = int(max(1, min(10, _f(o.get("strength"), 6))))

    def work(src, fmt, d, ctx):
        import cv2
        import numpy as np
        from PIL import Image, ImageDraw, ImageFilter, ImageOps

        from app.convert.eng_image import load_frames, rw, save_pil

        if fmt not in rw()[1]:
            raise ConvertError("Fathom cannot save this picture format.")
        frames, durs, first = load_frames(src, fmt, all_frames=True)
        if len(frames) > 1:
            raise ConvertError("Animated pictures are not supported here. Convert to a still picture first.")
        im = ImageOps.exif_transpose(frames[0]).convert("RGB")
        arr = np.array(im)
        found: list[tuple[int, int, int, int]] = []
        from app import reference

        if reference.faces_supported():
            if not reference.face_models_ready():
                try:
                    reference.ensure_face_models()
                except Exception as exc:
                    raise ConvertError(str(exc))
            for row, _feat in reference._faces_in(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), True):
                found.append((int(row[0]), int(row[1]), int(row[2]), int(row[3])))
        elif hasattr(cv2, "CascadeClassifier"):
            gray = cv2.equalizeHist(cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY))
            for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
                casc = cv2.CascadeClassifier(cv2.data.haarcascades + name)
                if casc.empty():
                    continue
                mn = max(24, min(im.size) // 24)
                for (x, y, w, h) in casc.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(mn, mn)):
                    if not any(abs(x - a) < w * 0.5 and abs(y - b) < h * 0.5 for a, b, _, _ in found):
                        found.append((int(x), int(y), int(w), int(h)))
        else:
            raise ConvertError("This computer's OpenCV cannot find faces. Run Problems and Fixes > Repair.")
        if not found:
            raise ConvertError("No faces found in this picture.")
        out = im.copy()
        for (x, y, w, h) in found:
            gx, gy = int(w * grow), int(h * grow)
            box = (max(0, x - gx), max(0, y - gy), min(im.width, x + w + gx), min(im.height, y + h + gy))
            part = im.crop(box)
            if style == "pixel":
                k = max(4, int(max(part.size) / (14 - strength)))
                small = part.resize((max(1, part.width // k), max(1, part.height // k)), Image.NEAREST)
                part = small.resize(part.size, Image.NEAREST)
            elif style == "black":
                part = Image.new("RGB", part.size, (0, 0, 0))
            else:
                part = part.filter(ImageFilter.GaussianBlur(radius=max(6, max(part.size) / 40 * strength / 3)))
            mask = Image.new("L", part.size, 0)
            ImageDraw.Draw(mask).ellipse((0, 0, part.width - 1, part.height - 1), fill=255)
            out.paste(part, box[:2], mask if style != "black" else None)
        dst = d / f"{src.stem} (faces hidden){src.suffix}"
        save_pil([out], durs[:1] if durs else durs, dst, fmt, Opts(image_quality=95), first)
        return [dst], f"Hid {len(found)} face{'s' if len(found) != 1 else ''}. Check the result: side faces, small faces or faces turned away can be missed."

    return _batch("blurfaces", "Hiding faces", paths, recursive, output, lambda f: formats.category(f) == "image", work, "Add a picture.")


# ---------------------------------------------------------------- meme maker
def _font(size: int):
    from PIL import ImageFont

    for name in ("impact.ttf", "Impact.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.upper().split("\n"):
        cur = ""
        for word in para.split():
            test = (cur + " " + word).strip()
            if draw.textlength(test, font=font) <= width or not cur:
                cur = test
            else:
                lines.append(cur); cur = word
        lines.append(cur)
    return [ln for ln in lines if ln != ""] or [""]


def meme_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    top, bottom = str(o.get("top") or "").strip(), str(o.get("bottom") or "").strip()
    if not top and not bottom:
        raise UserError("Type the top text, the bottom text, or both.")
    size_pct = max(4.0, min(20.0, _f(o.get("size"), 10.0)))

    def work(src, fmt, d, ctx):
        from PIL import ImageDraw, ImageOps

        from app.convert.eng_image import load_frames, rw, save_pil

        if fmt not in rw()[1]:
            raise ConvertError("Fathom cannot save this picture format.")
        frames, durs, first = load_frames(src, fmt, all_frames=False)
        im = ImageOps.exif_transpose(frames[0]).convert("RGB")
        dr = ImageDraw.Draw(im)
        fs = max(14, int(im.height * size_pct / 100))
        font = _font(fs)
        margin = int(im.width * 0.04)
        for text, at_top in ((top, True), (bottom, False)):
            if not text:
                continue
            f = font
            lines = _wrap(dr, text, f, im.width - 2 * margin)
            while len(lines) > 3 and f.size > 12:
                f = _font(int(f.size * 0.85)); lines = _wrap(dr, text, f, im.width - 2 * margin)
            lh = int(f.size * 1.08)
            y = margin // 2 if at_top else im.height - margin // 2 - lh * len(lines)
            for ln in lines:
                x = (im.width - dr.textlength(ln, font=f)) / 2
                dr.text((x, y), ln, font=f, fill="white", stroke_width=max(2, f.size // 12), stroke_fill="black")
                y += lh
        dst = d / f"{src.stem} (meme){src.suffix}"
        save_pil([im], durs[:1] if durs else durs, dst, fmt, Opts(image_quality=95), first)
        return [dst], "Meme made."

    return _batch("meme", "Making memes", paths, recursive, output, lambda f: formats.category(f) == "image", work, "Add a picture.")


# ---------------------------------------------------------------- video to GIF
def gif_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    fps = int(max(1, min(30, _f(o.get("fps"), 12))))
    width = int(max(64, min(1920, _f(o.get("width"), 480))))
    start = _f(o.get("start"), 0.0)
    length = _f(o.get("length"), 6.0)
    if length <= 0 or length > 120:
        raise UserError("Length must be between 1 and 120 seconds.")
    loop = "0" if o.get("loop", True) else "-1"

    def work(src, fmt, d, ctx):
        from app.convert.eng_media import probe, run_ffmpeg

        info = probe(ctx, src)
        if not info.get("video"):
            raise ConvertError("This file has no video.")
        dst = d / f"{src.stem}.gif"
        vf = f"fps={fps},scale='min({width},iw)':-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5"
        pre = ["-ss", f"{start:g}"] if start else []
        run_ffmpeg(ctx, [*pre, "-t", f"{length:g}", "-i", src, "-an", "-vf", vf, "-loop", loop, dst], min(length, max(0.1, info["duration"] - start)), "gif")
        return [dst], f"GIF of {length:g} s at {fps} pictures per second."

    return _batch("gif", "Making GIFs", paths, recursive, output, lambda f: formats.category(f) == "video", work, "Add a video.", heavy=True)


# ---------------------------------------------------------------- change speed
def _atempo(factor: float) -> str:
    parts = []
    while factor > 2.0:
        parts.append("atempo=2.0"); factor /= 2.0
    while factor < 0.5:
        parts.append("atempo=0.5"); factor /= 0.5
    parts.append(f"atempo={factor:.5f}")
    return ",".join(parts)


def speed_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    factor = _f(o.get("factor"), 2.0)
    if not 0.1 <= factor <= 16:
        raise UserError("Speed must be between 0.1 and 16 times.")
    keep_pitch = bool(o.get("pitch", True))

    def work(src, fmt, d, ctx):
        from app.convert.eng_media import AUDIO_OUT, VIDEO_OUT, audio_args, probe, run_ffmpeg, video_args

        info = probe(ctx, src)
        cat = formats.category(fmt)
        dst = d / f"{src.stem} ({factor:g}x){src.suffix}"
        af = _atempo(factor) if keep_pitch else f"asetrate=44100*{factor:g},aresample=44100"
        if cat == "video" and info["video"]:
            args = video_args(fmt, Opts(video_quality="high"), info["audio"]) if fmt in VIDEO_OUT else []
            cmd = ["-i", src, "-filter_complex", f"[0:v]setpts=PTS/{factor:g}[v]" + (f";[0:a]{af}[a]" if info["audio"] else ""), "-map", "[v]"]
            if info["audio"]:
                cmd += ["-map", "[a]"]
            run_ffmpeg(ctx, [*cmd, *args, dst], info["duration"] / factor, "speed")
        else:
            args = audio_args(fmt, Opts(audio_kbps=256)) if fmt in AUDIO_OUT else []
            run_ffmpeg(ctx, ["-i", src, "-vn", "-af", af, *args, dst], info["duration"] / factor, "speed")
        return [dst], f"Now {factor:g}x as fast."

    return _batch("speed", "Changing speed", paths, recursive, output, lambda f: formats.category(f) in ("video", "audio"), work, "Add a video or audio file.", heavy=True)


# ---------------------------------------------------------------- even out loudness
def loudness_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    target = _f(o.get("target"), -16.0)
    if not -30 <= target <= -5:
        raise UserError("Target loudness must be between -30 and -5 LUFS.")

    def work(src, fmt, d, ctx):
        from app.convert.eng_media import AUDIO_OUT, VIDEO_OUT, audio_args, probe, run_ffmpeg

        info = probe(ctx, src)
        if not info["audio"] and formats.category(fmt) != "audio":
            raise ConvertError("This file has no sound.")
        dst = d / f"{src.stem} (loudness){src.suffix}"
        af = f"loudnorm=I={target:g}:TP=-1.5:LRA=11"
        if info["video"]:
            run_ffmpeg(ctx, ["-i", src, "-c:v", "copy", "-af", af, "-c:s", "copy", dst], info["duration"], "loudness")
        else:
            args = audio_args(fmt, Opts(audio_kbps=256)) if fmt in AUDIO_OUT else []
            run_ffmpeg(ctx, ["-i", src, "-vn", "-af", af, *args, dst], info["duration"], "loudness")
        return [dst], f"Volume levelled to about {target:g} LUFS (the loudness streaming sites aim for)."

    return _batch("loudness", "Levelling volume", paths, recursive, output, lambda f: formats.category(f) in ("video", "audio"), work, "Add a video or audio file.", heavy=True)


# ---------------------------------------------------------------- mute a video
def mute_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    def work(src, fmt, d, ctx):
        from app.convert.eng_media import probe, run_ffmpeg

        info = probe(ctx, src)
        if not info["video"]:
            raise ConvertError("This file has no video.")
        dst = d / f"{src.stem} (no sound){src.suffix}"
        run_ffmpeg(ctx, ["-i", src, "-c", "copy", "-an", dst], info["duration"], "mute")
        return [dst], "Sound removed. The picture was not re-encoded, so there is no quality loss."

    return _batch("mute", "Removing sound", paths, recursive, output, lambda f: formats.category(f) == "video", work, "Add a video.", heavy=True)
