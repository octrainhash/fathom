# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""PDF -> Word / PowerPoint keeping every box, line, arrow, picture and piece of text exactly where it was.

Flowing converters rebuild a page as paragraphs and tables, which wrecks diagrams, posters, forms and anything designed (boxes become full-width
table cells, arrows drift). This builder instead reads what the page draws (the same objects the Visual editor works with) and re-creates each one:
shapes keep their exact outline (curves, rounded corners, arrow heads), pictures keep their position and size, and every line of text becomes a
text box with the same font, size, colour and angle. Nothing needs PyMuPDF, only pypdf and python-docx / python-pptx."""
from __future__ import annotations

import io
import math
import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import ContentStream

from app import pdfobjects as po

E = 12700.0                       # EMU per point
ASC = 0.905                       # Arial-like baseline position inside a line, as a fraction of the font size
LINE = 1.15                       # single line height as a fraction of the font size


# ------------------------------------------------------------------ fonts
from app.richtext import font_info  # noqa: E402  (PDF font name -> family, bold, italic)


def _hex(rgb) -> str:
    return "%02X%02X%02X" % tuple(max(0, min(255, int(round(float(v) * 255)))) for v in rgb)


def _rgb_from_seq(seq) -> str | None:
    """the last colour set before a show, from the recorded colour instructions"""
    try:
        for operands, op in reversed(seq):
            o = op.decode() if isinstance(op, bytes) else str(op)
            v = [float(x) for x in operands]
            if o == "g" and len(v) == 1:
                return _hex((v[0],) * 3)
            if o in ("rg", "sc", "scn") and len(v) == 3:
                return _hex(v)
            if o == "k" and len(v) == 4:
                c, m, y, k = v
                return _hex(((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)))
    except Exception:
        pass
    return None


# ------------------------------------------------------------------ reading a page
class Item:
    def __init__(self, kind, **kw):
        self.kind = kind
        self.__dict__.update(kw)


def _path_points(seg, ctm):
    """[('M',(x,y)), ('L',(x,y)), ('C',(p1,p2,p3)), ('Z',)] in page space (PDF origin)"""
    out = []
    cur = None
    start = None
    P = lambda x, y: po.pt(ctm, float(x), float(y))
    for operands, op in seg:
        o = op.decode() if isinstance(op, bytes) else str(op)
        v = [float(x) for x in operands] if operands else []
        if o == "m" and len(v) == 2:
            cur = P(*v); start = cur; out.append(("M", cur))
        elif o == "l" and len(v) == 2:
            cur = P(*v); out.append(("L", cur))
        elif o == "c" and len(v) == 6:
            p1, p2, p3 = P(v[0], v[1]), P(v[2], v[3]), P(v[4], v[5]); out.append(("C", (p1, p2, p3))); cur = p3
        elif o == "v" and len(v) == 4 and cur:
            p2, p3 = P(v[0], v[1]), P(v[2], v[3]); out.append(("C", (cur, p2, p3))); cur = p3
        elif o == "y" and len(v) == 4:
            p1, p3 = P(v[0], v[1]), P(v[2], v[3]); out.append(("C", (p1, p3, p3))); cur = p3
        elif o == "re" and len(v) == 4:
            x, y, w, h = v
            a, b, c, d = P(x, y), P(x + w, y), P(x + w, y + h), P(x, y + h)
            out += [("M", a), ("L", b), ("L", c), ("L", d), ("Z",)]
            cur = start = a
        elif o == "h":
            out.append(("Z",)); cur = start
    return out


def read_page(reader: PdfReader, page, number: int) -> tuple[list[Item], float, float]:
    x0, y0, x1, y1 = po._page_box(page)
    W, H = x1 - x0, y1 - y0
    ops, objs = po.parse(reader, page)
    pieces = []
    try:
        page.extract_text(visitor_text=lambda t, cm, tm, fd, fs: pieces.append((t, tm, fd, fs)) if t and t.strip("\n") != "" else None)
    except Exception:
        pass
    nshows = sum(len(o.get("shows") or []) for o in objs if o["kind"] == "text")
    by_order = len(pieces) == nshows           # pypdf reports one piece per show, in drawing order: the safest way to pair text with positions
    order_i = [0]
    items: list[Item] = []
    used = [False] * len(pieces)

    def screen(px, py):
        return px - x0, y1 - py

    imgs = None
    for o in objs:
        k = o["kind"]
        if k == "shape":
            seg = ops[o["a"]:o["b"] + 1]
            pts = _path_points(seg, o["ctm"])
            if not pts:
                continue
            paint = o.get("paint") or ""
            fill = o.get("fill") if any(c in paint for c in "fFB") else None
            stroke = o.get("stroke") if any(c in paint for c in "SsBb") else None
            if not fill and not stroke:
                continue
            items.append(Item("shape", pts=pts, fill=fill, stroke=stroke, lw=float(o.get("lw") or 1.0), z=o["id"]))
        elif k == "text":
            for sh in o.get("shows") or []:
                full = sh["full"]
                ox, oy = full[4], full[5]
                best = None
                if by_order:
                    best = order_i[0]
                    order_i[0] += 1
                else:
                    bd = 0.6
                    for pi, (t, tm, fd, fs) in enumerate(pieces):
                        if used[pi]:
                            continue
                        d = abs(tm[4] - ox) + abs(tm[5] - oy)
                        if d < bd:
                            best, bd = pi, d
                if best is None or best >= len(pieces):
                    continue
                used[best] = True
                text = pieces[best][0].replace("\n", " ").rstrip()
                if not text.strip():
                    continue
                fd = pieces[best][2]
                base = ""
                try:
                    base = str(fd.get("/BaseFont", "")) if fd else ""
                except Exception:
                    pass
                fam, bold, ital = font_info(base)
                size = float(sh.get("size") or o.get("size") or 12) * math.hypot(full[0], full[1])
                width = 0.0
                for g in o.get("glyphs") or []:
                    if g[0] == (o["shows"].index(sh)):
                        width = max(width, g[4] + g[6])
                ang = math.degrees(math.atan2(full[1], full[0]))
                sx, sy = screen(ox, oy)
                col = _rgb_from_seq(sh.get("fillseq") or []) or (o.get("fill") or "#000000").lstrip("#").upper()
                items.append(Item("text", text=text, x=sx, y=sy, size=size, w=width or len(text) * size * 0.5, family=fam, bold=bold, italic=ital, color=col, angle=ang, z=o["id"]))
        elif k == "image":
            try:
                name = ops[o["a"]][0][0]
                ref = page["/Resources"]["/XObject"].raw_get(name)
                data = None
                for im in page.images:
                    if getattr(im, "indirect_reference", None) is not None and im.indirect_reference == ref:
                        buf = io.BytesIO()
                        im.image.save(buf, "PNG")
                        data = buf.getvalue()
                        break
                if data:
                    bx = o["bbox"]
                    items.append(Item("image", data=data, x=bx[0] - x0, y=y1 - bx[3], w=bx[2] - bx[0], h=bx[3] - bx[1], z=o["id"]))
            except Exception:
                continue
    items.sort(key=lambda i: i.z)
    return items, W, H


def has_graphics(path: str, limit: int = 12) -> bool:
    """true when the PDF is a diagram / design rather than running text: several drawn shapes or pictures on a page"""
    try:
        r = PdfReader(path)
        if r.is_encrypted:
            return False
        for pg in list(r.pages)[:limit]:
            try:
                _ops, objs = po.parse(r, pg)
            except Exception:
                continue
            gfx = sum(1 for o in objs if o["kind"] in ("shape", "image", "group"))
            # table rules are shapes too, so only a real mix of boxes and text counts
            if gfx >= 5 or sum(1 for o in objs if o["kind"] == "image") >= 1:
                return True
    except Exception:
        return False
    return False


# ------------------------------------------------------------------ Word
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NSDECL = f'xmlns:w="{W_NS}" xmlns:wp="{WP}" xmlns:a="{A}" xmlns:wps="{WPS}" xmlns:pic="{PIC}" xmlns:r="{R_NS}"'


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _emu(v: float) -> int:
    return int(round(v * E))


def _anchor(x, y, cx, cy, inner, did, z, rot=0):
    return (f'<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="{251650000 + z}" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>{_emu(x)}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>{_emu(y)}</wp:posOffset></wp:positionV><wp:extent cx="{max(1, _emu(cx))}" cy="{max(1, _emu(cy))}"/>'
            f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/><wp:docPr id="{did}" name="Fathom {did}"/><wp:cNvGraphicFramePr/>{inner}</wp:anchor>')


def _text_xml(it: Item, did: int) -> tuple[str, float, float]:
    size = max(1.0, it.size)
    w = it.w * 1.0 + size * 0.6 + 4
    h = size * LINE
    rpr = (f'<w:rFonts w:ascii="{_esc(it.family)}" w:hAnsi="{_esc(it.family)}" w:cs="{_esc(it.family)}" w:eastAsia="{_esc(it.family)}"/>'
           + ("<w:b/>" if it.bold else "") + ("<w:i/>" if it.italic else "") + f'<w:color w:val="{it.color}"/><w:sz w:val="{max(2, int(round(size * 2)))}"/><w:szCs w:val="{max(2, int(round(size * 2)))}"/>')
    rot = (-it.angle) % 360
    # place the (possibly turned) box so the baseline start lands on the original point
    phi = math.radians(rot)
    ox, oy = w / 2, h / 2 - ASC * size            # from the baseline-left point to the centre of the box
    cxr = it.x + (ox * math.cos(phi) - oy * math.sin(phi))
    cyr = it.y + (ox * math.sin(phi) + oy * math.cos(phi))
    left, top = cxr - w / 2, cyr - h / 2
    xf = f' rot="{int(round(rot * 60000))}"' if abs(rot) > 0.05 and abs(rot - 360) > 0.05 else ""
    inner = (f'<a:graphic><a:graphicData uri="{WPS}"><wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr><a:xfrm{xf}><a:off x="0" y="0"/><a:ext cx="{_emu(w)}" cy="{_emu(h)}"/></a:xfrm>'
             f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></wps:spPr><wps:txbx><w:txbxContent><w:p><w:pPr>'
             f'<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{_esc(it.text)}</w:t></w:r></w:p></w:txbxContent></wps:txbx>'
             f'<wps:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t"><a:noAutofit/></wps:bodyPr></wps:wsp></a:graphicData></a:graphic>')
    return _anchor(left, top, w, h, inner, did, it.z), left, top


def _image_xml(it: Item, rid: str, did: int) -> str:
    inner = (f'<a:graphic><a:graphicData uri="{PIC}"><pic:pic><pic:nvPicPr><pic:cNvPr id="{did}" name="Picture {did}"/><pic:cNvPicPr/></pic:nvPicPr>'
             f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{_emu(it.w)}" cy="{_emu(it.h)}"/></a:xfrm>'
             f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>')
    return _anchor(it.x, it.y, it.w, it.h, inner, did, it.z)


def to_docx(src: str, dst: Path, progress=None) -> int:
    """a Word file whose every page is the PDF page rebuilt object by object; returns the number of pages"""
    import docx
    from docx.enum.section import WD_SECTION
    from docx.shared import Pt
    from lxml import etree

    reader = PdfReader(src)
    if reader.is_encrypted:
        raise po.UserError("This PDF is locked with a password. Remove the password first.")
    d = docx.Document()
    body = d.element.body
    for el in list(body):
        if el.tag != "{%s}sectPr" % W_NS:
            body.remove(el)
    did = 100
    n = len(reader.pages)
    for pi, page in enumerate(reader.pages):
        items, W, H = read_page(reader, page, pi + 1)
        sec = d.sections[0] if pi == 0 else d.add_section(WD_SECTION.NEW_PAGE)
        sec.page_width, sec.page_height = int(W * 12700), int(H * 12700)
        sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = 0
        sec.header_distance = sec.footer_distance = 0
        p = d.add_paragraph()
        p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = Pt(1)
        run = p.add_run()
        run.font.size = Pt(1)
        for it in items:
            did += 1
            try:
                if it.kind == "shape":
                    bx = po._page_box(page)
                    xml = _shape_xml_page(it, bx[0], bx[3])
                elif it.kind == "text":
                    xml, _l, _t = _text_xml(it, did)
                elif it.kind == "image":
                    rid, _img = d.part.get_or_add_image(io.BytesIO(it.data))
                    xml = _image_xml(it, rid, did)
                else:
                    continue
                run._r.append(etree.fromstring(f'<w:drawing {NSDECL}>{xml}</w:drawing>'))
            except Exception:
                continue
        if progress:
            progress((pi + 1) / n)
    d.save(str(dst))
    return n


def _shape_xml_page(it: Item, px0: float, py0: float) -> str:
    """shape in page space (PDF origin) -> anchored custom shape"""
    xs, ys = [], []
    for seg in it.pts:
        if seg[0] in ("M", "L"):
            xs.append(seg[1][0]); ys.append(seg[1][1])
        elif seg[0] == "C":
            for p in seg[1]:
                xs.append(p[0]); ys.append(p[1])
    bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
    cx, cy = max(bx1 - bx0, 0.01), max(by1 - by0, 0.01)
    P = lambda p: f'<a:pt x="{_emu(p[0] - bx0)}" y="{_emu(by1 - p[1])}"/>'
    path = []
    for seg in it.pts:
        if seg[0] == "M":
            path.append(f"<a:moveTo>{P(seg[1])}</a:moveTo>")
        elif seg[0] == "L":
            path.append(f"<a:lnTo>{P(seg[1])}</a:lnTo>")
        elif seg[0] == "C":
            path.append("<a:cubicBezTo>" + "".join(P(p) for p in seg[1]) + "</a:cubicBezTo>")
        else:
            path.append("<a:close/>")
    fill = f'<a:solidFill><a:srgbClr val="{it.fill.lstrip("#").upper()}"/></a:solidFill>' if it.fill else "<a:noFill/>"
    ln = (f'<a:ln w="{_emu(it.lw)}"><a:solidFill><a:srgbClr val="{it.stroke.lstrip("#").upper()}"/></a:solidFill></a:ln>' if it.stroke else "<a:ln><a:noFill/></a:ln>")
    geom = (f'<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/><a:pathLst><a:path w="{_emu(cx)}" h="{_emu(cy)}">'
            + "".join(path) + "</a:path></a:pathLst></a:custGeom>")
    inner = (f'<a:graphic><a:graphicData uri="{WPS}"><wps:wsp><wps:cNvSpPr/><wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{_emu(cx)}" cy="{_emu(cy)}"/></a:xfrm>'
             f'{geom}{fill}{ln}</wps:spPr><wps:bodyPr/></wps:wsp></a:graphicData></a:graphic>')
    return _anchor(bx0 - px0, py0 - by1, cx, cy, inner, 1000 + it.z, it.z)


# ------------------------------------------------------------------ PowerPoint
def _cust_geom_xml(it: Item, bx0, by1, cx, cy) -> str:
    P = lambda p: f'<a:pt x="{_emu(p[0] - bx0)}" y="{_emu(by1 - p[1])}"/>'
    path = []
    for seg in it.pts:
        if seg[0] == "M":
            path.append(f"<a:moveTo>{P(seg[1])}</a:moveTo>")
        elif seg[0] == "L":
            path.append(f"<a:lnTo>{P(seg[1])}</a:lnTo>")
        elif seg[0] == "C":
            path.append("<a:cubicBezTo>" + "".join(P(p) for p in seg[1]) + "</a:cubicBezTo>")
        else:
            path.append("<a:close/>")
    return (f'<a:custGeom xmlns:a="{A}"><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/><a:pathLst><a:path w="{_emu(cx)}" h="{_emu(cy)}">'
            + "".join(path) + "</a:path></a:pathLst></a:custGeom>")


def to_pptx(src: str, dst: Path, progress=None) -> int:
    """a PowerPoint file with one slide per page, every object rebuilt as an editable shape, text box or picture in its original place"""
    from lxml import etree
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR
    from pptx.util import Emu, Pt

    reader = PdfReader(src)
    if reader.is_encrypted:
        raise po.UserError("This PDF is locked with a password. Remove the password first.")
    prs = Presentation()
    bx = po._page_box(reader.pages[0])
    prs.slide_width, prs.slide_height = Emu(_emu(bx[2] - bx[0])), Emu(_emu(bx[3] - bx[1]))
    blank = prs.slide_layouts[6]
    n = len(reader.pages)
    for pi, page in enumerate(reader.pages):
        items, W, H = read_page(reader, page, pi + 1)
        slide = prs.slides.add_slide(blank)
        box = po._page_box(page)
        for it in items:
            try:
                if it.kind == "shape":
                    xs = [s[1][0] for s in it.pts if s[0] in ("M", "L")] + [q[0] for s in it.pts if s[0] == "C" for q in s[1]]
                    ys = [s[1][1] for s in it.pts if s[0] in ("M", "L")] + [q[1] for s in it.pts if s[0] == "C" for q in s[1]]
                    bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
                    cx, cy = max(bx1 - bx0, 0.01), max(by1 - by0, 0.01)
                    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(_emu(bx0 - box[0])), Emu(_emu(box[3] - by1)), Emu(max(1, _emu(cx))), Emu(max(1, _emu(cy))))
                    spPr = shp._element.spPr
                    old = spPr.find("{%s}prstGeom" % A)
                    geom = etree.fromstring(_cust_geom_xml(it, bx0, by1, cx, cy))
                    old.addprevious(geom)
                    spPr.remove(old)
                    if it.fill:
                        shp.fill.solid(); shp.fill.fore_color.rgb = RGBColor.from_string(it.fill.lstrip("#").upper())
                    else:
                        shp.fill.background()
                    if it.stroke:
                        shp.line.color.rgb = RGBColor.from_string(it.stroke.lstrip("#").upper()); shp.line.width = Emu(_emu(it.lw))
                    else:
                        shp.line.fill.background()
                    shp.shadow.inherit = False
                    st = shp._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}style")
                    if st is not None:
                        shp._element.remove(st)
                elif it.kind == "text":
                    size = max(1.0, it.size)
                    w, h = it.w + 2, size * LINE
                    rot = (-it.angle) % 360
                    phi = math.radians(rot)
                    ox, oy = w / 2, h / 2 - ASC * size
                    cxr = it.x + (ox * math.cos(phi) - oy * math.sin(phi))
                    cyr = it.y + (ox * math.sin(phi) + oy * math.cos(phi))
                    tb = slide.shapes.add_textbox(Emu(_emu(cxr - w / 2)), Emu(_emu(cyr - h / 2)), Emu(_emu(w)), Emu(_emu(h)))
                    tf = tb.text_frame
                    tf.word_wrap = False
                    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                    tf.vertical_anchor = MSO_ANCHOR.TOP
                    r = tf.paragraphs[0].add_run()
                    r.text = it.text
                    f = r.font
                    f.name = it.family; f.size = Pt(size); f.bold = it.bold; f.italic = it.italic
                    f.color.rgb = RGBColor.from_string(it.color)
                    if abs(rot) > 0.05 and abs(rot - 360) > 0.05:
                        tb.rotation = rot
                elif it.kind == "image":
                    slide.shapes.add_picture(io.BytesIO(it.data), Emu(_emu(it.x)), Emu(_emu(it.y)), Emu(max(1, _emu(it.w))), Emu(max(1, _emu(it.h))))
            except Exception:
                continue
        if progress:
            progress((pi + 1) / n)
    prs.save(str(dst))
    return n


# ------------------------------------------------------------------ OpenDocument text
def to_odt(src: str, dst: Path, progress=None) -> int:
    """an OpenDocument text file (also the base for .doc and .rtf) with every object of every page in its original place"""
    import zipfile

    reader = PdfReader(src)
    if reader.is_encrypted:
        raise po.UserError("This PDF is locked with a password. Remove the password first.")
    n = len(reader.pages)
    box0 = po._page_box(reader.pages[0])
    pw, ph = box0[2] - box0[0], box0[3] - box0[1]
    styles: list[str] = []
    body: list[str] = []
    pics: list[tuple[str, bytes]] = []
    sid = [0]

    def style_graphic(fill, stroke, lw):
        sid[0] += 1
        nm = f"gs{sid[0]}"
        f = f'draw:fill="solid" draw:fill-color="#{fill.lstrip("#")}"' if fill else 'draw:fill="none"'
        s = f'draw:stroke="solid" svg:stroke-color="#{stroke.lstrip("#")}" svg:stroke-width="{lw:.3f}pt"' if stroke else 'draw:stroke="none"'
        styles.append(f'<style:style style:name="{nm}" style:family="graphic"><style:graphic-properties {f} {s} fo:padding="0pt" draw:textarea-horizontal-align="left" '
                      f'style:wrap="none" style:run-through="foreground" style:vertical-pos="from-top" style:horizontal-pos="from-left" style:vertical-rel="page" style:horizontal-rel="page"/></style:style>')
        return nm

    def style_text(it: Item):
        sid[0] += 1
        nm = f"T{sid[0]}"
        w = ' fo:font-weight="bold"' if it.bold else ""
        i = ' fo:font-style="italic"' if it.italic else ""
        styles.append(f'<style:style style:name="{nm}" style:family="text"><style:text-properties style:font-name="{_esc(it.family)}" fo:font-family="{_esc(it.family)}" '
                      f'fo:font-size="{it.size:.2f}pt" fo:color="#{it.color}"{w}{i}/></style:style>')
        return nm

    styles.append('<style:style style:name="Pn" style:family="paragraph"><style:paragraph-properties fo:margin="0pt" fo:line-height="1pt"/><style:text-properties fo:font-size="1pt"/></style:style>')
    styles.append('<style:style style:name="Pb" style:family="paragraph"><style:paragraph-properties fo:margin="0pt" fo:line-height="1pt" fo:break-before="page"/><style:text-properties fo:font-size="1pt"/></style:style>')
    styles.append('<style:style style:name="Pt" style:family="paragraph"><style:paragraph-properties fo:margin="0pt" fo:line-height="100%"/></style:style>')
    z = 0
    for pi, page in enumerate(reader.pages):
        items, W, H = read_page(reader, page, pi + 1)
        box = po._page_box(page)
        parts = []
        for it in items:
            z += 1
            anchor = f'text:anchor-type="page" text:anchor-page-number="{pi + 1}" draw:z-index="{z}"'
            try:
                if it.kind == "shape":
                    xs = [s[1][0] for s in it.pts if s[0] in ("M", "L")] + [q[0] for s in it.pts if s[0] == "C" for q in s[1]]
                    ys = [s[1][1] for s in it.pts if s[0] in ("M", "L")] + [q[1] for s in it.pts if s[0] == "C" for q in s[1]]
                    bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
                    cx, cy = max(bx1 - bx0, 0.4), max(by1 - by0, 0.4)
                    d = []
                    f = lambda p: f"{int(round((p[0] - bx0) * 100))} {int(round((by1 - p[1]) * 100))}"
                    for seg in it.pts:
                        if seg[0] == "M":
                            d.append("M " + f(seg[1]))
                        elif seg[0] == "L":
                            d.append("L " + f(seg[1]))
                        elif seg[0] == "C":
                            d.append("C " + " ".join(f(p) for p in seg[1]))
                        else:
                            d.append("Z")
                    gs = style_graphic(it.fill, it.stroke, it.lw)
                    parts.append(f'<draw:path draw:style-name="{gs}" {anchor} svg:x="{bx0 - box[0]:.2f}pt" svg:y="{box[3] - by1:.2f}pt" svg:width="{cx:.2f}pt" svg:height="{cy:.2f}pt" '
                                 f'svg:viewBox="0 0 {int(cx * 100)} {int(cy * 100)}" svg:d="{" ".join(d)}"/>')
                elif it.kind == "text":
                    size = max(1.0, it.size)
                    w, h = it.w * 1.04 + 4, size * LINE
                    rot = (-it.angle) % 360
                    phi = math.radians(rot)
                    # top-left of the unturned box so that, turned about its top-left corner, the baseline start stays on the original point
                    tlx = it.x - (0 * math.cos(phi) - ASC * size * math.sin(phi))
                    tly = it.y - (0 * math.sin(phi) + ASC * size * math.cos(phi))
                    tn = style_text(it)
                    gs = style_graphic(None, None, 0)
                    pos = f'svg:x="{tlx:.2f}pt" svg:y="{tly:.2f}pt"'
                    if abs(rot) > 0.05 and abs(rot - 360) > 0.05:
                        pos = f'draw:transform="rotate ({-math.radians(rot):.5f}) translate ({tlx:.2f}pt {tly:.2f}pt)"'
                    parts.append(f'<draw:frame draw:style-name="{gs}" {anchor} {pos} svg:width="{w:.2f}pt" svg:height="{h:.2f}pt">'
                                 f'<draw:text-box><text:p text:style-name="Pt"><text:span text:style-name="{tn}">{_esc(it.text)}</text:span></text:p></draw:text-box></draw:frame>')
                elif it.kind == "image":
                    name = f"Pictures/img{len(pics) + 1}.png"
                    pics.append((name, it.data))
                    gs = style_graphic(None, None, 0)
                    parts.append(f'<draw:frame draw:style-name="{gs}" {anchor} svg:x="{it.x:.2f}pt" svg:y="{it.y:.2f}pt" svg:width="{it.w:.2f}pt" svg:height="{it.h:.2f}pt">'
                                 f'<draw:image xlink:href="{name}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/></draw:frame>')
            except Exception:
                continue
        body.append(f'<text:p text:style-name="{"Pb" if pi else "Pn"}">{"".join(parts)}</text:p>')
        if progress:
            progress((pi + 1) / n)
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
          'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
          'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"')
    content = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ns} office:version="1.2"><office:automatic-styles>{"".join(styles)}</office:automatic-styles>'
               f'<office:body><office:text>{"".join(body)}</office:text></office:body></office:document-content>')
    page_styles = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-styles {ns} office:version="1.2"><office:automatic-styles>'
                   f'<style:page-layout style:name="pm1"><style:page-layout-properties fo:page-width="{pw:.2f}pt" fo:page-height="{ph:.2f}pt" fo:margin-top="0pt" fo:margin-bottom="0pt" '
                   f'fo:margin-left="0pt" fo:margin-right="0pt" style:print-orientation="portrait"/></style:page-layout></office:automatic-styles>'
                   f'<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="pm1"/></office:master-styles></office:document-styles>')
    man = ('<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
           '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
           '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/><manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
           + "".join(f'<manifest:file-entry manifest:full-path="{n}" manifest:media-type="image/png"/>' for n, _d in pics) + "</manifest:manifest>")
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", content, zipfile.ZIP_DEFLATED)
        z.writestr("styles.xml", page_styles, zipfile.ZIP_DEFLATED)
        z.writestr("META-INF/manifest.xml", man, zipfile.ZIP_DEFLATED)
        for name, data in pics:
            z.writestr(name, data, zipfile.ZIP_DEFLATED)
    return n
