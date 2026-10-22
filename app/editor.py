# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""The editor: open one file and change its content directly.

* Text, code, web pages, CSV, JSON, settings ...  : a text editor (encoding and line endings are kept).
* Word, PowerPoint, OpenDocument text / slides   : every paragraph, in order, editable, with delete and add.
* Excel                                          : a grid of cells (values and formulas).
* SQLite databases                               : tables and rows, edit a cell or delete a row.
* PDF                                            : every piece of text on every page.
* Pictures                                       : a canvas (draw, write, box, blur, crop, turn) - the screen does the drawing, this saves it.
* Anything else                                  : opens in the Hex view.
Saving makes a copy (name_edited) or, when asked, replaces the original and sends the old one to the Recycle Bin."""
from __future__ import annotations

import base64
import html
import io
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path

from app import recycle
from app.convert import formats
from app.convert.core import file_bytes
from app.ops import OutputPolicy, unique_path
from app.service import UserError
from app.textedit import (IMG_EXT, MARKUP_EXT, OOXML, ODF, SQLITE_EXT, decode_text, encode_text, _rewrite_zip, _esc)

MAX_TEXT = 25 << 20
TEXT_FMTS = ("txt", "md", "csv", "tsv", "json", "jsonl", "yaml", "toml", "sql", "ini", "ipynb", "rst", "tex", "org", "textile", "wiki", "asciidoc", "srt", "vtt", "ass", "ssa", "sub", "html", "xml", "svg", "docbook", "stl", "obj", "off", "ply", "dae", "gltf")
WORD = {"docx", "docm", "dotx", "dotm"}
SLIDES = {"pptx", "pptm", "potx", "potm", "ppsx", "ppsm"}
SHEETS = {"xlsx", "xlsm", "xltx", "xltm"}
ODFTEXT = {"odt", "ott", "odp", "otp", "fodt"}


def kind_of(p: Path) -> str:
    ext = formats.ext_of(p)
    fmt = formats.detect(p)
    if ext in WORD or fmt in WORD:
        return "docx"
    if ext in SLIDES or fmt in SLIDES:
        return "pptx"
    if ext in SHEETS or fmt in SHEETS:
        return "xlsx"
    if ext in ("odt", "ott", "odp", "otp"):
        return "odf"
    if ext in SQLITE_EXT:
        try:
            with open(p, "rb") as f:
                if f.read(16) == b"SQLite format 3\x00":
                    return "sqlite"
        except OSError:
            pass
    if ext == "pdf" or fmt == "pdf":
        return "pdf"
    if ext in IMG_EXT or formats.category(fmt) == "image" and fmt not in ("svg",):
        return "image"
    if ext in MARKUP_EXT or fmt in TEXT_FMTS or formats.category(fmt) in ("text", "subtitle", "data") or fmt in ("txt",):
        return "text"
    try:
        with open(p, "rb") as f:
            head = f.read(8192)
        if b"\x00" not in head or head.startswith((b"\xff\xfe", b"\xfe\xff")):
            return "text"
    except OSError:
        pass
    return "binary"


# ================================================================== paragraph based files (Word, PowerPoint, OpenDocument)
def _word_parts(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    names = z.namelist()
    out = []
    if "word/document.xml" in names:
        out.append(("word/document.xml", "Body"))
    for n in sorted(names):
        if re.fullmatch(r"word/header\d*\.xml", n):
            out.append((n, "Header"))
        elif re.fullmatch(r"word/footer\d*\.xml", n):
            out.append((n, "Footer"))
    for n, lab in (("word/footnotes.xml", "Footnotes"), ("word/endnotes.xml", "Endnotes"), ("word/comments.xml", "Comments")):
        if n in names:
            out.append((n, lab))
    return out


def _slide_parts(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    names = z.namelist()
    slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
    out = [(n, f"Slide {i + 1}") for i, n in enumerate(slides)]
    notes = sorted((n for n in names if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
    out += [(n, f"Notes {i + 1}") for i, n in enumerate(notes)]
    return out


class _Markup:
    """paragraph finder for one XML dialect"""

    def __init__(self, p: str, t: str, br: str | None, tab: str | None, pPr: str):
        self.p, self.t, self.br, self.tab, self.pPr = p, t, br, tab, pPr
        self.para = re.compile(rf"<{p}/>|<{p}(?:\s[^>]*)?(?<!/)>.*?</{p}>", re.S)
        self.run = re.compile(rf"<{t}(?:\s[^>]*)?>([^<]*)</{t}>|<{t}\s*/>")
        self.token = re.compile(rf"<{t}(?:\s[^>]*)?>([^<]*)</{t}>" + (rf"|(<{br}\s*/>)" if br else "") + (rf"|(<{tab}\s*/>)" if tab else ""))


W = _Markup("w:p", "w:t", "w:br", "w:tab", "w:pPr")
A = _Markup("a:p", "a:t", "a:br", None, "a:pPr")


def _para_text(M: _Markup, para: str) -> str:
    out = []
    for m in re.finditer(M.token.pattern, para):
        if m.group(1) is not None:
            out.append(html.unescape(m.group(1)))
        elif m.lastindex == 2:
            out.append("\n")
        else:
            out.append("\t")
    return "".join(out)


def _paras(M: _Markup, xml: str) -> list[re.Match]:
    return list(M.para.finditer(xml))


def _rebuild_text(M: _Markup, para: str, text: str) -> str:
    """Puts new text into the first text run of a paragraph (formatting kept), empties the other runs, keeps pictures and fields."""
    def pieces(t: str) -> str:
        parts = re.split(r"(\n|\t)", t)
        out = []
        for x in parts:
            if x == "\n":
                out.append(f"<{M.br}/>")
            elif x == "\t" and M.tab:
                out.append(f"<{M.tab}/>")
            elif x == "\t":
                out.append(_open_t(M, "\t") + "\t</" + M.t + ">")
            elif x:
                out.append(f'<{M.t} xml:space="preserve">{_esc(x)}</{M.t}>' if M.t.startswith("w:") else f"<{M.t}>{_esc(x)}</{M.t}>")
        return "".join(out)
    runs = list(re.finditer(rf"<{M.t}(?:\s[^>]*)?>[^<]*</{M.t}>", para))
    if not runs:
        run_xml = f"<{M.p.replace(':p', ':r')}>" + pieces(text) + f"</{M.p.replace(':p', ':r')}>"
        if para.endswith("/>") and para.startswith(f"<{M.p}/>"):
            return f"<{M.p}>{run_xml}</{M.p}>"
        return para[: para.rindex(f"</{M.p}>")] + run_xml + f"</{M.p}>"
    # remove the text and line-break tokens of the later runs, put everything in the first run
    first = runs[0]
    out = para[: first.start()] + pieces(text)
    pos = first.end()
    rest = para[pos:]
    rest = re.sub(rf"<{M.t}(?:\s[^>]*)?>[^<]*</{M.t}>", "", rest)
    rest = re.sub(rf"<{M.br}\s*/>", "", rest) if M.br else rest
    if M.tab:
        rest = re.sub(rf"<{M.tab}\s*/>", "", rest)
    return out + rest


def _open_t(M: _Markup, _t: str) -> str:
    return f'<{M.t} xml:space="preserve">' if M.t.startswith("w:") else f"<{M.t}>"


def _new_para(M: _Markup, template: str, text: str) -> str:
    ppr = re.search(rf"<{M.pPr}(?:\s[^>]*)?>.*?</{M.pPr}>|<{M.pPr}\s*/>", template, re.S)
    rpr = re.search(r"<(?:w|a):rPr(?:\s[^>]*)?>.*?</(?:w|a):rPr>|<(?:w|a):rPr\s*/>", template, re.S)
    run = M.p.replace(":p", ":r")
    para = f"<{M.p}>{ppr.group(0) if ppr else ''}<{run}>{rpr.group(0) if rpr else ''}<{M.t}></{M.t}></{run}></{M.p}>"
    return _rebuild_text(M, para, text)


def _open_markup(p: Path, kind: str) -> dict:
    with zipfile.ZipFile(p) as z:
        M = W if kind == "docx" else A
        parts = []
        for name, label in (_word_parts(z) if kind == "docx" else _slide_parts(z)):
            xml = decode_text(z.read(name))[0]
            items = []
            for i, m in enumerate(_paras(M, xml)):
                items.append({"i": i, "text": _para_text(M, m.group(0))})
            if any(it["text"].strip() for it in items) or label in ("Body",):
                parts.append({"name": name, "label": label, "items": items})
    return {"kind": kind, "parts": parts}


def _save_markup(p: Path, dst: Path, kind: str, edits: list[dict]) -> int:
    M = W if kind == "docx" else A
    by = {e["name"]: e["items"] for e in edits}
    changed = 0

    def fn(name, data):
        nonlocal changed
        if name not in by:
            return None
        xml, enc = decode_text(data)
        ms = _paras(M, xml)
        items = by[name]
        keep = {int(it["i"]): it for it in items if int(it["i"]) >= 0}
        out, pos, last_template = [], 0, None
        # new paragraphs are inserted after the previous kept one: walk the item list in order
        new_after: dict[int, list[str]] = {}
        prev = -1
        for it in items:
            i = int(it["i"])
            if i >= 0:
                prev = i
            else:
                new_after.setdefault(prev, []).append(str(it.get("text", "")))
        for idx, m in enumerate(ms):
            out.append(xml[pos:m.start()])
            para = m.group(0)
            if idx in keep:
                new_text = str(keep[idx].get("text", ""))
                if new_text != _para_text(M, para):
                    para = _rebuild_text(M, para, new_text); changed += 1
                out.append(para)
            else:
                changed += 1                      # deleted
            for t in new_after.get(idx, []):
                out.append(_new_para(M, para, t)); changed += 1
            pos = m.end()
        out.append(xml[pos:])
        if -1 in new_after and ms:                # new paragraphs before the first one
            first = ms[0]
            head = "".join(_new_para(M, first.group(0), t) for t in new_after[-1])
            joined = "".join(out)
            at = joined.find(first.group(0)) if first.group(0) in joined else -1
            if at >= 0:
                joined = joined[:at] + head + joined[at:]
                out = [joined]
        res = "".join(out)
        if kind == "docx":                        # a table cell must keep at least one paragraph
            res = re.sub(r"(<w:tc(?:\s[^>]*)?>(?:(?!<w:p[\s/>]|</w:tc>).)*?)</w:tc>", lambda mm: mm.group(1) + "<w:p/></w:tc>" if "<w:p" not in mm.group(0) else mm.group(0), res, flags=re.S)
        return encode_text(res, enc)
    _rewrite_zip(p, dst, fn)
    return changed


# ---- OpenDocument text
_ODP = re.compile(r"<(text:p|text:h)(?:\s[^>]*)?(?<!/)>.*?</\1>|<text:p\s*/>", re.S)


def _odf_text(para: str) -> str:
    inner = re.sub(r"^<[^>]*>|</[^>]*>$", "", para, count=1) if para.startswith("<") else para
    inner = re.sub(r"</?text:[^>]*>$", "", inner)
    inner = re.sub(r"<text:s(?:\s+text:c=\"(\d+)\")?\s*/>", lambda m: " " * int(m.group(1) or 1), inner)
    inner = re.sub(r"<text:tab\s*/>", "\t", inner)
    inner = re.sub(r"<text:line-break\s*/>", "\n", inner)
    inner = re.sub(r"<[^>]+>", "", inner)
    return html.unescape(inner)


def _odf_rebuild(para: str, text: str) -> str:
    m = re.match(r"(<(?:text:p|text:h)(?:\s[^>]*)?>)(.*)(</(?:text:p|text:h)>)$", para, re.S)
    if not m:
        return f"<text:p>{_odf_inner(text)}</text:p>"
    return m.group(1) + _odf_inner(text) + m.group(3)


def _odf_inner(text: str) -> str:
    s = _esc(text)
    s = s.replace("\t", "<text:tab/>").replace("\n", "<text:line-break/>")
    s = re.sub(r"(?<= ) ", "<text:s/>", s)
    return s


def _open_odf(p: Path) -> dict:
    with zipfile.ZipFile(p) as z:
        xml = decode_text(z.read("content.xml"))[0]
    items = [{"i": i, "text": _odf_text(m.group(0))} for i, m in enumerate(_ODP.finditer(xml))]
    return {"kind": "odf", "parts": [{"name": "content.xml", "label": "Document", "items": items}]}


def _save_odf(p: Path, dst: Path, edits: list[dict]) -> int:
    items = edits[0]["items"] if edits else []
    changed = 0

    def fn(name, data):
        nonlocal changed
        if name != "content.xml":
            return None
        xml, enc = decode_text(data)
        ms = list(_ODP.finditer(xml))
        keep = {int(it["i"]): it for it in items if int(it["i"]) >= 0}
        new_after: dict[int, list[str]] = {}
        prev = -1
        for it in items:
            if int(it["i"]) >= 0:
                prev = int(it["i"])
            else:
                new_after.setdefault(prev, []).append(str(it.get("text", "")))
        out, pos = [], 0
        for idx, m in enumerate(ms):
            out.append(xml[pos:m.start()])
            para = m.group(0)
            if idx in keep:
                t = str(keep[idx].get("text", ""))
                if t != _odf_text(para):
                    para = _odf_rebuild(para, t); changed += 1
                out.append(para)
            else:
                changed += 1
            for t in new_after.get(idx, []):
                out.append(_odf_rebuild(para, t)); changed += 1
            pos = m.end()
        out.append(xml[pos:])
        return encode_text("".join(out), enc)
    _rewrite_zip(p, dst, fn)
    return changed


# ================================================================== spreadsheets
_WB: dict = {}


def _wb(path: Path):
    import openpyxl
    key = (str(path), path.stat().st_mtime)
    if key not in _WB:
        if len(_WB) > 2:
            _WB.clear()
        _WB[key] = openpyxl.load_workbook(path, keep_vba=path.suffix.lower() in (".xlsm", ".xltm"))
    return _WB[key]


def sheet_info(path: str) -> dict:
    p = Path(path)
    wb = _wb(p)
    return {"sheets": [{"name": ws.title, "rows": ws.max_row, "cols": ws.max_column} for ws in wb.worksheets]}


def sheet_cells(path: str, sheet: str, r0: int, c0: int, rows: int = 100, cols: int = 26) -> dict:
    from openpyxl.utils import get_column_letter
    wb = _wb(Path(path))
    ws = wb[sheet]
    rows, cols = min(rows, 300), min(cols, 60)
    data = []
    for r in range(r0, min(r0 + rows, ws.max_row + 1)):
        row = []
        for c in range(c0, min(c0 + cols, ws.max_column + 1)):
            v = ws.cell(r, c).value
            row.append("" if v is None else str(v))
        data.append(row)
    return {"r0": r0, "c0": c0, "rows": data, "cols": [get_column_letter(c) for c in range(c0, min(c0 + cols, ws.max_column + 1))], "max_row": ws.max_row, "max_col": ws.max_column}


def _coerce(v: str):
    s = v.strip()
    if s == "":
        return None
    if s.startswith("="):
        return s
    if re.fullmatch(r"[-+]?\d+", s) and len(s.lstrip("+-")) < 16:
        return int(s)
    if re.fullmatch(r"[-+]?\d*\.\d+([eE][-+]?\d+)?|[-+]?\d+[eE][-+]?\d+", s):
        return float(s)
    return v


def _save_xlsx(p: Path, dst: Path, edits: dict) -> int:
    import openpyxl
    wb = openpyxl.load_workbook(p, keep_vba=p.suffix.lower() in (".xlsm", ".xltm"))
    n = 0
    for sheet, cells in edits.items():
        ws = wb[sheet]
        for ref, val in cells.items():
            ws[ref].value = _coerce(str(val)); n += 1
    wb.save(dst)
    return n


# ================================================================== SQLite
def db_tables(path: str) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        out = []
        for (name,) in con.execute("select name from sqlite_master where type in ('table','view') and name not like 'sqlite_%' order by name"):
            cols = [r[1] for r in con.execute(f'pragma table_info("{name}")')]
            n = con.execute(f'select count(*) from "{name}"').fetchone()[0]
            out.append({"name": name, "columns": cols, "rows": n})
        return {"tables": out}
    finally:
        con.close()


def db_rows(path: str, table: str, offset: int = 0, limit: int = 100) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if not re.fullmatch(r"[^\"]+", table):
            raise UserError("Bad table name.")
        cols = [r[1] for r in con.execute(f'pragma table_info("{table}")')]
        has_rowid = True
        try:
            cur = con.execute(f'select rowid, * from "{table}" limit ? offset ?', (limit, offset))
        except sqlite3.OperationalError:
            has_rowid = False
            cur = con.execute(f'select * from "{table}" limit ? offset ?', (limit, offset))
        rows = []
        for r in cur.fetchall():
            if has_rowid:
                rows.append({"rowid": r[0], "values": ["" if v is None else (f"<{len(v)} bytes>" if isinstance(v, bytes) else str(v)) for v in r[1:]], "null": [v is None for v in r[1:]], "blob": [isinstance(v, bytes) for v in r[1:]]})
            else:
                rows.append({"rowid": None, "values": ["" if v is None else str(v) for v in r], "null": [v is None for v in r], "blob": [False] * len(r)})
        return {"columns": cols, "rows": rows, "has_rowid": has_rowid}
    finally:
        con.close()


def _save_db(p: Path, dst: Path, edits: dict) -> int:
    shutil.copyfile(p, dst)
    con = sqlite3.connect(dst)
    n = 0
    try:
        for table, spec in edits.items():
            types = {r[1]: (r[2] or "").upper() for r in con.execute(f'pragma table_info("{table}")')}
            for rid, cols in (spec.get("cells") or {}).items():
                for col, val in cols.items():
                    if col not in types:
                        continue
                    t = types[col]
                    v: object = val
                    if val is None:
                        v = None
                    elif "INT" in t and re.fullmatch(r"[-+]?\d+", str(val).strip()):
                        v = int(val)
                    elif any(x in t for x in ("REAL", "FLOA", "DOUB", "NUM", "DEC")) and re.fullmatch(r"[-+]?\d*\.?\d+([eE][-+]?\d+)?", str(val).strip()):
                        v = float(val)
                    con.execute(f'update "{table}" set "{col}" = ? where rowid = ?', (v, int(rid))); n += 1
            for rid in spec.get("delete") or []:
                con.execute(f'delete from "{table}" where rowid = ?', (int(rid),)); n += 1
        con.commit()
    finally:
        con.close()
    return n


# ================================================================== PDF
def _fitz():
    try:
        import fitz  # type: ignore
        return fitz
    except ImportError:
        raise UserError("Editing PDF text needs PyMuPDF (installed by Fathom's setup).")


def pdf_open(path: str) -> dict:
    fitz = _fitz()
    doc = fitz.open(path)
    if doc.needs_pass:
        raise UserError("This PDF is locked with a password. Remove the password first (Protect > PDF password).")
    pages = []
    for pno, page in enumerate(doc):
        spans = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for sp in line.get("spans", []):
                    spans.append({"i": len(spans), "text": sp["text"]})
        pages.append({"page": pno + 1, "spans": spans, "w": page.rect.width, "h": page.rect.height})
        if pno >= 400:
            break
    return {"kind": "pdf", "pages": pages, "total": len(doc)}


def _pdf_save(p: Path, dst: Path, edits: list[dict]) -> int:
    fitz = _fitz()
    doc = fitz.open(p)
    n = 0
    base14 = lambda flags, name: ("cour" if (flags & 8 or "mono" in name.lower() or "courier" in name.lower()) else "tiro" if (flags & 2 or ("serif" in name.lower() and "sans" not in name.lower()) or "times" in name.lower()) else "helv")
    by_page: dict[int, dict[int, str]] = {}
    for e in edits:
        by_page.setdefault(int(e["page"]) - 1, {})[int(e["i"])] = str(e["text"])
    for pno, changes in by_page.items():
        page = doc[pno]
        spans = [sp for b in page.get_text("dict")["blocks"] for ln in b.get("lines", []) for sp in ln.get("spans", [])]
        todo = [(spans[i], t) for i, t in changes.items() if i < len(spans) and spans[i]["text"] != t]
        for sp, _t in todo:
            page.add_redact_annot(fitz.Rect(sp["bbox"]), fill=False)
        if todo:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        for sp, t in todo:
            n += 1
            if not t:
                continue
            size, font = sp["size"], base14(sp.get("flags", 0), sp.get("font", ""))
            c = sp.get("color", 0)
            rgb = ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)
            width = fitz.Rect(sp["bbox"]).width
            try:
                need = fitz.get_text_length(t, fontname=font, fontsize=size)
                if need > width * 1.3 and need > 0:
                    size = max(size * 0.6, size * width * 1.3 / need)
            except Exception:
                pass
            page.insert_text(fitz.Point(sp["origin"][0], sp["origin"][1]), t, fontname=font, fontsize=size, color=rgb)
    doc.save(dst, garbage=3, deflate=True)
    return n


# ================================================================== open / save entry points
def open_file(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise UserError("That file was not found.")
    kind = kind_of(p)
    base = {"path": str(p), "name": p.name, "size": file_bytes(p)}
    if kind == "text":
        if base["size"] > MAX_TEXT:
            return {**base, "kind": "binary", "note": "This file is too big for the text editor (over 25 MB). Use Find & replace or the Hex view."}
        text, enc = decode_text(p.read_bytes())
        crlf = text.count("\r\n")
        newline = "crlf" if crlf and crlf >= text.count("\n") / 2 else "lf"
        return {**base, "kind": "text", "text": text.replace("\r\n", "\n"), "encoding": enc, "newline": newline}
    if kind in ("docx", "pptx"):
        return {**base, **_open_markup(p, kind)}
    if kind == "odf":
        return {**base, **_open_odf(p)}
    if kind == "xlsx":
        try:
            return {**base, "kind": "xlsx", **sheet_info(str(p))}
        except ImportError:
            raise UserError("Editing Excel files needs 'openpyxl' (installed by Fathom's setup).")
    if kind == "sqlite":
        return {**base, "kind": "sqlite", **db_tables(str(p))}
    if kind == "pdf":
        return {**base, **pdf_open(str(p))}
    if kind == "image":
        return {**base, "kind": "image", "ext": p.suffix.lower()}
    return {**base, "kind": "binary", "note": "This kind of file has no readable content to edit here. Open it in the Hex view to change its bytes."}


def _target(p: Path, output: dict, replace: bool, suffix: str, work: Path) -> tuple[Path, bool]:
    """(final path, replaced original?)"""
    if replace:
        return p, True
    pol = OutputPolicy.from_dict(output)
    base = pol.target_dir(p, Path("."))
    base.mkdir(parents=True, exist_ok=True)
    return unique_path(base / (p.stem + "_edited" + (suffix or p.suffix))), False


def save(path: str, kind: str, payload: dict, output: dict, replace: bool) -> dict:
    p = Path(path)
    if not p.is_file():
        raise UserError("That file was not found.")
    from app.paths import temp_dir
    import uuid
    work = temp_dir() / ("edit_" + uuid.uuid4().hex[:8])
    work.mkdir(parents=True, exist_ok=True)
    tmp = work / p.name
    suffix = p.suffix
    notes: list = []
    try:
        changed = 0
        if kind == "text":
            enc = str(payload.get("encoding") or "utf-8")
            text = str(payload.get("text", ""))
            if payload.get("newline") == "crlf":
                text = text.replace("\r\n", "\n").replace("\n", "\r\n")
            tmp.write_bytes(encode_text(text, enc)); changed = 1
        elif kind in ("docx", "pptx"):
            changed = _save_markup(p, tmp, kind, payload.get("parts", []))
        elif kind == "odf":
            changed = _save_odf(p, tmp, payload.get("parts", []))
        elif kind == "xlsx":
            changed = _save_xlsx(p, tmp, payload.get("cells", {}))
        elif kind == "sqlite":
            changed = _save_db(p, tmp, payload.get("tables", {}))
        elif kind == "pdf":
            changed = _pdf_save(p, tmp, payload.get("edits", []))
        elif kind == "pdfobj":
            from app import visual
            suf = visual.save_suffix(str(p))
            if suf:                                          # a Word file edited as pages is saved as a PDF, a RAW photo as a PNG
                tmp = work / (p.stem + suf); suffix = suf
            changed = visual.save_edits(p, tmp, payload.get("pages", []))
            from app import office_native
            notes = office_native.take_notes()
        elif kind == "image":
            m = re.match(r"data:image/\w+;base64,(.*)$", str(payload.get("data", "")), re.S)
            if not m:
                raise UserError("There is no picture to save.")
            from PIL import Image
            im = Image.open(io.BytesIO(base64.b64decode(m.group(1))))
            ext = p.suffix.lower()
            exif = None
            try:
                exif = Image.open(p).info.get("exif")
            except Exception:
                pass
            if ext in (".jpg", ".jpeg"):
                white = Image.new("RGB", im.size, (255, 255, 255))
                if im.mode in ("RGBA", "LA"):
                    white.paste(im.convert("RGBA"), mask=im.convert("RGBA").getchannel("A"))
                else:
                    white.paste(im.convert("RGB"))
                kw = {"quality": 95, "subsampling": 0}
                if exif:
                    kw["exif"] = exif
                white.save(tmp, **kw)
            elif ext in (".bmp",):
                im.convert("RGB").save(tmp)
            elif ext in (".png", ".webp", ".tif", ".tiff", ".gif"):
                im.save(tmp)
            else:
                suffix = ".png"; tmp = work / (p.stem + ".png"); im.save(tmp)
            changed = 1
        else:
            raise UserError("This kind of file cannot be saved from here.")
        if not tmp.exists():
            raise UserError("Nothing was saved.")
        try:
            from app import editproof
            shots = editproof.build(p, tmp, kind, payload)
        except Exception:
            shots = []
        final, replaced = _target(p, output, replace, suffix, work)
        if replaced:
            try:
                recycle.to_recycle_bin(p)
            except Exception as e:
                raise UserError(f"Could not move the original to the Recycle Bin: {e}")
            if suffix != p.suffix:
                final = p.with_suffix(suffix)
        shutil.move(str(tmp), str(final))
        return {"path": str(final), "changed": changed, "replaced": replaced, "proof": shots, "notes": notes}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def image_bytes(path: str) -> tuple[bytes, str]:
    """the picture at full size in a format every browser draws (PNG, or the original JPEG)"""
    from PIL import Image, ImageOps
    p = Path(path)
    if not p.is_file():
        raise UserError("That file was not found.")
    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        try:
            im = Image.open(p)
            if im.size[0] * im.size[1] < 80_000_000 and p.suffix.lower() in (".png", ".webp", ".gif", ".bmp") or p.suffix.lower() in (".jpg", ".jpeg") and not im.getexif().get(274):
                ct = {"png": "image/png", "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp"}.get(p.suffix.lower()[1:], "image/jpeg")
                return p.read_bytes(), ct
        except Exception:
            pass
    from app.convert.eng_image import load_frames
    frames, _d, _f = load_frames(p, formats.detect(p), all_frames=False)
    im = ImageOps.exif_transpose(frames[0])
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), "image/png"
