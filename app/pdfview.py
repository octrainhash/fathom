"""Page count, page sizes and small page pictures for the page picker."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from app import proof
from app.service import UserError


def info(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise UserError("That file was not found.")
    if p.suffix.lower() != ".pdf":
        return {"pages": 0, "sizes": [], "kind": p.suffix.lower().lstrip(".")}
    try:
        from pypdf import PdfReader
        r = PdfReader(str(p))
        if r.is_encrypted:
            try:
                r.decrypt("")
            except Exception:
                return {"pages": 0, "sizes": [], "locked": True}
        sizes = []
        for i, pg in enumerate(r.pages):
            if i >= 3000:
                break
            w, h = float(pg.mediabox.width), float(pg.mediabox.height)
            if (pg.get("/Rotate") or 0) % 180:
                w, h = h, w
            sizes.append([round(w), round(h)])
        return {"pages": len(r.pages), "sizes": sizes}
    except Exception as e:
        return {"pages": 0, "sizes": [], "error": str(e)[:200]}


def thumb_png(path: str, page: int, size: int = 160) -> bytes:
    p = Path(path)
    if not p.is_file():
        raise UserError("That file was not found.")
    size = max(48, min(size, 900))
    got = None
    try:
        dpi = max(24, min(200, int(size / 8.5)))              # a US letter page is ~8.5 inches wide
        got = proof.render_pdf_page(p, page, dpi)
    except Exception:
        got = None
    if got:
        im = got[0]
        im.thumbnail((size, int(size * 1.6)))
    else:                                                      # no renderer: a plain page with its number
        im = Image.new("RGB", (size, int(size * 1.3)), (250, 250, 250))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, im.width - 1, im.height - 1), outline=(190, 190, 200))
        d.text((im.width // 2 - 8, im.height // 2 - 6), str(page + 1), fill=(120, 120, 140))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ================================================================== "preview on one of my files"
PREVIEW_FMT = {"pdf", "jpg", "png", "bmp", "gif", "webp", "tif", "tiff", "heic", "avif", "docx", "xlsx", "pptx", "odt", "ods", "odp", "doc", "xls", "ppt", "rtf", "xlsm"}


def previewable(paths: list[str], recursive: bool = True, limit: int = 600) -> dict:
    """which of the added files can be shown as a page: {files:[{path,name,folder,kind}], has_folders, direct}. Files found inside added folders are
    listed so the screen can ask which one to preview on."""
    from app.convert import formats
    from app.opsvc import expand_sources
    folders = [p for p in paths if Path(p).is_dir()]
    direct_set = {str(Path(p)) for p in paths if Path(p).is_file()}
    out, seen = [], set()
    for src, rel in expand_sources(paths, recursive, skip_junk=True):
        if str(src) in seen:
            continue
        seen.add(str(src))
        try:
            fmt = formats.detect(src)
        except Exception:
            continue
        if fmt not in PREVIEW_FMT:
            continue
        out.append({"path": str(src), "name": src.name, "folder": str(src.parent) if str(src) not in direct_set else "", "kind": "pdf" if fmt == "pdf" else "image" if formats.category(fmt) == "image" else "document"})
        if len(out) >= limit:
            break
    return {"files": out, "has_folders": bool(folders), "direct": len([f for f in out if not f["folder"]]), "total_scanned": len(seen)}


def _cache_dir() -> Path:
    from app.paths import temp_dir
    d = temp_dir() / "preview"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _as_pdf(p: Path) -> Path:
    """a Word / Excel / PowerPoint file as a PDF (kept for next time); needs LibreOffice, which Fathom can install"""
    import hashlib
    import threading
    from app.convert.core import Ctx, Opts
    from app.convert.engines import convert_file
    from app.convert import formats
    st = p.stat()
    key = hashlib.sha1(f"{p}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:20]
    out = _cache_dir() / f"{key}.pdf"
    if out.exists():
        return out
    work = _cache_dir() / ("w_" + key)
    ctx = Ctx(work, threading.Event())
    try:
        files, _n = convert_file(p, formats.detect(p), "pdf", Opts(), ctx)
        import shutil
        shutil.copyfile(files[0], out)
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    return out


def page_png(path: str, page: int = 0, size: int = 900) -> tuple[bytes, dict]:
    """one page (or picture) as a PNG about `size` pixels wide + {pages, w, h}"""
    from app.convert import formats
    p = Path(path)
    if not p.is_file():
        raise UserError("That file was not found.")
    size = max(120, min(size, 2000))
    fmt = formats.detect(p)
    pdf = p if fmt == "pdf" else None
    if pdf is None and fmt in {"docx", "xlsx", "pptx", "odt", "ods", "odp", "doc", "xls", "ppt", "rtf", "xlsm"}:
        pdf = _as_pdf(p)
    if pdf is not None:
        meta = info(str(pdf))
        n = meta.get("pages", 0)
        if meta.get("locked"):
            raise UserError("This PDF is locked with a password.")
        page = max(0, min(page, max(0, n - 1)))
        w_pt = (meta["sizes"][page][0] if meta.get("sizes") else 595) or 595
        dpi = max(30, min(300, size / w_pt * 72))
        got = proof.render_pdf_page(pdf, page, int(dpi))
        if not got:
            raise UserError("Page pictures need PyMuPDF (installed by Fathom.bat) or poppler.")
        im = got[0]
        meta = {"pages": n, "w": im.width, "h": im.height}
    else:
        from app.convert.eng_image import load_frames
        frames, _d, _f = load_frames(p, fmt, all_frames=True)
        n = len(frames)
        page = max(0, min(page, n - 1))
        im = frames[page].convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
        meta = {"pages": n, "w": im.width, "h": im.height}
    if im.width > size:
        im = im.resize((size, max(1, int(im.height * size / im.width))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), {**meta, "shown_w": im.width, "shown_h": im.height}
