# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Saving Visual-editor changes into the SAME kind of file that was opened (Word, Excel, plain text), not into a PDF copy.

The page you see and drag things on is a picture of the file made by LibreOffice, so the editor knows each line of text and where it is on
the page. At save time every change is translated back into the real file:
  * Word (.docx): retyped, deleted, recoloured or resized text is changed inside its own paragraph; text you moved becomes a text frame fixed
    to the page at the new spot (the old text is removed); added text, boxes, ovals, lines, arrows and pictures are anchored to the page.
  * Excel (.xlsx): retyped or deleted cell text is written into the cell itself (the workbook's other parts, charts and pictures are untouched).
  * Text files: lines are retyped or deleted.
What a flowing document cannot hold (a moved Word picture, a text box floating over an Excel grid) is reported to the person instead of being lost silently."""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .service import UserError

NOTES: list[str] = []


def take_notes() -> list[str]:
    out = list(dict.fromkeys(NOTES))
    NOTES.clear()
    return out


# ------------------------------------------------------------------ text lines of a rendered page
def page_lines(pdf: str, n: int) -> list[dict]:
    """[{x, y, w, h, text}] for each printed line on page n, in points from the top-left (pdftotext does the reading)"""
    exe = shutil.which("pdftotext")
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "-bbox-layout", "-f", str(n), "-l", str(n), str(pdf), "-"], capture_output=True, text=True, timeout=60)
    except Exception:
        return []
    out = []
    for m in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', r.stdout, re.S):
        words = re.findall(r"<word[^>]*>(.*?)</word>", m.group(5), re.S)
        txt = " ".join(_unesc(w) for w in words).strip()
        x0, y0, x1, y1 = (float(m.group(i)) for i in (1, 2, 3, 4))
        if txt:
            out.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "text": txt})
    return out


def _unesc(s: str) -> str:
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def fill_text(objs: list[dict], lines: list[dict]) -> None:
    """give every text object the words printed inside its box (so it can be matched to the real file and retyped knowing what it says)"""
    for o in objs:
        if o.get("kind") != "text" or o.get("text"):
            continue
        x0, y0, x1, y1 = o["x"], o["y"], o["x"] + o["w"], o["y"] + o["h"]
        got = [ln for ln in lines if x0 - 2 <= ln["x"] + ln["w"] / 2 <= x1 + 2 and y0 - 3 <= ln["y"] + ln["h"] / 2 <= y1 + 3]
        got.sort(key=lambda ln: (round(ln["y"] / 3), ln["x"]))
        o["text"] = " ".join(g["text"] for g in got)


def _objs_with_text(pdf: str, n: int) -> list[dict]:
    from . import pdfobjects
    r = pdfobjects.open_page(pdf, n)
    objs = r["objects"]
    fill_text(objs, page_lines(pdf, n))
    return objs


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _split_page_edits(pdf: str, pages: list[dict]):
    """[(page, object, mod)] for edits of existing things, and [(page, add)] for new things"""
    mods, adds = [], []
    for pg in pages:
        n = int(pg.get("page", 1))
        byid = None
        for m in pg.get("mods") or []:
            if byid is None:
                byid = {o["id"]: o for o in _objs_with_text(pdf, n)}
            o = byid.get(int(m.get("id", -1)))
            if o:
                mods.append((n, o, m))
        for a in pg.get("adds") or []:
            adds.append((n, a))
    return mods, adds


def _colour(h) -> str:
    h = (h or "").lstrip("#")
    return h.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", h) else "000000"


# ================================================================== Word
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def _q(t): return "{%s}%s" % (W, t)


def _para_ts(p):
    """the text elements that belong to this paragraph itself (not to a text box inside it)"""
    out = []
    for t in p.iter(_q("t")):
        a = t.getparent()
        while a is not None and a.tag != _q("p"):
            a = a.getparent()
        if a is p:
            out.append(t)
    return out


def _para_index(body):
    """[(paragraph, [t elements], raw text, [(raw index of each non-space char)], squashed text)]"""
    out = []
    for p in body.iter(_q("p")):
        ts = _para_ts(p)
        if not ts:
            continue
        raw = "".join(t.text or "" for t in ts)
        idx = [i for i, ch in enumerate(raw) if not ch.isspace()]
        sq = "".join(raw[i] for i in idx)
        if sq:
            out.append((p, ts, raw, idx, sq))
    return out


def _locate(paras, target: str, used: set):
    """the paragraph and character range holding this printed line; each place is handed out once"""
    want = _norm(target)
    if not want:
        return None
    for pi, (p, ts, raw, idx, sq) in enumerate(paras):
        start = 0
        while True:
            k = sq.find(want, start)
            if k < 0:
                break
            if (pi, k) not in used:
                used.add((pi, k))
                return pi, idx[k], idx[k + len(want) - 1] + 1
            start = k + 1
    return None


def _split_at(ts, raw_a: int, raw_b: int, new_text: str | None, rpr_fn):
    """replace raw[a:b] (counted across this paragraph's text elements) by new_text (None = remove); returns the first run touched"""
    pos = 0
    first_run = None
    inserted = new_text is None
    for t in ts:
        txt = t.text or ""
        lo, hi = pos, pos + len(txt)
        pos = hi
        if hi <= raw_a or lo >= raw_b:
            continue
        a, b = max(raw_a, lo) - lo, min(raw_b, hi) - lo
        keep_before, keep_after = txt[:a], txt[b:]
        mid = "" if inserted else new_text
        inserted = True
        t.text = keep_before + mid + keep_after
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        run = t.getparent()
        if first_run is None:
            first_run = run
        if rpr_fn and mid:
            rpr_fn(run)
    return first_run


def _set_rpr(run, colour=None, size=None):
    from lxml import etree
    rpr = run.find(_q("rPr"))
    if rpr is None:
        rpr = etree.Element(_q("rPr"))
        run.insert(0, rpr)
    if colour:
        c = rpr.find(_q("color"))
        if c is None:
            c = etree.SubElement(rpr, _q("color"))
        c.set(_q("val"), _colour(colour))
    if size:
        for tag in ("sz", "szCs"):
            s = rpr.find(_q(tag))
            if s is None:
                s = etree.SubElement(rpr, _q(tag))
            s.set(_q("val"), str(max(2, int(round(float(size) * 2)))))


def _top_level(el, body):
    while el.getparent() is not None and el.getparent() is not body:
        el = el.getparent()
    return el


def _frame(text: str, x: float, y: float, w: float, size: float, colour: str, font: str = ""):
    from lxml import etree
    lines = str(text).split("\n")
    p = etree.Element(_q("p"))
    ppr = etree.SubElement(p, _q("pPr"))
    fr = etree.SubElement(ppr, _q("framePr"))
    for k, v in (("w", int(w * 20)), ("hRule", "auto"), ("wrap", "around"), ("vAnchor", "page"), ("hAnchor", "page"), ("x", int(x * 20)), ("y", int(y * 20))):
        fr.set(_q(k), str(v))
    sp = etree.SubElement(ppr, _q("spacing")); sp.set(_q("before"), "0"); sp.set(_q("after"), "0"); sp.set(_q("line"), "240"); sp.set(_q("lineRule"), "auto")
    r = etree.SubElement(p, _q("r"))
    rpr = etree.SubElement(r, _q("rPr"))
    if font:
        rf = etree.SubElement(rpr, _q("rFonts"))
        for a in ("ascii", "hAnsi", "cs"):
            rf.set(_q(a), font)
    etree.SubElement(rpr, _q("color")).set(_q("val"), _colour(colour))
    for tag in ("sz", "szCs"):
        etree.SubElement(rpr, _q(tag)).set(_q("val"), str(max(2, int(round(size * 2)))))
    for i, ln in enumerate(lines):
        if i:
            etree.SubElement(r, _q("br"))
        t = etree.SubElement(r, _q("t")); t.text = ln
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return p


def _frame_runs(a: dict, x: float, y: float):
    """a text frame fixed to the page holding styled runs (font, size, colour, bold, italic, underline) and an alignment"""
    from lxml import etree
    from . import richtext
    runs, align = richtext.normalize(a)
    lay, Wd, Hd = richtext.layout(runs, float(a.get("w", 0) or 0) or None, align)
    p = etree.Element(_q("p"))
    ppr = etree.SubElement(p, _q("pPr"))
    fr = etree.SubElement(ppr, _q("framePr"))
    for k, v in (("w", int((Wd + 8) * 20)), ("hRule", "auto"), ("wrap", "around"), ("vAnchor", "page"), ("hAnchor", "page"), ("x", int(x * 20)), ("y", int(y * 20))):
        fr.set(_q(k), str(v))
    sp = etree.SubElement(ppr, _q("spacing")); sp.set(_q("before"), "0"); sp.set(_q("after"), "0"); sp.set(_q("line"), "240"); sp.set(_q("lineRule"), "auto")
    if align != "left":
        etree.SubElement(ppr, _q("jc")).set(_q("val"), align)
    for li, (ln, _dx, _b, _w) in enumerate(lay):
        for r in ln:
            run = etree.SubElement(p, _q("r"))
            rpr = etree.SubElement(run, _q("rPr"))
            rf = etree.SubElement(rpr, _q("rFonts"))
            for at in ("ascii", "hAnsi", "cs"):
                rf.set(_q(at), r["font"])
            if r["b"]:
                etree.SubElement(rpr, _q("b"))
            if r["i"]:
                etree.SubElement(rpr, _q("i"))
            if r.get("u"):
                etree.SubElement(rpr, _q("u")).set(_q("val"), "single")
            etree.SubElement(rpr, _q("color")).set(_q("val"), _colour(r["color"]))
            for tag in ("sz", "szCs"):
                etree.SubElement(rpr, _q(tag)).set(_q("val"), str(max(2, int(round(r["size"] * 2)))))
            t = etree.SubElement(run, _q("t")); t.text = r["t"]
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        if li < len(lay) - 1:
            br = etree.SubElement(etree.SubElement(p, _q("r")), _q("br"))
    return p


_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _anchor_xml(x, y, cx, cy, inner: str, did: int, flip: str = "") -> str:
    E = 12700
    return (f'<w:r xmlns:w="{W}" xmlns:wp="{_WP}" xmlns:a="{_A}" xmlns:wps="{_WPS}" xmlns:pic="{_PIC}" xmlns:r="{_R}"><w:drawing>'
            f'<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="{251650000 + did}" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>{int(x * E)}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>{int(y * E)}</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{max(1, int(cx * E))}" cy="{max(1, int(cy * E))}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
            f'<wp:docPr id="{did}" name="Fathom {did}"/><wp:cNvGraphicFramePr/>{inner}</wp:anchor></w:drawing></w:r>')


def _shape_inner(a: dict, cx: float, cy: float, flip: str = "") -> str:
    E = 12700
    t = a.get("type")
    prst = {"rect": "rect", "round": "roundRect", "ellipse": "ellipse", "line": "line", "arrow": "line"}.get(t, "rect")
    fl, st = a.get("fill"), a.get("stroke")
    fill = f'<a:solidFill><a:srgbClr val="{_colour(fl)}"/></a:solidFill>' if fl and t not in ("line", "arrow") else "<a:noFill/>"
    lc = st or (fl if t in ("line", "arrow") else None)
    if lc or t in ("line", "arrow"):
        lw = int(float(a.get("lw") or (2 if t in ("line", "arrow") else 1)) * E)
        tail = '<a:tailEnd type="triangle"/>' if t == "arrow" else ""
        ln = f'<a:ln w="{lw}"><a:solidFill><a:srgbClr val="{_colour(lc or "#000000")}"/></a:solidFill>{tail}</a:ln>'
    else:
        ln = "<a:ln><a:noFill/></a:ln>"
    return (f'<a:graphic><a:graphicData uri="{_WPS}"><wps:wsp><wps:cNvSpPr/><wps:spPr><a:xfrm{flip}><a:off x="0" y="0"/>'
            f'<a:ext cx="{max(1, int(cx * E))}" cy="{max(1, int(cy * E))}"/></a:xfrm><a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>{fill}{ln}</wps:spPr>'
            f'<wps:bodyPr/></wps:wsp></a:graphicData></a:graphic>')


def _pic_inner(rid: str, cx: float, cy: float, did: int) -> str:
    E = 12700
    return (f'<a:graphic><a:graphicData uri="{_PIC}"><pic:pic><pic:nvPicPr><pic:cNvPr id="{did}" name="Picture {did}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
            f'<a:ext cx="{max(1, int(cx * E))}" cy="{max(1, int(cy * E))}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>')


def docx_write(src: Path, dst: Path, pdf: str, pages: list[dict]) -> int:
    import docx
    from lxml import etree
    d = docx.Document(str(src))
    body = d.element.body
    paras = _para_index(body)
    mods, adds = _split_page_edits(pdf, pages)
    used: set = set()
    changed = 0
    page_anchor: dict[int, object] = {}
    did = [900]

    def anchor_for(n: int):
        if n in page_anchor:
            return page_anchor[n]
        el = None
        for ln in page_lines(pdf, n)[:6]:
            hit = _locate(paras, ln["text"], set())
            if hit:
                el = _top_level(paras[hit[0]][0], body)
                break
        if el is None:
            kids = [k for k in body if k.tag in (_q("p"), _q("tbl"))]
            el = kids[0] if kids else None
        page_anchor[n] = el
        return el

    def put_after(n: int, new_el):
        a = anchor_for(n)
        if a is None:
            body.insert(0, new_el)
        else:
            a.addnext(new_el)

    def para_with(run_xml):
        p = etree.Element(_q("p"))
        p.append(etree.fromstring(run_xml))
        return p

    for n, o, m in mods:
        if o.get("kind") != "text":
            NOTES.append("A picture or shape that is already in a Word file can't be moved from here without breaking the layout, so those moves were left out. Text and anything you add are saved.")
            continue
        sx, sy = float(m.get("sx", 1) or 1), float(m.get("sy", 1) or 1)
        dx, dy = float(m.get("dx", 0) or 0), float(m.get("dy", 0) or 0)
        moved = abs(dx) > 0.5 or abs(dy) > 0.5 or abs(sx - 1) > 0.01 or abs(sy - 1) > 0.01
        retyped = m.get("text") is not None and _norm(m["text"]) != _norm(o.get("text"))
        recol = bool(m.get("fill"))
        size = (o.get("size") or 12) * sy if (abs(sy - 1) > 0.01) else None
        hit = _locate(paras, o.get("text", ""), used)
        if not hit:
            NOTES.append("Some text could not be matched to the Word file itself (it may be in a header, table or text box), so those edits were left out.")
            continue
        pi, a, b = hit
        p, ts, raw, idx, sq = paras[pi]
        text = str(m["text"]) if retyped else o.get("text", "")
        colour = m.get("fill") or o.get("fill") or "#000000"
        if m.get("delete"):
            _split_at(ts, a, b, None, None); changed += 1
            continue
        if m.get("dup"):
            dd = m["dup"] if isinstance(m["dup"], dict) else {}
            did[0] += 1
            put_after(n, _frame(text, o["x"] + float(dd.get("dx", 14)), o["y"] + float(dd.get("dy", 14)), o["w"] * 1.1 + 8, (o.get("size") or 12), colour))
            changed += 1
        if moved:
            _split_at(ts, a, b, None, None)
            put_after(n, _frame(text, o["x"] + dx, o["y"] + dy, max(o["w"] * sx, 10) * 1.12 + 8, (o.get("size") or 12) * sy, colour))
            changed += 1
        elif retyped or recol or size:
            if retyped:
                _split_at(ts, a, b, text, (lambda r: _set_rpr(r, colour if recol else None, size)) if (recol or size) else None)
            else:
                _restyle(ts, a, b, colour if recol else None, size)
            changed += 1

    for n, a in adds:
        t = a.get("type")
        did[0] += 1
        x, y, w, h = (float(a.get(k, 0) or 0) for k in ("x", "y", "w", "h"))
        if t == "text":
            put_after(n, _frame_runs(a, x, y))
        elif t in ("rect", "round", "ellipse"):
            put_after(n, para_with(_anchor_xml(x, y, w, h, _shape_inner(a, w, h), did[0])))
        elif t in ("line", "arrow"):
            x2, y2 = float(a.get("x2", 0) or 0), float(a.get("y2", 0) or 0)
            fx = ' flipH="1"' if x2 < x else ""
            fy = ' flipV="1"' if y2 < y else ""
            cx, cy = abs(x2 - x), abs(y2 - y)
            put_after(n, para_with(_anchor_xml(min(x, x2), min(y, y2), cx, cy, _shape_inner(a, cx, cy, fx + fy), did[0])))
        elif t == "image":
            from . import visual
            raw = visual._data_bytes(a.get("data", ""))
            if raw:
                rid, _img = d.part.get_or_add_image(io.BytesIO(raw))
                put_after(n, para_with(_anchor_xml(x, y, w, h, _pic_inner(rid, w, h, did[0]), did[0])))
            else:
                continue
        else:
            continue
        changed += 1
    d.save(str(dst))
    return changed


def _restyle(ts, a, b, colour, size):
    pos = 0
    for t in ts:
        txt = t.text or ""
        lo, hi = pos, pos + len(txt)
        pos = hi
        if hi > a and lo < b:
            _set_rpr(t.getparent(), colour, size)


# ================================================================== Excel (the cell text is patched inside the workbook, nothing else is rewritten)
def xlsx_write(src: Path, dst: Path, pdf: str, pages: list[dict]) -> int:
    import openpyxl
    mods, adds = _split_page_edits(pdf, pages)
    if adds:
        NOTES.append("Text boxes, shapes and pictures can't be placed over an Excel grid, so what you added was left out. Change cell text directly instead.")
    wb = openpyxl.load_workbook(str(src), data_only=False)
    cells = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None and str(c.value).strip():
                    cells.append((ws.title, c.coordinate, c.value))
    wb.close()
    used: set = set()
    edits: dict[str, dict[str, object]] = {}
    changed = 0
    for n, o, m in mods:
        if o.get("kind") != "text":
            continue
        if abs(float(m.get("dx", 0) or 0)) > 0.5 or abs(float(m.get("dy", 0) or 0)) > 0.5:
            NOTES.append("Cells stay on the Excel grid, so moving text was left out. Retyping and deleting cell text are saved.")
        retyped = m.get("text") is not None and _norm(m["text"]) != _norm(o.get("text"))
        if not (retyped or m.get("delete")):
            continue
        want = _norm(o.get("text", ""))
        hit = next((c for c in cells if (c[0], c[1]) not in used and _norm(str(c[2])) == want), None)
        if not hit:
            hit = next((c for c in cells if (c[0], c[1]) not in used and want and want in _norm(str(c[2]))), None)
        if not hit:
            NOTES.append("Some text could not be matched to a cell, so it was left unchanged.")
            continue
        used.add((hit[0], hit[1]))
        new = None if m.get("delete") else str(m["text"])
        if new is not None and _norm(str(hit[2])) != want:      # only a part of the cell was shown: change that part
            new = str(hit[2]).replace(o.get("text", ""), new, 1)
        edits.setdefault(hit[0], {})[hit[1]] = new
        changed += 1
    _patch_xlsx(src, dst, edits)
    return changed


def _patch_xlsx(src: Path, dst: Path, edits: dict):
    from xml.sax.saxutils import escape
    if not edits:
        shutil.copyfile(src, dst)
        return
    zin = zipfile.ZipFile(src)
    wbx = zin.read("xl/workbook.xml").decode("utf-8", "replace")
    rels = zin.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
    relmap = {m.group(1): m.group(2) for m in re.finditer(r'<Relationship\b[^>]*?\bId="([^"]+)"[^>]*?\bTarget="([^"]+)"', rels)}
    relmap.update({m.group(2): m.group(1) for m in re.finditer(r'<Relationship\b[^>]*?\bTarget="([^"]+)"[^>]*?\bId="([^"]+)"', rels)} if False else {})
    for m in re.finditer(r'<Relationship\b([^>]*)/?>', rels):
        at = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        if "Id" in at and "Target" in at:
            relmap[at["Id"]] = at["Target"]
    sheets = {}
    for m in re.finditer(r'<sheet\b([^>]*)/?>', wbx):
        at = dict(re.findall(r'([\w:]+)="([^"]*)"', m.group(1)))
        tgt = relmap.get(at.get("r:id", ""))
        if tgt:
            name = at.get("name", "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
            sheets[name] = ("xl/" + tgt.lstrip("/")) if not tgt.startswith("/") else tgt.lstrip("/")
            sheets[name] = sheets[name].replace("xl/xl/", "xl/")
    zout = zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED)
    todo = {sheets[s]: e for s, e in edits.items() if s in sheets}
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename in todo:
            xml = data.decode("utf-8")
            for coord, val in todo[item.filename].items():
                pat = re.compile(r'<c\b([^>]*\br="%s"[^>]*?)(/>|>(.*?)</c>)' % re.escape(coord), re.S)

                def sub(m, val=val):
                    attrs = re.sub(r'\s+t="[^"]*"', "", m.group(1)).rstrip("/")
                    if val is None:
                        return "<c%s/>" % attrs
                    try:
                        float(val)
                        return "<c%s><v>%s</v></c>" % (attrs, escape(str(val)))
                    except ValueError:
                        return '<c%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (attrs, escape(str(val)))
                xml = pat.sub(sub, xml, count=1)
            data = xml.encode("utf-8")
        elif item.filename == "xl/calcChain.xml" and False:
            continue
        zout.writestr(item, data)
    zout.close()
    zin.close()


# ================================================================== text files
def text_write(src: Path, dst: Path, pdf: str, pages: list[dict]) -> int:
    raw = src.read_bytes()
    enc = "utf-8"
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        enc = "cp1252"
        txt = raw.decode(enc, "replace")
    bom = txt.startswith("\ufeff")
    nl = "\r\n" if "\r\n" in txt else "\n"
    lines = txt.lstrip("\ufeff").splitlines()
    mods, adds = _split_page_edits(pdf, pages)
    if adds:
        NOTES.append("A plain text file holds only text, so shapes, pictures and floating text were left out.")
    used: set[int] = set()
    changed = 0
    for n, o, m in mods:
        if o.get("kind") != "text":
            continue
        if abs(float(m.get("dx", 0) or 0)) > 0.5 or abs(float(m.get("dy", 0) or 0)) > 0.5:
            NOTES.append("Plain text cannot be dragged around, so moves were left out. Retyping and deleting lines are saved.")
        retyped = m.get("text") is not None and _norm(m["text"]) != _norm(o.get("text"))
        if not (retyped or m.get("delete")):
            continue
        want = _norm(o.get("text", ""))
        i = next((k for k, l in enumerate(lines) if k not in used and want and _norm(l) == want), None)
        if i is None:
            i = next((k for k, l in enumerate(lines) if k not in used and want and want in _norm(l)), None)
        if i is None:
            NOTES.append("Some text could not be matched to the file, so it was left unchanged.")
            continue
        used.add(i)
        lines[i] = None if m.get("delete") else (lines[i].replace(o["text"], str(m["text"]), 1) if o.get("text") and o["text"] in lines[i] else str(m["text"]))
        changed += 1
    out = nl.join(l for l in lines if l is not None) + (nl if txt.endswith(("\n", "\r")) else "")
    dst.write_bytes((("\ufeff" if bom else "") + out).encode(enc if enc != "cp1252" else "cp1252", "replace"))
    return changed


# ================================================================== older / other formats: edit a modern twin, then convert back
def soffice_convert(src: Path, fmt: str, outdir: Path) -> Path:
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        for c in (r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
            if Path(c).is_file():
                exe = c
                break
    if not exe:
        raise UserError("Saving this kind of file in its own format needs LibreOffice. The full Fathom install adds it (run Fathom-Setup.vbs and tick LibreOffice).")
    prof = Path(tempfile.mkdtemp(prefix="fathom_lo_"))
    try:
        r = subprocess.run([exe, f"-env:UserInstallation={prof.as_uri()}", "--headless", "--convert-to", fmt, "--outdir", str(outdir), str(src)],
                           capture_output=True, text=True, timeout=240)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    out = outdir / (src.stem + "." + fmt.split(":")[0])
    if not out.exists():
        raise UserError("LibreOffice could not write the file back in its own format. " + (r.stderr or "")[:160])
    return out
