"""Making documents: PDF, Word, web page, text, PowerPoint, Excel and charts, from plain Markdown-style text or structured data."""
from __future__ import annotations

import base64
import html as _html
import io
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path

from app.service import UserError

# ================================================================== reading Markdown into blocks
Run = tuple  # (text, {"b":bool,"i":bool,"code":bool,"link":str,"s":bool})

_INLINE = re.compile(r"(\*\*\*(?P<bi>.+?)\*\*\*|\*\*(?P<b>.+?)\*\*|__(?P<b2>.+?)__|(?<![\w*])\*(?P<i>[^*\s][^*]*?)\*(?![\w*])|(?<![\w_])_(?P<i2>[^_\s][^_]*?)_(?![\w_])|`(?P<c>[^`]+)`|~~(?P<s>.+?)~~|!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)|\[(?P<lt>[^\]]+)\]\((?P<lu>[^)\s]+)\)|<br\s*/?>)")


def inline(text: str, base: dict | None = None) -> list[Run]:
    base = base or {}
    runs: list[Run] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], dict(base)))
        pos = m.end()
        g = m.groupdict()
        if m.group(0).startswith("<br"):
            runs.append(("\n", dict(base)))
        elif g["bi"]:
            runs += inline(g["bi"], {**base, "b": True, "i": True})
        elif g["b"] or g["b2"]:
            runs += inline(g["b"] or g["b2"], {**base, "b": True})
        elif g["i"] or g["i2"]:
            runs += inline(g["i"] or g["i2"], {**base, "i": True})
        elif g["c"]:
            runs.append((g["c"], {**base, "code": True}))
        elif g["s"]:
            runs += inline(g["s"], {**base, "s": True})
        elif g["src"] is not None:
            runs.append((g["alt"] or "", {**base, "img": g["src"]}))
        elif g["lt"]:
            runs += inline(g["lt"], {**base, "link": g["lu"]})
    if pos < len(text):
        runs.append((text[pos:], dict(base)))
    return [r for r in runs if r[0] != ""] or [("", dict(base))]


def plain(runs: list[Run]) -> str:
    return "".join(t for t, _ in runs)


def parse(md: str) -> list[dict]:
    """Markdown-ish text -> blocks: h, p, ul, ol, table, code, quote, hr, img, pagebreak"""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[dict] = []
    i = 0

    def list_block(start: int) -> tuple[dict, int]:
        first = lines[start]
        m0 = re.match(r"^(\s*)([-*+]|\d+[.)])\s+", first)
        ordered = m0.group(2)[0].isdigit()
        base_indent = len(m0.group(1).replace("\t", "    "))
        items, j = [], start
        while j < len(lines):
            ln = lines[j]
            m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", ln)
            if m:
                ind = len(m.group(1).replace("\t", "    "))
                if ind < base_indent:
                    break
                if ind <= base_indent + 1 and items and m.group(2)[0].isdigit() != ordered:
                    break
                if ind > base_indent + 1 and items:
                    sub, j2 = list_block(j)
                    items[-1]["children"].append(sub)
                    j = j2
                    continue
                txt = m.group(3)
                task = None
                tm = re.match(r"^\[( |x|X)\]\s+(.*)$", txt)
                if tm:
                    task, txt = tm.group(1).lower() == "x", tm.group(2)
                items.append({"runs": inline(txt), "children": [], "task": task})
                j += 1
            elif ln.strip() == "":
                nxt = lines[j + 1] if j + 1 < len(lines) else ""
                mn = re.match(r"^(\s*)([-*+]|\d+[.)])\s+", nxt)
                if mn and (len(mn.group(1)) > base_indent + 1 or (len(mn.group(1)) >= base_indent and mn.group(2)[0].isdigit() == ordered)):
                    j += 1
                    continue
                break
            elif re.match(r"^\s{2,}\S", ln) and items:
                items[-1]["runs"] += [(" ", {})] + inline(ln.strip())
                j += 1
            else:
                break
        return {"type": "ol" if ordered else "ul", "items": items}, j

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if re.match(r"^(```|~~~)", s):
            fence = s[:3]
            lang = s[3:].strip()
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].strip().startswith(fence):
                buf.append(lines[j])
                j += 1
            out.append({"type": "code", "text": "\n".join(buf), "lang": lang})
            i = j + 1
            continue
        if re.match(r"^(\\pagebreak|<!--\s*pagebreak\s*-->|-{3,}\s*pagebreak\s*-{3,}|\[\[pagebreak\]\])$", s, re.I):
            out.append({"type": "pagebreak"})
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", s)
        if m:
            out.append({"type": "h", "level": len(m.group(1)), "runs": inline(m.group(2))})
            i += 1
            continue
        if re.match(r"^([-*_])(\s*\1){2,}$", s):
            out.append({"type": "hr"})
            i += 1
            continue
        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append({"type": "quote", "blocks": parse("\n".join(buf))})
            continue
        if "|" in s and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$", lines[i + 1]) and "|" in lines[i + 1]:
            def cells(row: str) -> list[str]:
                row = row.strip()
                if row.startswith("|"):
                    row = row[1:]
                if row.endswith("|"):
                    row = row[:-1]
                return [c.strip() for c in re.split(r"(?<!\\)\|", row)]
            head = cells(ln)
            aligns = []
            for c in cells(lines[i + 1]):
                aligns.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else "left")
            rows = []
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append(cells(lines[j]))
                j += 1
            out.append({"type": "table", "header": [inline(c) for c in head], "rows": [[inline(c) for c in r] + [[("", {})]] * max(0, len(head) - len(r)) for r in rows], "aligns": aligns})
            i = j
            continue
        if re.match(r"^\s*([-*+]|\d+[.)])\s+", ln):
            b, i = list_block(i)
            out.append(b)
            continue
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", s)
        if m:
            out.append({"type": "img", "alt": m.group(1), "src": m.group(2)})
            i += 1
            continue
        buf = [s]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|~~~|>|\s*([-*+]|\d+[.)])\s+|([-*_])(\s*\3){2,}$)", lines[i].strip()) and not ("|" in lines[i] and i + 1 < len(lines) and (re.match(r"^\s*\|?\s*:?-+:?\s*\|", lines[i + 1] if i + 1 < len(lines) else "") is not None)):
            buf.append(lines[i].strip())
            i += 1
        out.append({"type": "p", "runs": inline(" ".join(buf))})
    return out


# ================================================================== themes and fonts
THEMES = {
    "clean": {"accent": "#2f5bea", "text": "#1d2433", "muted": "#6b7385", "heading_font": "sans", "body_font": "sans", "size": 10.5, "zebra": "#f3f5fb", "code_bg": "#f1f3f8", "rule": "#d8dce8"},
    "report": {"accent": "#1f3a5f", "text": "#1a1a1a", "muted": "#666666", "heading_font": "serif", "body_font": "serif", "size": 11, "zebra": "#f5f5f0", "code_bg": "#f2f2ec", "rule": "#cfcfc4"},
    "modern": {"accent": "#0f8b8d", "text": "#18222b", "muted": "#64727e", "heading_font": "sans", "body_font": "sans", "size": 10.5, "zebra": "#eef7f7", "code_bg": "#eef2f4", "rule": "#cfe3e3"},
    "warm": {"accent": "#c2562b", "text": "#2a211c", "muted": "#7a6a60", "heading_font": "serif", "body_font": "sans", "size": 10.5, "zebra": "#fbf3ee", "code_bg": "#f6efe9", "rule": "#ead9cd"},
    "dark-accent": {"accent": "#6d4aff", "text": "#16161d", "muted": "#6a6a78", "heading_font": "sans", "body_font": "sans", "size": 10.5, "zebra": "#f3f1ff", "code_bg": "#f0eef9", "rule": "#dcd8f3"},
}


def theme(name: str | None, opts: dict | None = None) -> dict:
    t = dict(THEMES.get((name or "clean").lower(), THEMES["clean"]))
    for k in ("accent", "text", "size", "heading_font", "body_font"):
        if opts and opts.get(k):
            t[k] = opts[k]
    return t


_FONT_DIRS = [r"C:\Windows\Fonts", "/usr/share/fonts", "/usr/share/fonts/truetype", "/usr/local/share/fonts", os.path.expanduser("~/Library/Fonts"), "/Library/Fonts", "/System/Library/Fonts/Supplemental"]
_FAMILIES = {
    "sans": [("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"), ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"), ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf"),
             ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"), ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf")],
    "serif": [("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"), ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"), ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSerif-Italic.ttf", "DejaVuSerif-BoldItalic.ttf"),
              ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf", "LiberationSerif-Italic.ttf", "LiberationSerif-BoldItalic.ttf")],
    "mono": [("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"), ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"), ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Oblique.ttf", "DejaVuSansMono-BoldOblique.ttf"),
             ("LiberationMono-Regular.ttf", "LiberationMono-Bold.ttf", "LiberationMono-Italic.ttf", "LiberationMono-BoldItalic.ttf")],
}
_PDF_FONTS: dict[str, str] = {}


def _find_font(fname: str) -> str | None:
    for d in _FONT_DIRS:
        if not os.path.isdir(d):
            continue
        p = os.path.join(d, fname)
        if os.path.exists(p):
            return p
        for root, _dirs, files in os.walk(d):
            if fname in files:
                return os.path.join(root, fname)
    try:
        import matplotlib
        p = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf", fname)
        if os.path.exists(p):
            return p
    except Exception:
        pass
    return None


def pdf_font_family(kind: str) -> str:
    """registers a Unicode TrueType family with reportlab (bold, italic, bold italic) and returns its name; built-in Helvetica/Times/Courier if none is found"""
    if kind in _PDF_FONTS:
        return _PDF_FONTS[kind]
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    name = {"sans": "Helvetica", "serif": "Times-Roman", "mono": "Courier"}.get(kind, "Helvetica")
    for fam in _FAMILIES.get(kind, _FAMILIES["sans"]):
        paths = [_find_font(f) for f in fam]
        if paths[0] and paths[1]:
            try:
                n = f"Fx{kind}"
                pdfmetrics.registerFont(TTFont(n, paths[0]))
                pdfmetrics.registerFont(TTFont(n + "-B", paths[1]))
                pdfmetrics.registerFont(TTFont(n + "-I", paths[2] or paths[0]))
                pdfmetrics.registerFont(TTFont(n + "-BI", paths[3] or paths[1]))
                pdfmetrics.registerFontFamily(n, normal=n, bold=n + "-B", italic=n + "-I", boldItalic=n + "-BI")
                name = n
                break
            except Exception:
                continue
    else:
        if name == "Helvetica":
            pass
    _PDF_FONTS[kind] = name
    return name


def _hexrgb(c: str) -> tuple[float, float, float]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _img_path(src: str, base: Path | None) -> Path | None:
    if src.startswith("data:image"):
        return None
    p = Path(src.strip().strip('"'))
    if not p.is_absolute() and base:
        p = base / p
    return p if p.exists() else None


def _img_bytes(src: str, base: Path | None) -> bytes | None:
    if src.startswith("data:image"):
        try:
            return base64.b64decode(src.split(",", 1)[1])
        except Exception:
            return None
    p = _img_path(src, base)
    return p.read_bytes() if p else None


# ================================================================== PDF
def _para_xml(runs: list[Run], mono: str, accent: str) -> str:
    out = []
    for text, st in runs:
        t = _html.escape(text, quote=False).replace("\n", "<br/>")
        if st.get("code"):
            t = f'<font name="{mono}" backColor="#eef0f5" color="#b3311d">{t}</font>'
        if st.get("b"):
            t = f"<b>{t}</b>"
        if st.get("i"):
            t = f"<i>{t}</i>"
        if st.get("s"):
            t = f"<strike>{t}</strike>"
        if st.get("link"):
            t = f'<a href="{_html.escape(st["link"], quote=True)}" color="{accent}"><u>{t}</u></a>'
        out.append(t)
    return "".join(out)


def make_pdf(md: str, path: Path, title: str = "", opts: dict | None = None) -> dict:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4, LETTER, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, Image, KeepTogether, ListFlowable, ListItem, PageBreak, PageTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle)
    from reportlab.platypus.tableofcontents import TableOfContents

    opts = opts or {}
    th = theme(opts.get("theme"), opts)
    blocks = parse(md)
    body = pdf_font_family(th["body_font"])
    head = pdf_font_family(th["heading_font"])
    mono = pdf_font_family("mono")
    bold = lambda f: f + "-B" if f.startswith("Fx") else {"Helvetica": "Helvetica-Bold", "Times-Roman": "Times-Bold", "Courier": "Courier-Bold"}.get(f, f)
    size = float(th["size"])
    accent, text_c, muted = colors.HexColor(th["accent"]), colors.HexColor(th["text"]), colors.HexColor(th["muted"])
    page = LETTER if str(opts.get("page", "A4")).lower() == "letter" else A4
    if str(opts.get("orientation", "")).lower() == "landscape":
        page = landscape(page)
    margin = float(opts.get("margin_mm", 20)) * mm
    base_dir = Path(opts["base_dir"]) if opts.get("base_dir") else None

    S = {
        "p": ParagraphStyle("p", fontName=body, fontSize=size, leading=size * 1.5, textColor=text_c, spaceAfter=size * 0.6, alignment={"justify": 4, "center": TA_CENTER, "right": TA_RIGHT}.get(str(opts.get("align", "")).lower(), TA_LEFT)),
        "li": ParagraphStyle("li", fontName=body, fontSize=size, leading=size * 1.45, textColor=text_c, spaceAfter=2),
        "q": ParagraphStyle("q", fontName=body, fontSize=size, leading=size * 1.5, textColor=muted, leftIndent=12, borderPadding=(2, 0, 2, 8), spaceAfter=size * 0.6),
        "cell": ParagraphStyle("cell", fontName=body, fontSize=size - 1, leading=(size - 1) * 1.35, textColor=text_c),
        "cellh": ParagraphStyle("cellh", fontName=bold(body), fontSize=size - 1, leading=(size - 1) * 1.35, textColor=colors.white),
        "cap": ParagraphStyle("cap", fontName=body, fontSize=size - 2, leading=size, textColor=muted, alignment=TA_CENTER, spaceAfter=size),
        "code": ParagraphStyle("code", fontName=mono, fontSize=size - 2, leading=(size - 2) * 1.35, textColor=text_c),
    }
    for lvl, (mult, before) in {1: (2.0, 18), 2: (1.55, 14), 3: (1.25, 10), 4: (1.1, 8), 5: (1.0, 6), 6: (0.95, 6)}.items():
        S[f"h{lvl}"] = ParagraphStyle(f"h{lvl}", fontName=bold(head), fontSize=size * mult, leading=size * mult * 1.25, textColor=accent if lvl <= 2 else text_c, spaceBefore=before, spaceAfter=size * 0.5, keepWithNext=1)

    story: list = []
    heads: list[tuple[int, str, str]] = []
    heads_made: list[int] = []

    class Doc(BaseDocTemplate):
        def afterFlowable(self, fl):
            if isinstance(fl, Paragraph) and getattr(fl, "_fx_level", None):
                key = fl._fx_key
                self.canv.bookmarkPage(key)
                lv = min(fl._fx_level - 1, getattr(self, "_fx_last", -1) + 1)
                self._fx_last = lv
                self.canv.addOutlineEntry(fl.getPlainText(), key, level=lv, closed=False)
                self.notify("TOCEntry", (fl._fx_level - 1, fl.getPlainText(), self.page - (1 if opts.get("cover") else 0), key))
                heads.append((fl._fx_level, fl.getPlainText(), key))

    class Numbered(rl_canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            n = len(self._saved)
            for st in self._saved:
                self.__dict__.update(st)
                self._footer(n)
                super().showPage()
            super().save()

        def _footer(self, n):
            if self._pageNumber == 1 and opts.get("cover"):
                return
            self.setFont(body, 8)
            self.setFillColor(muted)
            w, h = page
            if opts.get("footer", True) is not False:
                label = str(opts.get("footer_text") or "")
                self.drawString(margin, margin * 0.55, label[:90])
                self.drawRightString(w - margin, margin * 0.55, f"Page {self._pageNumber - (1 if opts.get('cover') else 0)} of {n - (1 if opts.get('cover') else 0)}")
            if opts.get("header_text"):
                self.drawString(margin, h - margin * 0.55, str(opts["header_text"])[:100])
                self.setStrokeColor(colors.HexColor(th["rule"]))
                self.line(margin, h - margin * 0.65, w - margin, h - margin * 0.65)

    def img_flowable(src: str, alt: str, maxw: float):
        data = _img_bytes(src, base_dir)
        if not data:
            return Paragraph(f"[picture not found: {_html.escape(src[:60])}]", S["cap"])
        from PIL import Image as PILImage
        im = PILImage.open(io.BytesIO(data))
        w, h = im.size
        scale = min(maxw / w, (page[1] * 0.5) / h, 1.0 if max(w, h) < 900 else 10)
        scale = min(maxw / w, (page[1] * 0.55) / h)
        bio = io.BytesIO(data)
        f = Image(bio, width=w * scale, height=h * scale)
        f.hAlign = "CENTER"
        items = [f]
        if alt:
            items.append(Paragraph(_html.escape(alt), S["cap"]))
        return KeepTogether(items)

    avail_w = page[0] - 2 * margin

    def render(bl: list[dict], indent: float = 0.0, width: float | None = None) -> list:
        out: list = []
        width = width or avail_w
        for b in bl:
            t = b["type"]
            if t == "h":
                lvl = min(6, b["level"])
                p = Paragraph(_para_xml(b["runs"], mono, th["accent"]), S[f"h{lvl}"])
                if lvl <= 3:
                    p._fx_level = lvl
                    p._fx_key = f"h{len(heads_made)}"
                    heads_made.append(1)
                out.append(p)
            elif t == "p":
                out.append(Paragraph(_para_xml(b["runs"], mono, th["accent"]), S["p"]))
            elif t in ("ul", "ol"):
                out.append(_list(b, width))
            elif t == "table":
                out.append(_table(b, width))
            elif t == "code":
                lines = []
                for ln in b["text"].split("\n"):
                    while len(ln) > 92:
                        lines.append(ln[:92])
                        ln = "    " + ln[92:]
                    lines.append(ln)
                pre = Preformatted("\n".join(lines) or " ", S["code"])
                tb = Table([[pre]], colWidths=[width])
                tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(th["code_bg"])), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(th["rule"])), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
                out += [tb, Spacer(1, size * 0.7)]
            elif t == "quote":
                inner = render(b["blocks"], width=width - 18)
                tb = Table([[inner]], colWidths=[width])
                tb.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, -1), 3, accent), ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TEXTCOLOR", (0, 0), (-1, -1), muted)]))
                out += [tb, Spacer(1, size * 0.6)]
            elif t == "hr":
                out.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor(th["rule"]), spaceBefore=6, spaceAfter=10))
            elif t == "img":
                out.append(img_flowable(b["src"], b["alt"], width))
            elif t == "pagebreak":
                out.append(PageBreak())
        return out

    def _list(b: dict, width: float):
        items = []
        for it in b["items"]:
            label = _para_xml(it["runs"], mono, th["accent"])
            if it.get("task") is not None:
                label = ("☑ " if it["task"] else "☐ ") + label
            sub = [Paragraph(label, S["li"])]
            for ch in it["children"]:
                sub.append(_list(ch, width - 16))
            items.append(ListItem(sub, leftIndent=14))
        kw = {"bulletType": "1", "bulletFormat": "%s."} if b["type"] == "ol" else {"bulletType": "bullet", "start": "•"}
        return ListFlowable(items, bulletFontName=body, bulletFontSize=size, leftIndent=14, bulletColor=accent, spaceAfter=size * 0.5, **kw)

    def _table(b: dict, width: float):
        ncol = len(b["header"])
        data = [[Paragraph(_para_xml(c, mono, th["accent"]), S["cellh"]) for c in b["header"]]]
        als = b.get("aligns", [])
        def cs(ci, hdr=False):
            al = als[ci] if ci < len(als) else "left"
            base = S["cellh"] if hdr else S["cell"]
            return base if al == "left" else ParagraphStyle(base.name + al, parent=base, alignment=TA_CENTER if al == "center" else TA_RIGHT)
        data[0] = [Paragraph(_para_xml(c, mono, th["accent"]), cs(ci, True)) for ci, c in enumerate(b["header"])]
        for r in b["rows"]:
            data.append([Paragraph(_para_xml(c, mono, th["accent"]), cs(ci)) for ci, c in enumerate(r[:ncol])])
        lens = [max(len(plain(b["header"][c])), *(len(plain(r[c])) for r in b["rows"] if c < len(r)), 4) if b["rows"] else len(plain(b["header"][c])) + 2 for c in range(ncol)]
        lens = [min(max(x, 6), 40) for x in lens]
        tot = sum(lens)
        widths = [width * x / tot for x in lens]
        tb = Table(data, colWidths=widths, repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), accent), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(th["rule"])), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        for ri in range(1, len(data)):
            if ri % 2 == 0:
                style.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor(th["zebra"])))
        for ci, al in enumerate(b.get("aligns", [])):
            if al != "left" and ci < ncol:
                style.append(("ALIGN", (ci, 1), (ci, -1), al.upper()))
        tb.setStyle(TableStyle(style))
        return KeepTogether([tb, Spacer(1, size * 0.8)]) if len(data) < 18 else tb

    meta_title = title or opts.get("title") or ""
    if blocks and blocks[0]["type"] == "h" and blocks[0]["level"] == 1 and plain(blocks[0]["runs"]).strip().lower() == meta_title.strip().lower() and not opts.get("cover"):
        blocks = blocks[1:]
    if opts.get("cover"):
        cs = ParagraphStyle("covert", fontName=bold(head), fontSize=size * 3, leading=size * 3.6, textColor=accent, spaceAfter=14)
        story += [Spacer(1, page[1] * 0.26), Paragraph(_html.escape(meta_title or "Document"), cs)]
        if opts.get("subtitle"):
            story.append(Paragraph(_html.escape(str(opts["subtitle"])), ParagraphStyle("covers", fontName=body, fontSize=size * 1.5, leading=size * 2, textColor=muted, spaceAfter=24)))
        story.append(HRFlowable(width="30%", thickness=3, color=accent, hAlign="LEFT", spaceAfter=20))
        story.append(Paragraph(_html.escape(" · ".join(x for x in [str(opts.get("author") or ""), str(opts.get("date") or datetime.now().strftime("%d %B %Y"))] if x)), S["p"]))
        story.append(PageBreak())
    elif meta_title and opts.get("title_block", True):
        story += [Paragraph(_html.escape(meta_title), ParagraphStyle("tt", fontName=bold(head), fontSize=size * 2.3, leading=size * 2.8, textColor=accent, spaceAfter=4))]
        sub = " · ".join(x for x in [str(opts.get("subtitle") or ""), str(opts.get("author") or ""), str(opts.get("date") or "")] if x)
        if sub:
            story.append(Paragraph(_html.escape(sub), ParagraphStyle("ts", fontName=body, fontSize=size, textColor=muted, spaceAfter=6)))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor(th["rule"]), spaceAfter=10))
    if opts.get("toc"):
        toc = TableOfContents()
        toc.levelStyles = [ParagraphStyle(f"toc{i}", fontName=body, fontSize=size, leading=size * 1.7, leftIndent=14 * i, textColor=text_c) for i in range(3)]
        story += [Paragraph("Contents", S["h1"]), toc, PageBreak()]
    story += render(blocks)
    if not story:
        story = [Paragraph(" ", S["p"])]
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = Doc(str(path), pagesize=page, leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin, title=meta_title or path.stem, author=str(opts.get("author") or "Fathom"))
    doc.addPageTemplates([PageTemplate("main", [Frame(margin, margin, page[0] - 2 * margin, page[1] - 2 * margin, id="f")])])
    if opts.get("toc"):
        doc.multiBuild(story, canvasmaker=Numbered)
    else:
        doc.build(story, canvasmaker=Numbered)
    pages = 0
    try:
        from pypdf import PdfReader
        pages = len(PdfReader(str(path)).pages)
    except Exception:
        pass
    return {"path": str(path), "pages": pages}


# ================================================================== Word
def make_docx(md: str, path: Path, title: str = "", opts: dict | None = None) -> dict:
    import docx
    from docx.enum.text import WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    opts = opts or {}
    th = theme(opts.get("theme"), opts)
    d = docx.Document()
    base_dir = Path(opts["base_dir"]) if opts.get("base_dir") else None
    sec = d.sections[0]
    if str(opts.get("page", "A4")).lower() == "letter":
        sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    else:
        sec.page_width, sec.page_height = Inches(8.27), Inches(11.69)
    for m in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, m, Inches(float(opts.get("margin_mm", 22)) / 25.4))
    fonts = {"sans": "Calibri", "serif": "Georgia", "mono": "Consolas"}
    st = d.styles["Normal"]
    st.font.name = fonts.get(th["body_font"], "Calibri")
    st.font.size = Pt(float(th["size"]))
    st.element.rPr.rFonts.set(qn("w:eastAsia"), st.font.name)
    rgb = lambda h: RGBColor(*[int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)])
    for lvl in range(1, 5):
        hs = d.styles[f"Heading {lvl}"]
        hs.font.name = fonts.get(th["heading_font"], "Calibri")
        hs.font.color.rgb = rgb(th["accent"]) if lvl <= 2 else rgb(th["text"])
        hs.font.size = Pt(float(th["size"]) * {1: 2.0, 2: 1.55, 3: 1.25, 4: 1.1}[lvl])
    ts = d.styles["Title"]
    ts.font.name = fonts.get(th["heading_font"], "Calibri")
    ts.font.color.rgb = rgb(th["accent"])

    def shade(cell_or_par, hexcolor: str, par=False):
        pr = cell_or_par._p.get_or_add_pPr() if par else cell_or_par._tc.get_or_add_tcPr()
        sh = OxmlElement("w:shd")
        sh.set(qn("w:val"), "clear")
        sh.set(qn("w:color"), "auto")
        sh.set(qn("w:fill"), hexcolor.lstrip("#"))
        pr.append(sh)

    def add_runs(par, runs, size=None):
        for text, s in runs:
            if s.get("img"):
                data = _img_bytes(s["img"], base_dir)
                if data:
                    par.add_run().add_picture(io.BytesIO(data), width=Inches(5.5))
                continue
            parts = text.split("\n")
            for k, part in enumerate(parts):
                r = par.add_run(part)
                if k:
                    r.add_break(WD_BREAK.LINE)
                if s.get("b"):
                    r.bold = True
                if s.get("i"):
                    r.italic = True
                if s.get("s"):
                    r.font.strike = True
                if s.get("code"):
                    r.font.name = "Consolas"
                    r.font.size = Pt(float(th["size"]) - 1)
                    r.font.color.rgb = RGBColor(0xB3, 0x31, 0x1D)
                if s.get("link"):
                    r.font.color.rgb = rgb(th["accent"])
                    r.underline = True
                if size:
                    r.font.size = Pt(size)

    def lst(b, level=0):
        ordered = b["type"] == "ol"
        for it in b["items"]:
            name = ("List Number" if ordered else "List Bullet") + (f" {level + 1}" if level else "")
            try:
                par = d.add_paragraph(style=name)
            except KeyError:
                par = d.add_paragraph(style="List Number" if ordered else "List Bullet")
            if it.get("task") is not None:
                par.add_run("☑ " if it["task"] else "☐ ")
            add_runs(par, it["runs"])
            for ch in it["children"]:
                lst(ch, min(level + 1, 2))

    def render(bl):
        for b in bl:
            t = b["type"]
            if t == "h":
                par = d.add_heading(level=min(b["level"], 4))
                add_runs(par, [(x, {k: v for k, v in s.items() if k not in ("b",)}) for x, s in b["runs"]])
            elif t == "p":
                par = d.add_paragraph()
                add_runs(par, b["runs"])
                al = str(opts.get("align", "")).lower()
                if al in ("justify", "center", "right"):
                    par.alignment = {"justify": 3, "center": 1, "right": 2}[al]
            elif t in ("ul", "ol"):
                lst(b)
            elif t == "table":
                n = len(b["header"])
                tb = d.add_table(rows=1, cols=n)
                tb.style = "Table Grid"
                for ci, c in enumerate(b["header"]):
                    cell = tb.rows[0].cells[ci]
                    cell.text = ""
                    add_runs(cell.paragraphs[0], [(x, {**s, "b": True}) for x, s in c])
                    shade(cell, th["accent"])
                    for r in cell.paragraphs[0].runs:
                        r.font.color.rgb = RGBColor(255, 255, 255)
                for ri, row in enumerate(b["rows"]):
                    cells = tb.add_row().cells
                    for ci in range(n):
                        cells[ci].text = ""
                        add_runs(cells[ci].paragraphs[0], row[ci] if ci < len(row) else [("", {})])
                        if ri % 2 == 1:
                            shade(cells[ci], th["zebra"])
                        al = b["aligns"][ci] if ci < len(b.get("aligns", [])) else "left"
                        if al != "left":
                            cells[ci].paragraphs[0].alignment = 1 if al == "center" else 2
                d.add_paragraph()
            elif t == "code":
                for ln in (b["text"] or " ").split("\n"):
                    par = d.add_paragraph()
                    r = par.add_run(ln or " ")
                    r.font.name = "Consolas"
                    r.font.size = Pt(float(th["size"]) - 1.5)
                    shade(par, th["code_bg"], par=True)
                    par.paragraph_format.space_after = Pt(0)
                d.add_paragraph()
            elif t == "quote":
                for sb in b["blocks"]:
                    if sb["type"] == "p":
                        par = d.add_paragraph()
                        par.paragraph_format.left_indent = Inches(0.35)
                        add_runs(par, [(x, {**s, "i": True}) for x, s in sb["runs"]])
                        for r in par.runs:
                            r.font.color.rgb = RGBColor(0x66, 0x6B, 0x78)
                    else:
                        render([sb])
            elif t == "hr":
                par = d.add_paragraph()
                pPr = par._p.get_or_add_pPr()
                bd = OxmlElement("w:pBdr")
                bt = OxmlElement("w:bottom")
                for k, v in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", th["rule"].lstrip("#"))):
                    bt.set(qn("w:" + k), v)
                bd.append(bt)
                pPr.append(bd)
            elif t == "img":
                data = _img_bytes(b["src"], base_dir)
                if data:
                    d.add_picture(io.BytesIO(data), width=Inches(5.8))
                    d.paragraphs[-1].alignment = 1
                    if b["alt"]:
                        cp = d.add_paragraph(b["alt"])
                        cp.alignment = 1
                        for r in cp.runs:
                            r.italic = True
                            r.font.size = Pt(float(th["size"]) - 2)
                else:
                    d.add_paragraph(f"[picture not found: {b['src'][:60]}]")
            elif t == "pagebreak":
                d.add_page_break()

    if opts.get("cover"):
        for _ in range(7):
            d.add_paragraph()
        d.add_paragraph(title or "Document", style="Title")
        if opts.get("subtitle"):
            d.add_paragraph(str(opts["subtitle"]))
        d.add_paragraph(" · ".join(x for x in [str(opts.get("author") or ""), str(opts.get("date") or datetime.now().strftime("%d %B %Y"))] if x))
        d.add_page_break()
    elif title:
        _bl = parse(md)
        if _bl and _bl[0]["type"] == "h" and _bl[0]["level"] == 1 and plain(_bl[0]["runs"]).strip().lower() == title.strip().lower():
            md = md.split("\n", 1)[1] if "\n" in md else ""
        d.add_paragraph(title, style="Title")
        sub = " · ".join(x for x in [str(opts.get("subtitle") or ""), str(opts.get("author") or ""), str(opts.get("date") or "")] if x)
        if sub:
            d.add_paragraph(sub)
    if opts.get("toc"):
        d.add_heading("Contents", level=1)
        par = d.add_paragraph()
        run = par.add_run()
        for typ, txt in (("begin", None), (None, 'TOC \\o "1-3" \\h \\z \\u'), ("separate", None), (None, "Right-click here and choose Update field to fill the table of contents."), ("end", None)):
            if typ:
                el = OxmlElement("w:fldChar")
                el.set(qn("w:fldCharType"), typ)
                run._r.append(el)
            elif txt.startswith("TOC"):
                it = OxmlElement("w:instrText")
                it.set(qn("xml:space"), "preserve")
                it.text = txt
                run._r.append(it)
            else:
                tt = OxmlElement("w:t")
                tt.text = txt
                run._r.append(tt)
        d.add_page_break()
    render(parse(md))
    if opts.get("footer", True) is not False:
        fp = sec.footer.paragraphs[0]
        fp.text = str(opts.get("footer_text") or "")
        fp.add_run("\tPage ")
        run = fp.add_run()
        for typ in ("begin", "instr", "end"):
            if typ == "instr":
                it = OxmlElement("w:instrText")
                it.text = "PAGE"
                run._r.append(it)
            else:
                el = OxmlElement("w:fldChar")
                el.set(qn("w:fldCharType"), typ)
                run._r.append(el)
    if opts.get("header_text"):
        sec.header.paragraphs[0].text = str(opts["header_text"])
    d.core_properties.title = title or path.stem
    d.core_properties.author = str(opts.get("author") or "Fathom")
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(path))
    return {"path": str(path)}


# ================================================================== web page / text
def make_html(md: str, path: Path, title: str = "", opts: dict | None = None) -> dict:
    opts = opts or {}
    th = theme(opts.get("theme"), opts)
    base_dir = Path(opts["base_dir"]) if opts.get("base_dir") else None

    def runs_html(runs):
        out = []
        for t, s in runs:
            if s.get("img"):
                data = _img_bytes(s["img"], base_dir)
                if data:
                    mt = mimetypes.guess_type(s["img"])[0] or "image/png"
                    out.append(f'<img alt="{_html.escape(t)}" src="data:{mt};base64,{base64.b64encode(data).decode()}">')
                continue
            x = _html.escape(t).replace("\n", "<br>")
            if s.get("code"):
                x = f"<code>{x}</code>"
            if s.get("b"):
                x = f"<strong>{x}</strong>"
            if s.get("i"):
                x = f"<em>{x}</em>"
            if s.get("s"):
                x = f"<del>{x}</del>"
            if s.get("link"):
                x = f'<a href="{_html.escape(s["link"], quote=True)}">{x}</a>'
            out.append(x)
        return "".join(out)

    def lst(b):
        tag = b["type"]
        items = []
        for it in b["items"]:
            pre = ("☑ " if it["task"] else "☐ ") if it.get("task") is not None else ""
            items.append(f"<li>{pre}{runs_html(it['runs'])}{''.join(lst(c) for c in it['children'])}</li>")
        return f"<{tag}>{''.join(items)}</{tag}>"

    def render(bl):
        out = []
        for b in bl:
            t = b["type"]
            if t == "h":
                out.append(f"<h{min(b['level'], 6)}>{runs_html(b['runs'])}</h{min(b['level'], 6)}>")
            elif t == "p":
                out.append(f"<p>{runs_html(b['runs'])}</p>")
            elif t in ("ul", "ol"):
                out.append(lst(b))
            elif t == "table":
                th_ = "".join(f"<th>{runs_html(c)}</th>" for c in b["header"])
                rows = "".join("<tr>" + "".join(f"<td>{runs_html(c)}</td>" for c in r) + "</tr>" for r in b["rows"])
                out.append(f"<table><thead><tr>{th_}</tr></thead><tbody>{rows}</tbody></table>")
            elif t == "code":
                out.append(f"<pre><code>{_html.escape(b['text'])}</code></pre>")
            elif t == "quote":
                out.append(f"<blockquote>{''.join(render(b['blocks']))}</blockquote>")
            elif t == "hr":
                out.append("<hr>")
            elif t == "img":
                data = _img_bytes(b["src"], base_dir)
                if data:
                    mt = mimetypes.guess_type(b["src"])[0] or "image/png"
                    out.append(f'<figure><img alt="{_html.escape(b["alt"])}" src="data:{mt};base64,{base64.b64encode(data).decode()}"><figcaption>{_html.escape(b["alt"])}</figcaption></figure>')
            elif t == "pagebreak":
                out.append('<div style="break-after:page"></div>')
        return out

    fam = {"sans": "system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif", "serif": "Georgia,'Times New Roman',serif"}
    css = f"""body{{max-width:820px;margin:40px auto;padding:0 20px;font:{th['size'] + 5}px/1.65 {fam.get(th['body_font'], fam['sans'])};color:{th['text']};background:#fff}}
h1,h2,h3,h4{{font-family:{fam.get(th['heading_font'], fam['sans'])};line-height:1.25;margin:1.6em 0 .5em}}h1,h2{{color:{th['accent']}}}h1{{font-size:2em}}
a{{color:{th['accent']}}}code{{background:{th['code_bg']};padding:.1em .35em;border-radius:4px;font-size:.92em}}pre{{background:{th['code_bg']};padding:14px;border-radius:8px;overflow:auto}}pre code{{background:none;padding:0}}
table{{border-collapse:collapse;width:100%;margin:1em 0}}th{{background:{th['accent']};color:#fff;text-align:left}}th,td{{padding:7px 10px;border-bottom:1px solid {th['rule']}}}tbody tr:nth-child(even){{background:{th['zebra']}}}
blockquote{{margin:1em 0;padding:.2em 1em;border-left:4px solid {th['accent']};color:{th['muted']}}}img{{max-width:100%}}figure{{text-align:center;margin:1.2em 0}}figcaption{{color:{th['muted']};font-size:.85em}}hr{{border:0;border-top:1px solid {th['rule']}}}
@media print{{body{{margin:0;max-width:none}}}}"""
    body = "".join(render(parse(md)))
    head = f"<h1>{_html.escape(title)}</h1>" if title and not re.match(r"^\s*#\s", md) else ""
    doc = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_html.escape(title or path.stem)}</title><style>{css}</style></head><body>{head}{body}</body></html>'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return {"path": str(path)}


# ================================================================== PowerPoint
def make_pptx(slides: list[dict], path: Path, title: str = "", opts: dict | None = None) -> dict:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Emu, Inches, Pt

    opts = opts or {}
    th = theme(opts.get("theme"), opts)
    base_dir = Path(opts["base_dir"]) if opts.get("base_dir") else None
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    rgb = lambda h: RGBColor(*[int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)])
    font = {"sans": "Calibri", "serif": "Georgia"}.get(th["heading_font"], "Calibri")
    W, H = prs.slide_width, prs.slide_height
    dark = bool(opts.get("dark"))
    bg_c, fg_c = ("#14161f", "#f2f4fa") if dark else ("#ffffff", th["text"])

    def tb(slide, x, y, w, h, text="", size=18, bold=False, color=None, align=None, font_name=None, anchor=None):
        box = slide.shapes.add_textbox(x, y, w, h)
        tf = box.text_frame
        tf.word_wrap = True
        if anchor:
            tf.vertical_anchor = anchor
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = text
        r.font.size, r.font.bold = Pt(size), bold
        r.font.name = font_name or font
        r.font.color.rgb = rgb(color or fg_c)
        if align:
            p.alignment = align
        return box

    def bg(slide, color):
        f = slide.background.fill
        f.solid()
        f.fore_color.rgb = rgb(color)

    def bullets(slide, items, x, y, w, h, size=22):
        box = slide.shapes.add_textbox(x, y, w, h)
        tf = box.text_frame
        tf.word_wrap = True
        first = True
        for it in items:
            lvl, txt = (it.get("level", 0), it.get("text", "")) if isinstance(it, dict) else (0, str(it))
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.level = min(4, lvl)
            r = p.add_run()
            r.text = ("• " if lvl == 0 else "– ") + txt
            r.font.size = Pt(size - 3 * lvl)
            r.font.name = "Calibri" if th["body_font"] == "sans" else "Georgia"
            r.font.color.rgb = rgb(fg_c)
            p.space_after = Pt(10)
        return box

    def picture(slide, src, x, y, w, h):
        data = _img_bytes(str(src), base_dir)
        if not data:
            return None
        from PIL import Image as PILImage
        im = PILImage.open(io.BytesIO(data))
        iw, ih = im.size
        sc = min(w / iw, h / ih)
        pw, ph = int(iw * sc), int(ih * sc)
        return slide.shapes.add_picture(io.BytesIO(data), x + (w - pw) // 2, y + (h - ph) // 2, pw, ph)

    def chrome(slide, ttl):
        bar = slide.shapes.add_shape(1, 0, 0, Inches(0.22), H)
        bar.fill.solid()
        bar.fill.fore_color.rgb = rgb(th["accent"])
        bar.line.fill.background()
        if ttl:
            tb(slide, Inches(0.8), Inches(0.45), W - Inches(1.6), Inches(1.0), ttl, 34, True, th["accent"] if not dark else "#ffffff")

    lst = list(slides)
    if title and not (lst and str(lst[0].get("layout", "")) == "title"):
        lst.insert(0, {"layout": "title", "title": title, "subtitle": opts.get("subtitle", "")})
    for n, sd in enumerate(lst, 1):
        s = prs.slides.add_slide(blank)
        lay = str(sd.get("layout") or ("bullets" if sd.get("bullets") else "image" if sd.get("image") else "title" if n == 1 else "bullets"))
        bg(s, th["accent"] if lay in ("title", "section") else bg_c)
        ttl = str(sd.get("title") or "")
        if lay in ("title", "section"):
            tb(s, Inches(0.9), Inches(2.4 if lay == "title" else 2.9), W - Inches(1.8), Inches(1.6), ttl, 54 if lay == "title" else 44, True, "#ffffff")
            if sd.get("subtitle"):
                tb(s, Inches(0.9), Inches(4.2), W - Inches(1.8), Inches(1.0), str(sd["subtitle"]), 24, False, "#e8ecff")
            if sd.get("image"):
                picture(s, sd["image"], W - Inches(5.2), Inches(1.4), Inches(4.4), Inches(4.7))
        elif lay == "quote":
            chrome(s, "")
            tb(s, Inches(1.2), Inches(1.8), W - Inches(2.4), Inches(3.2), "“" + str(sd.get("quote") or ttl) + "”", 38, False, fg_c, font_name="Georgia")
            if sd.get("author"):
                tb(s, Inches(1.2), Inches(5.3), W - Inches(2.4), Inches(0.8), "— " + str(sd["author"]), 22, False, th["accent"])
        elif lay == "image":
            chrome(s, ttl)
            picture(s, sd.get("image", ""), Inches(0.8), Inches(1.5), W - Inches(1.6), H - Inches(2.2))
            if sd.get("caption"):
                tb(s, Inches(0.8), H - Inches(0.8), W - Inches(1.6), Inches(0.5), str(sd["caption"]), 14, False, th["muted"], PP_ALIGN.CENTER)
        elif lay == "two_column":
            chrome(s, ttl)
            bullets(s, sd.get("bullets", []), Inches(0.8), Inches(1.6), Inches(6.0), H - Inches(2.3))
            if sd.get("image"):
                picture(s, sd["image"], Inches(7.2), Inches(1.6), Inches(5.4), H - Inches(2.4))
            elif sd.get("bullets2"):
                bullets(s, sd["bullets2"], Inches(7.0), Inches(1.6), Inches(5.8), H - Inches(2.3))
        elif lay == "table" and sd.get("table"):
            chrome(s, ttl)
            hdr, rows = sd["table"].get("header", []), sd["table"].get("rows", [])
            ncol = max(len(hdr), *(len(r) for r in rows)) if rows or hdr else 1
            shape = s.shapes.add_table(len(rows) + 1, ncol, Inches(0.8), Inches(1.6), W - Inches(1.6), Inches(0.5) * (len(rows) + 1))
            t = shape.table
            for ci in range(ncol):
                c = t.cell(0, ci)
                c.text = str(hdr[ci]) if ci < len(hdr) else ""
                c.fill.solid()
                c.fill.fore_color.rgb = rgb(th["accent"])
                for p in c.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.size, r.font.bold, r.font.color.rgb = Pt(16), True, RGBColor(255, 255, 255)
            for ri, row in enumerate(rows, 1):
                for ci in range(ncol):
                    c = t.cell(ri, ci)
                    c.text = str(row[ci]) if ci < len(row) else ""
                    c.fill.solid()
                    c.fill.fore_color.rgb = rgb(th["zebra"] if ri % 2 == 0 else "#ffffff")
                    for p in c.text_frame.paragraphs:
                        for r in p.runs:
                            r.font.size, r.font.color.rgb = Pt(15), rgb("#222222")
        elif lay == "chart" and sd.get("chart"):
            chrome(s, ttl)
            ch = sd["chart"]
            cd = CategoryChartData()
            cd.categories = [str(c) for c in ch.get("categories", [])]
            for ser in ch.get("series", []):
                cd.add_series(str(ser.get("name", "")), [float(v) for v in ser.get("values", [])])
            kind = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED, "column": XL_CHART_TYPE.COLUMN_CLUSTERED, "barh": XL_CHART_TYPE.BAR_CLUSTERED, "line": XL_CHART_TYPE.LINE_MARKERS, "pie": XL_CHART_TYPE.PIE, "area": XL_CHART_TYPE.AREA}.get(str(ch.get("type", "bar")), XL_CHART_TYPE.COLUMN_CLUSTERED)
            gf = s.shapes.add_chart(kind, Inches(0.9), Inches(1.6), W - Inches(1.8), H - Inches(2.3), cd)
            gf.chart.has_legend = len(ch.get("series", [])) > 1 or kind == XL_CHART_TYPE.PIE
            if gf.chart.has_legend:
                gf.chart.legend.position = XL_LEGEND_POSITION.BOTTOM
                gf.chart.legend.include_in_layout = False
        else:
            chrome(s, ttl)
            bullets(s, sd.get("bullets", []), Inches(0.8), Inches(1.6), W - Inches(1.6), H - Inches(2.3))
            if sd.get("image"):
                picture(s, sd["image"], W - Inches(5.0), Inches(1.6), Inches(4.4), H - Inches(2.4))
        if sd.get("notes"):
            s.notes_slide.notes_text_frame.text = str(sd["notes"])
        tb(s, W - Inches(1.0), H - Inches(0.5), Inches(0.8), Inches(0.35), str(n), 11, False, th["muted"] if lay not in ("title", "section") else "#dfe4ff", PP_ALIGN.RIGHT)
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    return {"path": str(path), "slides": len(lst)}


# ================================================================== Excel
def make_xlsx(sheets: list[dict], path: Path, opts: dict | None = None) -> dict:
    import openpyxl
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference, ScatterChart, Series
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    opts = opts or {}
    th = theme(opts.get("theme"), opts)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    fill = PatternFill("solid", fgColor=th["accent"].lstrip("#"))
    zebra = PatternFill("solid", fgColor=th["zebra"].lstrip("#"))
    thin = Side(style="thin", color=th["rule"].lstrip("#"))

    def coerce(v):
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("="):
                return s
            if re.fullmatch(r"[-+]?\d+", s) and len(s.lstrip("+-")) < 16:
                return int(s)
            if re.fullmatch(r"[-+]?\d*\.\d+", s):
                return float(s)
        return v

    for i, sh in enumerate(sheets or [{"name": "Sheet1", "rows": []}], 1):
        ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", "_", str(sh.get("name") or f"Sheet{i}"))[:31])
        rows = sh.get("rows") or []
        header = sh.get("header", True)
        for r in rows:
            ws.append([coerce(c) for c in r])
        if rows and header:
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = fill
                c.alignment = Alignment(vertical="center", wrap_text=True)
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
        for ri, row in enumerate(ws.iter_rows(min_row=2 if header else 1), 2 if header else 1):
            for c in row:
                c.border = Border(bottom=thin)
                if ri % 2 == 0 and sh.get("zebra", True):
                    c.fill = zebra
        for ci in range(1, (ws.max_column or 0) + 1):
            width = max((len(str(c.value)) for c in ws[get_column_letter(ci)] if c.value is not None and not str(c.value).startswith("=")), default=8)
            ws.column_dimensions[get_column_letter(ci)].width = min(60, max(9, width + 3))
        for col, fmt in (sh.get("formats") or {}).items():          # e.g. {"C": "0.00%", "D": "#,##0.00"}
            for c in ws[col][1 if header else 0:]:
                c.number_format = fmt
        ch = sh.get("chart")
        if ch and rows:
            kind = str(ch.get("type", "bar"))
            nrows = len(rows)
            ncols = max(len(r) for r in rows)
            cats = Reference(ws, min_col=1, min_row=2, max_row=nrows)
            if kind == "pie":
                chart = PieChart()
                chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=nrows), titles_from_data=True)
            elif kind == "line":
                chart = LineChart()
                chart.add_data(Reference(ws, min_col=2, max_col=ncols, min_row=1, max_row=nrows), titles_from_data=True)
            elif kind == "scatter":
                chart = ScatterChart()
                for c in range(2, ncols + 1):
                    s = Series(Reference(ws, min_col=c, min_row=1, max_row=nrows), Reference(ws, min_col=1, min_row=2, max_row=nrows), title_from_data=True)
                    chart.series.append(s)
            else:
                chart = BarChart()
                chart.type = "bar" if kind == "barh" else "col"
                chart.add_data(Reference(ws, min_col=2, max_col=ncols, min_row=1, max_row=nrows), titles_from_data=True)
            if kind != "scatter":
                chart.set_categories(cats)
            chart.title = ch.get("title") or None
            chart.width, chart.height = 18, 9
            ws.add_chart(chart, str(ch.get("anchor") or f"{get_column_letter(ncols + 2)}2"))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return {"path": str(path), "sheets": [s.title for s in wb.worksheets]}


# ================================================================== charts (pictures)
PALETTE = ["#4c6ef5", "#f76707", "#2f9e44", "#e03131", "#7048e8", "#0c8599", "#f59f00", "#d6336c", "#5c7cfa", "#82c91e"]


def make_chart(spec: dict, path: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    kind = str(spec.get("type", "bar"))
    cats = [str(c) for c in spec.get("categories", [])]
    series = spec.get("series") or []
    colors = spec.get("colors") or PALETTE
    fig, ax = plt.subplots(figsize=(float(spec.get("width", 9)), float(spec.get("height", 5.2))), dpi=int(spec.get("dpi", 160)))
    fig.patch.set_facecolor("white")
    if kind == "pie":
        vals = series[0]["values"] if series else []
        ax.pie(vals, labels=cats, autopct="%1.0f%%", colors=colors[:len(vals)], startangle=90, wedgeprops={"linewidth": 1, "edgecolor": "white"})
        ax.axis("equal")
    elif kind in ("scatter",):
        for i, s in enumerate(series):
            ax.scatter(s.get("x", cats), s["values"], label=s.get("name"), color=colors[i % len(colors)], s=40, alpha=.85)
    elif kind == "hist":
        for i, s in enumerate(series):
            ax.hist(s["values"], bins=int(spec.get("bins", 12)), alpha=.75, label=s.get("name"), color=colors[i % len(colors)])
    else:
        n = max(1, len(series))
        import numpy as np
        x = np.arange(len(cats))
        for i, s in enumerate(series):
            vals = s["values"]
            if kind in ("bar", "column"):
                w = 0.8 / n
                ax.bar(x + (i - (n - 1) / 2) * w, vals, w, label=s.get("name"), color=colors[i % len(colors)])
            elif kind == "barh":
                h = 0.8 / n
                ax.barh(x + (i - (n - 1) / 2) * h, vals, h, label=s.get("name"), color=colors[i % len(colors)])
            elif kind == "line":
                ax.plot(x, vals, marker="o", linewidth=2.2, label=s.get("name"), color=colors[i % len(colors)])
            elif kind == "area":
                ax.fill_between(x, vals, alpha=.35, color=colors[i % len(colors)])
                ax.plot(x, vals, linewidth=2, label=s.get("name"), color=colors[i % len(colors)])
        if kind == "barh":
            ax.set_yticks(x)
            ax.set_yticklabels(cats)
        else:
            ax.set_xticks(x)
            ax.set_xticklabels(cats, rotation=int(spec.get("rotate", 0)))
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.grid(axis="y" if kind != "barh" else "x", alpha=.25)
    if spec.get("title"):
        ax.set_title(str(spec["title"]), fontsize=14, fontweight="bold", loc="left", pad=12)
    if spec.get("xlabel"):
        ax.set_xlabel(str(spec["xlabel"]))
    if spec.get("ylabel"):
        ax.set_ylabel(str(spec["ylabel"]))
    if len(series) > 1 and kind != "pie":
        ax.legend(frameon=False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), facecolor="white")
    plt.close(fig)
    return {"path": str(path)}
