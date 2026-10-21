# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""A visual PDF editor that works on the objects themselves: every shape, line, arrow, picture and piece of text on a page can be
picked, dragged, resized, recoloured, copied or deleted, and new ones can be added. It works on the page's own drawing
instructions (pypdf), so it needs no extra program and nothing is turned into a flat picture.

The page is parsed into objects (stable ids, in drawing order). A page's edits are always applied to the ORIGINAL page, so the screen can
keep a simple list of edits and Undo is just removing the last one.

Coordinates for the screen are in points with the origin at the TOP LEFT of the visible page (y grows downward)."""
from __future__ import annotations

import base64
import io
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, FloatObject, NameObject, NumberObject

from .service import UserError

PATH_OPS = {"m", "l", "c", "v", "y", "h", "re"}
PAINT = {"S": (1, 0), "s": (1, 0), "f": (0, 1), "F": (0, 1), "f*": (0, 1), "B": (1, 1), "B*": (1, 1), "b": (1, 1), "b*": (1, 1)}
MAX_OBJECTS = 4000
MAX_GLYPHS = 20000          # characters kept per text object (a page is never this big)
IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


# ---------------------------------------------------------------- small matrix helpers (a b c d e f), PDF convention
def mul(m, n):
    """apply m first, then n"""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F)


def inv(m):
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        return IDENT
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(e * ia + f * ic), -(e * ib + f * id_))


def pt(m, x, y):
    a, b, c, d, e, f = m
    return (x * a + y * c + e, x * b + y * d + f)


def _f(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in c)


def _rgb(h: str, default=(0.0, 0.0, 0.0)):
    h = (h or "").lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) if len(h) == 6 else default
    except ValueError:
        return default


def _page_box(page):
    box = page.cropbox if page.get("/CropBox") is not None else page.mediabox
    return float(box.left), float(box.bottom), float(box.right), float(box.top)


def _check_page(page):
    rot = int(page.get("/Rotate", 0) or 0) % 360
    if rot:
        raise UserError("This page is turned (rotated). Straighten it first in Edit > PDF pages, then edit it here.")


# ---------------------------------------------------------------- fonts: how wide is a piece of text (for the selection boxes)
class _Fonts:
    def __init__(self, page):
        self.page = page
        self.cache: dict[str, tuple] = {}

    def get(self, name: str):
        if name in self.cache:
            return self.cache[name]
        info = (False, 0.5, {}, 0.0, "")      # (two-byte, default width em, widths by code, first, basefont)
        try:
            fd = self.page["/Resources"]["/Font"][name].get_object()
            base = str(fd.get("/BaseFont", ""))
            if fd.get("/Subtype") == "/Type0":
                dfont = fd["/DescendantFonts"][0].get_object()
                dw = _f(dfont.get("/DW", 1000)) / 1000
                widths: dict[int, float] = {}
                W = dfont.get("/W")
                if W:
                    W = [x.get_object() if hasattr(x, "get_object") else x for x in W]
                    i = 0
                    while i < len(W):
                        c = int(W[i])
                        nxt = W[i + 1]
                        if isinstance(nxt, list):
                            for k, w in enumerate(nxt):
                                widths[c + k] = _f(w) / 1000
                            i += 2
                        else:
                            for k in range(c, int(nxt) + 1):
                                widths[k] = _f(W[i + 2]) / 1000
                            i += 3
                info = (True, dw, widths, 0.0, base)
            else:
                first = int(fd.get("/FirstChar", 0))
                ws = fd.get("/Widths")
                widths = {first + k: _f(w) / 1000 for k, w in enumerate(ws)} if ws else {}
                info = (False, 0.5, widths, first, base)
                if not widths:
                    info = (False, 0.5, {}, 0, base)
        except Exception:
            pass
        self.cache[name] = info
        return info

    def glyphs(self, name: str, raw: bytes, size: float) -> list[tuple[int, float, int]]:
        """one entry per character shown: (bytes it takes, its width in text units, its code)"""
        two, dw, widths, _first, _b = self.get(name)
        out: list[tuple[int, float, int]] = []
        if two:
            i = 0
            while i < len(raw):
                if i + 1 < len(raw):
                    c = (raw[i] << 8) | raw[i + 1]
                    out.append((2, widths.get(c, dw) * size, c)); i += 2
                else:
                    out.append((1, dw * size, raw[i])); i += 1
            return out
        measure = None
        if not widths and _b:
            try:
                from reportlab.pdfbase.pdfmetrics import stringWidth
                fn = _rl_font(_b)
                measure = lambda b: stringWidth(chr(b), fn, size)     # noqa: E731
            except Exception:
                measure = None
        for b in raw:
            out.append((1, measure(b) if measure else widths.get(b, dw) * size, b))
        return out

    def width(self, name: str, raw: bytes, size: float) -> float:
        two, dw, widths, _first, _b = self.get(name)
        if two:
            return sum(widths.get((raw[i] << 8) | raw[i + 1], dw) for i in range(0, len(raw) - 1, 2)) * size
        if not widths and _b:
            try:
                from reportlab.pdfbase.pdfmetrics import stringWidth
                return stringWidth(raw.decode("latin-1"), _rl_font(_b), size)
            except Exception:
                pass
        return sum(widths.get(b, dw) for b in raw) * size


def _raw(o) -> bytes:
    ob = getattr(o, "original_bytes", None)      # the exact bytes of a string in the page, whatever pypdf made of them
    if isinstance(ob, (bytes, bytearray)):
        return bytes(ob)
    try:
        return bytes(o)
    except Exception:
        return str(o).encode("latin-1", "replace")


# ---------------------------------------------------------------- parsing a page into objects
def _contents(reader: PdfReader, page):
    c = page.get_contents()
    if c is None:
        return []
    cs = c if isinstance(c, ContentStream) else ContentStream(c, reader)
    return list(cs.operations)


def parse(reader: PdfReader, page) -> tuple[list[tuple], list[dict]]:
    """(operations, objects). Object: {id, kind: shape|text|image|group, a, b (op index range), bbox (page space, PDF origin), ctm,
    stroke, fill, lw, paint, text, size, font}"""
    ops = _contents(reader, page)
    fonts = _Fonts(page)
    xobj = {}
    try:
        xobj = page["/Resources"]["/XObject"]
    except Exception:
        pass
    objs: list[dict] = []
    ctm, stack = IDENT, []
    state = {"stroke": (0.0, 0.0, 0.0), "fill": (0.0, 0.0, 0.0), "lw": 1.0, "tc": 0.0, "tw": 0.0, "th": 1.0, "rise": 0.0, "fillseq": [([NumberObject(0)], "g")]}
    sstack = []
    path_start, pb = None, None       # first path op index, [x0,y0,x1,y1]
    cur = (0.0, 0.0)
    in_text, t_start = False, 0
    tm = tlm = IDENT
    tfont, tsize, tlead = "", 0.0, 0.0
    t_box = None
    t_shows = 0
    t_glyphs: list[tuple] = []     # every character of the current text object (see glyph_boxes)
    t_infos: list[dict] = []       # one entry per show instruction

    def grow(box, x, y):
        X, Y = pt(ctm, x, y)
        if box is None:
            return [X, Y, X, Y]
        box[0], box[1], box[2], box[3] = min(box[0], X), min(box[1], Y), max(box[2], X), max(box[3], Y)
        return box

    for i, (operands, op) in enumerate(ops):
        op = op.decode() if isinstance(op, bytes) else str(op)
        if op == "q":
            stack.append(ctm)
            sstack.append(dict(state))
        elif op == "Q":
            if stack:
                ctm = stack.pop()
                state = sstack.pop()
        elif op == "cm" and len(operands) == 6:
            ctm = mul(tuple(_f(x) for x in operands), ctm)
        elif op == "w" and operands:
            state["lw"] = _f(operands[0])
        elif op in ("g", "G") and operands:
            v = _f(operands[0]); state["fill" if op == "g" else "stroke"] = (v, v, v)
            if op == "g":
                state["fillseq"] = [(list(operands), "g")]
        elif op in ("rg", "RG") and len(operands) == 3:
            state["fill" if op == "rg" else "stroke"] = tuple(_f(x) for x in operands)
            if op == "rg":
                state["fillseq"] = [(list(operands), "rg")]
        elif op in ("k", "K") and len(operands) == 4:
            c_, m_, y_, k_ = (_f(x) for x in operands)
            state["fill" if op == "k" else "stroke"] = ((1 - c_) * (1 - k_), (1 - m_) * (1 - k_), (1 - y_) * (1 - k_))
            if op == "k":
                state["fillseq"] = [(list(operands), "k")]
        elif op == "cs" and operands:
            state["fillseq"] = [(list(operands), "cs")]
        elif op in ("sc", "scn") and operands:
            state["fillseq"] = [x for x in state["fillseq"] if x[1] == "cs"] + [(list(operands), op)]
        elif op == "Tc" and operands:
            state["tc"] = _f(operands[0])
        elif op == "Tw" and operands:
            state["tw"] = _f(operands[0])
        elif op == "Tz" and operands:
            state["th"] = (_f(operands[0]) or 100.0) / 100.0
        elif op == "Ts" and operands:
            state["rise"] = _f(operands[0])
        elif op in PATH_OPS:
            if path_start is None:
                path_start, pb = i, None
            if op == "re" and len(operands) == 4:
                x, y, w, h = (_f(v) for v in operands)
                for px, py in ((x, y), (x + w, y), (x + w, y + h), (x, y + h)):
                    pb = grow(pb, px, py)
                cur = (x, y)
            elif op in ("m", "l") and len(operands) == 2:
                cur = (_f(operands[0]), _f(operands[1])); pb = grow(pb, *cur)
            elif op == "c" and len(operands) == 6:
                for k in range(0, 6, 2):
                    pb = grow(pb, _f(operands[k]), _f(operands[k + 1]))
                cur = (_f(operands[4]), _f(operands[5]))
            elif op in ("v", "y") and len(operands) == 4:
                for k in range(0, 4, 2):
                    pb = grow(pb, _f(operands[k]), _f(operands[k + 1]))
        elif op in ("W", "W*"):
            if path_start is not None:
                path_start = ("clip", path_start)
        elif op == "n":
            path_start, pb = None, None
        elif op in PAINT:
            if path_start is not None and pb is not None and not isinstance(path_start, tuple) and len(objs) < MAX_OBJECTS:
                st, fl = PAINT[op]
                lw = state["lw"] * (sum(abs(v) for v in ctm[:2]) / 2 or 1)
                pad = lw / 2 if st else 0
                objs.append({"id": len(objs), "kind": "shape", "a": path_start, "b": i, "bbox": [pb[0] - pad, pb[1] - pad, pb[2] + pad, pb[3] + pad], "ctm": ctm,
                             "stroke": _hex(state["stroke"]) if st else None, "fill": _hex(state["fill"]) if fl else None, "lw": round(state["lw"], 3), "paint": op})
            path_start, pb = None, None
        elif op == "BT":
            in_text, t_start, tm = True, i, IDENT
            tlm = IDENT
            t_box, t_shows = None, 0
            t_glyphs, t_infos = [], []
        elif op == "ET":
            if in_text and t_box is not None and len(objs) < MAX_OBJECTS:
                objs.append({"id": len(objs), "kind": "text", "a": t_start, "b": i, "bbox": t_box, "ctm": ctm, "fill": _hex(state["fill"]), "stroke": None,
                             "size": round(tsize, 2), "font": tfont, "text": "", "n_show": t_shows, "glyphs": t_glyphs, "shows": t_infos})
            in_text = False
        elif in_text and op == "Tf" and len(operands) == 2:
            tfont, tsize = str(operands[0]), _f(operands[1])
        elif in_text and op == "TL" and operands:
            tlead = _f(operands[0])
        elif in_text and op in ("Td", "TD") and len(operands) == 2:
            tlm = mul((1, 0, 0, 1, _f(operands[0]), _f(operands[1])), tlm); tm = tlm
            if op == "TD":
                tlead = -_f(operands[1])
        elif in_text and op == "Tm" and len(operands) == 6:
            tlm = tuple(_f(x) for x in operands); tm = tlm
        elif in_text and op == "T*":
            tlm = mul((1, 0, 0, 1, 0, -tlead), tlm); tm = tlm
        elif in_text and op in ("Tj", "TJ", "'", '"'):
            if op in ("'", '"'):
                if op == '"' and len(operands) == 3:
                    state["tw"], state["tc"] = _f(operands[0]), _f(operands[1])
                tlm = mul((1, 0, 0, 1, 0, -tlead), tlm); tm = tlm
            parts = []
            if op == "TJ" and operands:
                parts = [x for x in operands[0]]
            elif operands:
                parts = [operands[-1]]
            full = mul(tm, ctm)
            th, tc, tw, rise = state["th"], state["tc"], state["tw"], state["rise"]
            si = len(t_infos)
            adv = 0.0
            for pi, p_ in enumerate(parts):
                if isinstance(p_, (int, float, NumberObject, FloatObject)):
                    adv -= _f(p_) / 1000 * tsize * th
                else:
                    off = 0
                    for nb, w0, code in fonts.glyphs(tfont, _raw(p_), tsize):
                        step = (w0 + tc + (tw if nb == 1 and code == 32 else 0.0)) * th
                        if len(t_glyphs) < MAX_GLYPHS:
                            t_glyphs.append((si, pi, off, nb, adv, step, w0, code))
                        adv += step
                        off += nb
            t_infos.append({"op": i, "full": full, "size": tsize, "th": th, "tc": tc, "tw": tw, "rise": rise, "font": tfont, "fillseq": list(state["fillseq"])})
            asc, desc = tsize * 0.9 + rise, -tsize * 0.25 + rise
            for X, Y in ((0, desc), (adv, desc), (adv, asc), (0, asc)):
                px, py = pt(full, X, Y)
                t_box = [px, py, px, py] if t_box is None else [min(t_box[0], px), min(t_box[1], py), max(t_box[2], px), max(t_box[3], py)]
            t_shows += 1
            tm = mul((1, 0, 0, 1, adv, 0), tm)
        elif op == "Do" and operands and len(objs) < MAX_OBJECTS:
            try:
                x = xobj[operands[0]].get_object()
                sub = str(x.get("/Subtype"))
            except Exception:
                x, sub = None, ""
            if sub in ("/Image", "/Form"):
                if sub == "/Form":
                    bx = [float(v) for v in x.get("/BBox", [0, 0, 1, 1])]
                    mt = tuple(float(v) for v in x.get("/Matrix", [1, 0, 0, 1, 0, 0]))
                    m2 = mul(mt, ctm)
                    corners = [pt(m2, bx[0], bx[1]), pt(m2, bx[2], bx[1]), pt(m2, bx[2], bx[3]), pt(m2, bx[0], bx[3])]
                else:
                    corners = [pt(ctm, 0, 0), pt(ctm, 1, 0), pt(ctm, 1, 1), pt(ctm, 0, 1)]
                xs, ys = [c[0] for c in corners], [c[1] for c in corners]
                objs.append({"id": len(objs), "kind": "image" if sub == "/Image" else "group", "a": i, "b": i, "bbox": [min(xs), min(ys), max(xs), max(ys)], "ctm": ctm,
                             "stroke": None, "fill": None})
    return ops, objs


def _decode_texts(page, objs: list[dict]) -> None:
    """give each text object its words (pypdf decodes the fonts); if the counts do not line up the text stays empty (it can still be moved)"""
    texts = [o for o in objs if o["kind"] == "text"]
    if not texts:
        return
    got: list[str] = []
    try:
        page.extract_text(visitor_text=lambda t, cm, tm, fd, fs: got.append(t) if t else None)
    except Exception:
        return
    # group the decoded pieces by text object using the number of show operations each one contains
    ops_count = [o.get("n_show", 0) for o in texts]
    if sum(ops_count) != len(got):
        for o in texts:
            o["text"] = ""
        return
    k = 0
    for o, n in zip(texts, ops_count):
        o["text"] = "".join(got[k:k + n]).rstrip("\n")
        k += n


# ---------------------------------------------------------------- the screen's view of a page
def open_page(path: str, page_no: int) -> dict:
    p = Path(path)
    if not p.is_file():
        raise UserError("That file was not found.")
    r = PdfReader(str(p))
    if r.is_encrypted:
        raise UserError("This PDF is locked with a password. Remove the password first (Protect > PDF password).")
    if not 1 <= page_no <= len(r.pages):
        raise UserError("That page does not exist.")
    page = r.pages[page_no - 1]
    _check_page(page)
    ops, objs = parse(r, page)
    _decode_texts(page, objs)
    x0, y0, x1, y1 = _page_box(page)
    out = []
    for o in objs:
        bx = o["bbox"]
        out.append({"id": o["id"], "kind": o["kind"], "x": round(bx[0] - x0, 2), "y": round(y1 - bx[3], 2), "w": round(bx[2] - bx[0], 2), "h": round(bx[3] - bx[1], 2),
                    "stroke": o.get("stroke"), "fill": o.get("fill"), "lw": o.get("lw"), "text": o.get("text", ""), "size": o.get("size")})
    return {"page": page_no, "total": len(r.pages), "w": x1 - x0, "h": y1 - y0, "objects": out, "capped": len(objs) >= MAX_OBJECTS}


def glyph_boxes(path: str, page_no: int) -> dict:
    """every single character of the page's text, as a box for the screen: {objects: [{id, g: [[index, x, y, w, h, is_space], ...]}]}.
    Used by the visual editor to move one letter, one full stop or one word instead of a whole line."""
    p = Path(path)
    if not p.is_file():
        raise UserError("That file was not found.")
    r = PdfReader(str(p))
    if r.is_encrypted:
        raise UserError("This PDF is locked with a password. Remove the password first (Protect > PDF password).")
    if not 1 <= page_no <= len(r.pages):
        raise UserError("That page does not exist.")
    page = r.pages[page_no - 1]
    _check_page(page)
    _ops, objs = parse(r, page)
    x0, y0, x1, y1 = _page_box(page)
    out, total = [], 0
    for o in objs:
        if o["kind"] != "text" or not o.get("glyphs"):
            continue
        gl = []
        for gi, (si, _pi, _off, nb, a0, step, _w0, code) in enumerate(o["glyphs"]):
            sh = o["shows"][si]
            size, rise = sh["size"], sh["rise"]
            q = [pt(sh["full"], X, Y) for X, Y in ((a0, -0.25 * size + rise), (a0 + step, -0.25 * size + rise), (a0 + step, 0.9 * size + rise), (a0, 0.9 * size + rise))]
            xs, ys = [v[0] for v in q], [v[1] for v in q]
            gl.append([gi, round(min(xs) - x0, 2), round(y1 - max(ys), 2), round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2), 1 if (nb == 1 and code == 32) else 0])
        total += len(gl)
        out.append({"id": o["id"], "g": gl, "size": o.get("size"), "fill": o.get("fill")})
    return {"page": page_no, "objects": out, "count": total}


# ---------------------------------------------------------------- moving single characters inside a text object
def _fill_ops(hexcol: str) -> list:
    return [([_num(v) for v in _rgb(hexcol)], b"rg")]


def _restore_fill(sh: dict, override: str | None) -> list:
    if override:
        return _fill_ops(override)
    return [([x for x in operands], op.encode()) for operands, op in sh["fillseq"]]


def _glyph_run(chunk: bytes, g: tuple, sh: dict, mod: dict, offx: float, offy: float, back: float, target_net: float, fill_back: str | None) -> list:
    """the instructions that show ONE character moved by (offx, offy) points on the page (screen axes: y grows downward), optionally recoloured
    or resized. Text-state changes are undone straight after, and the advance is corrected so every other character stays exactly where it was."""
    _si, _pi, _off, _nb, _a0, step, w0, _code = g
    size, th, rise = sh["size"], sh["th"], sh["rise"]
    sx = float(mod.get("sx") or 1.0)
    s2 = size * sx
    L = sh["full"]
    det = L[0] * L[3] - L[1] * L[2]
    px, py = offx, -offy
    if abs(det) < 1e-12:
        tx = ty = 0.0
    else:                                                       # page offset -> text space (the TJ number and Ts work there)
        tx = (px * L[3] - py * L[2]) / det
        ty = (-px * L[1] + py * L[0]) / det
    step2 = (w0 * sx + sh["tc"] + (sh["tw"] if (_nb == 1 and _code == 32) else 0.0)) * th
    first = tx - back
    post = target_net - first - step2
    k = 1000.0 / (s2 * th)
    arr = []
    if abs(first) > 1e-6:
        arr.append(_num(-first * k))
    arr.append(ByteStringObject(chunk))
    if abs(post) > 1e-6:
        arr.append(_num(-post * k))
    out: list = []
    if mod.get("fill"):
        out += _fill_ops(mod["fill"])
    if sx != 1.0:
        out.append(([NameObject(sh["font"]), _num(s2)], b"Tf"))
    if abs(ty) > 1e-9:
        out.append(([_num(rise + ty)], b"Ts"))
    out.append(([ArrayObject(arr)], b"TJ"))
    if abs(ty) > 1e-9:
        out.append(([_num(rise)], b"Ts"))
    if sx != 1.0:
        out.append(([NameObject(sh["font"]), _num(size)], b"Tf"))
    if mod.get("fill"):
        out += _restore_fill(sh, fill_back)
    return out


def _rebuild_show(operands, op, o: dict, si: int, by_part: dict, gm: dict, fill_back: str | None) -> list:
    sh = o["shows"][si]
    opn = op.decode() if isinstance(op, bytes) else str(op)
    out: list = []
    if opn == "'":
        out.append(([], b"T*"))
    elif opn == '"':
        if len(operands) == 3:
            out += [([operands[0]], b"Tw"), ([operands[1]], b"Tc")]
        out.append(([], b"T*"))
    parts = list(operands[0]) if opn == "TJ" else [operands[-1]]
    buf: list = []
    cur = bytearray()

    def push():
        nonlocal cur
        if cur:
            buf.append(ByteStringObject(bytes(cur)))
            cur = bytearray()

    def flush():
        nonlocal buf
        push()
        if buf:
            out.append(([ArrayObject(buf)], b"TJ"))
            buf = []

    usable = sh["size"] * sh["th"] != 0
    for pi, p_ in enumerate(parts):
        if isinstance(p_, (int, float, NumberObject, FloatObject)):
            push(); buf.append(p_)
            continue
        raw = _raw(p_)
        for gi, g in by_part.get(pi, []):
            chunk = raw[g[2]:g[2] + g[3]]
            mod = gm.get(str(gi)) or gm.get(gi)
            if not mod or not usable or not (mod.get("dx") or mod.get("dy") or mod.get("sx") or mod.get("fill") or mod.get("delete") or mod.get("dup")):
                cur += chunk
                continue
            flush()
            step, k = g[5], 1000.0 / (sh["size"] * sh["th"])
            if mod.get("delete"):                                # leave the gap, so the rest of the line does not slide
                if abs(step) > 1e-9:
                    out.append(([ArrayObject([_num(-step * k)])], b"TJ"))
                continue
            dx, dy = float(mod.get("dx") or 0), float(mod.get("dy") or 0)
            out += _glyph_run(chunk, g, sh, mod, dx, dy, 0.0, step, fill_back)
            d = mod.get("dup")
            if d:
                d = d if isinstance(d, dict) else {}
                out += _glyph_run(chunk, g, sh, mod, dx + float(d.get("dx", 14)), dy + float(d.get("dy", 14)), step, 0.0, fill_back)
    flush()
    return out


def _glyph_edit(seg: list, o: dict, gm: dict, base: int, fill_back: str | None) -> list:
    """the text object's instructions with the single-character edits applied"""
    if not gm or not o.get("glyphs"):
        return seg
    by_show: dict[int, dict[int, list]] = {}
    for gi, g in enumerate(o["glyphs"]):
        by_show.setdefault(g[0], {}).setdefault(g[1], []).append((gi, g))
    touched = {int(k) for k in gm.keys()}
    show_op = {sh["op"]: si for si, sh in enumerate(o["shows"])}
    out: list = []
    for k, (operands, op) in enumerate(seg):
        si = show_op.get(base + k)
        if si is None or not any(gi in touched for part in by_show.get(si, {}).values() for gi, _g in part):
            out.append((operands, op))
            continue
        out += _rebuild_show(operands, op, o, si, by_show[si], gm, fill_back)
    return out


# ---------------------------------------------------------------- applying edits
def _T(o: dict, m: dict):
    """the page-space transform for one object's edit: scale about its top-left corner, then move. Returns a 6-tuple in PDF page space."""
    bx = o["bbox"]
    sx, sy = float(m.get("sx", 1) or 1), float(m.get("sy", 1) or 1)
    dx, dy = float(m.get("dx", 0) or 0), -float(m.get("dy", 0) or 0)      # the screen's y grows downward
    ax, ay = bx[0], bx[3]                                               # top-left in PDF space
    return (sx, 0.0, 0.0, sy, ax - sx * ax + dx, ay - sy * ay + dy)


def _num(v):
    return FloatObject(repr(round(float(v), 4)))


def _wrap(seg: list, o: dict, m: dict, extra: tuple[float, float] = (0.0, 0.0)) -> list:
    """the object's own instructions wrapped in q <matrix> [colours] ... Q"""
    mm = dict(m)
    mm["dx"] = float(mm.get("dx", 0) or 0) + extra[0]
    mm["dy"] = float(mm.get("dy", 0) or 0) + extra[1]
    T = _T(o, mm)
    ctm = o["ctm"]
    M = mul(mul(ctm, T), inv(ctm))           # local-space matrix equivalent to the page-space move
    out = [([], b"q")]
    if any(abs(M[k] - IDENT[k]) > 1e-9 for k in range(6)):
        out.append(([_num(v) for v in M], b"cm"))
    if m.get("lw") is not None and o["kind"] == "shape":
        out.append(([_num(m["lw"])], b"w"))
    if m.get("stroke") and o["kind"] == "shape":
        out.append(([_num(v) for v in _rgb(m["stroke"])], b"RG"))
    if m.get("fill") and o["kind"] in ("shape", "text"):
        out.append(([_num(v) for v in _rgb(m["fill"])], b"rg"))
    out += seg
    out.append(([], b"Q"))
    return out


_SINGLE = {"w", "J", "j", "M", "d", "ri", "i", "Tc", "Tw", "Tz", "TL", "Tf", "Tr", "Ts"}


def _leaks(seg: list) -> list:
    """Settings a piece of the page leaves behind for what is drawn after it (colour, line width, text size, spacing...). Wrapping the piece in
    q ... Q for a move would throw them away, so they are put back right after it."""
    fill: list = []
    stroke: list = []
    single: dict = {}
    gs: list = []
    depth = 0
    for operands, op in seg:
        o = op.decode() if isinstance(op, bytes) else str(op)
        if o == "q":
            depth += 1
        elif o == "Q":
            depth = max(0, depth - 1)
        elif depth:
            continue
        elif o in ("g", "rg", "k", "cs"):
            fill = [(operands, op)]
        elif o in ("G", "RG", "K", "CS"):
            stroke = [(operands, op)]
        elif o in ("sc", "scn"):
            fill = [x for x in fill if (x[1].decode() if isinstance(x[1], bytes) else x[1]) == "cs"] + [(operands, op)]
        elif o in ("SC", "SCN"):
            stroke = [x for x in stroke if (x[1].decode() if isinstance(x[1], bytes) else x[1]) == "CS"] + [(operands, op)]
        elif o == "gs":
            gs.append((operands, op))
        elif o in _SINGLE:
            single[o] = (operands, op)
    return gs + list(single.values()) + fill + stroke


def apply_page(reader: PdfReader, page, mods: list[dict], adds: list[dict]) -> int:
    """changes the page in place; returns how many things were changed"""
    _check_page(page)
    ops, objs = parse(reader, page)
    _decode_texts(page, objs)
    by_id = {o["id"]: o for o in objs}
    mods_by = {int(m["id"]): m for m in mods if int(m.get("id", -1)) in by_id}
    by_start = {o["a"]: o for o in objs if o["id"] in mods_by}
    overlay: list[dict] = []
    out: list = []
    changed = 0
    i = 0
    x0, y0, x1, y1 = _page_box(page)
    while i < len(ops):
        o = by_start.get(i)
        if o is None:
            out.append(ops[i]); i += 1
            continue
        m = mods_by[o["id"]]
        seg = ops[o["a"]:o["b"] + 1]
        if o["kind"] == "text" and m.get("glyphs") and not m.get("delete") and not (m.get("text") is not None and m["text"] != o.get("text")):
            try:
                seg = _glyph_edit(seg, o, m["glyphs"], o["a"], m.get("fill"))
            except Exception:                         # a page with unusual text instructions: leave that text as it was rather than break the page
                seg = ops[o["a"]:o["b"] + 1]
        changed += 1
        leak = _leaks(ops[o["a"]:o["b"] + 1]) if o["kind"] == "text" else []
        if m.get("delete"):
            out += leak
        elif m.get("text") is not None and o["kind"] == "text" and m["text"] != o.get("text"):
            out += leak
            bx = o["bbox"]
            overlay.append({"type": "text", "text": str(m["text"]), "x": bx[0] - x0 + float(m.get("dx", 0) or 0), "y": (y1 - bx[1]) + float(m.get("dy", 0) or 0),
                            "size": o.get("size") or 12, "color": m.get("fill") or o.get("fill") or "#000000", "font": o.get("font_family") or "", "from_pdf": True,
                            "_base": _fontname(page, o.get("font", ""))})
        else:
            out += _wrap(seg, o, m)
            out += leak
        if m.get("dup"):
            d = m["dup"] if isinstance(m["dup"], dict) else {}
            dm = {k: v for k, v in m.items() if k not in ("dup", "delete", "text")}
            out += _wrap(seg, o, dm, (float(d.get("dx", 14)), float(d.get("dy", 14))))
        i = o["b"] + 1
    for a in adds:
        overlay.append(a)
    cs = ContentStream(None, reader)
    cs.operations = out
    page.replace_contents(cs)
    if overlay:
        _merge_overlay(reader, page, overlay, (x0, y0, x1, y1))
        changed += len(overlay)
    return changed


def _fontname(page, name: str) -> str:
    try:
        return str(page["/Resources"]["/Font"][name].get_object().get("/BaseFont", ""))
    except Exception:
        return ""


def _rl_font(base: str, family: str = "", bold: bool = False, italic: bool = False) -> str:
    b = (base or "").lower()
    fam = (family or "").lower()
    if fam in ("serif", "times") or ("times" in b or "serif" in b and "sans" not in b):
        f = "Times-Roman"
        if "bold" in b or bold:
            f = "Times-BoldItalic" if ("italic" in b or italic) else "Times-Bold"
        elif "italic" in b or italic:
            f = "Times-Italic"
        return f
    if fam in ("mono", "courier") or "courier" in b or "mono" in b:
        f = "Courier"
        if "bold" in b or bold:
            f = "Courier-BoldOblique" if ("italic" in b or italic) else "Courier-Bold"
        elif "italic" in b or italic:
            f = "Courier-Oblique"
        return f
    f = "Helvetica"
    if "bold" in b or bold:
        f = "Helvetica-BoldOblique" if ("italic" in b or italic) else "Helvetica-Bold"
    elif "italic" in b or "oblique" in b or italic:
        f = "Helvetica-Oblique"
    return f


def _merge_overlay(reader, page, items: list[dict], box) -> None:
    from reportlab.pdfgen import canvas
    x0, y0, x1, y1 = box
    W, H = x1 - x0, y1 - y0
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    for it in items:
        draw_item(c, it, H)
    c.showPage()
    c.save()
    buf.seek(0)
    ov = PdfReader(buf).pages[0]
    from pypdf import Transformation
    page.merge_transformed_page(ov, Transformation().translate(x0, y0))


def draw_item(c, it: dict, H: float) -> None:
    """one new object, drawn with the screen's coordinates (top-left origin)"""
    t = it.get("type")
    stroke, fill = it.get("stroke"), it.get("fill")
    lw = float(it.get("lw") or 1)
    x, y, w, h = (float(it.get(k, 0) or 0) for k in ("x", "y", "w", "h"))
    c.saveState()
    if t != "text":
        c.setLineWidth(lw)
        if stroke:
            c.setStrokeColorRGB(*_rgb(stroke))
        if fill:
            c.setFillColorRGB(*_rgb(fill))
    if t in ("rect", "ellipse", "round"):
        yy = H - y - h
        do_s, do_f = (1 if stroke else 0), (1 if fill else 0)
        if not do_s and not do_f:
            do_s = 1
        if t == "rect":
            c.rect(x, yy, w, h, stroke=do_s, fill=do_f)
        elif t == "round":
            c.roundRect(x, yy, w, h, min(w, h) * 0.18, stroke=do_s, fill=do_f)
        else:
            c.ellipse(x, yy, x + w, yy + h, stroke=do_s, fill=do_f)
    elif t in ("line", "arrow"):
        ax, ay, bx, by = float(it.get("x", 0)), H - float(it.get("y", 0)), float(it.get("x2", 0)), H - float(it.get("y2", 0))
        col = _rgb(stroke or fill or "#000000")
        c.setStrokeColorRGB(*col)
        c.setFillColorRGB(*col)
        import math
        ang = math.atan2(by - ay, bx - ax)
        head = max(8.0, lw * 4)
        if t == "arrow":
            sx, sy = bx - math.cos(ang) * head * 0.8, by - math.sin(ang) * head * 0.8
            c.line(ax, ay, sx, sy)
            p = c.beginPath()
            p.moveTo(bx, by)
            p.lineTo(bx - head * math.cos(ang - 0.4), by - head * math.sin(ang - 0.4))
            p.lineTo(bx - head * math.cos(ang + 0.4), by - head * math.sin(ang + 0.4))
            p.close()
            c.drawPath(p, stroke=0, fill=1)
        else:
            c.line(ax, ay, bx, by)
    elif t == "image":
        import base64 as _b64
        m = re.match(r"data:image/[\w+.-]+;base64,(.*)$", it.get("data", ""), re.S)
        if m and w > 0 and h > 0:
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(io.BytesIO(_b64.b64decode(m.group(1)))), x, H - y - h, w, h, mask="auto")
    elif t == "text":
        size = float(it.get("size") or 14)
        name = _rl_font(it.get("_base", ""), it.get("font", ""), bool(it.get("bold")), bool(it.get("italic")))
        c.setFillColorRGB(*_rgb(it.get("color") or it.get("fill") or "#000000"))
        c.setFont(name, size)
        yy = H - float(it.get("y", 0))
        if it.get("from_pdf"):
            yy = H - float(it.get("y", 0)) + size * 0.25          # the old box bottom is the descender; sit the text on its baseline
        else:
            yy = H - float(it.get("y", 0)) - size                  # screen y is the top of the text box
        for k, line in enumerate(str(it.get("text", "")).split("\n")):
            try:
                c.drawString(float(it.get("x", 0)), yy - k * size * 1.2, line)
            except Exception:
                c.drawString(float(it.get("x", 0)), yy - k * size * 1.2, line.encode("latin-1", "replace").decode("latin-1"))
    c.restoreState()


# ---------------------------------------------------------------- preview and save
def _edited_writer(path: str, pages: list[dict]) -> tuple[PdfWriter, int]:
    r = PdfReader(path)
    w = PdfWriter(clone_from=r)
    changed = 0
    for pg in pages or []:
        n = int(pg.get("page", 0))
        if not 1 <= n <= len(w.pages):
            continue
        changed += apply_page(w, w.pages[n - 1], pg.get("mods") or [], pg.get("adds") or [])
    return w, changed


def preview(path: str, pages: list[dict], page_no: int, dpi: int = 110) -> dict:
    """the page with this list of edits applied, as a PNG data URL"""
    from . import proof
    from .paths import temp_dir
    import uuid
    w, _n = _edited_writer(path, [pg for pg in pages if int(pg.get("page", 0)) == page_no])
    tmp = temp_dir() / ("pdfobj_" + uuid.uuid4().hex[:8] + ".pdf")
    try:
        with open(tmp, "wb") as fh:
            w.write(fh)
        got = proof.render_pdf_page(tmp, page_no - 1, dpi)
        if not got:
            raise UserError("This computer cannot draw the page picture (PDF engine missing).")
        im, scale = got
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return {"png": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), "scale": scale, "w": im.width, "h": im.height}
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def save_edits(src: Path, dst: Path, pages: list[dict]) -> int:
    w, n = _edited_writer(str(src), pages)
    with open(dst, "wb") as fh:
        w.write(fh)
    return n
