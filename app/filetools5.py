"""File tools, part 5 (the second "more tools" batch).
PDF: header, footer and Bates numbers; tables to Excel or CSV; clean hidden data; add bookmarks; change page size.
Pictures: collage, frames and rounded corners, icon maker, make a colour transparent, pictures to animated GIF, slideshow video.
Video and sound: crop to a shape, reverse, cut out silence, fade in and out, add music to a video, text watermark.
Tables: tidy a CSV. Same plumbing as filetools4."""
from __future__ import annotations

import csv
import io
import re
import time
from pathlib import Path

from app import ops
from app.convert import formats
from app.convert.core import ConvertError, Ctx, Opts
from app.filetools4 import _batch, _f, _is_pdf, _open_pdf
from app.ops import Output, OutputPolicy, Task
from app.opsvc import expand_sources
from app.service import UserError


def _cat(fmt: str) -> str:
    return formats.category(fmt)


def _is_image(f: str) -> bool:
    return _cat(f) == "image"


def _is_av(f: str) -> bool:
    return _cat(f) in ("video", "audio")


def _color(v, default: str = "#ffffff"):
    from PIL import ImageColor

    try:
        return ImageColor.getrgb(str(v or default).strip() or default)
    except ValueError:
        raise UserError(f"'{v}' is not a colour. Use a name (white) or a code like #ff8800.")


def _group(kind: str, title: str, paths: list[str], recursive: bool, output: dict, accept, work, empty: str, minimum: int = 2, heavy: bool = False) -> dict:
    """one result made from all the files in the list (in the order shown). work(files, formats, scratch, ctx) -> (outputs, note)"""
    files = [(p, r) for p, r in expand_sources(paths, recursive) if accept(formats.detect(p))]
    if len(files) < minimum:
        raise UserError(empty)
    policy = OutputPolicy.from_dict(output)
    items = [p for p, _ in files]

    def fn(ctx: Ctx, task: Task) -> Output:
        outs, note = work(items, [formats.detect(p) for p in items], ctx.scratch_dir(), ctx)
        return Output(policy.place(outs, items[0], Path(".")), note)

    return {"job": ops.start(kind, title, [Task(f"{len(items)} files", fn, items[0], heavy=heavy)]).id, "count": len(items)}


# ================================================================ PDF: header, footer, Bates numbers
POS = {"left": 0, "center": 1, "right": 2}


def pdf_header_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    fields = {k: str(o.get(k) or "") for k in ("hl", "hc", "hr", "fl", "fc", "fr")}
    bates = str(o.get("bates") or "").strip()
    if not any(v.strip() for v in fields.values()) and not bates:
        raise UserError("Type some header or footer text, or a Bates prefix.")
    size = max(6.0, min(36.0, _f(o.get("size"), 10.0)))
    margin = max(5.0, min(100.0, _f(o.get("margin"), 28.0)))
    start = int(_f(o.get("start"), 1))
    digits = int(max(1, min(12, _f(o.get("digits"), 6))))
    pages = str(o.get("pages") or "")
    color = tuple(c / 255 for c in _color(o.get("color"), "#444444"))

    def work(src, fmt, d, ctx):
        from app import pagesel

        fitz, doc = _open_pdf(src)
        try:
            chosen = pagesel.need(pages, doc.page_count)
            total = doc.page_count
            today = time.strftime("%Y-%m-%d")
            seq = start
            for i in chosen:
                pg = doc[i]
                r = pg.rect
                subs = {"{page}": str(i + 1), "{pages}": str(total), "{file}": src.stem, "{date}": today, "{n}": str(seq)}

                def fill(t: str) -> str:
                    for k, v in subs.items():
                        t = t.replace(k, v)
                    return t

                row = {"h": (fields["hl"], fields["hc"], fields["hr"]), "f": (fields["fl"], fields["fc"], fields["fr"])}
                if bates:                                  # a Bates number goes bottom right unless the footer's right part is used
                    row["f"] = (row["f"][0], row["f"][1], fill(bates + str(seq).zfill(digits)) if not row["f"][2].strip() else row["f"][2])
                for place, texts in row.items():
                    for col, txt in enumerate(texts):
                        txt = fill(txt).strip()
                        if not txt:
                            continue
                        w = fitz.get_text_length(txt, fontname="helv", fontsize=size)
                        x = (margin, (r.width - w) / 2, r.width - margin - w)[col]
                        y = margin if place == "h" else r.height - margin + size * 0.3
                        pt = fitz.Point(x, y + (size * 0.8 if place == "h" else 0))
                        if pg.rotation:
                            pt = pt * pg.derotation_matrix
                        pg.insert_text(pt, txt, fontsize=size, fontname="helv", color=color, rotate=pg.rotation)
                seq += 1
            dst = d / f"{src.stem} (numbered).pdf"
            doc.save(str(dst), garbage=3, deflate=True)
        finally:
            doc.close()
        return [dst], f"Added text to {len(chosen)} page{'s' if len(chosen) != 1 else ''}. Letters outside the basic Latin alphabet may not show; use Stamp for those."

    return _batch("pdfheader", "Adding header and footer", paths, recursive, output, _is_pdf, work, "Add a PDF.")


# ================================================================ PDF: tables to Excel or CSV
def pdf_tables_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    kind = str(o.get("kind") or "xlsx")
    pages = str(o.get("pages") or "")

    def work(src, fmt, d, ctx):
        from app import pagesel

        fitz, doc = _open_pdf(src)
        tables = []
        try:
            for i in pagesel.need(pages, doc.page_count):
                try:
                    for t in doc[i].find_tables().tables:
                        rows = [[("" if c is None else str(c).replace("\n", " ").strip()) for c in r] for r in t.extract()]
                        if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                            keep = [j for j in range(max(len(r) for r in rows)) if any(len(r) > j and r[j] for r in rows)]
                            tables.append((i + 1, [[r[j] if j < len(r) else "" for j in keep] for r in rows]))
                except Exception:
                    continue
        finally:
            doc.close()
        if not tables:
            raise ConvertError("No tables found. Tables in scans must be read with Searchable PDF (OCR) first.")
        outs = []
        if kind == "csv":
            for n, (pg, rows) in enumerate(tables, 1):
                dst = d / f"{src.stem} - table {n} (page {pg}).csv"
                with open(dst, "w", newline="", encoding="utf-8-sig") as fh:
                    csv.writer(fh).writerows(rows)
                outs.append(dst)
        else:
            from openpyxl import Workbook
            from openpyxl.styles import Font

            wb = Workbook(); wb.remove(wb.active)
            for n, (pg, rows) in enumerate(tables, 1):
                ws = wb.create_sheet(f"Table {n} (p{pg})"[:31])
                for r in rows:
                    ws.append([_num(c) for c in r])
                for c in ws[1]:
                    c.font = Font(bold=True)
                for col in ws.columns:
                    ws.column_dimensions[col[0].column_letter].width = min(50, max(8, max(len(str(c.value or "")) for c in col) + 2))
            dst = d / f"{src.stem} (tables).xlsx"
            wb.save(dst); outs.append(dst)
        return outs, f"{len(tables)} table{'s' if len(tables) != 1 else ''} found."

    return _batch("pdftables", "Reading tables", paths, recursive, output, _is_pdf, work, "Add a PDF with tables.")


def _num(s: str):
    t = s.replace(",", "").replace(" ", "")
    if re.fullmatch(r"-?\d+", t) and not t.startswith("0") or t == "0":
        return int(t)
    if re.fullmatch(r"-?\d+\.\d+", t):
        return float(t)
    return s


# ================================================================ PDF: clean hidden data
def pdf_clean_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    def work(src, fmt, d, ctx):
        fitz, doc = _open_pdf(src)
        try:
            before = {k: v for k, v in (doc.metadata or {}).items() if v}
            n_files = len(doc.embfile_names()) if hasattr(doc, "embfile_names") else 0
            doc.scrub(metadata=bool(o.get("meta", True)), xml_metadata=bool(o.get("meta", True)), javascript=bool(o.get("js", True)),
                      attached_files=bool(o.get("files", True)), embedded_files=bool(o.get("files", True)), thumbnails=True,
                      hidden_text=False, redactions=False, remove_links=bool(o.get("links", False)), reset_fields=False, reset_responses=bool(o.get("comments", False)),
                      clean_pages=True, redact_images=0)
            if o.get("comments"):
                for pg in doc:
                    for a in list(pg.annots() or []):
                        pg.delete_annot(a)
            dst = d / f"{src.stem} (clean).pdf"
            doc.save(str(dst), garbage=4, deflate=True, clean=True)
        finally:
            doc.close()
        bits = []
        if before:
            bits.append(f"{len(before)} document detail{'s' if len(before) != 1 else ''} removed ({', '.join(list(before)[:4])})")
        if n_files:
            bits.append(f"{n_files} attached file{'s' if n_files != 1 else ''} removed")
        return [dst], "Cleaned. " + ("; ".join(bits) + "." if bits else "There was little hidden data.")

    return _batch("pdfclean", "Cleaning PDFs", paths, recursive, output, _is_pdf, work, "Add a PDF.")


# ================================================================ PDF: bookmarks from headings
def pdf_bookmarks_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    levels = int(max(1, min(4, _f(o.get("levels"), 3))))
    keep = bool(o.get("keep", False))

    def work(src, fmt, d, ctx):
        fitz, doc = _open_pdf(src)
        try:
            counts: dict[float, int] = {}
            lines = []
            for pg in doc:
                for b in pg.get_text("dict")["blocks"]:
                    for ln in b.get("lines", []):
                        txt = "".join(s["text"] for s in ln["spans"]).strip()
                        if not txt:
                            continue
                        sz = round(max(s["size"] for s in ln["spans"]) * 2) / 2
                        counts[sz] = counts.get(sz, 0) + len(txt)
                        lines.append((pg.number + 1, sz, txt, "bold" in ln["spans"][0]["font"].lower() or bool(ln["spans"][0]["flags"] & 16), ln["bbox"][1]))
            if not counts:
                raise ConvertError("No text found. Scans need Searchable PDF (OCR) first.")
            body = max(counts, key=counts.get)
            sizes = sorted({s for s in counts if s >= body * 1.15}, reverse=True)[:levels]
            if not sizes:
                raise ConvertError("No headings found: nothing in this PDF is set larger than the body text.")
            lvl = {s: i + 1 for i, s in enumerate(sizes)}
            toc = [] if not keep else doc.get_toc()
            seen = set()
            for pno, sz, txt, bold, y in lines:
                if sz in lvl and 2 < len(txt) < 140 and not re.fullmatch(r"[\d\W]+", txt) and (pno, txt) not in seen:
                    seen.add((pno, txt))
                    toc.append([lvl[sz], txt, pno, {"kind": 1, "to": fitz.Point(0, max(0, y - 6))}] if True else [])
            toc.sort(key=lambda t: t[2]) if keep else None
            # the first entry must be level 1 and each step may go down only one level
            fixed, prev = [], 0
            for t in toc:
                t = list(t); t[0] = min(t[0], prev + 1); prev = t[0]; fixed.append(t)
            doc.set_toc(fixed)
            dst = d / f"{src.stem} (bookmarks).pdf"
            doc.save(str(dst), garbage=3, deflate=True)
        finally:
            doc.close()
        return [dst], f"{len(fixed)} bookmark{'s' if len(fixed) != 1 else ''} added from the headings."

    return _batch("pdfbookmarks", "Adding bookmarks", paths, recursive, output, _is_pdf, work, "Add a PDF.")


# ================================================================ PDF: change the page size
PAPER = {"a3": (842, 1191), "a4": (595, 842), "a5": (420, 595), "a6": (298, 420), "letter": (612, 792), "legal": (612, 1008), "tabloid": (792, 1224)}


def pdf_resize_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    size = str(o.get("size") or "a4").lower()
    if size not in PAPER:
        raise UserError("Choose a paper size.")
    orient = str(o.get("orient") or "auto")
    margin = max(0.0, min(100.0, _f(o.get("margin"), 0.0))) * 72 / 25.4
    fill = str(o.get("fill") or "fit")

    def work(src, fmt, d, ctx):
        fitz, doc = _open_pdf(src)
        out = fitz.open()
        try:
            for pg in doc:
                w, h = PAPER[size]
                r = pg.rect
                land = (r.width > r.height) if orient == "auto" else (orient == "landscape")
                if land:
                    w, h = h, w
                new = out.new_page(width=w, height=h)
                box = fitz.Rect(margin, margin, w - margin, h - margin)
                sc = min(box.width / r.width, box.height / r.height) if fill == "fit" else max(box.width / r.width, box.height / r.height)
                tw, th = r.width * sc, r.height * sc
                tgt = fitz.Rect(0, 0, tw, th) + (box.x0 + (box.width - tw) / 2, box.y0 + (box.height - th) / 2, box.x0 + (box.width - tw) / 2, box.y0 + (box.height - th) / 2)
                new.show_pdf_page(tgt, doc, pg.number, clip=None, keep_proportion=True, rotate=0)
            dst = d / f"{src.stem} ({size.upper()}).pdf"
            out.save(str(dst), garbage=3, deflate=True)
            n = out.page_count
        finally:
            out.close(); doc.close()
        return [dst], f"{n} page{'s' if n != 1 else ''} fitted onto {size.upper()}. Form fields and notes are baked in as plain content."

    return _batch("pdfresize", "Changing page size", paths, recursive, output, _is_pdf, work, "Add a PDF.")


# ================================================================ pictures: collage
def collage_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    layout = str(o.get("layout") or "grid")
    cols = int(max(1, min(12, _f(o.get("cols"), 3))))
    cell = int(max(64, min(2000, _f(o.get("cell"), 400))))
    gap = int(max(0, min(200, _f(o.get("gap"), 12))))
    bg = _color(o.get("bg"), "#ffffff")
    fit = str(o.get("fit") or "fill")
    fmt_out = str(o.get("format") or "jpg")

    def work(items, fmts, d, ctx):
        from PIL import Image, ImageOps

        from app.convert.eng_image import load_frames, rw

        ims = []
        for p, f in zip(items, fmts):
            if f not in rw()[0]:
                continue
            fr, _du, _fi = load_frames(p, f, all_frames=False)
            ims.append(ImageOps.exif_transpose(fr[0]).convert("RGB"))
        if len(ims) < 2:
            raise ConvertError("Fathom could read fewer than two of these pictures.")
        n = len(ims)
        c = cols if layout == "grid" else (n if layout == "row" else 1)
        rows = -(-n // c)
        W, H = c * cell + (c + 1) * gap, rows * cell + (rows + 1) * gap
        if layout in ("row", "column"):                                     # keep each picture's own shape in a strip
            if layout == "row":
                th = cell; scaled = [im.resize((max(1, int(im.width * th / im.height)), th), Image.LANCZOS) for im in ims]
                W, H = sum(s.width for s in scaled) + (n + 1) * gap, th + 2 * gap
                sheet = Image.new("RGB", (W, H), bg); x = gap
                for s in scaled:
                    sheet.paste(s, (x, gap)); x += s.width + gap
            else:
                tw = cell; scaled = [im.resize((tw, max(1, int(im.height * tw / im.width))), Image.LANCZOS) for im in ims]
                W, H = tw + 2 * gap, sum(s.height for s in scaled) + (n + 1) * gap
                sheet = Image.new("RGB", (W, H), bg); y = gap
                for s in scaled:
                    sheet.paste(s, (gap, y)); y += s.height + gap
        else:
            sheet = Image.new("RGB", (W, H), bg)
            for k, im in enumerate(ims):
                r_, c_ = divmod(k, c)
                tile = ImageOps.fit(im, (cell, cell), Image.LANCZOS) if fit == "fill" else ImageOps.pad(im, (cell, cell), Image.LANCZOS, color=bg)
                sheet.paste(tile, (gap + c_ * (cell + gap), gap + r_ * (cell + gap)))
        dst = d / f"Collage.{'png' if fmt_out == 'png' else 'jpg'}"
        sheet.save(dst, quality=92) if dst.suffix == ".jpg" else sheet.save(dst)
        return [dst], f"{n} pictures in one {sheet.width} x {sheet.height} picture."

    return _group("collage", "Making a collage", paths, recursive, output, _is_image, work, "Add at least two pictures (in the order you want them).")


# ================================================================ pictures: frame, rounded corners, shadow
def frame_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    border = int(max(0, min(400, _f(o.get("border"), 24))))
    radius = max(0.0, min(50.0, _f(o.get("radius"), 0.0)))
    shadow = bool(o.get("shadow", False))
    circle = bool(o.get("circle", False))
    col = _color(o.get("color"), "#ffffff")
    transparent_bg = bool(o.get("transparent", False))

    def work(src, fmt, d, ctx):
        from PIL import Image, ImageDraw, ImageFilter, ImageOps

        from app.convert.eng_image import load_frames, rw

        if fmt not in rw()[0]:
            raise ConvertError("Fathom cannot read this picture format.")
        fr, _du, _fi = load_frames(src, fmt, all_frames=False)
        im = ImageOps.exif_transpose(fr[0]).convert("RGBA")
        if circle:
            s = min(im.size)
            im = ImageOps.fit(im, (s, s), Image.LANCZOS)
        w, h = im.size
        rr = (min(w, h) // 2) if circle else int(min(w, h) * radius / 100)
        if rr:
            m = Image.new("L", (w * 2, h * 2), 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 2 - 1, h * 2 - 1), radius=rr * 2, fill=255)
            im.putalpha(m.resize((w, h), Image.LANCZOS))
        pad = border + (max(20, min(w, h) // 25) * 2 if shadow else 0)
        canvas = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0) if transparent_bg else col + (255,))
        if border and not rr:
            pass
        if shadow:
            sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            off = max(6, min(w, h) // 60)
            blk = Image.new("RGBA", (w, h), (0, 0, 0, 120)); blk.putalpha(im.getchannel("A").point(lambda a: a * 120 // 255))
            sh.paste(blk, (pad + off, pad + off))
            canvas = Image.alpha_composite(canvas, sh.filter(ImageFilter.GaussianBlur(max(8, min(w, h) // 40))))
        if border and rr:                                  # the frame follows the rounded shape
            fm = Image.new("L", (w * 2 + 4 * border, h * 2 + 4 * border), 0)
            ImageDraw.Draw(fm).rounded_rectangle((0, 0, fm.width - 1, fm.height - 1), radius=(rr + border) * 2, fill=255)
            fimg = Image.new("RGBA", (w + 2 * border, h + 2 * border), col + (255,)); fimg.putalpha(fm.resize(fimg.size, Image.LANCZOS))
            canvas.alpha_composite(fimg, (pad - border, pad - border))
        elif border:
            canvas.alpha_composite(Image.new("RGBA", (w + 2 * border, h + 2 * border), col + (255,)), (pad - border, pad - border))
        canvas.alpha_composite(im, (pad, pad))
        keep_alpha = transparent_bg or rr or shadow
        out_fmt = "png" if keep_alpha else (fmt if fmt in ("jpg", "jpeg", "png", "webp") else "png")
        dst = d / f"{src.stem} (framed).{'jpg' if out_fmt in ('jpg', 'jpeg') else out_fmt}"
        if dst.suffix == ".jpg":
            bgc = Image.new("RGB", canvas.size, col); bgc.paste(canvas, mask=canvas.getchannel("A")); bgc.save(dst, quality=95)
        else:
            canvas.save(dst)
        return [dst], "Framed" + (" (saved as PNG so the corners and shadow can be see-through)." if keep_alpha and fmt != "png" else ".")

    return _batch("frame", "Framing pictures", paths, recursive, output, _is_image, work, "Add a picture.")


# ================================================================ pictures: icon maker
def icon_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    sizes = [int(s) for s in (o.get("sizes") or [16, 32, 48, 64, 128, 256]) if str(s).isdigit() and 8 <= int(s) <= 256] or [16, 32, 48, 256]
    pack = bool(o.get("pack", True))

    def work(src, fmt, d, ctx):
        from PIL import Image, ImageOps

        from app.convert.eng_image import load_frames, rw

        if fmt not in rw()[0]:
            raise ConvertError("Fathom cannot read this picture format.")
        fr, _du, _fi = load_frames(src, fmt, all_frames=False)
        im = ImageOps.exif_transpose(fr[0]).convert("RGBA")
        s = max(im.size)
        sq = Image.new("RGBA", (s, s), (0, 0, 0, 0)); sq.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
        outs = []
        ico = d / f"{src.stem}.ico"
        sq.save(ico, sizes=[(x, x) for x in sorted(sizes)]); outs.append(ico)
        if pack:
            for name, x in (("favicon-32.png", 32), ("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
                p = d / f"{src.stem} {name}"
                sq.resize((x, x), Image.LANCZOS).save(p); outs.append(p)
        return outs, f"An .ico with {len(sizes)} sizes" + (" and the web icon set (favicon, Apple touch icon, 192 and 512)." if pack else ".")

    return _batch("icon", "Making icons", paths, recursive, output, _is_image, work, "Add a picture (a square logo works best).")


# ================================================================ pictures: make a colour see-through
def transparent_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    tol = max(0.0, min(100.0, _f(o.get("tolerance"), 12.0)))
    soft = max(0.0, min(50.0, _f(o.get("soft"), 6.0)))
    pick = str(o.get("color") or "auto").strip()

    def work(src, fmt, d, ctx):
        import numpy as np
        from PIL import Image, ImageOps

        from app.convert.eng_image import load_frames, rw

        if fmt not in rw()[0]:
            raise ConvertError("Fathom cannot read this picture format.")
        fr, _du, _fi = load_frames(src, fmt, all_frames=False)
        im = ImageOps.exif_transpose(fr[0]).convert("RGBA")
        a = np.array(im).astype(np.float32)
        if pick in ("", "auto"):
            edge = np.concatenate([a[0, :, :3], a[-1, :, :3], a[:, 0, :3], a[:, -1, :3]])
            key = np.median(edge, axis=0)
        else:
            key = np.array(_color(pick), dtype=np.float32)
        dist = np.sqrt(((a[:, :, :3] - key) ** 2).sum(axis=2)) / 441.67 * 100          # 0 = same colour, 100 = opposite
        alpha = np.clip((dist - tol) / max(soft, 0.001), 0, 1)
        a[:, :, 3] = np.minimum(a[:, :, 3], alpha * 255)
        gone = float((alpha < 0.5).mean()) * 100
        dst = d / f"{src.stem} (transparent).png"
        Image.fromarray(a.astype(np.uint8), "RGBA").save(dst)
        return [dst], f"{gone:.0f}% of the picture is now see-through (saved as PNG). Raise 'How close' if a halo is left, lower it if too much went."

    return _batch("transparent", "Making colour transparent", paths, recursive, output, _is_image, work, "Add a picture.")


# ================================================================ pictures: animated GIF or WebP
def pics_gif_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    ms = int(max(20, min(10000, _f(o.get("ms"), 500))))
    width = int(max(32, min(2000, _f(o.get("width"), 480))))
    kind = "webp" if str(o.get("kind")) == "webp" else "gif"
    loop = 0 if o.get("loop", True) else 1

    def work(items, fmts, d, ctx):
        from PIL import Image, ImageOps

        from app.convert.eng_image import load_frames, rw

        frames = []
        for p, f in zip(items, fmts):
            if f not in rw()[0]:
                continue
            fr, _du, _fi = load_frames(p, f, all_frames=False)
            frames.append(ImageOps.exif_transpose(fr[0]).convert("RGB"))
        if len(frames) < 2:
            raise ConvertError("Fathom could read fewer than two of these pictures.")
        w = min(width, frames[0].width); h = int(frames[0].height * w / frames[0].width)
        frames = [ImageOps.pad(f, (w, h), Image.LANCZOS, color=(255, 255, 255)) for f in frames]
        dst = d / f"Animation.{kind}"
        if kind == "gif":
            q = [f.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG) for f in frames]
            q[0].save(dst, save_all=True, append_images=q[1:], duration=ms, loop=loop, optimize=True, disposal=2)
        else:
            frames[0].save(dst, save_all=True, append_images=frames[1:], duration=ms, loop=loop, quality=85, method=4)
        return [dst], f"{len(frames)} pictures, {ms} ms each."

    return _group("picsgif", "Making an animation", paths, recursive, output, _is_image, work, "Add at least two pictures (in the order you want them).")


# ================================================================ pictures (and a song): slideshow video
def slideshow_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    sec = max(0.5, min(60.0, _f(o.get("seconds"), 3.0)))
    size = str(o.get("size") or "1280x720")
    if size not in ("1280x720", "1920x1080", "1080x1920", "1080x1080"):
        size = "1280x720"
    fade = max(0.0, min(2.0, _f(o.get("fade"), 0.5)))

    def work(items, fmts, d, ctx):
        from PIL import Image, ImageOps

        from app.convert.eng_image import load_frames, rw
        from app.convert.eng_media import probe, run_ffmpeg

        W, H = (int(x) for x in size.split("x"))
        pics, music = [], None
        for p, f in zip(items, fmts):
            if _cat(f) == "audio" and music is None:
                music = p
            elif _cat(f) == "image" and f in rw()[0]:
                fr, _du, _fi = load_frames(p, f, all_frames=False)
                pics.append(ImageOps.pad(ImageOps.exif_transpose(fr[0]).convert("RGB"), (W, H), Image.LANCZOS, color=(0, 0, 0)))
        if not pics:
            raise ConvertError("No pictures could be read.")
        tmp = d / "frames"; tmp.mkdir()
        for i, im in enumerate(pics):
            im.save(tmp / f"{i:04d}.png")
        n = len(pics)
        total = n * sec
        fps = 25
        dst = d / "Slideshow.mp4"
        args = ["-framerate", f"1/{sec:g}", "-i", str(tmp / "%04d.png")]
        vf = f"fps={fps},format=yuv420p"
        if fade > 0 and n > 1:
            vf = f"fps={fps},fade=t=in:st=0:d={min(fade, sec / 2):g},fade=t=out:st={total - min(fade, sec / 2):g}:d={min(fade, sec / 2):g},format=yuv420p"
        if music:
            args += ["-i", music, "-af", f"afade=t=out:st={max(0, total - 2):g}:d=2", "-shortest", "-c:a", "aac", "-b:a", "192k"]
        run_ffmpeg(ctx, [*args, "-vf", vf, "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-movflags", "+faststart", "-t", f"{total:g}", dst], total, "slideshow")
        return [dst], f"{n} pictures, {sec:g} s each" + (", with your music." if music else ". Add a song to the list to give it music.")

    return _group("slideshow", "Making a slideshow", paths, recursive, output, lambda f: _cat(f) in ("image", "audio"), work, "Add at least one picture (and, if you like, a song).", minimum=1, heavy=True)


# ================================================================ video: crop to a shape
RATIOS = {"9:16": (9, 16), "1:1": (1, 1), "4:5": (4, 5), "16:9": (16, 9), "4:3": (4, 3), "21:9": (21, 9)}


def video_crop_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    ratio = str(o.get("ratio") or "9:16")
    if ratio not in RATIOS:
        raise UserError("Choose a shape.")
    anchor = str(o.get("anchor") or "center")

    def work(src, fmt, d, ctx):
        from app.convert.eng_media import VIDEO_OUT, probe, run_ffmpeg, video_args

        info = probe(ctx, src)
        if not info["video"]:
            raise ConvertError("This file has no video.")
        rw_, rh_ = RATIOS[ratio]
        pos = {"center": "(iw-ow)/2", "left": "0", "right": "iw-ow", "top": "0", "bottom": "ih-oh"}
        x = pos["center"] if anchor in ("center", "top", "bottom") else pos[anchor]
        y = pos["center"].replace("iw-ow", "ih-oh") if anchor in ("center", "left", "right") else pos[anchor]
        vf = f"crop='if(gte(iw/ih,{rw_}/{rh_}),floor(ih*{rw_}/{rh_}/2)*2,iw)':'if(gte(iw/ih,{rw_}/{rh_}),ih,floor(iw*{rh_}/{rw_}/2)*2)':{x}:{y}"
        out_fmt = fmt if fmt in VIDEO_OUT else "mp4"
        dst = d / f"{src.stem} ({ratio.replace(':', 'x')}).{out_fmt}"
        args = video_args(out_fmt, Opts(video_quality="high"), info["audio"])
        run_ffmpeg(ctx, ["-i", src, "-vf", vf, *args, dst], info["duration"], "crop")
        return [dst], f"Cropped to {ratio}."

    return _batch("videocrop", "Cropping video", paths, recursive, output, lambda f: _cat(f) == "video", work, "Add a video.", heavy=True)


# ================================================================ video and sound: reverse
def reverse_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    def work(src, fmt, d, ctx):
        from app.convert.eng_media import AUDIO_OUT, VIDEO_OUT, audio_args, probe, run_ffmpeg, video_args

        info = probe(ctx, src)
        if info["duration"] > 180:
            raise ConvertError("Reversing keeps the whole clip in memory, so it is limited to 3 minutes. Cut a shorter piece first.")
        dst = d / f"{src.stem} (reversed){src.suffix}"
        if info["video"]:
            args = video_args(fmt, Opts(video_quality="high"), info["audio"]) if fmt in VIDEO_OUT else []
            run_ffmpeg(ctx, ["-i", src, "-vf", "reverse", *(["-af", "areverse"] if info["audio"] else []), *args, dst], info["duration"], "reverse")
        else:
            args = audio_args(fmt, Opts(audio_kbps=256)) if fmt in AUDIO_OUT else []
            run_ffmpeg(ctx, ["-i", src, "-vn", "-af", "areverse", *args, dst], info["duration"], "reverse")
        return [dst], "Played backwards."

    return _batch("reverse", "Reversing", paths, recursive, output, _is_av, work, "Add a video or sound.", heavy=True)


# ================================================================ sound: cut out silence
def silence_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    db = max(-80.0, min(-10.0, _f(o.get("db"), -40.0)))
    gap = max(0.1, min(10.0, _f(o.get("gap"), 0.6)))
    keep = max(0.0, min(2.0, _f(o.get("keep"), 0.15)))

    def work(src, fmt, d, ctx):
        from app.convert.eng_media import AUDIO_OUT, audio_args, probe, run_ffmpeg

        info = probe(ctx, src)
        dst = d / f"{src.stem} (no silence){src.suffix}"
        args = audio_args(fmt, Opts(audio_kbps=256)) if fmt in AUDIO_OUT else []
        af = f"silenceremove=start_periods=1:start_silence={keep:g}:start_threshold={db:g}dB:stop_periods=-1:stop_silence={max(keep, gap):g}:stop_threshold={db:g}dB:detection=peak"
        run_ffmpeg(ctx, ["-i", src, "-vn", "-af", af, *args, dst], info["duration"], "silence")
        new = probe(ctx, dst)["duration"] if dst.exists() else 0
        return [dst], f"Shortened from {info['duration']:.0f} s to {new:.0f} s."

    return _batch("silence", "Cutting silence", paths, recursive, output, lambda f: _cat(f) == "audio", work, "Add a sound file (a recording or podcast).", heavy=True)


# ================================================================ video and sound: fade in and out
def fade_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    fin, fout = max(0.0, _f(o.get("fin"), 1.0)), max(0.0, _f(o.get("fout"), 2.0))
    if not fin and not fout:
        raise UserError("Choose a fade in or a fade out time.")

    def work(src, fmt, d, ctx):
        from app.convert.eng_media import AUDIO_OUT, VIDEO_OUT, audio_args, probe, run_ffmpeg, video_args

        info = probe(ctx, src)
        dur = info["duration"]
        if dur <= 0 or fin + fout > dur:
            raise ConvertError("The fades are longer than the file.")
        af = ",".join(x for x in (f"afade=t=in:st=0:d={fin:g}" if fin else "", f"afade=t=out:st={dur - fout:g}:d={fout:g}" if fout else "") if x)
        vf = ",".join(x for x in (f"fade=t=in:st=0:d={fin:g}" if fin else "", f"fade=t=out:st={dur - fout:g}:d={fout:g}" if fout else "") if x)
        dst = d / f"{src.stem} (faded){src.suffix}"
        if info["video"]:
            args = video_args(fmt, Opts(video_quality="high"), info["audio"]) if fmt in VIDEO_OUT else []
            run_ffmpeg(ctx, ["-i", src, "-vf", vf, *(["-af", af] if info["audio"] else []), *args, dst], dur, "fade")
        else:
            args = audio_args(fmt, Opts(audio_kbps=256)) if fmt in AUDIO_OUT else []
            run_ffmpeg(ctx, ["-i", src, "-vn", "-af", af, *args, dst], dur, "fade")
        return [dst], "Faded."

    return _batch("fade", "Adding fades", paths, recursive, output, _is_av, work, "Add a video or sound.", heavy=True)


# ================================================================ video: add or replace the music
def add_audio_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    mode = str(o.get("mode") or "replace")
    vol = max(0.0, min(2.0, _f(o.get("volume"), 1.0)))
    orig = max(0.0, min(2.0, _f(o.get("orig"), 0.4)))

    def work(items, fmts, d, ctx):
        from app.convert.eng_media import VIDEO_OUT, probe, run_ffmpeg, video_args

        video = next((p for p, f in zip(items, fmts) if _cat(f) == "video"), None)
        song = next((p for p, f in zip(items, fmts) if _cat(f) == "audio"), None)
        if not video or not song:
            raise ConvertError("Put one video and one sound file in the list.")
        vf = formats.detect(video)
        info = probe(ctx, video)
        dst = d / f"{video.stem} (with music).mp4" if vf not in VIDEO_OUT else d / f"{video.stem} (with music){video.suffix}"
        if mode == "mix" and info["audio"]:
            fc = f"[0:a]volume={orig:g}[a0];[1:a]volume={vol:g}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]"
            run_ffmpeg(ctx, ["-i", video, "-stream_loop", "-1", "-i", song, "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{info['duration']:g}", dst], info["duration"], "music")
        else:
            run_ffmpeg(ctx, ["-i", video, "-stream_loop", "-1", "-i", song, "-map", "0:v", "-map", "1:a", "-af", f"volume={vol:g}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{info['duration']:g}", dst], info["duration"], "music")
        return [dst], "Music added. It is looped or cut to match the video; the picture was not re-encoded."

    return _group("addaudio", "Adding music", paths, recursive, output, _is_av, work, "Put one video and one sound file in the list.", heavy=True)


# ================================================================ video: text watermark
def video_mark_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    text = str(o.get("text") or "").strip()
    if not text:
        raise UserError("Type the watermark text.")
    pos = str(o.get("pos") or "br")
    size_pct = max(2.0, min(20.0, _f(o.get("size"), 5.0)))
    opacity = max(0.1, min(1.0, _f(o.get("opacity"), 0.6)))
    col = _color(o.get("color"), "#ffffff")

    def work(src, fmt, d, ctx):
        from PIL import Image, ImageDraw

        from app.convert.eng_media import VIDEO_OUT, probe, run_ffmpeg, video_args
        from app.filetools4 import _font

        info = probe(ctx, src)
        if not info["video"]:
            raise ConvertError("This file has no video.")
        vw, vh = info.get("width") or 1280, info.get("height") or 720
        fs = max(12, int(vh * size_pct / 100))
        font = _font(fs)
        tmp = Image.new("RGBA", (10, 10)); dr = ImageDraw.Draw(tmp)
        tw = int(dr.textlength(text, font=font)) + 16; th = int(fs * 1.4)
        png = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(png).text((8, int(fs * 0.1)), text, font=font, fill=col + (int(255 * opacity),), stroke_width=max(1, fs // 16), stroke_fill=(0, 0, 0, int(200 * opacity)))
        pth = d / "mark.png"; png.save(pth)
        m = 16
        xy = {"tl": f"{m}:{m}", "tr": f"W-w-{m}:{m}", "bl": f"{m}:H-h-{m}", "br": f"W-w-{m}:H-h-{m}", "c": "(W-w)/2:(H-h)/2"}.get(pos, f"W-w-{m}:H-h-{m}")
        out_fmt = fmt if fmt in VIDEO_OUT else "mp4"
        dst = d / f"{src.stem} (marked).{out_fmt}"
        args = video_args(out_fmt, Opts(video_quality="high"), info["audio"])
        run_ffmpeg(ctx, ["-i", src, "-i", pth, "-filter_complex", f"[0:v][1:v]overlay={xy}", *args, dst], info["duration"], "mark")
        return [dst], "Watermark added."

    return _batch("videomark", "Adding a watermark", paths, recursive, output, lambda f: _cat(f) == "video", work, "Add a video.", heavy=True)


# ================================================================ tables: tidy a CSV
def csv_clean_start(paths: list[str], recursive: bool, output: dict, o: dict) -> dict:
    trim = bool(o.get("trim", True))
    dedupe = bool(o.get("dedupe", True))
    drop_empty = bool(o.get("empty", True))
    key = str(o.get("key") or "").strip()
    sort = str(o.get("sort") or "").strip()
    desc = bool(o.get("desc", False))

    def work(src, fmt, d, ctx):
        raw = src.read_bytes()
        try:
            from charset_normalizer import from_bytes

            enc = (from_bytes(raw[:200000]).best() or None)
            text = raw.decode(enc.encoding if enc else "utf-8", errors="replace")
        except Exception:
            text = raw.decode("utf-8", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel_tab if fmt == "tsv" else csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
        if not rows:
            raise ConvertError("The table is empty.")
        head, body = rows[0], rows[1:]
        n0 = len(body)
        if trim:
            body = [[c.strip() for c in r] for r in body]
        if drop_empty:
            body = [r for r in body if any(c.strip() for c in r)]

        def col(name: str):
            if not name:
                return None
            for i, h in enumerate(head):
                if h.strip().lower() == name.lower():
                    return i
            if name.isdigit() and 1 <= int(name) <= len(head):
                return int(name) - 1
            raise ConvertError(f"There is no column '{name}'. Columns: {', '.join(head[:12])}")

        if dedupe:
            ki, seen, out_rows = col(key), set(), []
            for r in body:
                k = r[ki] if (ki is not None and ki < len(r)) else tuple(r)
                if k not in seen:
                    seen.add(k); out_rows.append(r)
            body = out_rows
        si = col(sort)
        if si is not None:
            def kf(r):
                v = r[si] if si < len(r) else ""
                try:
                    return (0, float(v.replace(",", "")), "")
                except ValueError:
                    return (1, 0.0, v.lower())
            body.sort(key=kf, reverse=desc)
        dst = d / f"{src.stem} (tidy){src.suffix}"
        with open(dst, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=dialect.delimiter)
            w.writerow(head); w.writerows(body)
        return [dst], f"{n0} rows became {len(body)}."

    return _batch("csvclean", "Tidying tables", paths, recursive, output, lambda f: f in ("csv", "tsv"), work, "Add a CSV or TSV file.")


def pdfa_start(paths, recursive, output, options) -> dict:
    """Make long-term-archive PDFs (PDF/A). Ghostscript if installed, otherwise LibreOffice."""
    import os
    import shutil
    from app.convert.core import find_program
    from app.convert.eng_docs import soffice_exe

    level = str((options or {}).get("level") or "2")
    level = level if level in ("1", "2", "3") else "2"
    pf = [os.environ.get("ProgramFiles", r"C:\Program Files")]
    gs = find_program("gswin64c", "gswin32c", "gs", extra=[str(p) for base in pf for p in sorted(Path(base).glob("gs/gs*/bin/gswin64c.exe"), reverse=True)] if pf[0] else None)
    so = None if gs else soffice_exe()
    if not gs and not so:
        raise UserError("PDF/A needs Ghostscript or LibreOffice on this PC. Open Problems and Fixes in Fathom Manager, or install LibreOffice (free), then try again.")

    def work(src, fmt, scratch, ctx):
        dst = scratch / (src.stem + "-PDFA.pdf")
        if gs:
            cmd = [gs, "-dPDFA=%s" % level, "-dBATCH", "-dNOPAUSE", "-dQUIET", "-dNOOUTERSAVE", "-sColorConversionStrategy=RGB",
                   "-sDEVICE=pdfwrite", "-dPDFACompatibilityPolicy=1", "-sOutputFile=" + str(dst), str(src)]
            ctx.status("Converting with Ghostscript…")
            ctx.run(cmd, timeout=1800)
            note = "PDF/A-%sb made with Ghostscript." % level
        else:
            from app.paths import data_root
            prof = data_root() / "lo_profile"
            prof.mkdir(parents=True, exist_ok=True)
            tmp = scratch / "lo"
            tmp.mkdir(exist_ok=True)
            link = tmp / "in.pdf"
            shutil.copy2(src, link)
            spec = 'pdf:draw_pdf_Export:{"SelectPdfVersion":{"type":"long","value":"%s"}}' % level
            ctx.status("Converting with LibreOffice…")
            ctx.run([so, "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nologo", f"-env:UserInstallation={prof.as_uri()}",
                     "--convert-to", spec, "--outdir", str(tmp / "o"), str(link)], timeout=1800)
            res = tmp / "o" / "in.pdf"
            if res.exists():
                shutil.copy2(res, dst)
            note = "PDF/A-%sb made with LibreOffice. Fonts and layout can shift a little: check the result." % level
        if not dst.exists() or dst.stat().st_size < 100:
            raise ConvertError("Could not make a PDF/A from this file. It may be damaged or protected.")
        return [dst], note

    return _batch("pdfa", "Making PDF/A", paths, recursive, output, _is_pdf, work, "Add a PDF file.", heavy=True)
