# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Visual editor for everything that has objects you can drag: PDF pages, PowerPoint slides, SVG drawings and pictures (as layers).
One screen, one model: objects {id, kind, x, y, w, h, fill, stroke, lw, text, size} in page units with the origin at the top left,
edits = {mods: [{id, dx, dy, sx, sy, fill, stroke, lw, text, delete, dup}], adds: [{type, x, y, w, h, x2, y2, stroke, fill, lw, text, size, color, data}]}."""
from __future__ import annotations

import base64
import copy
import io
import math
import re
from pathlib import Path
import shutil

from .service import UserError

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
KINDS_TEXT = "PDF, PowerPoint, SVG, pictures, and any other file Fathom can turn into pages or a picture (Word, Excel, e-books, camera RAW, HEIC, PSD, videos and more)"
CONVERT_FIRST = {"image": ("png", "pdf"), "video": ("png", "pdf"), "mesh": ("png", "pdf"), "font": ("png", "pdf")}


def kind_of(path: str) -> str:
    """pdf | pptx | svg | image for the files the editor reads directly; "office" for every other file, which is turned into pages or a picture first"""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext == ".pptx":
        return "pptx"
    if ext == ".svg":
        return "svg"
    if ext in IMG_EXT:
        return "image"
    return "office"


DOC_LIKE = {".docx", ".doc", ".dot", ".dotx", ".odt", ".ott", ".rtf", ".docm"}
SHEET_LIKE = {".xlsx", ".xls", ".ods", ".xlsm", ".xlsb"}
SLIDE_LIKE = {".ppt", ".pps", ".odp", ".ppsx", ".pot", ".potx", ".pptm"}


def native_of(path: str) -> str | None:
    """which of Fathom's own writers saves this file in ITS OWN format: docx | xlsx | text | None (then a PDF or picture copy is saved)"""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in DOC_LIKE:
        return "docx"
    if ext in SHEET_LIKE:
        return "xlsx"
    if ext in SLIDE_LIKE:
        return "slides"
    try:
        from .convert import formats
        if p.is_file() and formats.category(formats.detect(p)) == "text":
            return "text"
    except Exception:
        pass
    return None


def _modern_twin(p: Path, ext: str) -> Path:
    """the same file as a modern format (.doc -> .docx, .xls -> .xlsx, .ppt -> .pptx), made by LibreOffice and kept for next time"""
    import hashlib
    from .pdfview import _cache_dir
    from . import office_native
    st = p.stat()
    key = hashlib.sha1(f"{p}|{st.st_mtime_ns}|{st.st_size}|{ext}".encode()).hexdigest()[:20]
    out = _cache_dir() / f"{key}.{ext}"
    if out.exists():
        return out
    tmp = _cache_dir() / ("t_" + key)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        got = office_native.soffice_convert(p, ext, tmp)
        shutil.copyfile(got, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _converted(p: Path, fmt: str, target: str) -> Path:
    """the file as `target` (pdf or png) made by Fathom's own converter, kept for next time"""
    import hashlib
    import shutil
    import threading
    from .convert import formats
    from .convert.core import Ctx, Opts
    from .convert.engines import convert_file
    from .pdfview import _cache_dir
    st = p.stat()
    key = hashlib.sha1(f"{p}|{st.st_mtime_ns}|{st.st_size}|{target}".encode()).hexdigest()[:20]
    out = _cache_dir() / f"{key}.{target}"
    if out.exists():
        return out
    work = _cache_dir() / ("w_" + key)
    try:
        files, _n = convert_file(p, fmt, target, Opts(), Ctx(work, threading.Event()))
        shutil.copyfile(files[0], out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out


def _resolve(path: str) -> tuple[str, str]:
    """(kind, path to work on). Any other file type becomes a PDF copy (documents, sheets, e-books, text...) or a PNG picture (photos, RAW, HEIC,
    PSD, videos' first frame...), kept for next time, and is then edited like a PDF or a picture."""
    k = kind_of(path)
    if k != "office":
        return k, path
    p = Path(path)
    if not p.is_file():
        raise UserError("That file was not found.")
    if native_of(path) == "slides":                    # older / OpenDocument slides: edited as the PowerPoint twin, written back in their own format
        return "pptx", str(_modern_twin(p, "pptx"))
    from .convert import formats
    fmt = formats.detect(p)
    cat = formats.category(fmt)
    last: Exception | None = None
    for target in CONVERT_FIRST.get(cat, ("pdf", "png")):
        try:
            out = _converted(p, fmt, target)
            return ("pdf" if target == "pdf" else "image"), str(out)
        except Exception as e:
            last = e
    msg = str(last or "")
    if "LibreOffice" in msg or "office" in msg.lower():
        raise UserError("This file needs LibreOffice to be shown as pages. The full Fathom install adds it (run Fathom-Setup.vbs and tick LibreOffice). "
                        "Meanwhile use Editor to change the text itself.")
    raise UserError(f"Fathom cannot show a {formats.label(fmt)} as pages or a picture, so there is nothing to drag around. ({msg[:140]})")


def save_suffix(path: str) -> str | None:
    """the extension a saved copy gets when it differs from the original (a Word file is saved as a PDF, a RAW photo as a PNG)"""
    if kind_of(path) != "office":
        return None
    if native_of(path):
        return None
    k, real = _resolve(path)
    return Path(real).suffix.lower()


def _rgb(h, default=(0, 0, 0)):
    h = (h or "").lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else default
    except ValueError:
        return default


def _data_bytes(url: str) -> bytes | None:
    m = re.match(r"data:[\w/+.-]+;base64,(.*)$", url or "", re.S)
    return base64.b64decode(m.group(1)) if m else None


def open_page(path: str, n: int) -> dict:
    orig_kind = kind_of(path)
    orig_path = path
    k, path = _resolve(path)
    if k == "pdf":
        from . import pdfobjects
        r = pdfobjects.open_page(path, n)
        try:
            from . import office_native
            office_native.fill_text(r["objects"], office_native.page_lines(path, n))
        except Exception:
            pass
    elif k == "pptx":
        r = _pptx_open(path, n)
    elif k == "svg":
        r = _svg_open(path)
    else:
        r = _img_open(path)
    r["type"] = k
    if orig_kind == "office" and native_of(orig_path) in ("docx", "xlsx", "text"):
        r["native"] = True
    nat = native_of(orig_path) if orig_kind == "office" else None
    if orig_kind == "office" and k == "pptx":
        r["note"] = "Saved back as the same kind of file."
    elif orig_kind == "office" and nat:
        r["note"] = {"docx": "Shown as pages. Saving writes the changes into the Word file itself (same file type): retyped, deleted and recoloured text, text you move or add (kept in place on the page), boxes, arrows and pictures you add.",
                     "xlsx": "Shown as pages. Saving writes retyped or deleted cell text into the workbook itself (same file type). Cells stay on the grid, so moving things is not saved.",
                     "text": "Shown as pages. Saving writes retyped or deleted lines into the text file itself (same file type)."}[nat]
    elif orig_kind == "office":
        r["note"] = ("Shown as a picture you can add layers to. Saving makes a PNG copy; the original file is not changed." if k == "image"
                     else "Shown as pages. Saving makes a PDF copy; the original file is not changed. (To change the words inside a Word file itself, use Editor.)")
    return r


def glyphs(path: str, n: int) -> dict:
    """the boxes of single letters (PDF text only; the other kinds have text you can retype directly)"""
    k, path = _resolve(path)
    if k != "pdf":
        return {"page": n, "objects": [], "count": 0, "note": "Single letters can be moved in PDF text only."}
    from . import pdfobjects
    return pdfobjects.glyph_boxes(path, n)


def preview(path: str, pages: list[dict], page_no: int, dpi: int = 110) -> dict:
    k, path = _resolve(path)
    mine = [pg for pg in pages if int(pg.get("page", 1)) == page_no]
    if k == "pdf":
        from . import pdfobjects
        return pdfobjects.preview(path, mine, page_no, dpi)
    if k == "pptx":
        return _pptx_preview(path, mine, page_no, dpi)
    if k == "svg":
        return _svg_preview(path, mine)
    return _img_preview(path, mine)


def _save_native(src: Path, dst: Path, pages: list[dict], nat: str) -> int:
    """write the edits into the file's own format (see office_native); older formats are edited as a modern twin and converted back"""
    import tempfile
    from . import office_native as on
    ext = src.suffix.lower()
    k, pdf = _resolve(str(src))
    if nat == "text":
        return on.text_write(src, dst, pdf, pages)
    modern = ".docx" if nat == "docx" else ".xlsx"
    writer = on.docx_write if nat == "docx" else on.xlsx_write
    if ext == modern:
        return writer(src, dst, pdf, pages)
    tmp = Path(tempfile.mkdtemp(prefix="fathom_nat_"))
    try:
        twin = _modern_twin(src, modern[1:])
        mid = tmp / ("mid" + modern)
        n = writer(twin, mid, pdf, pages)
        back = on.soffice_convert(mid, ext[1:], tmp / "back") if (tmp / "back").mkdir() is None else None
        shutil.copyfile(back, dst)
        return n
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def save_edits(src: Path, dst: Path, pages: list[dict]) -> int:
    nat = native_of(str(src)) if kind_of(str(src)) == "office" else None
    if nat in ("docx", "xlsx", "text"):
        return _save_native(Path(src), Path(dst), pages, nat)
    k, real = _resolve(str(src))
    if nat == "slides":                                  # slides: edit the PowerPoint twin, then convert it back to .ppt / .odp
        import tempfile
        from . import office_native as on
        tmp = Path(tempfile.mkdtemp(prefix="fathom_nat_"))
        try:
            mid = tmp / "mid.pptx"
            n = _pptx_write(Path(real), mid, pages)
            (tmp / "back").mkdir()
            back = on.soffice_convert(mid, Path(src).suffix.lower()[1:], tmp / "back")
            shutil.copyfile(back, dst)
            return n
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    src = Path(real)
    if k == "pdf":
        from . import pdfobjects
        return pdfobjects.save_edits(src, dst, pages)
    if k == "pptx":
        return _pptx_write(src, dst, pages)
    if k == "svg":
        txt, n = _svg_apply(str(src), pages)
        dst.write_text(txt, encoding="utf-8")
        return n
    return _img_write(src, dst, pages)


# ================================================================== pictures: the picture is the background, everything else is a layer
def _img_open(path: str) -> dict:
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
    return {"page": 1, "total": 1, "w": w, "h": h, "objects": [], "capped": False, "note": "A picture is flat pixels, so what is already in it cannot be dragged. Everything you add here (text, shapes, arrows, other pictures) is a layer you can move, resize and recolour until you save."}


def _img_compose(path: str, pages: list[dict]):
    from PIL import Image, ImageDraw
    im = Image.open(path)
    im.load()
    base = im.convert("RGBA")
    adds = []
    for pg in pages:
        adds += pg.get("adds") or []
    for a in adds:
        base = _img_layer(base, a)
    return base, im


def _img_layer(base, a: dict):
    from PIL import Image, ImageDraw
    from . import textsnap
    t = a.get("type")
    x, y = float(a.get("x", 0) or 0), float(a.get("y", 0) or 0)
    w, h = float(a.get("w", 0) or 0), float(a.get("h", 0) or 0)
    lw = max(1, round(float(a.get("lw") or 2)))
    st = _rgb(a.get("stroke")) if a.get("stroke") else None
    fl = _rgb(a.get("fill")) if a.get("fill") else None
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if t in ("rect", "round", "ellipse"):
        box = [x, y, x + w, y + h]
        if not st and not fl:
            st = (0, 0, 0)
        if t == "ellipse":
            d.ellipse(box, fill=fl, outline=st, width=lw if st else 0)
        elif t == "round":
            d.rounded_rectangle(box, radius=min(w, h) * 0.18, fill=fl, outline=st, width=lw if st else 0)
        else:
            d.rectangle(box, fill=fl, outline=st, width=lw if st else 0)
    elif t in ("line", "arrow"):
        x2, y2 = float(a.get("x2", 0) or 0), float(a.get("y2", 0) or 0)
        col = st or fl or (0, 0, 0)
        ang = math.atan2(y2 - y, x2 - x)
        head = max(8.0, lw * 4)
        if t == "arrow":
            sx, sy = x2 - math.cos(ang) * head * 0.8, y2 - math.sin(ang) * head * 0.8
            d.line([x, y, sx, sy], fill=col, width=lw)
            d.polygon([(x2, y2), (x2 - head * math.cos(ang - 0.4), y2 - head * math.sin(ang - 0.4)), (x2 - head * math.cos(ang + 0.4), y2 - head * math.sin(ang + 0.4))], fill=col)
        else:
            d.line([x, y, x2, y2], fill=col, width=lw)
    elif t == "text":
        from . import richtext
        runs, align = richtext.normalize(a)
        lay, _W, _H = richtext.layout(runs, float(a.get("w", 0) or 0) or None, align)
        for ln, dx, bl, _w in lay:
            cx = x + dx
            for r in ln:
                px = max(6, int(round(r["size"])))
                fp = richtext.font_path(r["font"], r["b"], r["i"])
                try:
                    f = richtext._pil_font(fp, px) if fp else textsnap.get_font(px)
                except Exception:
                    f = textsnap.get_font(px)
                col = _rgb(r["color"])
                d.text((cx, y + bl), r["t"], font=f, fill=col, anchor="ls")
                wd = d.textlength(r["t"], font=f)
                if r.get("u"):
                    d.line([cx, y + bl + px * 0.12, cx + wd, y + bl + px * 0.12], fill=col, width=max(1, int(px * 0.06)))
                cx += wd
    elif t == "image":
        raw = _data_bytes(a.get("data", ""))
        if raw and w > 0 and h > 0:
            pic = Image.open(io.BytesIO(raw)).convert("RGBA").resize((max(1, int(w)), max(1, int(h))))
            layer.paste(pic, (int(x), int(y)), pic)
    return Image.alpha_composite(base, layer)


def _img_preview(path: str, pages: list[dict]) -> dict:
    base, _im = _img_compose(path, pages)
    if base.width > 1600:
        base = base.resize((1600, max(1, round(base.height * 1600 / base.width))))
    buf = io.BytesIO()
    base.save(buf, "PNG")
    return {"png": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), "scale": 1, "w": base.width, "h": base.height}


def _img_write(src: Path, dst: Path, pages: list[dict]) -> int:
    from PIL import Image
    base, orig = _img_compose(str(src), pages)
    ext = dst.suffix.lower()
    n = sum(len(pg.get("adds") or []) for pg in pages)
    if ext in (".jpg", ".jpeg"):
        white = Image.new("RGB", base.size, (255, 255, 255))
        white.paste(base, mask=base.getchannel("A"))
        kw = {"quality": 95, "subsampling": 0}
        if orig.info.get("exif"):
            kw["exif"] = orig.info["exif"]
        white.save(dst, **kw)
    elif ext in (".bmp",):
        base.convert("RGB").save(dst)
    else:
        base.save(dst)
    return n


# ================================================================== PowerPoint slides (python-pptx); shapes keep their own formatting
EMU = 12700.0


def _pptx_open(path: str, n: int) -> dict:
    from pptx import Presentation
    prs = Presentation(path)
    total = len(prs.slides)
    if not 1 <= n <= total:
        raise UserError("That slide does not exist.")
    slide = prs.slides[n - 1]
    objs = []
    for i, sh in enumerate(slide.shapes):
        if sh.left is None or sh.width is None:
            continue                                   # placeholders that inherit their place cannot be moved reliably
        fill = stroke = None
        text = ""
        kind = "shape"
        try:
            if sh.shape_type == 13:
                kind = "image"
            elif sh.shape_type == 6:
                kind = "group"
        except Exception:
            pass
        runs = None
        ix = iy = 0.0
        if kind == "shape" and sh.has_text_frame and sh.text_frame.text.strip():
            try:
                textbox = sh.shape_type == 17 or (not sh.is_placeholder and sh.fill.type is None and sh.line.fill.type in (None, 5))
            except Exception:
                textbox = False
            if textbox:
                try:
                    tf = sh.text_frame
                    ix, iy = (tf.margin_left if tf.margin_left is not None else 91440) / EMU, (tf.margin_top if tf.margin_top is not None else 45720) / EMU
                    runs = []
                    for pi_, para in enumerate(tf.paragraphs):
                        if pi_:
                            runs.append({"t": "\n", "font": "Calibri", "size": 18.0, "color": "#000000", "b": False, "i": False, "u": False})
                        for r in para.runs:
                            f = r.font
                            col = "#000000"
                            try:
                                if f.color is not None and f.color.type is not None:
                                    col = "#" + str(f.color.rgb)
                            except Exception:
                                pass
                            runs.append({"t": r.text, "font": f.name or "Calibri", "size": float(f.size.pt) if f.size else 18.0, "color": col, "b": bool(f.bold), "i": bool(f.italic), "u": bool(f.underline)})
                    if runs:
                        kind = "text"
                except Exception:
                    runs = None
        if kind == "shape":
            try:
                if sh.fill.type == 1:
                    fill = "#" + str(sh.fill.fore_color.rgb)
            except Exception:
                pass
            try:
                if sh.line.fill.type == 1:
                    stroke = "#" + str(sh.line.color.rgb)
            except Exception:
                pass
            if sh.has_text_frame:
                text = sh.text_frame.text
        lw = None
        try:
            lw = round(sh.line.width / EMU, 2) if sh.line.width else None
        except Exception:
            pass
        objs.append({"id": i, "kind": kind, "x": round(sh.left / EMU, 2), "y": round(sh.top / EMU, 2), "w": round(sh.width / EMU, 2), "h": round(sh.height / EMU, 2),
                     "fill": fill, "stroke": stroke, "lw": lw, "text": text if kind != "text" else sh.text_frame.text, "size": (max(r["size"] for r in runs) if runs else None),
                     "textable": bool(sh.has_text_frame) if kind == "shape" else False, "runs": runs, "ix": ix, "iy": iy, "top": bool(runs)})
    return {"page": n, "total": total, "w": prs.slide_width / EMU, "h": prs.slide_height / EMU, "objects": objs, "capped": False}


def _set_text(tf, text: str) -> None:
    lines = str(text).split("\n")
    paras = list(tf.paragraphs)
    if not paras:
        tf.text = text
        return
    p0 = paras[0]
    for p in paras[1:]:
        p._p.getparent().remove(p._p)
    runs = list(p0.runs)
    if runs:
        runs[0].text = lines[0]
        for r in runs[1:]:
            r._r.getparent().remove(r._r)
    else:
        p0.text = lines[0]
    last = p0
    for ln in lines[1:]:
        newp = copy.deepcopy(p0._p)
        last._p.addnext(newp)
        from pptx.text.text import _Paragraph
        np_ = _Paragraph(newp, p0._parent)
        rs = list(np_.runs)
        if rs:
            rs[0].text = ln
            for r in rs[1:]:
                r._r.getparent().remove(r._r)
        else:
            np_.text = ln
        last = np_


def _pptx_apply(prs, pages: list[dict]) -> int:
    from pptx.dml.color import RGBColor
    from pptx.util import Emu, Pt
    changed = 0
    for pg in pages:
        n = int(pg.get("page", 1))
        if not 1 <= n <= len(prs.slides):
            continue
        slide = prs.slides[n - 1]
        shapes = list(slide.shapes)
        for m in pg.get("mods") or []:
            i = int(m.get("id", -1))
            if not 0 <= i < len(shapes):
                continue
            sh = shapes[i]
            changed += 1
            if m.get("delete"):
                sh._element.getparent().remove(sh._element)
                continue
            if m.get("dup"):
                d = m["dup"] if isinstance(m["dup"], dict) else {}
                el = copy.deepcopy(sh._element)
                sh._element.addnext(el)
                try:
                    from pptx.shapes.autoshape import Shape
                    dup = [s for s in slide.shapes if s._element is el][0]
                    dup.left = Emu(int(sh.left + float(d.get("dx", 14)) * EMU)); dup.top = Emu(int(sh.top + float(d.get("dy", 14)) * EMU))
                except Exception:
                    pass
            sx, sy = float(m.get("sx", 1) or 1), float(m.get("sy", 1) or 1)
            if sh.left is not None:
                left, top, w, h = sh.left, sh.top, sh.width, sh.height
                sh.left = Emu(int(left + float(m.get("dx", 0) or 0) * EMU)); sh.top = Emu(int(top + float(m.get("dy", 0) or 0) * EMU))
                if sx != 1 or sy != 1:
                    sh.width = Emu(max(1, int(w * sx))); sh.height = Emu(max(1, int(h * sy)))
            try:
                if "fill" in m:
                    if m["fill"]:
                        sh.fill.solid(); sh.fill.fore_color.rgb = RGBColor(*_rgb(m["fill"]))
                    else:
                        sh.fill.background()
                if "stroke" in m:
                    if m["stroke"]:
                        sh.line.color.rgb = RGBColor(*_rgb(m["stroke"]))
                    else:
                        sh.line.fill.background()
                if m.get("lw") is not None:
                    sh.line.width = Pt(float(m["lw"]))
                if m.get("text") is not None and sh.has_text_frame and m["text"] != sh.text_frame.text:
                    _set_text(sh.text_frame, m["text"])
            except Exception:
                pass
        for a in pg.get("adds") or []:
            changed += 1
            _pptx_add(slide, a)
    return changed


def _pptx_add(slide, a: dict) -> None:
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.util import Emu, Pt
    t = a.get("type")
    x, y, w, h = (float(a.get(k, 0) or 0) * EMU for k in ("x", "y", "w", "h"))
    st, fl = a.get("stroke"), a.get("fill")
    if t in ("rect", "round", "ellipse"):
        shp = slide.shapes.add_shape({"rect": MSO_SHAPE.RECTANGLE, "round": MSO_SHAPE.ROUNDED_RECTANGLE, "ellipse": MSO_SHAPE.OVAL}[t], Emu(int(x)), Emu(int(y)), Emu(max(1, int(w))), Emu(max(1, int(h))))
        if fl:
            shp.fill.solid(); shp.fill.fore_color.rgb = RGBColor(*_rgb(fl))
        else:
            shp.fill.background()
        if st:
            shp.line.color.rgb = RGBColor(*_rgb(st)); shp.line.width = Pt(float(a.get("lw") or 1))
        else:
            shp.line.fill.background()
        shp.shadow.inherit = False
    elif t in ("line", "arrow"):
        x2, y2 = float(a.get("x2", 0) or 0) * EMU, float(a.get("y2", 0) or 0) * EMU
        c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(int(x)), Emu(int(y)), Emu(int(x2)), Emu(int(y2)))
        c.line.color.rgb = RGBColor(*_rgb(st or fl or "#000000")); c.line.width = Pt(float(a.get("lw") or 2))
        if t == "arrow":
            from lxml import etree
            ln = c.line._get_or_add_ln()
            ln.append(etree.SubElement(ln, "{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd", type="triangle"))
    elif t == "text":
        from pptx.enum.text import PP_ALIGN
        from . import richtext
        runs, align = richtext.normalize(a)
        lay, Wd, Hd = richtext.layout(runs, float(a.get("w", 0) or 0) or None, align)
        tb = slide.shapes.add_textbox(Emu(int(x)), Emu(int(y)), Emu(int((Wd + 6) * EMU)), Emu(int(Hd * EMU)))
        tf = tb.text_frame
        tf.word_wrap = False
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        for k, (ln, _dx, _b, _w) in enumerate(lay):
            p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
            p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[align]
            for r in ln:
                rr = p.add_run(); rr.text = r["t"]
                f = rr.font
                f.name = r["font"]; f.size = Pt(r["size"]); f.bold = r["b"]; f.italic = r["i"]; f.underline = bool(r.get("u"))
                f.color.rgb = RGBColor(*_rgb(r["color"]))
    elif t == "image":
        raw = _data_bytes(a.get("data", ""))
        if raw:
            slide.shapes.add_picture(io.BytesIO(raw), Emu(int(x)), Emu(int(y)), Emu(max(1, int(w))), Emu(max(1, int(h))))


def _pptx_write(src: Path, dst: Path, pages: list[dict]) -> int:
    from pptx import Presentation
    prs = Presentation(str(src))
    n = _pptx_apply(prs, pages)
    prs.save(str(dst))
    return n


def _pptx_preview(path: str, pages: list[dict], page_no: int, dpi: int) -> dict:
    import uuid
    from . import pdfview, proof
    from .paths import temp_dir
    tmp = temp_dir() / ("vis_" + uuid.uuid4().hex[:8] + ".pptx")
    try:
        _pptx_write(Path(path), tmp, pages)
        try:
            pdf = pdfview._as_pdf(tmp)
        except Exception as e:
            raise UserError("The slide picture needs LibreOffice, which the Lite install leaves out. Run Fathom.bat full to add it. (" + str(e)[:80] + ")")
        got = proof.render_pdf_page(pdf, page_no - 1, dpi)
        if not got:
            raise UserError("This computer cannot draw the slide picture (PDF engine missing).")
        im, scale = got
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return {"png": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), "scale": scale, "w": im.width, "h": im.height}
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


# ================================================================== SVG drawings (the browser draws the result itself)
SVGNS = "http://www.w3.org/2000/svg"
DRAWABLE = {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text", "image"}


def _ln(tag: str) -> str:
    return tag.split("}")[-1]


def _mat(s: str):
    """an SVG transform list as a matrix (a b c d e f)"""
    from .pdfobjects import IDENT, mul
    m = IDENT
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in re.findall(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", args)]
        try:
            if name == "translate":
                t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
            elif name == "scale":
                t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
            elif name == "matrix":
                t = tuple(v[:6])
            elif name == "rotate":
                a = math.radians(v[0]); c, s_ = math.cos(a), math.sin(a)
                t = (c, s_, -s_, c, 0, 0)
                if len(v) == 3:
                    t = mul(mul((1, 0, 0, 1, -v[1], -v[2]), t), (1, 0, 0, 1, v[1], v[2]))
            else:
                continue
        except IndexError:
            continue
        m = mul(t, m)
    return m


def _path_pts(d: str):
    toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d or "")
    pts, i, cx, cy, sx, sy, cmd = [], 0, 0.0, 0.0, 0.0, 0.0, ""
    def num():
        nonlocal i
        v = float(toks[i]); i += 1
        return v
    n = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
    while i < len(toks):
        if re.match(r"[A-Za-z]", toks[i]):
            cmd = toks[i]; i += 1
            if cmd in "Zz":
                cx, cy = sx, sy
                continue
        up = cmd.upper(); rel = cmd.islower()
        if up not in n or i + n[up] > len(toks):
            break
        a = [num() for _ in range(n[up])]
        if up == "H":
            cx = cx + a[0] if rel else a[0]; pts.append((cx, cy))
        elif up == "V":
            cy = cy + a[0] if rel else a[0]; pts.append((cx, cy))
        elif up == "A":
            cx, cy = (cx + a[5], cy + a[6]) if rel else (a[5], a[6]); pts.append((cx, cy))
        else:
            for k in range(0, len(a), 2):
                px, py = (cx + a[k], cy + a[k + 1]) if rel else (a[k], a[k + 1])
                pts.append((px, py))
            cx, cy = pts[-1]
            if up == "M":
                sx, sy = cx, cy
                cmd = "l" if rel else "L"
    return pts


def _bbox(el):
    from . import pdfobjects  # noqa: F401
    t = _ln(el.tag)
    g = lambda k, dflt=0.0: float(re.findall(r"-?\d*\.?\d+", el.get(k, str(dflt)))[0]) if re.findall(r"-?\d*\.?\d+", el.get(k, "") or "") else dflt
    if t == "rect" or t == "image":
        return (g("x"), g("y"), g("x") + g("width"), g("y") + g("height"))
    if t == "circle":
        return (g("cx") - g("r"), g("cy") - g("r"), g("cx") + g("r"), g("cy") + g("r"))
    if t == "ellipse":
        return (g("cx") - g("rx"), g("cy") - g("ry"), g("cx") + g("rx"), g("cy") + g("ry"))
    if t == "line":
        return (min(g("x1"), g("x2")), min(g("y1"), g("y2")), max(g("x1"), g("x2")), max(g("y1"), g("y2")))
    if t in ("polyline", "polygon"):
        v = [float(x) for x in re.findall(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", el.get("points", ""))]
        pts = list(zip(v[0::2], v[1::2]))
    elif t == "path":
        pts = _path_pts(el.get("d", ""))
    elif t == "text":
        size = g("font-size", 16.0) or 16.0
        txt = "".join(el.itertext()).strip()
        w = len(txt) * size * 0.55
        x, y = g("x"), g("y")
        anchor = el.get("text-anchor", "start")
        x0 = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
        return (x0, y - size * 0.85, x0 + w, y + size * 0.25)
    else:
        return None
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _svg_load(path: str):
    from lxml import etree
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False, huge_tree=False)
    tree = etree.parse(path, parser)
    return tree


def _svg_size(root):
    vb = root.get("viewBox")
    if vb:
        v = [float(x) for x in re.findall(r"-?\d*\.?\d+", vb)]
        if len(v) == 4:
            return v[0], v[1], v[2], v[3]
    f = lambda k: float(re.findall(r"\d*\.?\d+", root.get(k, "0") or "0")[0]) if re.findall(r"\d*\.?\d+", root.get(k, "") or "") else 0.0
    return 0.0, 0.0, f("width") or 300.0, f("height") or 150.0


def _svg_objects(root):
    from .pdfobjects import IDENT, mul, pt
    objs = []

    def walk(el, ctm):
        for ch in el:
            if not isinstance(ch.tag, str):
                continue
            t = _ln(ch.tag)
            if t in ("defs", "style", "script", "metadata", "title", "desc", "clipPath", "mask", "marker", "symbol"):
                continue
            m = mul(_mat(ch.get("transform", "")), ctm)
            if t in DRAWABLE:
                b = _bbox(ch)
                if b is None:
                    continue
                cs = [pt(m, b[0], b[1]), pt(m, b[2], b[1]), pt(m, b[2], b[3]), pt(m, b[0], b[3])]
                xs, ys = [c[0] for c in cs], [c[1] for c in cs]
                style = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+)", ch.get("style", "") or ""))
                get = lambda k: style.get(k, ch.get(k))
                fill, stroke = get("fill"), get("stroke")
                lw = get("stroke-width")
                objs.append({"id": len(objs), "kind": "text" if t == "text" else "image" if t == "image" else "shape", "el": ch, "pm": ctm, "x": min(xs), "y": min(ys), "w": max(xs) - min(xs), "h": max(ys) - min(ys),
                             "fill": fill if fill and fill.startswith("#") else None, "stroke": stroke if stroke and stroke.startswith("#") else None,
                             "lw": float(lw) if lw and re.match(r"^[\d.]+$", lw) else None, "text": "".join(ch.itertext()).strip() if t == "text" else "", "size": None,
                             "textable": t == "text"})
                if t == "text":
                    sz = get("font-size") or "16"
                    try:
                        sz = float(re.sub(r"[^\d.]", "", sz) or 16)
                    except ValueError:
                        sz = 16.0
                    fam = (get("font-family") or "Arial").split(",")[0].strip().strip("'\"") or "Arial"
                    fc = fill if fill and fill.startswith("#") else "#000000"
                    wt, fs_, td = (get("font-weight") or ""), (get("font-style") or ""), (get("text-decoration") or "")
                    objs[-1].update({"size": sz, "runs": [{"t": objs[-1]["text"], "font": fam, "size": sz, "color": fc, "b": wt in ("bold", "700", "800", "900"), "i": fs_ == "italic", "u": "underline" in td}],
                                     "base": min(ys) + sz * 0.85})
            elif t in ("g", "a", "svg"):
                walk(ch, m)
    walk(root, IDENT)
    return objs


def _svg_open(path: str) -> dict:
    tree = _svg_load(path)
    root = tree.getroot()
    vx, vy, vw, vh = _svg_size(root)
    objs = _svg_objects(root)
    out = [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in o.items() if k not in ("el", "pm")} for o in objs]
    for o in out:
        o["x"] = round(o["x"] - vx, 2); o["y"] = round(o["y"] - vy, 2)
    return {"page": 1, "total": 1, "w": vw, "h": vh, "objects": out, "capped": False}


def _set_style(el, key: str, value: str | None) -> None:
    style = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+)", el.get("style", "") or ""))
    style.pop(key, None)
    if style:
        el.set("style", ";".join(f"{k}:{v}" for k, v in style.items()))
    elif "style" in el.attrib:
        del el.attrib["style"]
    if value is None:
        el.attrib.pop(key, None)
    else:
        el.set(key, value)


def _svg_apply(path: str, pages: list[dict]) -> tuple[str, int]:
    from lxml import etree
    from .pdfobjects import inv, mul, pt
    tree = _svg_load(path)
    root = tree.getroot()
    vx, vy, vw, vh = _svg_size(root)
    objs = _svg_objects(root)
    mods, adds = [], []
    for pg in pages:
        mods += pg.get("mods") or []
        adds += pg.get("adds") or []
    changed = 0
    for m in mods:
        i = int(m.get("id", -1))
        if not 0 <= i < len(objs):
            continue
        o = objs[i]; el = o["el"]
        changed += 1
        if m.get("delete"):
            el.getparent().remove(el)
            continue
        if m.get("dup"):
            d = m["dup"] if isinstance(m["dup"], dict) else {}
            c = copy.deepcopy(el)
            c.set("transform", f"translate({float(d.get('dx', 14))} {float(d.get('dy', 14))}) " + (el.get("transform") or ""))
            el.addnext(c)
        dx, dy = float(m.get("dx", 0) or 0), float(m.get("dy", 0) or 0)
        sx, sy = float(m.get("sx", 1) or 1), float(m.get("sy", 1) or 1)
        if dx or dy or sx != 1 or sy != 1:
            P = o["pm"]                                         # parent's transform: screen space -> element's parent space
            ax, ay = o["x"] + vx, o["y"] + vy                    # top-left in root space
            T = (sx, 0, 0, sy, ax - sx * ax + dx, ay - sy * ay + dy)
            L = mul(mul(P, T), inv(P))                           # the same change expressed in the parent's own space
            el.set("transform", "matrix(%s) %s" % (" ".join(repr(round(v, 5)) for v in L), el.get("transform") or ""))
        if "fill" in m:
            _set_style(el, "fill", m["fill"] or "none")
        if "stroke" in m:
            _set_style(el, "stroke", m["stroke"] or "none")
        if m.get("lw") is not None:
            _set_style(el, "stroke-width", str(m["lw"]))
        if m.get("text") is not None and _ln(el.tag) == "text" and m["text"] != o["text"]:
            for ch in list(el):
                el.remove(ch)
            el.text = str(m["text"])
    S = lambda tag, **kw: etree.SubElement(root, "{%s}%s" % (SVGNS, tag), **{k: str(v) for k, v in kw.items()})
    for a in adds:
        changed += 1
        t = a.get("type")
        x, y = float(a.get("x", 0) or 0) + vx, float(a.get("y", 0) or 0) + vy
        w, h = float(a.get("w", 0) or 0), float(a.get("h", 0) or 0)
        st, fl, lw = a.get("stroke") or "none", a.get("fill") or "none", a.get("lw") or 1
        if t in ("rect", "round"):
            e = S("rect", x=x, y=y, width=w, height=h, fill=fl, stroke=st if (a.get("stroke") or not a.get("fill")) else "none", **{"stroke-width": lw})
            if t == "round":
                e.set("rx", str(min(w, h) * 0.18))
        elif t == "ellipse":
            S("ellipse", cx=x + w / 2, cy=y + h / 2, rx=w / 2, ry=h / 2, fill=fl, stroke=st, **{"stroke-width": lw})
        elif t in ("line", "arrow"):
            x2, y2 = float(a.get("x2", 0) or 0) + vx, float(a.get("y2", 0) or 0) + vy
            col = a.get("stroke") or a.get("fill") or "#000000"
            ang = math.atan2(y2 - y, x2 - x); head = max(8.0, float(lw) * 4)
            ex, ey = (x2 - math.cos(ang) * head * 0.8, y2 - math.sin(ang) * head * 0.8) if t == "arrow" else (x2, y2)
            S("line", x1=x, y1=y, x2=ex, y2=ey, stroke=col, **{"stroke-width": lw})
            if t == "arrow":
                S("polygon", points=f"{x2},{y2} {x2 - head * math.cos(ang - 0.4)},{y2 - head * math.sin(ang - 0.4)} {x2 - head * math.cos(ang + 0.4)},{y2 - head * math.sin(ang + 0.4)}", fill=col)
        elif t == "text":
            from . import richtext
            runs, align = richtext.normalize(a)
            lay, _W, _H = richtext.layout(runs, float(a.get("w", 0) or 0) or None, align)
            for ln, dx, base, _w in lay:
                e = S("text", x=x + dx, y=y + base)
                e.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                for r in ln:
                    ts = etree.SubElement(e, "{%s}tspan" % SVGNS)
                    ts.set("fill", r["color"]); ts.set("font-size", str(r["size"])); ts.set("font-family", f"'{r['font']}', Arial, Helvetica, sans-serif")
                    if r["b"]:
                        ts.set("font-weight", "bold")
                    if r["i"]:
                        ts.set("font-style", "italic")
                    if r.get("u"):
                        ts.set("text-decoration", "underline")
                    ts.text = r["t"]
        elif t == "image":
            raw = a.get("data", "")
            if raw.startswith("data:image/"):
                S("image", x=x, y=y, width=w, height=h, href=raw)
    return etree.tostring(tree, encoding="unicode", xml_declaration=False), changed


def _svg_preview(path: str, pages: list[dict]) -> dict:
    txt, _n = _svg_apply(path, pages)
    vx, vy, vw, vh = _svg_size(_svg_load(path).getroot())
    return {"png": "data:image/svg+xml;base64," + base64.b64encode(txt.encode("utf-8")).decode(), "scale": 1, "w": vw, "h": vh}
