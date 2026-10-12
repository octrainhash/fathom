"""Open any kind of file and hand back its text (with locations) and/or pictures.

Nothing here renders pictures of text. That only happens for matches (see textsnap.py), so
huge logs, 1000-page PDFs and GB-sized binaries stay fast and light on memory."""
from __future__ import annotations

import bz2
import gzip
import io
import lzma
import re
import shutil
import tarfile
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image, ImageFile, ImageOps, ImageSequence

from app.annotate import to_rgb

Image.MAX_IMAGE_PIXELS = None
ImageFile.LOAD_TRUNCATED_IMAGES = True

try:  # iPhone photos (.heic) and .avif, if the optional package is installed
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF = True
except Exception:
    HEIF = False

IMAGE_EXT = {
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp", ".bmp", ".dib", ".tif", ".tiff", ".gif", ".ico",
    ".heic", ".heif", ".avif", ".jp2", ".ppm", ".pgm", ".pbm", ".tga", ".psd",
}
VIDEO_EXT = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v", ".mpeg", ".mpg", ".3gp", ".3g2",
    ".ogv", ".mts", ".m2ts", ".vob", ".asf", ".divx", ".f4v", ".rm", ".rmvb", ".mxf",
}
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wma", ".aiff", ".aif", ".amr"}
OFFICE_EXT = {
    ".docx", ".docm", ".dotx", ".pptx", ".pptm", ".potx", ".ppsx", ".xlsx", ".xlsm", ".xltx",
    ".odt", ".ods", ".odp", ".epub",
}
ARCHIVE_EXT = {".zip", ".cbz", ".jar", ".war", ".apk", ".tar", ".tgz", ".tbz2", ".txz", ".gz", ".bz2", ".xz"}
TEXT_EXT = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".html", ".htm", ".xhtml", ".css", ".js", ".mjs", ".ts",
    ".tsx", ".jsx", ".py", ".rs", ".go", ".java", ".c", ".cpp", ".cc", ".h", ".hpp", ".cs", ".php", ".rb", ".sh", ".bat",
    ".cmd", ".ps1", ".sql", ".log", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env", ".rtf", ".svg", ".tex",
    ".srt", ".vtt", ".ass", ".ipynb", ".vcf", ".ics", ".reg", ".m3u", ".m3u8", ".pls", ".nfo", ".mht", ".mhtml", ".dxf", ".ps", ".lua", ".kt", ".swift", ".r", ".m", ".vue", ".gradle", ".properties", ".rst",
}
# old binary Office formats, e-mail, databases and camera RAW photos (searched properly, not as raw bytes)
LEGACY_OFFICE = {".doc": "docx", ".dot": "docx", ".wpd": "docx", ".wps": "docx", ".sxw": "docx",
                 ".xls": "xlsx", ".xlt": "xlsx", ".sxc": "xlsx", ".xlsb": "xlsx",
                 ".ppt": "pptx", ".pps": "pptx", ".sxi": "pptx"}
EMAIL_EXT = {".eml", ".mbox", ".mbx"}
DB_EXT = {".sqlite", ".sqlite3", ".db", ".db3", ".s3db", ".sdb", ".sqlitedb"}
RAW_EXT = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".orf", ".rw2", ".raf", ".pef", ".srw", ".x3f", ".3fr", ".kdc", ".dcr", ".mrw", ".erf", ".mef", ".raw"}
SQLITE_MAGIC = b"SQLite format 3\x00"
IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"II*\x00", b"MM\x00*", b"BM")


def _head(path: Path, n: int = 4096) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


def _is_mpeg_ts(path: Path) -> bool:
    data = _head(path, 188 * 4 + 1)
    return len(data) > 376 and data[0] == 0x47 and data[188] == 0x47 and data[376] == 0x47


def looks_text(head: bytes) -> bool:
    if not head:
        return True
    if head.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")):
        return True
    if b"\x00" in head:
        return False
    for cut in range(4):
        try:
            head[: len(head) - cut].decode("utf-8")
            bad = sum(1 for b in head if b < 32 and b not in (9, 10, 13))
            return bad / len(head) < 0.05
        except UnicodeDecodeError:
            continue
    usable = sum(32 <= b <= 126 or b in (9, 10, 13) or b >= 160 for b in head)
    return usable / len(head) > 0.92


def classify(path: Path) -> str:
    """video | audio | image | pdf | office | archive | text | binary | empty"""
    ext = path.suffix.lower()
    try:
        if path.stat().st_size == 0:
            return "empty"
    except OSError:
        return "binary"
    if ext in VIDEO_EXT:
        return "video"
    if ext == ".ts":
        return "video" if _is_mpeg_ts(path) else "text"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in EMAIL_EXT:
        return "email"
    if ext in LEGACY_OFFICE:
        return "legacy"
    if ext in DB_EXT and _head(path, 16).startswith(SQLITE_MAGIC):
        return "database"
    if ext in RAW_EXT:
        return "raw"
    if ext in OFFICE_EXT:
        return "office"
    if ext in ARCHIVE_EXT:
        return "archive"
    if ext in TEXT_EXT:
        return "text"
    head = _head(path)
    if head.startswith(SQLITE_MAGIC):
        return "database"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(IMAGE_MAGIC[:-1]) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "video"
    if head[4:8] == b"ftyp" or head.startswith(b"\x1aE\xdf\xa3"):
        return "video"
    if head.startswith((b"ID3", b"OggS", b"fLaC")) or (head[:4] == b"RIFF" and head[8:12] == b"WAVE"):
        return "audio"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"\x1f\x8b"):
        return "archive"
    return "text" if looks_text(head) else "binary"


# ---------------------------------------------------------------- plain text, logs, code, csv, rtf ...
def detect_encoding(path: Path) -> str:
    head = _head(path, 262144)
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    for cut in range(4):
        try:
            head[: len(head) - cut].decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            continue
    return "cp1252"


_RTF_SKIP = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "themedata", "colorschememapping", "latentstyles", "datastore", "generator"}
_RTF_WORD = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?")


def rtf_to_text(raw: str) -> str:
    """Small RTF reader: keeps the text, drops formatting and font/colour tables."""
    out: list[str] = []
    i, n, depth, skip_depth = 0, len(raw), 0, None
    while i < n:
        ch = raw[i]
        if ch == "{":
            depth += 1
            i += 1
            if skip_depth is None:
                if raw.startswith("\\*", i):
                    skip_depth = depth
                else:
                    m = _RTF_WORD.match(raw, i)
                    if m and m.group(1) in _RTF_SKIP:
                        skip_depth = depth
            continue
        if ch == "}":
            if skip_depth is not None and depth == skip_depth:
                skip_depth = None
            depth -= 1
            i += 1
            continue
        if ch == "\\":
            m = _RTF_WORD.match(raw, i)
            if m:
                word, arg = m.group(1), m.group(2)
                i = m.end()
                if skip_depth is None:
                    if word in ("par", "line", "sect", "page"):
                        out.append("\n")
                    elif word == "tab":
                        out.append("\t")
                    elif word == "u" and arg:
                        out.append(chr(int(arg) % 65536))
                        if raw[i:i + 1] == "?":
                            i += 1
                continue
            if raw.startswith("\\'", i):
                try:
                    if skip_depth is None:
                        out.append(bytes([int(raw[i + 2:i + 4], 16)]).decode("cp1252", "replace"))
                except ValueError:
                    pass
                i += 4
                continue
            if i + 1 < n:
                if skip_depth is None and raw[i + 1] in "\\{}":
                    out.append(raw[i + 1])
                i += 2
                continue
        if skip_depth is None and ch not in "\r\n":
            out.append(ch)
        i += 1
    return "".join(out)


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table", "ul", "ol", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    parser = _HTMLText()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return raw
    return "".join(parser.parts)


def iter_text_lines(path: Path) -> Iterator[tuple[str, str, str]]:
    """(label, where, text) for every line of a text-like file, streamed (so GB-sized logs are fine)."""
    enc = detect_encoding(path)
    if path.suffix.lower() == ".rtf":
        with open(path, "r", encoding=enc, errors="replace") as fh:
            lines = rtf_to_text(fh.read()).splitlines()
        for i, line in enumerate(lines, 1):
            yield str(i), f"line {i}", line
        return
    with open(path, "r", encoding=enc, errors="replace", newline=None) as fh:
        for i, line in enumerate(fh, 1):
            yield str(i), f"line {i}", line.rstrip("\r\n")


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(v))} bytes>"
    return str(v).replace("\r", " ").replace("\n", " ")


def iter_sqlite(path: Path) -> Iterator[tuple[str, str, str]]:
    """Every row of every table of an SQLite database as text: 'column=value | column=value'. The file is opened read-only."""
    import sqlite3

    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for t in tables:
            q = '"' + t.replace('"', '""') + '"'
            cols = [c[1] for c in con.execute(f"PRAGMA table_info({q})")]
            yield t, f"table {t}", " | ".join(cols)
            try:
                for i, row in enumerate(con.execute(f"SELECT * FROM {q}"), 1):
                    yield f"{t}:{i}", f"table {t}, row {i}", " | ".join(f"{c}={_cell(v)}" for c, v in zip(cols, row))
            except sqlite3.Error:
                continue
    finally:
        con.close()


def iter_email(path: Path) -> Iterator[tuple[int, object]]:
    """(number, message) for every e-mail in an .eml file or an .mbox mailbox."""
    import email
    import mailbox
    from email import policy

    if path.suffix.lower() == ".eml":
        with open(path, "rb") as fh:
            yield 1, email.message_from_binary_file(fh, policy=policy.default)
        return
    box = mailbox.mbox(str(path), factory=lambda f: email.message_from_binary_file(f, policy=policy.default))
    for i, msg in enumerate(box, 1):
        yield i, msg


def email_text_lines(msg, n: int) -> Iterator[tuple[str, str, str]]:
    """The header fields and the readable body of one e-mail, line by line."""
    tag = f"message {n}"
    for h in ("From", "To", "Cc", "Bcc", "Subject", "Date"):
        try:
            v = msg.get(h)
        except Exception:
            v = None
        if v:
            yield f"{n}:{h}", f"{tag} · {h}", f"{h}: {v}"
    try:
        body = msg.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body is not None else ""
        if body is not None and body.get_content_type() == "text/html":
            text = html_to_text(text)
    except Exception:
        text = ""
    for i, line in enumerate(str(text).splitlines(), 1):
        yield f"{n}:{i}", f"{tag} · line {i}", line


def email_attachments(msg) -> Iterator[tuple[str, bytes]]:
    try:
        for part in msg.iter_attachments():
            name = part.get_filename() or "attachment"
            data = part.get_payload(decode=True)
            if data:
                yield name, data
    except Exception:
        return


_ASCII = re.compile(rb"[\x20-\x7e\t]{5,}")
_UTF16 = re.compile(rb"(?:[\x20-\x7e]\x00){5,}")


def iter_binary_strings(path: Path, chunk: int = 4 << 20) -> Iterator[tuple[str, str, str]]:
    """Like the Unix `strings` tool: readable text hiding inside any binary (exe, dll, db, doc, xls, mp3 tags...)."""
    offset = 0
    carry_a = carry_u = b""
    with open(path, "rb") as fh:
        while True:
            data = fh.read(chunk)
            final = not data
            buf_a, buf_u = carry_a + data, carry_u + data
            start_a, start_u = offset - len(carry_a), offset - len(carry_u)
            found: list[tuple[int, str]] = []
            carry_a = b""
            for m in _ASCII.finditer(buf_a):
                if m.end() == len(buf_a) and not final:
                    carry_a = buf_a[m.start():]
                    continue
                found.append((start_a + m.start(), m.group().decode("ascii", "replace")))
            carry_u = b""
            for m in _UTF16.finditer(buf_u):
                if m.end() >= len(buf_u) - 1 and not final:
                    carry_u = buf_u[m.start():]
                    continue
                found.append((start_u + m.start(), m.group().decode("utf-16-le", "replace")))
            found.sort()
            for off, text in found:
                yield f"0x{off:X}", f"offset 0x{off:X}", text
            offset += len(data)
            if final:
                break


# ---------------------------------------------------------------- pictures
def _decode_with_cv2(path: Path) -> Image.Image:
    import cv2

    arr = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise RuntimeError("This picture format could not be opened.")
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def _decode_raw(path: Path) -> Image.Image:
    """A camera RAW photo (.cr2 .nef .arw .dng ...) as a picture, through the optional rawpy package."""
    try:
        import rawpy  # type: ignore
    except ImportError:
        raise RuntimeError("Camera RAW photos need the optional 'rawpy' package (run Fathom.bat repair with internet).")
    with rawpy.imread(str(path)) as raw:
        try:
            rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=False, output_bps=8)
            return Image.fromarray(rgb)
        except Exception:
            thumb = raw.extract_thumb()                      # the small JPEG most cameras store inside
            if thumb.format == rawpy.ThumbFormat.JPEG:
                return image_from_bytes(thumb.data)
            raise


def iter_image_frames(path: Path) -> Iterator[tuple[str, Image.Image]]:
    """One (label, RGB picture) per frame (animated GIF / multi-page TIFF give several)."""
    if path.suffix.lower() in RAW_EXT:
        yield "", to_rgb(ImageOps.exif_transpose(_decode_raw(path)))
        return
    try:
        im = Image.open(path)
    except Exception:
        yield "", _decode_with_cv2(path)
        return
    with im:
        if getattr(im, "n_frames", 1) > 1:
            for i, frame in enumerate(ImageSequence.Iterator(im), 1):
                yield f"frame {i}", to_rgb(ImageOps.exif_transpose(frame.copy()))
        else:
            im.load()
            yield "", to_rgb(ImageOps.exif_transpose(im))


def image_from_bytes(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        return to_rgb(ImageOps.exif_transpose(im))


# ---------------------------------------------------------------- Word / PowerPoint / Excel / OpenDocument / EPUB
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TABLE_NS = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"


def _strip_fallback(root) -> None:
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag == MC + "Fallback":
                parent.remove(child)


def _para_text(p, p_tag: str, t_tag: str, extra: dict[str, str]) -> str:
    out: list[str] = []

    def walk(el):
        for ch in el:
            if ch.tag == p_tag:
                continue  # nested paragraph (text box): reported on its own
            if ch.tag == t_tag:
                out.append(ch.text or "")
            elif ch.tag in extra:
                out.append(extra[ch.tag])
            walk(ch)

    walk(p)
    return "".join(out)


def _docx_text(zf: zipfile.ZipFile) -> Iterator[tuple[str, str, str]]:
    names = set(zf.namelist())
    parts = [("word/document.xml", "", "paragraph")]
    parts += [(n, n.split("/")[-1][:-4], n.split("/")[-1][:-4]) for n in sorted(names) if re.fullmatch(r"word/(header|footer)\d*\.xml", n)]
    parts += [(n, n[5:-4], n[5:-4]) for n in ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml") if n in names]
    extra = {W + "tab": "\t", W + "br": " ", W + "cr": " "}
    for part, short, word in parts:
        if part not in names:
            continue
        root = ET.fromstring(zf.read(part))
        _strip_fallback(root)
        for i, p in enumerate(root.iter(W + "p"), 1):
            text = _para_text(p, W + "p", W + "t", extra)
            if text.strip():
                yield (f"{short}:{i}" if short else str(i)), (f"{word} paragraph {i}" if short else f"paragraph {i}"), text


def _pptx_text(zf: zipfile.ZipFile) -> Iterator[tuple[str, str, str]]:
    names = zf.namelist()

    def num(n: str) -> int:
        m = re.search(r"(\d+)\.xml$", n)
        return int(m.group(1)) if m else 0

    for kind, pattern, suffix in (("slide", r"ppt/slides/slide\d+\.xml", ""), ("notes", r"ppt/notesSlides/notesSlide\d+\.xml", " notes")):
        for name in sorted((n for n in names if re.fullmatch(pattern, n)), key=num):
            root = ET.fromstring(zf.read(name))
            n = num(name)
            for i, p in enumerate(root.iter(A + "p"), 1):
                text = _para_text(p, A + "p", A + "t", {A + "br": " "})
                if text.strip():
                    yield (f"s{n}.{i}" if kind == "slide" else f"n{n}.{i}"), f"slide {n}{suffix}", text


def _xlsx_text(path: Path) -> Iterator[tuple[str, str, str]]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            for r, row in enumerate(ws.iter_rows(values_only=True), 1):
                cells = ["" if v is None else str(v) for v in row]
                if any(c.strip() for c in cells):
                    yield f"r{r}", f"sheet {ws.title}, row {r}", "\t".join(cells).rstrip("\t")
    finally:
        wb.close()


def _odf_text(zf: zipfile.ZipFile) -> Iterator[tuple[str, str, str]]:
    root = ET.fromstring(zf.read("content.xml"))
    rows = list(root.iter(TABLE_NS + "table-row"))
    if rows:
        for i, row in enumerate(rows, 1):
            cells = ["".join(c.itertext()) for c in row if c.tag in (TABLE_NS + "table-cell", TABLE_NS + "covered-table-cell")]
            text = "\t".join(cells).rstrip("\t")
            if text.strip():
                yield f"r{i}", f"row {i}", text
        return
    i = 0
    for el in root.iter():
        if el.tag in (TEXT_NS + "p", TEXT_NS + "h"):
            i += 1
            text = "".join(el.itertext())
            if text.strip():
                yield str(i), f"paragraph {i}", text


def _epub_text(zf: zipfile.ZipFile) -> Iterator[tuple[str, str, str]]:
    for name in sorted(n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))):
        text = html_to_text(zf.read(name).decode("utf-8", "replace"))
        short = name.split("/")[-1]
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip():
                yield f"{i}", f"{short} line {i}", line


def iter_office_text(path: Path) -> Iterator[tuple[str, str, str]]:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xltx"):
        yield from _xlsx_text(path)
        return
    with zipfile.ZipFile(path) as zf:
        if ext in (".docx", ".docm", ".dotx"):
            yield from _docx_text(zf)
        elif ext in (".pptx", ".pptm", ".potx", ".ppsx"):
            yield from _pptx_text(zf)
        elif ext in (".odt", ".ods", ".odp"):
            yield from _odf_text(zf)
        elif ext == ".epub":
            yield from _epub_text(zf)


def iter_office_images(path: Path) -> Iterator[tuple[str, bytes]]:
    """Pictures embedded in a document (word/media, ppt/media, xl/media, Pictures/...)."""
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            name = info.filename
            if info.is_dir() or Path(name).suffix.lower() not in IMAGE_EXT or info.file_size < 2500:
                continue
            if re.match(r"(word|ppt|xl)/media/", name) or name.startswith("Pictures/") or path.suffix.lower() == ".epub":
                yield name.split("/")[-1], zf.read(name)


# ---------------------------------------------------------------- PDF text with a box for every character
def pdf_blocks(page) -> list[tuple[str, list, list]]:
    """[(text, char_boxes, line_ids)] per paragraph-like block. Lines are joined with a space so a phrase
    that wraps onto the next line is still found."""
    data = page.get_text("rawdict")
    blocks = []
    for blk in data.get("blocks", []):
        if blk.get("type", 0) != 0:
            continue
        chars: list[str] = []
        boxes: list = []
        line_ids: list[int] = []
        for li, line in enumerate(blk.get("lines", [])):
            if chars and chars[-1] != " ":
                chars.append(" ")
                boxes.append(None)
                line_ids.append(li - 1)
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    for sub in ch.get("c", ""):
                        chars.append(sub)
                        boxes.append(tuple(ch["bbox"]))
                        line_ids.append(li)
        if chars:
            blocks.append(("".join(chars), boxes, line_ids))
    return blocks


def pdf_match_boxes(block, s: int, e: int) -> list[tuple[float, float, float, float]]:
    """One rectangle per line the match touches."""
    _, boxes, line_ids = block
    by_line: dict[int, list] = {}
    for i in range(s, e):
        if boxes[i] is not None:
            by_line.setdefault(line_ids[i], []).append(boxes[i])
    return [(min(b[0] for b in g), min(b[1] for b in g), max(b[2] for b in g), max(b[3] for b in g)) for g in by_line.values()]


# ---------------------------------------------------------------- archives (zip family, tar family, single .gz/.bz2/.xz)
def iter_archive(path: Path, tmp_dir: Path) -> Iterator[tuple[str, Path]]:
    """Yields (name inside archive, extracted temp file). The temp file is deleted right after use,
    so even huge archives never need much disk space."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    counter = 0

    def dest_for(name: str) -> Path:
        nonlocal counter
        counter += 1
        return tmp_dir / f"{counter}{Path(name).suffix[:12]}"

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                dest = dest_for(info.filename)
                try:
                    with zf.open(info) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
                    dest.unlink(missing_ok=True)
                    raise RuntimeError(f"{info.filename}: {exc} (password-protected or unsupported)") from exc
                try:
                    yield info.filename, dest
                finally:
                    dest.unlink(missing_ok=True)
        return
    if tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as tf:
            for member in tf:
                if not member.isfile():
                    continue
                src = tf.extractfile(member)
                if src is None:
                    continue
                dest = dest_for(member.name)
                with src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                try:
                    yield member.name, dest
                finally:
                    dest.unlink(missing_ok=True)
        return
    opener = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}.get(path.suffix.lower())
    if opener is None:
        raise RuntimeError("Unsupported archive type.")
    inner = path.stem
    dest = dest_for(inner)
    with opener(path, "rb") as src, open(dest, "wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
    try:
        yield inner, dest
    finally:
        dest.unlink(missing_ok=True)
