"""Stamps, signatures, watermarks and page numbers.

* A library of pictures on this PC: your signatures (drawn, typed, or cleaned up from a photo / scan of ink on paper) and stamps (ready-made words
  like APPROVED, or your own words, or your own picture such as a company seal).
* Putting one on PDF pages (every page, the first, the last, odd, even or a list) and on pictures. Word, Excel, PowerPoint and other document files are
  first turned into a PDF so the same stamp can go on them.
* The original file is never changed: the stamped copy is saved next to it or in your chosen folder.

This is a *visible* signature (the picture of your signature on the page), the same as signing a printout and scanning it. It is not a cryptographic
certificate signature."""
from __future__ import annotations

import base64
import io
import json
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from app import ops
from app.convert import formats
from app.convert.core import ConvertError, Ctx, Opts, file_bytes
from app.ops import Output, OutputPolicy, Task
from app.opsvc import expand_sources
from app.paths import data_root
from app.service import UserError

PRESETS = [
    {"id": "approved", "text": "APPROVED", "color": "#1e8449"}, {"id": "rejected", "text": "REJECTED", "color": "#b03a2e"},
    {"id": "draft", "text": "DRAFT", "color": "#7f8c8d"}, {"id": "final", "text": "FINAL", "color": "#1f4e9c"},
    {"id": "confidential", "text": "CONFIDENTIAL", "color": "#b03a2e"}, {"id": "paid", "text": "PAID", "color": "#1e8449"},
    {"id": "void", "text": "VOID", "color": "#b03a2e"}, {"id": "copy", "text": "COPY", "color": "#1f4e9c"},
    {"id": "urgent", "text": "URGENT", "color": "#d35400"}, {"id": "received", "text": "RECEIVED\n{date}", "color": "#1f4e9c"},
    {"id": "reviewed", "text": "REVIEWED\n{date}", "color": "#1e8449"}, {"id": "sample", "text": "SAMPLE", "color": "#7f8c8d"},
    {"id": "notforsale", "text": "NOT FOR DISTRIBUTION", "color": "#b03a2e"}, {"id": "original", "text": "ORIGINAL", "color": "#1f4e9c"},
]
FONTS = {
    "sans": (["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf", "Helvetica.ttc"],
             ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "FreeSans.ttf", "Helvetica.ttc"]),
    "serif": (["timesbd.ttf", "Times New Roman Bold.ttf", "DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "FreeSerifBold.ttf"],
              ["times.ttf", "Times New Roman.ttf", "DejaVuSerif.ttf", "LiberationSerif-Regular.ttf", "FreeSerif.ttf"]),
    "mono": (["courbd.ttf", "Courier New Bold.ttf", "DejaVuSansMono-Bold.ttf", "LiberationMono-Bold.ttf", "FreeMonoBold.ttf"],
             ["cour.ttf", "Courier New.ttf", "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf", "FreeMono.ttf"]),
    # handwriting-like fonts that ship with Windows / macOS / many Linux systems, best first
    "script": (["segoesc.ttf", "LHANDW.TTF", "BRUSHSCI.TTF", "Z003-MediumItalic.otf", "Z003-MediumItalic.t1", "Caveat-Regular.ttf", "FreeSerifItalic.ttf", "DejaVuSerif-Italic.ttf"],) * 2,
    "formal": (["MTCORSVA.TTF", "Monotype Corsiva.ttf", "Z003-MediumItalic.otf", "timesi.ttf", "FreeSerifItalic.ttf", "DejaVuSerif-Italic.ttf"],) * 2,
    "casual": (["Inkfree.ttf", "segoepr.ttf", "comic.ttf", "Caveat-Regular.ttf", "FreeSansOblique.ttf", "DejaVuSans-Oblique.ttf"],) * 2,
    "brush": (["BRUSHSCI.TTF", "SCRIPTBL.TTF", "FREESCPT.TTF", "segoesc.ttf", "Z003-MediumItalic.otf", "FreeSerifItalic.ttf"],) * 2,
}


def store() -> Path:
    p = data_root() / "stamps"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _hex(c: str, default=(0, 0, 0)) -> tuple[int, int, int]:
    c = (c or "").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, IndexError):
        return default


def _font(name: str, size: int, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = FONTS.get(name, FONTS["sans"])[0 if bold else 1]
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def tokens(text: str, extra: dict | None = None) -> str:
    now = datetime.now()
    vals = {"date": now.strftime("%d %b %Y"), "time": now.strftime("%H:%M"), "datetime": now.strftime("%d %b %Y %H:%M"), "year": str(now.year), "page": "1", "pages": "1", "file": "", "name": "", "user": ""}
    vals.update(extra or {})
    return re.sub(r"\{(\w+)\}", lambda m: str(vals.get(m.group(1), m.group(0))), text)


# ================================================================== drawing stamps
def render_text(spec: dict, extra: dict | None = None) -> Image.Image:
    """spec: text, color, font (sans|serif|mono|script|formal|casual|brush), bold, style (plain|box|double|round|banner|underline), size"""
    text = tokens(str(spec.get("text") or "STAMP"), extra) or " "
    color = _hex(str(spec.get("color") or "#1f4e9c"))
    style = str(spec.get("style") or "box")
    fname = str(spec.get("font") or "sans")
    bold = bool(spec.get("bold", fname in ("sans", "serif", "mono")))
    size = max(24, min(400, int(spec.get("size") or 140)))
    font = _font(fname, size, bold)
    lines = text.split("\n")
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    boxes = [probe.textbbox((0, 0), ln or " ", font=font) for ln in lines]
    lh = max(b[3] - b[1] for b in boxes)
    gap = int(lh * 0.25)
    tw = max(b[2] - b[0] for b in boxes)
    th = lh * len(lines) + gap * (len(lines) - 1)
    pad = int(size * (0.45 if style in ("box", "double", "round", "banner") else 0.12))
    bw = max(3, size // 14)
    W, H = tw + pad * 2 + bw * 2, th + pad * 2 + bw * 2
    im = Image.new("RGBA", (W + 8, H + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ox, oy = 4 + bw + pad, 4 + bw + pad
    ink = color + (255,)
    if style == "banner":
        d.rounded_rectangle((4, 4, W + 3, H + 3), radius=size // 5, fill=ink)
        ink_text = (255, 255, 255, 255) if sum(color) < 600 else (0, 0, 0, 255)
    else:
        ink_text = ink
    y = oy
    for ln, b in zip(lines, boxes):
        w = b[2] - b[0]
        d.text((ox + (tw - w) / 2 - b[0], y - b[1]), ln, font=font, fill=ink_text)
        y += lh + gap
    if style in ("box", "double"):
        d.rectangle((4, 4, W + 3, H + 3), outline=ink, width=bw)
        if style == "double":
            g = bw * 2
            d.rectangle((4 + g, 4 + g, W + 3 - g, H + 3 - g), outline=ink, width=max(2, bw // 2))
    elif style == "round":
        d.rounded_rectangle((4, 4, W + 3, H + 3), radius=min(W, H) // 2, outline=ink, width=bw)
    elif style == "underline":
        d.line((ox, oy + th + int(size * 0.08), ox + tw, oy + th + int(size * 0.08)), fill=ink, width=max(2, bw // 2))
    # a slightly worn look makes it feel stamped; leave it crisp when the user asked for a clean one
    if spec.get("worn"):
        import random
        px = im.load()
        rnd = random.Random(1)
        for _ in range(int(im.width * im.height * 0.02)):
            x, y2 = rnd.randrange(im.width), rnd.randrange(im.height)
            r, g, b2, a = px[x, y2]
            if a:
                px[x, y2] = (r, g, b2, int(a * 0.35))
    return crop_alpha(im, 2)


def crop_alpha(im: Image.Image, pad: int = 0) -> Image.Image:
    bb = im.getchannel("A").getbbox()
    if not bb:
        return im
    l, t, r, b = bb
    return im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad)))


def clean_ink(im: Image.Image, ink: str = "keep", strength: int = 50) -> Image.Image:
    """Turns a photo or scan of a signature (dark ink on light paper) into ink on a see-through background.
    ink: keep (original colour) | black | blue. strength 1-100: higher removes more of the paper and shadow."""
    import numpy as np
    src = im.convert("RGBA")
    a = np.asarray(src.getchannel("A"))
    if a.min() < 250 and (a < 20).mean() > 0.05:      # already has a see-through background: only recolour
        rgb = src
    else:
        rgb = src.convert("RGB")
    g = np.asarray(rgb.convert("L")).astype("float32")
    h, w = g.shape
    # estimate the paper brightness with a heavy blur of a "max filter" so ink does not darken its own background
    small = Image.fromarray(g.astype("uint8")).resize((max(8, w // 8), max(8, h // 8)))
    bgs = small.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(max(2, min(w, h) // 80)))
    bg = np.asarray(bgs.resize((w, h), Image.BILINEAR)).astype("float32")
    bg = np.maximum(bg, 40)
    dark = 1.0 - np.clip(g / bg, 0, 1)                # 0 = paper, 1 = very dark ink
    lo = 0.06 + (strength / 100) * 0.20
    hi = lo + 0.30
    alpha = np.clip((dark - lo) / (hi - lo), 0, 1)
    if im.mode == "RGBA" and a.min() < 250 and (a < 20).mean() > 0.05:
        alpha = np.maximum(alpha * 0, a / 255.0)
    out = np.zeros((h, w, 4), dtype="uint8")
    if ink == "black":
        col = np.array([20, 20, 24])
    elif ink == "blue":
        col = np.array([27, 58, 140])
    else:
        col = None
    if col is None:
        base = np.asarray(rgb.convert("RGB")).astype("float32")
        # darken the kept ink a little: scanned pen lines are washed out
        base = np.clip(base * 0.75, 0, 255)
        out[..., :3] = base.astype("uint8")
    else:
        out[..., :3] = col
    out[..., 3] = (alpha * 255).astype("uint8")
    res = Image.fromarray(out, "RGBA")
    return crop_alpha(res, 4)


# ================================================================== the library
def _thumb_data(im: Image.Image, width: int = 360) -> str:
    t = im.copy()
    t.thumbnail((width, width))
    buf = io.BytesIO()
    t.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def list_items() -> list[dict]:
    out = []
    for meta in sorted(store().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            m = json.loads(meta.read_text("utf-8"))
            png = meta.with_suffix(".png")
            if not png.exists():
                continue
            with Image.open(png) as im:
                im.load()
                out.append({"id": meta.stem, "name": m.get("name", meta.stem), "kind": m.get("kind", "signature"), "w": im.width, "h": im.height, "thumb": _thumb_data(im)})
        except Exception:
            continue
    return out


def load_item(item_id: str) -> Image.Image:
    if not re.fullmatch(r"[0-9a-f]{12}", item_id or ""):
        raise UserError("That signature or stamp is not in your library any more.")
    p = store() / f"{item_id}.png"
    if not p.exists():
        raise UserError("That signature or stamp is not in your library any more.")
    return Image.open(p).convert("RGBA")


def decode_data(data: str) -> Image.Image:
    m = re.match(r"data:[\w/+.-]+;base64,(.*)$", data or "", re.S)
    if not m:
        raise UserError("That picture could not be read.")
    try:
        return Image.open(io.BytesIO(base64.b64decode(m.group(1)))).convert("RGBA")
    except Exception:
        raise UserError("That picture could not be read. Use a PNG, JPG or similar picture.")


def save_item(name: str, kind: str, im: Image.Image) -> dict:
    kind = "stamp" if kind == "stamp" else "signature"
    im = crop_alpha(im.convert("RGBA"), 2)
    if max(im.size) > 2400:
        im.thumbnail((2400, 2400), Image.LANCZOS)
    iid = uuid.uuid4().hex[:12]
    im.save(store() / f"{iid}.png")
    (store() / f"{iid}.json").write_text(json.dumps({"name": (name or "").strip() or ("My " + kind), "kind": kind, "made": time.time()}), "utf-8")
    return {"id": iid, "name": (name or "").strip() or ("My " + kind), "kind": kind}


def delete_item(item_id: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{12}", item_id or ""):
        return
    for ext in (".png", ".json"):
        (store() / f"{item_id}{ext}").unlink(missing_ok=True)


def make_from_spec(b: dict) -> Image.Image:
    """b: {data} a picture (data URL) | {render} a text stamp/typed signature spec; options: remove_bg, ink, strength"""
    if b.get("data"):
        im = decode_data(b["data"])
        if b.get("remove_bg"):
            im = clean_ink(im, str(b.get("ink") or "keep"), int(b.get("strength") or 50))
        elif b.get("ink") in ("black", "blue"):
            im = clean_ink(im, str(b["ink"]), int(b.get("strength") or 50))
        return im
    if b.get("render"):
        return render_text(dict(b["render"]))
    raise UserError("Draw, type or choose a picture first.")


# ================================================================== placing
def parse_pages(spec: str, mode: str, total: int) -> list[int]:
    """0-based page numbers (see pagesel for everything a page list can say)"""
    from app import pagesel
    if mode == "custom" and (spec or "").strip():
        return pagesel.parse(spec, total)
    if mode in ("first", "last", "odd", "even"):
        return pagesel.parse(mode, total)
    return list(range(total))


ANCHORS = {"tl": (0, 0), "tc": (0.5, 0), "tr": (1, 0), "ml": (0, 0.5), "c": (0.5, 0.5), "mr": (1, 0.5), "bl": (0, 1), "bc": (0.5, 1), "br": (1, 1)}


def _stamp_image(spec: dict, extra: dict) -> Image.Image:
    """The picture to place for one page (text stamps re-render per page so {page} etc. work)."""
    if spec.get("item") or spec.get("_img") is not None:
        im = spec["_img"].copy() if spec.get("_img") is not None else load_item(str(spec["item"]))
        if spec.get("caption"):
            cap = render_text({"text": tokens(str(spec["caption"]), extra), "color": spec.get("caption_color") or "#333333", "font": "sans", "bold": False, "style": "plain", "size": max(30, im.height // 4)})
            scale = min(1.0, im.width / max(1, cap.width))
            cap = cap.resize((max(1, int(cap.width * scale)), max(1, int(cap.height * scale))), Image.LANCZOS)
            canvas = Image.new("RGBA", (max(im.width, cap.width), im.height + cap.height + 6), (0, 0, 0, 0))
            canvas.alpha_composite(im, ((canvas.width - im.width) // 2, 0))
            canvas.alpha_composite(cap, ((canvas.width - cap.width) // 2, im.height + 6))
            im = canvas
    else:
        im = render_text(dict(spec.get("render") or {}), extra)
    return im


def _finish(im: Image.Image, spec: dict) -> Image.Image:
    op = max(0, min(100, float(spec.get("opacity", 100)))) / 100
    if op < 1:
        a = im.getchannel("A").point(lambda v: int(v * op))
        im = im.copy()
        im.putalpha(a)
    return im


def _positions(spec: dict, W: float, H: float, w: float, h: float) -> list[tuple[float, float]]:
    """centre points (x right, y down) of the stamp(s) on a W x H page in the same unit as w and h"""
    if spec.get("tile"):
        stepx, stepy = w * 1.6, h * 2.4
        pts, row = [], 0
        y = -stepy / 2
        while y < H + stepy:
            x = -stepx / 2 + (stepx / 2 if row % 2 else 0)
            while x < W + stepx:
                pts.append((x, y))
                x += stepx
            y += stepy
            row += 1
        return pts
    ax, ay = ANCHORS.get(str(spec.get("position") or "br"), (1, 1))
    m = float(spec.get("margin", 4)) / 100 * min(W, H)
    cx = m + w / 2 + ax * (W - 2 * m - w)
    cy = m + h / 2 + ay * (H - 2 * m - h)
    if spec.get("x") is not None and spec.get("y") is not None and spec.get("free"):
        cx, cy = float(spec["x"]) * W, float(spec["y"]) * H
    cx += float(spec.get("dx", 0)) / 100 * W
    cy += float(spec.get("dy", 0)) / 100 * H
    return [(cx, cy)]


def _rotated(im: Image.Image, deg: float) -> Image.Image:
    return im.rotate(deg, expand=True, resample=Image.BICUBIC) if deg % 360 else im


def stamp_pdf(src: Path, dst: Path, spec: dict, ctx: Ctx | None = None, info: dict | None = None) -> int:
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    reader = PdfReader(str(src))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ConvertError("This PDF is locked with a password. Remove the password first (Protect → PDF password).")
        except ConvertError:
            raise
        except Exception:
            raise ConvertError("This PDF is locked with a password. Remove the password first (Protect → PDF password).")
    total = len(reader.pages)
    chosen = set(parse_pages(str(spec.get("pages_spec") or ""), str(spec.get("pages") or "all"), total))
    if not chosen:
        raise ConvertError("None of the pages you chose exist in this file.")
    writer = PdfWriter(clone_from=reader)
    rot = float(spec.get("rotation", 0))
    width_pct = max(2.0, min(100.0, float(spec.get("size", 25)))) / 100
    count = 0
    for i, page in enumerate(writer.pages):
        if i not in chosen:
            continue
        if ctx:
            ctx.check(); ctx.progress(i / max(1, total))
        mb = page.mediabox
        W, H = float(mb.width), float(mb.height)
        pr = int(page.get("/Rotate", 0) or 0) % 360 if "/Rotate" in page else 0
        Wd, Hd = (H, W) if pr in (90, 270) else (W, H)
        extra = {"page": str(i + 1), "pages": str(total), "file": src.name, "name": str(spec.get("name") or "")}
        base = _stamp_image(spec, extra)
        tw = Wd * width_pct
        ph = tw * base.height / base.width
        if ph > Hd * 0.95:
            ph = Hd * 0.95; tw = ph * base.width / base.height
        px_w = int(min(2600, max(80, tw * 4)))
        img = base.resize((px_w, max(1, int(px_w * base.height / base.width))), Image.LANCZOS)
        img = _finish(_rotated(img, rot), spec)
        # size of the rotated picture in points
        sw = img.width * tw / px_w
        sh = img.height * tw / px_w
        pts = _positions(spec, Wd, Hd, sw, sh)
        pic = _rotated(img, pr)
        ir = ImageReader(pic)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(W, H))
        c.translate(-float(mb.left), -float(mb.bottom))
        if info is not None:
            info.setdefault("pages", {})[i] = [(cx - sw / 2, cy - sh / 2, cx + sw / 2, cy + sh / 2) for (cx, cy) in pts[:6]]
            info["tile"] = bool(spec.get("tile"))
        for (cx, cy) in pts:
            if pr == 0:
                xu, yu = cx, H - cy
            elif pr == 90:
                xu, yu = cy, cx
            elif pr == 180:
                xu, yu = W - cx, cy
            else:
                xu, yu = W - cy, H - cx
            xu += float(mb.left); yu += float(mb.bottom)
            pw, phh = (sw, sh) if pr in (0, 180) else (sh, sw)
            c.drawImage(ir, xu - pw / 2, yu - phh / 2, width=pw, height=phh, mask="auto")
        c.save()
        buf.seek(0)
        ov = PdfReader(buf).pages[0]
        page.merge_page(ov)
        count += 1
    with open(dst, "wb") as f:
        writer.write(f)
    return count


def stamp_image(src: Path, dst: Path, spec: dict, info: dict | None = None) -> int:
    im0 = Image.open(src)
    frames = []
    exif = im0.info.get("exif")
    n = getattr(im0, "n_frames", 1)
    total = n
    chosen = set(parse_pages(str(spec.get("pages_spec") or ""), str(spec.get("pages") or "all"), total)) if n > 1 else {0}
    width_pct = max(2.0, min(100.0, float(spec.get("size", 25)))) / 100
    rot = float(spec.get("rotation", 0))
    count = 0
    for i in range(n):
        im0.seek(i)
        frame = im0.convert("RGBA")
        if i in chosen:
            W, H = frame.size
            extra = {"page": str(i + 1), "pages": str(total), "file": src.name, "name": str(spec.get("name") or "")}
            base = _stamp_image(spec, extra)
            tw = W * width_pct
            th = tw * base.height / base.width
            if th > H * 0.95:
                th = H * 0.95; tw = th * base.width / base.height
            img = base.resize((max(1, int(tw)), max(1, int(th))), Image.LANCZOS)
            img = _finish(_rotated(img, rot), spec)
            if info is not None and "boxes" not in info:
                info["boxes"] = [(cx - img.width / 2, cy - img.height / 2, cx + img.width / 2, cy + img.height / 2) for cx, cy in _positions(spec, W, H, img.width, img.height)[:6]]
            for cx, cy in _positions(spec, W, H, img.width, img.height):
                frame.alpha_composite(img, (int(cx - img.width / 2), int(cy - img.height / 2))) if (0 <= cx - img.width / 2 and 0 <= cy - img.height / 2 and cx + img.width / 2 <= W and cy + img.height / 2 <= H) else _paste_clipped(frame, img, int(cx - img.width / 2), int(cy - img.height / 2))
            count += 1
        frames.append(frame)
    ext = src.suffix.lower()
    keep_alpha = ext in (".png", ".webp", ".tif", ".tiff", ".gif", ".bmp") and im0.mode in ("RGBA", "LA", "P")
    out_frames = [f if keep_alpha else f.convert("RGB") for f in frames]
    kw: dict = {}
    if ext in (".jpg", ".jpeg"):
        kw = {"quality": 95, "subsampling": 0}
        if exif:
            kw["exif"] = exif
    if len(out_frames) > 1 and ext in (".tif", ".tiff", ".gif", ".webp"):
        kw.update(save_all=True, append_images=out_frames[1:])
    out_frames[0].save(dst, **kw)
    return count


def _paste_clipped(frame: Image.Image, img: Image.Image, x: int, y: int) -> None:
    W, H = frame.size
    l, t = max(0, x), max(0, y)
    r, b = min(W, x + img.width), min(H, y + img.height)
    if r <= l or b <= t:
        return
    piece = img.crop((l - x, t - y, r - x, b - y))
    frame.alpha_composite(piece, (l, t))


DOC_CATS = {"document", "presentation", "spreadsheet", "ebook", "text", "data"}


def apply_start(paths: list[str], recursive: bool, spec: dict, output: dict) -> dict:
    spec = dict(spec)
    if spec.get("make"):
        spec["_img"] = make_from_spec(dict(spec.pop("make")))
    if not (spec.get("item") or spec.get("render") or spec.get("_img") is not None):
        raise UserError("Choose or make a stamp or signature first.")
    if spec.get("item"):
        load_item(str(spec["item"]))
    policy = OutputPolicy.from_dict(output)
    files = expand_sources(paths, recursive, skip_junk=True)
    if not files:
        raise UserError("Add the PDFs or pictures to stamp.")
    suffix = "_signed" if spec.get("as") == "sign" else "_stamped"

    def make(src: Path, rel: Path):
        def fn(ctx: Ctx, task: Task) -> Output:
            fmt = formats.detect(src)
            cat = formats.category(fmt)
            d = ctx.scratch_dir()
            info: dict = {}
            before_pdf: Path | None = None
            if fmt == "pdf":
                dst = d / (src.stem + suffix + ".pdf")
                n = stamp_pdf(src, dst, spec, ctx, info)
                note = f"Put on {n} page{'s' if n != 1 else ''}."
                before_pdf = src
            elif cat == "image":
                dst = d / (src.stem + suffix + src.suffix)
                n = stamp_image(src, dst, spec, info)
                note = "Placed on the picture."
            elif cat in DOC_CATS:
                from app.convert.engines import convert_file
                ctx.status("Turning it into a PDF first")
                outs, _n = convert_file(src, fmt, "pdf", Opts(), ctx)
                dst = d / (src.stem + suffix + ".pdf")
                n = stamp_pdf(outs[0], dst, spec, ctx, info)
                note = f"Turned into a PDF and put on {n} page{'s' if n != 1 else ''}."
                before_pdf = outs[0]
            else:
                return Output([], "Only PDFs, pictures and documents can be stamped.", skipped=True)
            proofs = _proofs(ctx, src, dst, before_pdf, info, "Signature" if spec.get("as") == "sign" else "Stamp")
            return Output(policy.place([dst], src, rel), note + " The original was not touched.", extra={"proof": proofs})
        return fn

    tasks = [Task(s.name, make(s, r), s, rel=r) for s, r in files]
    return {"job": ops.start("stamp", "Stamping", tasks, workers=2).id, "count": len(tasks)}


def _proofs(ctx: Ctx, src: Path, dst: Path, before_pdf: Path | None, info: dict, what: str) -> list[dict]:
    """BEFORE / AFTER pictures with the stamp or signature circled."""
    from app import proof
    P = proof.Proofs(ctx.job.id)  # type: ignore[attr-defined]
    try:
        if info.get("pages") and before_pdf is not None:
            pages = {k: v[:1] if info.get("tile") else v for k, v in info["pages"].items()}
            proof.pdf_page_changes(P, before_pdf, dst, pages, f"{what} on {src.name}", "object", max_pages=2)
        elif info.get("boxes"):
            from PIL import Image
            proof.picture_change(P, f"{what} on {src.name}", src.name, Image.open(src), [], Image.open(dst), info["boxes"][:1] if info.get("tile") else info["boxes"], "object")
    except Exception:
        pass
    return P.result()
