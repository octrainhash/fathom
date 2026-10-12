"""Find and replace in ANY kind of file.

How each kind is handled (the original is never touched unless you ask for it to be replaced, and then it goes to the Recycle Bin):
* Word, Excel, PowerPoint (and macro / template versions): the text inside the file, even when Word split a phrase into several pieces.
* OpenDocument (odt, ods, odp ...), EPUB, HTML, XML, SVG: the visible text, not the markup around it.
* Plain text, code, CSV, JSON, settings, subtitles ... : the characters, in whatever encoding the file uses (the encoding and line endings are kept).
* PDF: the text is found, rubbed out and typed again in the same place, in a matching standard font.
* SQLite databases (db, sqlite, sqlite3): every text value in every table.
* Older office formats (doc, xls, ppt, rtf, wps ...): converted to the modern format, edited, and converted back when the converter allows.
* Pictures: the words are found with OCR, painted over and typed again (best effort).
* Anything else: optional byte-for-byte replacement for text hidden inside programs and other binary files."""
from __future__ import annotations

import codecs
import html
import io
import os
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path

from app import ops, recycle
from app.convert import formats
from app.convert.core import ConvertError, Ctx, Opts, file_bytes
from app.ops import Output, OutputPolicy, Task
from app.opsvc import expand_sources
from app.service import UserError

MAX_TEXT = 400 << 20
OOXML = {"docx", "docm", "dotx", "dotm", "xlsx", "xlsm", "xltx", "xltm", "pptx", "pptm", "potx", "potm", "ppsx", "ppsm"}
ODF = {"odt", "ods", "odp", "odg", "ott", "ots", "otp", "otg", "fodt", "fods", "fodp"}
LEGACY = {"doc": "docx", "dot": "docx", "rtf": "docx", "wpd": "docx", "wps": "docx", "sxw": "docx", "abw": "docx", "pages": "docx",
          "xls": "xlsx", "xlt": "xlsx", "sxc": "xlsx", "numbers": "xlsx", "dif": "xlsx", "slk": "xlsx",
          "ppt": "pptx", "pps": "pptx", "sxi": "pptx", "key": "pptx"}
SQLITE_EXT = {"db", "sqlite", "sqlite3", "db3", "s3db"}
MARKUP_EXT = {"html", "htm", "xhtml", "xml", "svg", "xsl", "xslt", "rss", "atom", "opf", "ncx", "plist", "fb2", "kml", "gpx", "dae", "docbook"}
HTML_INLINE = {"a", "b", "i", "u", "em", "strong", "span", "font", "sub", "sup", "small", "big", "mark", "code", "tt", "s", "strike", "del", "ins", "abbr", "cite", "q", "kbd", "samp", "var", "label", "tspan", "textpath"}
ODF_INLINE = {"text:span", "text:a", "text:meta", "text:meta-field", "text:ruby", "text:ruby-base"}
IMG_EXT = {"png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp", "gif"}


# ================================================================== the matcher
class Replacer:
    """Several find/replace pairs applied in order. Works on a list of 'runs' (pieces of one paragraph) so a phrase that a program split into
    several pieces is still found, and the formatting of the first piece is kept."""

    def __init__(self, pairs: list[dict], regex: bool = False, case: bool = False, whole: bool = False, keep_case: bool = False, redact: bool = False):
        self.items: list[tuple[re.Pattern, str]] = []
        self.raw: list[tuple[str, str]] = []
        self.regex, self.keep_case, self.redact = regex, keep_case, redact
        self.pages = ""                 # PDF pages to work on ("" = every page; see pagesel)
        flags = 0 if case else re.IGNORECASE
        for p in pairs:
            f = str(p.get("find", ""))
            if f == "":
                continue
            if redact:
                p = dict(p, replace="")
            try:
                body = f if regex else re.escape(f)
                if whole:
                    body = rf"(?<!\w)(?:{body})(?!\w)"
                self.items.append((re.compile(body, flags | (re.MULTILINE if regex else 0)), str(p.get("replace", ""))))
                self.raw.append((f, str(p.get("replace", ""))))
            except re.error as e:
                raise UserError(f"'{f}' is not a valid pattern: {e}")
        if not self.items:
            raise UserError("Type what to find (and what to replace it with).")
        self.count = 0
        self.samples: list[dict] = []
        self.sample_limit = 0
        self.events: list[dict] | None = None     # when a list: every changed piece of text with before/after (for the proof pictures)
        self.event_limit = 12
        self.pdf_hits: dict[int, list[tuple]] = {}
        self.img_hits: list[tuple] = []
        self.bin_hits: list[tuple[int, int]] = []

    def _new(self, m: re.Match, repl: str) -> str:
        if self.redact:
            return "\u2588" * len(m.group(0))
        r = m.expand(repl) if self.regex else repl
        if self.keep_case and len(m.group(0)) > 1:
            g = m.group(0)
            if g.isupper():
                r = r.upper()
            elif g[0].isupper() and g[1:].islower():
                r = r[:1].upper() + r[1:]
            elif g.islower():
                r = r.lower()
        return r

    def apply(self, runs: list[str], where: str = "") -> list[str]:
        runs = list(runs)
        for pat, repl in self.items:
            text = "".join(runs)
            ms = [m for m in pat.finditer(text) if m.end() > m.start()]
            if not ms:
                continue
            starts, pos = [], 0
            for r in runs:
                starts.append(pos); pos += len(r)
            news = [self._new(m, repl) for m in ms]
            if self.events is not None and len(self.events) < self.event_limit and len(text) < 5_000_000:
                out_t, pos, delta, bsp, asp = [], 0, 0, [], []
                for m, nw in zip(ms, news):
                    out_t.append(text[pos:m.start()])
                    asp.append((m.start() + delta, m.start() + delta + len(nw)))
                    bsp.append((m.start(), m.end()))
                    out_t.append(nw)
                    delta += len(nw) - (m.end() - m.start())
                    pos = m.end()
                out_t.append(text[pos:])
                self.events.append({"where": where, "before": text, "bspans": bsp, "after": "".join(out_t), "aspans": asp})
            for m, new in reversed(list(zip(ms, news))):
                s, e = m.span()
                self.count += 1
                if len(self.samples) < self.sample_limit:
                    self.samples.append({"before": text[max(0, s - 28):s], "match": m.group(0), "after": text[e:e + 28], "to": new, "where": where})
                i = next((k for k in range(len(runs)) if starts[k] <= s < starts[k] + len(runs[k])), None)
                j = next((k for k in range(len(runs)) if starts[k] < e <= starts[k] + len(runs[k])), None)
                if i is None or j is None:
                    continue
                if i == j:
                    runs[i] = runs[i][:s - starts[i]] + new + runs[i][e - starts[i]:]
                else:
                    runs[i] = runs[i][:s - starts[i]] + new
                    for k in range(i + 1, j):
                        runs[k] = ""
                    runs[j] = runs[j][e - starts[j]:]
        return runs

    def apply_text(self, text: str, where: str = "") -> str:
        return self.apply([text], where)[0]


# ================================================================== text files
def decode_text(b: bytes) -> tuple[str, str]:
    """(text, encoding) - the encoding name is what to use to write it back the same way."""
    if b.startswith(codecs.BOM_UTF8):
        return b[3:].decode("utf-8", "replace"), "utf-8-sig"
    if b.startswith(codecs.BOM_UTF32_LE) or b.startswith(codecs.BOM_UTF32_BE):
        return b.decode("utf-32", "replace"), "utf-32"
    if b.startswith(codecs.BOM_UTF16_LE) or b.startswith(codecs.BOM_UTF16_BE):
        return b.decode("utf-16", "replace"), "utf-16"
    try:
        return b.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes  # type: ignore
        best = from_bytes(b).best()
        enc = (best.encoding or "").lower().replace("-", "_") if best is not None else ""
        # only trust encodings people really use; the detector's exotic guesses on short texts are usually wrong
        if enc and (enc.startswith(("cp125", "iso8859", "mac_", "utf_16", "utf_32", "koi8", "big5", "gb", "shift_jis", "euc_", "cp9", "johab", "hz", "iso2022")) or enc in ("ascii",)):
            return str(best), best.encoding
    except Exception:
        pass
    return b.decode("cp1252", "replace"), "cp1252"


def encode_text(t: str, enc: str) -> bytes:
    try:
        return t.encode(enc)
    except UnicodeEncodeError:
        return t.replace("\u2588", "#").encode(enc, errors="xmlcharrefreplace")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ================================================================== OOXML: Word / Excel / PowerPoint
_RUN = re.compile(r"(<(?:w:t|a:t|m:t|t)(?:\s[^>]*)?>)([^<]*)(</(?:w:t|a:t|m:t|t)>)")
_BOUND = re.compile(r"</w:p>|</a:p>|</si>|</is>|</m:oMath>|<w:br\b[^>]*/>|<w:tab\b[^>]*/>|<w:cr\b[^>]*/>|<a:br\b[^>]*/>|</w:tc>|</a:tc>|</c>|</row>")
_TOKENS = re.compile(_RUN.pattern + "|" + _BOUND.pattern)
_SKIP_PARTS = re.compile(r"(_rels/|\.rels$|theme|styles|settings|numbering|fontTable|webSettings|printerSettings|\[Content_Types\]|vmlDrawing|calcChain|customXml|docProps/(app|custom))", re.I)


def _ooxml_part(name: str) -> bool:
    return name.endswith(".xml") and name.split("/")[0] in ("word", "xl", "ppt") and not _SKIP_PARTS.search(name)


def edit_ooxml_xml(xml: str, R: Replacer, part: str = "") -> str:
    edits: list[tuple[int, int, str]] = []
    group: list[tuple[re.Match, str]] = []

    def flush():
        nonlocal group
        if group:
            old = [t for _m, t in group]
            new = R.apply(old, part)
            for (m, o), n in zip(group, new):
                if n != o:
                    open_tag = m.group(1)
                    if (n != n.strip() or "\n" in n) and "xml:space" not in open_tag:
                        open_tag = open_tag[:-1] + ' xml:space="preserve">'
                    edits.append((m.start(), m.end(), open_tag + _esc(n) + m.group(3)))
        group = []

    for m in _TOKENS.finditer(xml):
        if m.group(1) is not None:
            group.append((m, html.unescape(m.group(2))))
        else:
            flush()
    flush()
    for s, e, rep in reversed(edits):
        xml = xml[:s] + rep + xml[e:]
    return xml


# ================================================================== HTML / XML / ODF text nodes
_MTOK = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<[^>]+>|[^<]+", re.S)


def edit_markup(doc: str, R: Replacer, inline: set[str], skip_inside: tuple[str, ...] = ("script", "style"), where: str = "") -> str:
    toks = _MTOK.findall(doc)
    out = list(toks)
    group: list[int] = []
    skipping = None

    def flush():
        nonlocal group
        if group:
            decoded = [html.unescape(toks[i]) for i in group]
            new = R.apply(decoded, where)
            for i, o, n in zip(group, decoded, new):
                if n != o:
                    out[i] = _esc(n)
        group = []

    for i, t in enumerate(toks):
        if t.startswith("<"):
            m = re.match(r"</?\s*([\w:.-]+)", t)
            name = m.group(1).lower() if m else ""
            closing = t.startswith("</")
            if skipping:
                if closing and name == skipping:
                    skipping = None
                flush()
                continue
            if name in skip_inside and not closing and not t.endswith("/>"):
                skipping = name
                flush()
                continue
            if name in inline and not t.startswith("<!"):
                continue
            flush()
        else:
            if skipping:
                continue
            if t.strip():
                group.append(i)
            elif group:
                group.append(i)               # whitespace between inline tags stays part of the phrase
    flush()
    return "".join(out)


def _decode_xml_bytes(b: bytes) -> tuple[str, str]:
    text, enc = decode_text(b)
    return text, enc


# ================================================================== zip containers
def _rewrite_zip(src: Path, dst: Path, fn) -> int:
    """Copies a zip, passing each entry through fn(name, bytes) -> bytes | None (None = unchanged)."""
    changed = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            new = fn(info.filename, data) if not info.is_dir() else None
            zi = zipfile.ZipInfo(info.filename, info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zi.comment = info.comment
            zi.extra = info.extra
            zout.writestr(zi, new if new is not None else data)
            if new is not None and new != data:
                changed += 1
    return changed


def edit_ooxml(src: Path, dst: Path, R: Replacer) -> None:
    def fn(name, data):
        if not _ooxml_part(name):
            return None
        text, enc = _decode_xml_bytes(data)
        new = edit_ooxml_xml(text, R, name)
        return None if new == text else encode_text(new, enc)
    _rewrite_zip(src, dst, fn)


def edit_odf(src: Path, dst: Path, R: Replacer) -> None:
    def fn(name, data):
        if name not in ("content.xml", "styles.xml"):
            return None
        text, enc = _decode_xml_bytes(data)
        new = edit_markup(text, R, ODF_INLINE, skip_inside=(), where=name)
        return None if new == text else encode_text(new, enc)
    _rewrite_zip(src, dst, fn)


def edit_epub(src: Path, dst: Path, R: Replacer) -> None:
    def fn(name, data):
        if not name.lower().endswith((".xhtml", ".html", ".htm", ".xml", ".ncx", ".opf", ".svg")) or name == "mimetype":
            return None
        text, enc = _decode_xml_bytes(data)
        new = edit_markup(text, R, HTML_INLINE, where=name)
        return None if new == text else encode_text(new, enc)
    _rewrite_zip(src, dst, fn)


# ================================================================== PDF
def edit_pdf(src: Path, dst: Path, R: Replacer, ctx: Ctx) -> None:
    try:
        import fitz  # type: ignore
    except ImportError:
        raise ConvertError("PDF editing needs PyMuPDF (it is installed by Fathom's setup).")
    doc = fitz.open(src)
    if doc.needs_pass:
        raise ConvertError("This PDF is locked with a password. Remove the password first (Protect → PDF password).")
    base14 = lambda flags, name: ("cour" if (flags & 8 or "mono" in name.lower() or "courier" in name.lower()) else "tiro" if (flags & 2 or "serif" in name.lower() and "sans" not in name.lower() or "times" in name.lower()) else "helv")
    from app import pagesel
    chosen = set(pagesel.need(R.pages, len(doc)))
    for pno, page in enumerate(doc):
        ctx.check(); ctx.progress(pno / max(1, len(doc)))
        if pno not in chosen:
            continue
        todo = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                texts = [s["text"] for s in spans]
                new = R.apply(texts, f"page {pno + 1}")
                for sp, o, n in zip(spans, texts, new):
                    if n != o:
                        todo.append((sp, o, n))
        if R.redact:
            hit = False
            for sp, o, n in todo:
                for pat, _r in R.items:
                    for m in pat.finditer(o):
                        for rect in page.search_for(m.group(0), clip=fitz.Rect(sp["bbox"]) + (-1, -1, 1, 1)) or [fitz.Rect(sp["bbox"])]:
                            page.add_redact_annot(rect, fill=(0, 0, 0)); hit = True
                            R.pdf_hits.setdefault(pno, []).append(tuple(rect))
            if hit:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            todo = []                                  # redaction leaves a black box and no text at all
        else:
            for sp, o, n in todo:
                page.add_redact_annot(fitz.Rect(sp["bbox"]), fill=False)
                R.pdf_hits.setdefault(pno, []).append(tuple(sp["bbox"]))
            if todo:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        for sp, o, n in todo:
            size = sp["size"]
            font = base14(sp.get("flags", 0), sp.get("font", ""))
            color = sp.get("color", 0)
            rgb = ((color >> 16 & 255) / 255, (color >> 8 & 255) / 255, (color & 255) / 255)
            width = fitz.Rect(sp["bbox"]).width
            try:
                need = fitz.get_text_length(n, fontname=font, fontsize=size)
                if need > width * 1.08 and need > 0:
                    size = max(size * 0.7, size * width * 1.08 / need)
            except Exception:
                pass
            page.insert_text(fitz.Point(sp["origin"][0], sp["origin"][1]), n, fontname=font, fontsize=size, color=rgb)
    doc.save(dst, garbage=3, deflate=True)
    doc.close()


# ================================================================== SQLite
def edit_sqlite(src: Path, dst: Path, R: Replacer) -> None:
    shutil.copyfile(src, dst)
    con = sqlite3.connect(dst)
    try:
        con.create_function("fx_replace", 1, lambda v: R.apply_text(v) if isinstance(v, str) else v)
        tables = [r[0] for r in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' and sql not like 'CREATE VIRTUAL%'")]
        for t in tables:
            cols = [r[1] for r in con.execute(f'pragma table_info("{t}")') if not r[1].startswith("sqlite_")]
            for c in cols:
                con.execute(f'update "{t}" set "{c}" = fx_replace("{c}") where typeof("{c}") = \'text\'')
        con.commit()
    finally:
        con.close()


# ================================================================== pictures (OCR)
def edit_image(src: Path, dst: Path, R: Replacer) -> None:
    from PIL import Image, ImageDraw, ImageFont
    from app import ocr
    im = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(im)
    boxes = ocr.ocr_boxes(im)
    for b in boxes:
        text = b.get("text", "")
        new = R.apply_text(text, "picture")
        if new == text:
            continue
        x0, y0, x1, y1 = [int(v) for v in b["bbox"]]
        R.img_hits.append((x0, y0, x1, y1))
        edge = [im.getpixel((min(im.width - 1, max(0, x0 - 1)), min(im.height - 1, max(0, y0 + (y1 - y0) // 2)))), im.getpixel((min(im.width - 1, x1 + 1), min(im.height - 1, max(0, y0 + (y1 - y0) // 2))))]
        bg = tuple(sum(c[i] for c in edge) // 2 for i in range(3))
        fg = (0, 0, 0) if sum(bg) > 380 else (255, 255, 255)
        if R.redact:
            draw.rectangle((x0, y0, x1, y1), fill=(0, 0, 0))
            continue
        draw.rectangle((x0, y0, x1, y1), fill=bg)
        h = max(8, y1 - y0)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", int(h * 0.8))
        except OSError:
            font = ImageFont.load_default()
        draw.text((x0, y0), new, fill=fg, font=font)
    im.save(dst)


# ================================================================== binary
def edit_binary(src: Path, dst: Path, R: Replacer) -> int:
    """Same-length byte replacement (a shorter replacement is padded with NUL). Longer ones are skipped so the file stays valid."""
    data = bytearray(src.read_bytes())
    n = 0
    for find, repl in R.raw:
        if R.regex:
            continue
        for enc in ("utf-8", "utf-16-le"):
            try:
                needle, rep = find.encode(enc), repl.encode(enc)
            except UnicodeError:
                continue
            if not needle or len(rep) > len(needle):
                continue
            rep = rep + b"\x00" * (len(needle) - len(rep))
            i = data.find(needle)
            while i != -1:
                data[i:i + len(needle)] = rep
                R.bin_hits.append((i, len(needle)))
                n += 1
                i = data.find(needle, i + len(needle))
    R.count += n
    dst.write_bytes(bytes(data))
    return n


# ================================================================== the job
def _kind(p: Path, binary: bool) -> str:
    ext = formats.ext_of(p)
    fmt = formats.detect(p)
    if fmt in OOXML or ext in OOXML:
        return "ooxml"
    if fmt in ODF or ext in ODF:
        return "odf"
    if fmt == "epub" or ext == "epub":
        return "epub"
    if fmt == "pdf" or ext == "pdf":
        return "pdf"
    if ext in SQLITE_EXT:
        try:
            with open(p, "rb") as f:
                if f.read(16) == b"SQLite format 3\x00":
                    return "sqlite"
        except OSError:
            pass
    if ext in IMG_EXT or fmt in ("png", "jpg", "bmp", "tif", "webp", "gif"):
        return "image"
    if ext in LEGACY or fmt in LEGACY:
        return "legacy"
    if ext in MARKUP_EXT or fmt in ("html", "xml", "svg"):
        return "markup"
    if fmt in ("txt", "md", "csv", "tsv", "json", "jsonl", "yaml", "toml", "sql", "ini", "ipynb", "rst", "tex", "org", "textile", "wiki", "asciidoc", "srt", "vtt", "ass", "ssa", "sub", "docbook", "stl", "obj", "off", "ply", "dae", "gltf"):
        return "text"
    return "binary" if binary else "skip"


def replace_start(paths: list[str], recursive: bool, pairs: list[dict], opts: dict, output: dict, dry: bool = False) -> dict:
    """opts: regex, case, whole, keep_case, binary, raw_markup (also change tags), inplace (original to Recycle Bin), legacy (use converters)."""
    R0 = Replacer(pairs, bool(opts.get("regex")), bool(opts.get("case")), bool(opts.get("whole")), bool(opts.get("keep_case")), bool(opts.get("redact")))
    del R0
    pol = OutputPolicy.from_dict(output)
    inplace = bool(opts.get("inplace")) and not dry
    files = expand_sources(paths, recursive, skip_junk=False)
    if not files:
        raise UserError("Add the files to edit.")
    binary, raw_markup, use_legacy = bool(opts.get("binary")), bool(opts.get("raw_markup")), opts.get("legacy", True)

    def make(src: Path, rel: Path):
        def fn(ctx: Ctx, task: Task) -> Output:
            R = Replacer(pairs, bool(opts.get("regex")), bool(opts.get("case")), bool(opts.get("whole")), bool(opts.get("keep_case")), bool(opts.get("redact")))
            R.sample_limit = 6 if dry else 0
            R.pages = str(opts.get("pages") or "")
            R.events = []
            kind = _kind(src, binary)
            if kind == "skip":
                return Output([], "This kind of file has no text Fathom can edit (turn on 'binary files' to try anyway).", skipped=True)
            if file_bytes(src) > MAX_TEXT and kind in ("text", "markup"):
                return Output([], "Too big to edit as text (over 400 MB).", skipped=True)
            d = ctx.scratch_dir()
            dst = d / (src.stem + "_edited" + src.suffix)
            note_extra = ""
            if kind == "text":
                text, enc = decode_text(src.read_bytes())
                new = R.apply_text(text, src.name)
                if R.count:
                    dst.write_bytes(encode_text(new, enc))
            elif kind == "markup":
                text, enc = decode_text(src.read_bytes())
                new = R.apply_text(text) if raw_markup else edit_markup(text, R, HTML_INLINE if formats.ext_of(src) in ("html", "htm", "xhtml", "svg") else set(), where=src.name)
                if R.count:
                    dst.write_bytes(encode_text(new, enc))
            elif kind == "ooxml":
                edit_ooxml(src, dst, R)
            elif kind == "odf":
                edit_odf(src, dst, R)
            elif kind == "epub":
                edit_epub(src, dst, R)
            elif kind == "pdf":
                if dry:
                    _pdf_count(src, R)
                else:
                    edit_pdf(src, dst, R, ctx)
            elif kind == "sqlite":
                edit_sqlite(src, dst, R)
            elif kind == "image":
                edit_image(src, dst, R)
            elif kind == "binary":
                edit_binary(src, dst, R)
            elif kind == "legacy":
                if not use_legacy:
                    return Output([], "Older Office files are skipped (the 'old Office formats' option is off).", skipped=True)
                target = LEGACY[formats.ext_of(src)] if formats.ext_of(src) in LEGACY else LEGACY.get(formats.detect(src), "docx")
                from app.convert.engines import convert_file
                mid, _n = convert_file(src, formats.detect(src), target, Opts(), ctx)
                mid_edited = d / ("mid_edited." + target)
                {"docx": edit_ooxml, "xlsx": edit_ooxml, "pptx": edit_ooxml}[target](mid[0], mid_edited, R)
                if not R.count:
                    return Output([], "No matches.", skipped=True, extra={"count": 0})
                try:
                    back, _n2 = convert_file(mid_edited, target, formats.detect(src), Opts(), ctx)
                    shutil.copyfile(back[0], dst)
                except ConvertError:
                    dst = d / (src.stem + "_edited." + target)
                    shutil.copyfile(mid_edited, dst)
                    note_extra = f" Saved as {target.upper()} because it could not be converted back to the old format."
            if not R.count:
                return Output([], "No matches.", skipped=True, extra={"count": 0})
            proofs = _proofs(ctx, src, dst if dst.exists() else None, kind, R, dry)
            if dry:
                return Output([], f"{R.count} match{'es' if R.count != 1 else ''} would be replaced.", extra={"count": R.count, "samples": R.samples, "proof": proofs})
            if not dst.exists():
                raise ConvertError("The file could not be edited.")
            if inplace:
                original = src
                try:
                    recycle.to_recycle_bin(original)
                except Exception as e:
                    raise ConvertError(f"Could not move the original to the Recycle Bin: {e}")
                final = original if dst.suffix == original.suffix else original.with_suffix(dst.suffix)
                shutil.move(str(dst), str(final))
                return Output([final], f"{R.count} replaced. The original is in the Recycle Bin." + note_extra, extra={"count": R.count, "proof": proofs})
            return Output(pol.place([dst], src, rel), f"{R.count} replaced. The original was not touched." + note_extra, extra={"count": R.count, "proof": proofs})
        return fn

    tasks = [Task(s.name, make(s, r), s, rel=r, heavy=False) for s, r in files]
    return {"job": ops.start("replace-preview" if dry else "replace", "Looking for matches" if dry else "Replacing", tasks, workers=3).id, "count": len(tasks)}


def _pdf_count(src: Path, R: Replacer) -> None:
    try:
        import fitz  # type: ignore
    except ImportError:
        raise ConvertError("PDF editing needs PyMuPDF.")
    from app import pagesel
    with fitz.open(src) as doc:
        chosen = set(pagesel.need(R.pages, len(doc)))
        for pno, page in enumerate(doc):
            if pno not in chosen:
                continue
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    before = R.count
                    texts = [s["text"] for s in line.get("spans", [])]
                    new = R.apply(texts, f"page {pno + 1}")
                    for sp, o, n in zip(line.get("spans", []), texts, new):
                        if n != o:
                            R.pdf_hits.setdefault(pno, []).append(tuple(sp["bbox"]))


def _proofs(ctx: Ctx, src: Path, dst: Path | None, kind: str, R: Replacer, dry: bool) -> list[dict]:
    """BEFORE / AFTER pictures of what changed, highlighted and circled."""
    from app import proof
    P = proof.Proofs(ctx.job.id)  # type: ignore[attr-defined]
    try:
        mode = "object" if R.redact else "text"
        if kind == "pdf" and R.pdf_hits:
            if proof.pdf_page_changes(P, src, None if dry else dst, R.pdf_hits, src.name, mode):
                return P.result()
        if kind == "image" and R.img_hits and dst is not None:
            from PIL import Image
            b, a = Image.open(src), Image.open(dst)
            proof.picture_change(P, src.name, src.name, b, R.img_hits, a, R.img_hits, mode)
            return P.result()
        if kind == "binary" and R.bin_hits and dst is not None:
            old, new = src.read_bytes(), dst.read_bytes()
            for off, ln in R.bin_hits[:proof.MAX_PER_FILE]:
                lo = max(0, off - 16) // 16 * 16
                seg_b, seg_a = old[lo:lo + 64], new[lo:lo + 64]
                changed = {i for i in range(off, off + ln)}
                tb, sb = proof.hex_rows(seg_b, lo, changed)
                ta, sa = proof.hex_rows(seg_a, lo, changed)
                proof.text_change(P, src.name + f"  ·  byte {off:,}", f"0x{off:X}", tb, ta, sb, sa)
            return P.result()
        for ev in R.events or []:
            title = src.name + ("  ·  " + ev["where"] if ev["where"] and ev["where"] != src.name else "")
            before, after = ev["before"], ev["after"]
            if R.redact:
                proof.text_change(P, title, ev["where"], before, after, ev["bspans"], ev["aspans"])
            else:
                proof.text_change(P, title, ev["where"], before, after, ev["bspans"], ev["aspans"])
    except Exception:
        pass
    return P.result()
