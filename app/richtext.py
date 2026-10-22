# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Text with a different font, size, colour, weight or underline on every stretch of it (what you get when you select part of a text box and style it).

A text object carries `runs`: [{t, font, size, color, b, i, u}] (t may contain "\\n"), plus `align` (left | center | right). The same description is drawn by every
writer in the Visual editor (PDF, picture, PowerPoint, SVG, Word), using the fonts that are really installed on this computer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from functools import lru_cache
from pathlib import Path

LINE = 1.2          # line pitch as a multiple of the biggest size on the line
BASE = 0.95         # baseline of the first line below the top of the box, as a multiple of the biggest size on that line
STD_SERIF = ("times", "georgia", "garamond", "palatino", "cambria", "book antiqua", "bookman", "century", "constantia", "serif", "minion", "baskerville", "didot")
STD_MONO = ("courier", "consolas", "monaco", "menlo", "lucida console", "mono", "terminal", "fixedsys")
COMMON = ["Arial", "Calibri", "Cambria", "Candara", "Comic Sans MS", "Consolas", "Courier New", "Georgia", "Helvetica", "Impact", "Lucida Sans", "Palatino Linotype",
          "Segoe UI", "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana"]

_lock = threading.Lock()


def _dirs() -> list[Path]:
    out: list[Path] = []
    if sys.platform.startswith("win"):
        out.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
        la = os.environ.get("LOCALAPPDATA")
        if la:
            out.append(Path(la) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        out += [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    else:
        out += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts", Path.home() / ".local/share/fonts"]
    return [d for d in out if d.is_dir()]


def _style_key(style: str) -> str:
    s = (style or "").lower()
    bold = "bold" in s or "black" in s or "heavy" in s
    ital = "italic" in s or "oblique" in s
    if bold and ital:
        return "bolditalic"
    if bold:
        return "bold"
    if ital:
        return "italic"
    if s in ("", "regular", "normal", "book", "roman", "medium", "standard"):
        return "regular"
    return ""          # light, condensed, semibold...: listed as a family of its own by its full name, not as a style of the plain one


def _scan() -> dict[str, dict[str, str]]:
    from PIL import ImageFont
    fam: dict[str, dict[str, str]] = {}
    seen = 0
    for d in _dirs():
        for root, _dn, files in os.walk(d):
            for fn in files:
                if not fn.lower().endswith((".ttf", ".otf", ".ttc")):
                    continue
                p = os.path.join(root, fn)
                try:
                    f = ImageFont.truetype(p, 12)
                    name, style = f.getname()
                except Exception:
                    continue
                sk = _style_key(style)
                if not sk:
                    name, sk = f"{name} {style}".strip(), "regular"
                fam.setdefault(name, {}).setdefault(sk, p)
                seen += 1
                if seen > 4000:
                    return fam
    return fam


@lru_cache(maxsize=1)
def font_index() -> dict[str, dict[str, str]]:
    """{family name: {regular|bold|italic|bolditalic: file}} for the fonts installed on this computer (remembered between runs)"""
    cache = None
    try:
        from .paths import data_root
        cache = Path(data_root()) / "fonts_index.json"
    except Exception:
        pass
    sig = hashlib.sha1("|".join(f"{d}:{int(d.stat().st_mtime)}" for d in _dirs()).encode()).hexdigest()[:12]
    try:
        if cache and cache.is_file():
            j = json.loads(cache.read_text(encoding="utf-8"))
            if j.get("sig") == sig and j.get("fonts"):
                return j["fonts"]
    except Exception:
        pass
    with _lock:
        fonts = _scan()
    try:
        if cache:
            cache.write_text(json.dumps({"sig": sig, "fonts": fonts}), encoding="utf-8")
    except Exception:
        pass
    return fonts


def families() -> list[dict]:
    """[{name, bold, italic}] for the font drop-down: the well known ones first, then everything installed, A to Z"""
    idx = font_index()
    names = {n.lower(): n for n in idx}
    out, done = [], set()
    for c in COMMON:
        n = names.get(c.lower()) or (c if c in ("Arial", "Times New Roman", "Courier New", "Helvetica") else None)
        if n and n.lower() not in done:
            done.add(n.lower())
            st = idx.get(n, {})
            out.append({"name": n, "bold": True, "italic": True, "common": True})
    for n in sorted(idx, key=str.lower):
        if n.lower() not in done:
            st = idx[n]
            out.append({"name": n, "bold": "bold" in st, "italic": "italic" in st, "common": False})
    return out


def _pdf_std(family: str, bold: bool, italic: bool) -> str:
    f = (family or "").lower()
    if any(k in f for k in STD_MONO):
        base = "Courier"
        return base + ("-BoldOblique" if bold and italic else "-Bold" if bold else "-Oblique" if italic else "")
    if any(k in f for k in STD_SERIF):
        return "Times-BoldItalic" if bold and italic else "Times-Bold" if bold else "Times-Italic" if italic else "Times-Roman"
    return "Helvetica" + ("-BoldOblique" if bold and italic else "-Bold" if bold else "-Oblique" if italic else "")


def resolve(family: str, bold: bool = False, italic: bool = False) -> tuple[str, str]:
    """("ttf", path) when that font is installed, else ("std", name of the closest built-in PDF font)"""
    idx = font_index()
    key = {n.lower(): n for n in idx}.get((family or "").lower().strip())
    if key:
        st = idx[key]
        want = "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"
        for cand in (want, "bold" if bold else "regular", "regular", *st.keys()):
            if cand in st:
                return "ttf", st[cand]
    return "std", _pdf_std(family, bold, italic)


def font_path(family: str, bold: bool = False, italic: bool = False) -> str | None:
    k, v = resolve(family, bold, italic)
    return v if k == "ttf" else None


# ------------------------------------------------------------------ the runs of a text object
def hexcolor(c, default="#000000") -> str:
    c = str(c or "").strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", c):
        return "#" + c.lstrip("#").lower()
    m = re.fullmatch(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", c)
    if m:
        return "#%02x%02x%02x" % tuple(int(v) for v in m.groups())
    return default


def normalize(a: dict) -> tuple[list[dict], str]:
    """(runs, align) of a text object, from `runs` or from the old single-style fields (text, size, color, font, bold, italic)"""
    size = float(a.get("size") or 14)
    col = hexcolor(a.get("color") or a.get("fill"), "#000000")
    runs = []
    for r in a.get("runs") or []:
        t = str(r.get("t", ""))
        if t == "":
            continue
        runs.append({"t": t, "font": str(r.get("font") or a.get("font") or "Arial"), "size": float(r.get("size") or size), "color": hexcolor(r.get("color"), col),
                     "b": bool(r.get("b", a.get("bold"))), "i": bool(r.get("i", a.get("italic"))), "u": bool(r.get("u"))})
    if not runs:
        runs = [{"t": str(a.get("text", "")), "font": str(a.get("font") or "Arial"), "size": size, "color": col, "b": bool(a.get("bold")), "i": bool(a.get("italic")), "u": False}]
    al = a.get("align") if a.get("align") in ("left", "center", "right") else "left"
    return runs, al


def plain(runs: list[dict]) -> str:
    return "".join(r["t"] for r in runs)


def split_lines(runs: list[dict]) -> list[list[dict]]:
    """the runs cut at every new line"""
    lines: list[list[dict]] = [[]]
    for r in runs:
        parts = r["t"].split("\n")
        for k, part in enumerate(parts):
            if k:
                lines.append([])
            if part != "":
                lines[-1].append({**r, "t": part})
    return lines


@lru_cache(maxsize=256)
def _pil_font(path: str, px: int):
    from PIL import ImageFont
    return ImageFont.truetype(path, px)


def width(text: str, family: str, size: float, bold: bool = False, italic: bool = False) -> float:
    """how wide the text is in points, measured with the real font (or a close built-in one)"""
    kind, ref = resolve(family, bold, italic)
    try:
        if kind == "ttf":
            f = _pil_font(ref, 200)
            return f.getlength(text) * size / 200.0
        from reportlab.pdfbase.pdfmetrics import stringWidth
        return stringWidth(text, ref, size)
    except Exception:
        return len(text) * size * 0.55


def line_height(line: list[dict], default: float = 14.0) -> float:
    return max([r["size"] for r in line] or [default]) * LINE


def layout(runs: list[dict], box_w: float | None = None, align: str = "left"):
    """[(line runs, x offset, baseline offset from the top of the box, line width)], total width, total height"""
    lines = split_lines(runs)
    ws = [sum(width(r["t"], r["font"], r["size"], r["b"], r["i"]) for r in ln) for ln in lines]
    W = max(ws + [1.0]) if box_w is None else max(box_w, max(ws + [1.0]))
    out, y = [], 0.0
    for ln, w in zip(lines, ws):
        big = max([r["size"] for r in ln] or [14.0])
        dx = 0.0 if align == "left" else (W - w) / 2 if align == "center" else W - w
        out.append((ln, dx, y + BASE * big, w))
        y += big * LINE
    return out, W, y


# ------------------------------------------------------------------ PDF font names
_FAMILY = (("helvetica", "Arial"), ("arial", "Arial"), ("timesnewroman", "Times New Roman"), ("times", "Times New Roman"), ("courier", "Courier New"),
           ("calibri", "Calibri"), ("cambria", "Cambria"), ("verdana", "Verdana"), ("tahoma", "Tahoma"), ("georgia", "Georgia"), ("segoeui", "Segoe UI"),
           ("symbol", "Symbol"), ("comicsans", "Comic Sans MS"), ("trebuchet", "Trebuchet MS"), ("palatino", "Palatino Linotype"), ("garamond", "Garamond"),
           ("consolas", "Consolas"), ("lucida", "Lucida Sans"), ("impact", "Impact"), ("candara", "Candara"), ("corbel", "Corbel"), ("constantia", "Constantia"))


def font_info(base: str) -> tuple[str, bool, bool]:
    """(family a Word machine knows, bold, italic) from a PDF BaseFont name like 'ABCDEF+Helvetica-BoldOblique'"""
    n = re.sub(r"^[A-Z]{6}\+", "", str(base or "").lstrip("/"))
    low = n.lower().replace(" ", "")
    bold = any(k in low for k in ("bold", "black", "heavy", "semibold", "demi"))
    ital = any(k in low for k in ("italic", "oblique", "slanted"))
    key = re.sub(r"[^a-z]", "", low.split("-")[0].split(",")[0])
    for k, fam in _FAMILY:
        if key.startswith(k):
            return fam, bold, ital
    fam = re.split(r"[-,]", n)[0]
    fam = re.sub(r"(MT|PS|PSMT)$", "", fam)
    fam = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", fam).strip()
    return (fam or "Arial"), bold, ital


