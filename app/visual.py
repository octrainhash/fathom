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

from .service import UserError

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
KINDS_TEXT = "PDF, PowerPoint (.pptx), SVG and picture files"


def kind_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext == ".pptx":
        return "pptx"
    if ext == ".svg":
        return "svg"
    if ext in IMG_EXT:
        return "image"
    raise UserError(f"The visual editor opens {KINDS_TEXT}. For Word, Excel and other files use Editor.")


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
    k = kind_of(path)
    if k == "pdf":
        from . import pdfobjects
        r = pdfobjects.open_page(path, n)
    elif k == "pptx":
        r = _pptx_open(path, n)
    elif k == "svg":
        r = _svg_open(path)
    else:
        r = _img_open(path)
    r["type"] = k
    return r


def preview(path: str, pages: list[dict], page_no: int, dpi: int = 110) -> dict:
    k = kind_of(path)
    mine = [pg for pg in pages if int(pg.get("page", 1)) == page_no]
    if k == "pdf":
        from . import pdfobjects
        return pdfobjects.preview(path, mine, page_no, dpi)
    if k == "pptx":
        return _pptx_preview(path, mine, page_no, dpi)
    if k == "svg":
        return _svg_preview(path, mine)
    return _img_preview(path, mine)


def save_edits(src: Path, dst: Path, pages: list[dict]) -> int:
    k = kind_of(str(src))
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
        size = max(6, int(float(a.get("size") or 16)))
        f = textsnap.get_font(size)
        col = _rgb(a.get("color") or a.get("fill") or "#000000")
        for k, line in enumerate(str(a.get("text", "")).split("\n")):
            d.text((x, y + k * size * 1.25), line, font=f, fill=col)
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
                     "fill": fill, "stroke": stroke, "lw": lw, "text": text, "size": None, "textable": bool(sh.has_text_frame) if kind == "shape" else False})
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
        size = float(a.get("size") or 16)
        lines = str(a.get("text", "")).split("\n")
        tb = slide.shapes.add_textbox(Emu(int(x)), Emu(int(y)), Emu(int(max(len(l) for l in lines) * size * 0.6 * EMU + 20 * EMU)), Emu(int(len(lines) * size * 1.4 * EMU)))
        tf = tb.text_frame
        tf.word_wrap = False
        for k, ln in enumerate(lines):
            p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
            r = p.add_run(); r.text = ln; r.font.size = Pt(size); r.font.color.rgb = RGBColor(*_rgb(a.get("color") or a.get("fill") or "#000000"))
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
            size = float(a.get("size") or 16)
            for k, line in enumerate(str(a.get("text", "")).split("\n")):
                e = S("text", x=x, y=y + size * 0.9 + k * size * 1.25, fill=a.get("color") or a.get("fill") or "#000000", **{"font-size": size, "font-family": "Arial, Helvetica, sans-serif"})
                e.text = line
        elif t == "image":
            raw = a.get("data", "")
            if raw.startswith("data:image/"):
                S("image", x=x, y=y, width=w, height=h, href=raw)
    return etree.tostring(tree, encoding="unicode", xml_declaration=False), changed


def _svg_preview(path: str, pages: list[dict]) -> dict:
    txt, _n = _svg_apply(path, pages)
    vx, vy, vw, vh = _svg_size(_svg_load(path).getroot())
    return {"png": "data:image/svg+xml;base64," + base64.b64encode(txt.encode("utf-8")).decode(), "scale": 1, "w": vw, "h": vh}
