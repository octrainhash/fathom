"""Everyday extras: Compare files and folders, QR codes (make and read), Hex view and patch, Picture touch-up.
Everything writes copies; the originals are never changed."""
from __future__ import annotations

import base64
import difflib
import hashlib
import io
import os
import re
import shutil
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from app import ops
from app.convert import formats
from app.convert.core import ConvertError, Ctx, Opts, file_bytes
from app.ops import Output, OutputPolicy, Task
from app.opsvc import expand_sources
from app.service import UserError


# ================================================================== compare
def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_text(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            head = f.read(8192)
    except OSError:
        return False
    return b"\x00" not in head or head.startswith((b"\xff\xfe", b"\xfe\xff"))


def _data_url(im: Image.Image, width: int = 900) -> str:
    im = im.copy()
    im.thumbnail((width, width))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _text_of(p: Path, ctx: Ctx) -> str | None:
    fmt = formats.detect(p)
    cat = formats.category(fmt)
    if cat in ("document", "presentation", "spreadsheet", "ebook") and fmt != "pdf":
        try:
            from app.convert.engines import convert_file
            outs, _n = convert_file(p, fmt, "txt", Opts(), ctx)
            from app.textedit import decode_text
            return decode_text(outs[0].read_bytes())[0]
        except Exception:
            return None
    if fmt == "pdf":
        try:
            from app.convert.engines import convert_file
            outs, _n = convert_file(p, fmt, "txt", Opts(), ctx)
            from app.textedit import decode_text
            return decode_text(outs[0].read_bytes())[0]
        except Exception:
            return None
    if _looks_text(p):
        from app.textedit import decode_text
        return decode_text(p.read_bytes())[0]
    return None


def compare_files(a: Path, b: Path, ctx: Ctx, ignore_space: bool = False) -> dict:
    res: dict = {"a": str(a), "b": str(b), "size_a": file_bytes(a), "size_b": file_bytes(b)}
    if _sha(a) == _sha(b):
        res.update(kind="same", same=True, summary="The two files are exactly the same, byte for byte.")
        return res
    res["same"] = False
    ca, cb = formats.category(formats.detect(a)), formats.category(formats.detect(b))
    if ca == "image" and cb == "image":
        try:
            ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
            if ia.size != ib.size:
                res.update(kind="image", summary=f"Different picture sizes: {ia.width}×{ia.height} and {ib.width}×{ib.height}.", sizes=[ia.size, ib.size])
                ib = ib.resize(ia.size)
            diff = ImageChops.difference(ia, ib)
            import numpy as np
            arr = np.asarray(diff).max(axis=2)
            changed = float((arr > 12).mean() * 100)
            bb = diff.convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
            hl = ia.copy()
            mask = diff.convert("L").point(lambda v: 255 if v > 12 else 0).filter(ImageFilter.MaxFilter(5))
            red = Image.new("RGB", ia.size, (255, 40, 40))
            hl = Image.composite(red, ImageEnhance.Brightness(ia).enhance(0.55), mask)
            res.update(kind="image", changed_percent=round(changed, 3), bbox=bb, diff=_data_url(hl),
                       summary=("The pictures look the same to the eye (tiny differences only)." if changed < 0.01 else f"{changed:.2f}% of the picture is different. The changes are shown in red.") + (res.get("summary") and "  " + res["summary"] or ""))
            return res
        except Exception:
            pass
    ta, tb = _text_of(a, ctx), _text_of(b, ctx)
    if ta is not None and tb is not None:
        la, lb = ta.splitlines(), tb.splitlines()
        if ignore_space:
            la, lb = [" ".join(x.split()) for x in la], [" ".join(x.split()) for x in lb]
        diff = list(difflib.unified_diff(la, lb, a.name, b.name, lineterm="", n=2))
        add = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        rem = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        if not diff:
            res.update(kind="text", summary="The words are the same (only formatting or hidden data differs).", lines=[])
        else:
            res.update(kind="text", summary=f"{add} line{'s' if add != 1 else ''} added, {rem} removed.", added=add, removed=rem, lines=diff[:4000], truncated=len(diff) > 4000)
        return res
    # plain bytes
    n = min(res["size_a"], res["size_b"])
    first = None
    with open(a, "rb") as fa, open(b, "rb") as fb:
        pos = 0
        while pos < n:
            ca_, cb_ = fa.read(1 << 20), fb.read(1 << 20)
            if ca_ != cb_:
                for i, (x, y) in enumerate(zip(ca_, cb_)):
                    if x != y:
                        first = pos + i
                        break
                break
            pos += len(ca_)
            if not ca_:
                break
    diffs = 0
    if first is not None and n <= 200 << 20:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            da, db = fa.read(), fb.read()
        diffs = sum(1 for x, y in zip(da, db) if x != y) + abs(len(da) - len(db))
    res.update(kind="binary", first_difference=first, differing_bytes=diffs,
               summary=(f"Different sizes ({res['size_a']:,} and {res['size_b']:,} bytes). " if res["size_a"] != res["size_b"] else "") + (f"The first difference is at byte {first:,} (hex offset 0x{first:X})." if first is not None else "The shorter file matches the start of the longer one."))
    return res


def compare_folders(a: Path, b: Path, ctx: Ctx) -> dict:
    def walk(root: Path) -> dict[str, Path]:
        out = {}
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                p = Path(dp) / fn
                out[str(p.relative_to(root)).replace("\\", "/")] = p
        return out
    wa, wb = walk(a), walk(b)
    only_a = sorted(set(wa) - set(wb))
    only_b = sorted(set(wb) - set(wa))
    both = sorted(set(wa) & set(wb))
    diff, same = [], 0
    for i, rel in enumerate(both):
        ctx.check(); ctx.progress(i / max(1, len(both)))
        pa, pb = wa[rel], wb[rel]
        if file_bytes(pa) != file_bytes(pb) or _sha(pa) != _sha(pb):
            diff.append({"path": rel, "size_a": file_bytes(pa), "size_b": file_bytes(pb), "newer": "a" if pa.stat().st_mtime > pb.stat().st_mtime else "b"})
        else:
            same += 1
    return {"kind": "folders", "a": str(a), "b": str(b), "only_a": only_a[:5000], "only_b": only_b[:5000], "different": diff[:5000], "same": same,
            "summary": f"{same} identical, {len(diff)} different, {len(only_a)} only on the left, {len(only_b)} only on the right."}


def compare_start(a: str, b: str, ignore_space: bool = False) -> dict:
    pa, pb = Path(a), Path(b)
    if not pa.exists() or not pb.exists():
        raise UserError("Choose two files or two folders to compare.")
    if pa.is_dir() != pb.is_dir():
        raise UserError("Choose two files, or two folders. A file cannot be compared with a folder.")

    def fn(ctx: Ctx, task: Task) -> Output:
        r = compare_folders(pa, pb, ctx) if pa.is_dir() else compare_files(pa, pb, ctx, ignore_space)
        ctx.job.data["result"] = r  # type: ignore[attr-defined]
        return Output([], r["summary"])
    return {"job": ops.start("compare", "Comparing", [Task("Compare", fn, None)], workers=1).id}


# ================================================================== QR codes
def qr_png(text: str, scale: int = 10, ecc: str = "M", dark: str = "#000000", light: str = "#ffffff", border: int = 4) -> bytes:
    if not text:
        raise UserError("Type what the QR code should say.")
    scale = max(2, min(40, scale))
    try:
        import segno  # type: ignore
    except ImportError:
        segno = None
    if segno is not None:
        try:
            q = segno.make(text, error=ecc.lower() if ecc in ("L", "M", "Q", "H") else "m", micro=False)
        except Exception as e:
            raise UserError(f"That is too long for one QR code ({e}).")
        buf = io.BytesIO()
        q.save(buf, kind="png", scale=scale, border=border, dark=dark, light=light)
        return buf.getvalue()
    # fallback: OpenCV's own encoder (always present with Fathom)
    try:
        import cv2  # type: ignore
        import numpy as np
        params = cv2.QRCodeEncoder_Params()
        params.correction_level = {"L": cv2.QRCodeEncoder_CORRECT_LEVEL_L, "M": cv2.QRCodeEncoder_CORRECT_LEVEL_M, "Q": cv2.QRCodeEncoder_CORRECT_LEVEL_Q, "H": cv2.QRCodeEncoder_CORRECT_LEVEL_H}.get(ecc, cv2.QRCodeEncoder_CORRECT_LEVEL_M)
        enc = cv2.QRCodeEncoder.create(params)
        m = enc.encode(text)
    except Exception as e:
        raise UserError(f"The QR code could not be made ({e}). It may be too long.")
    if m is None or not getattr(m, "size", 0):
        raise UserError("The QR code could not be made. The text may be too long.")
    # OpenCV adds a 2-module margin and draws each module 1 pixel at version scale 1; find the module grid
    mod = (np.asarray(m) < 128)
    ys, xs = np.where(mod)
    mod = mod[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    n = mod.shape[0]
    # downsample if the encoder already scaled modules
    side = 1
    while side < n and not (mod[:side * 7:1, :side * 7:1].any() and n % side == 0 and (n // side - 17) % 4 == 0):
        side += 1
    mod = mod[::side, ::side] if n % side == 0 else mod
    img = Image.fromarray((~mod).astype("uint8") * 255).convert("L")
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    img = ImageOps.expand(img, border * scale, fill=255)
    out = Image.new("RGB", img.size, light)
    out.paste(Image.new("RGB", img.size, dark), mask=img.point(lambda v: 255 if v < 128 else 0))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def wifi_text(ssid: str, password: str, security: str = "WPA", hidden: bool = False) -> str:
    esc = lambda s: re.sub(r"([\\;,:\"])", r"\\\1", s)
    return f"WIFI:T:{security};S:{esc(ssid)};P:{esc(password)};{'H:true;' if hidden else ''};"


def qr_save_start(text: str, scale: int, ecc: str, dark: str, light: str, name: str, output: dict) -> dict:
    data = qr_png(text, scale, ecc, dark, light)
    pol = OutputPolicy.from_dict(output)
    if pol.mode != "folder" or not pol.dir:
        raise UserError("Choose a folder to save the QR code in (on the left).")

    def fn(ctx: Ctx, task: Task) -> Output:
        d = ctx.scratch_dir()
        dst = d / (re.sub(r'[\\/:*?"<>|]', "_", name or "QR code") + ".png")
        dst.write_bytes(data)
        return Output(pol.place([dst], Path("qr"), Path(".")), "QR code saved.")
    return {"job": ops.start("qr", "Saving QR code", [Task("QR code", fn, None)], workers=1).id}


def qr_read(path: Path) -> list[str]:
    import cv2  # type: ignore
    import numpy as np
    im = Image.open(path).convert("RGB")
    found: list[str] = []
    det = cv2.QRCodeDetector()
    for scale in (1.0, 2.0, 0.5):
        img = im if scale == 1 else im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
        arr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
        for variant in (arr, cv2.cvtColor(cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)):
            try:
                ok, infos, _pts, _ = det.detectAndDecodeMulti(variant)
                if ok:
                    found += [i for i in infos if i]
            except Exception:
                try:
                    t, _p, _s = det.detectAndDecode(variant)
                    if t:
                        found.append(t)
                except Exception:
                    pass
        if found:
            break
    out = []
    for f in found:
        if f not in out:
            out.append(f)
    return out


def qr_read_start(paths: list[str], recursive: bool) -> dict:
    files = expand_sources(paths, recursive, skip_junk=True)
    if not files:
        raise UserError("Add pictures that contain QR codes.")

    def make(src: Path):
        def fn(ctx: Ctx, task: Task) -> Output:
            if formats.category(formats.detect(src)) != "image":
                return Output([], "Only pictures can be read.", skipped=True)
            codes = qr_read(src)
            if not codes:
                return Output([], "No QR code found.", skipped=True)
            return Output([], "; ".join(codes)[:2000], extra={"codes": codes})
        return fn
    return {"job": ops.start("qr-read", "Reading QR codes", [Task(s.name, make(s), s) for s, _r in files], workers=2).id}


# ================================================================== hex view / patch
def hex_view(path: str, offset: int = 0, length: int = 4096) -> dict:
    p = Path(path)
    if not p.is_file():
        raise UserError("Choose a file.")
    size = file_bytes(p)
    offset = max(0, min(int(offset), max(0, size - 1)))
    length = max(16, min(int(length), 1 << 16))
    with open(p, "rb") as f:
        f.seek(offset)
        data = f.read(length)
    rows = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        rows.append({"offset": offset + i, "hex": " ".join(f"{b:02X}" for b in chunk), "text": "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)})
    return {"size": size, "offset": offset, "rows": rows}


def hex_find(path: str, query: str, mode: str, start: int = 0) -> dict:
    p = Path(path)
    if not p.is_file():
        raise UserError("Choose a file.")
    if mode == "hex":
        try:
            needle = bytes.fromhex(re.sub(r"[^0-9A-Fa-f]", "", query))
        except ValueError:
            raise UserError("Type bytes like 4D 5A 90 00.")
    else:
        needle = query.encode("utf-8")
    if not needle:
        raise UserError("Type what to look for.")
    hits = []
    keep = len(needle) - 1
    pos, carry = int(start), b""
    with open(p, "rb") as f:
        f.seek(pos)
        base = pos
        while len(hits) < 200:
            chunk = f.read(1 << 22)
            if not chunk:
                break
            buf = carry + chunk
            i = buf.find(needle)
            while i != -1 and len(hits) < 200:
                hits.append(base - len(carry) + i)
                i = buf.find(needle, i + 1)
            carry = buf[-keep:] if keep else b""
            base += len(chunk)
    return {"hits": hits}


def _hex_proofs(src: Path, dst: Path, patches: list[dict]) -> list[dict]:
    """before/after hex rows around every patched place, the changed bytes highlighted and circled"""
    from app import proof
    P = proof.Proofs(proof.new_sid())
    with open(src, "rb") as a, open(dst, "rb") as b:
        for pt in patches:
            if P.full():
                P.more += 1
                continue
            off = int(pt.get("offset", 0))
            data = bytes.fromhex(re.sub(r"[^0-9A-Fa-f]", "", str(pt.get("hex", "")))) if pt.get("hex") is not None else str(pt.get("text", "")).encode("utf-8")
            lo = max(0, (off // 16 - 1) * 16)
            n = ((off + len(data) - 1) // 16 + 2) * 16 - lo
            n = min(n, 160)
            a.seek(lo); before = a.read(n)
            b.seek(lo); after = b.read(n)
            changed = {i for i in range(off, off + len(data)) if i - lo < len(before) and before[i - lo] != after[i - lo]} or set(range(off, off + min(len(data), 16)))
            bt, bs = proof.hex_rows(before, lo, changed)
            at, as_ = proof.hex_rows(after, lo, changed)
            proof.text_change(P, f"Bytes changed at 0x{off:X}", f"0x{off:X}", bt, at, bs, as_, f"{len(data)} byte{'s' if len(data) != 1 else ''} changed")
    return P.result()


def hex_patch_start(path: str, patches: list[dict], output: dict) -> dict:
    """patches: [{offset, hex}] or [{offset, text}]. The patched COPY is saved; the original stays as it is."""
    p = Path(path)
    if not p.is_file():
        raise UserError("Choose a file.")
    if not patches:
        raise UserError("Add at least one change.")
    pol = OutputPolicy.from_dict(output)

    def fn(ctx: Ctx, task: Task) -> Output:
        d = ctx.scratch_dir()
        dst = d / (p.stem + "_patched" + p.suffix)
        shutil.copyfile(p, dst)
        size = file_bytes(p)
        with open(dst, "r+b") as f:
            for pt in patches:
                off = int(pt.get("offset", 0))
                data = bytes.fromhex(re.sub(r"[^0-9A-Fa-f]", "", str(pt.get("hex", "")))) if pt.get("hex") is not None else str(pt.get("text", "")).encode("utf-8")
                if off < 0 or off + len(data) > size:
                    raise ConvertError(f"A change at 0x{off:X} would go past the end of the file ({size:,} bytes). Patching never changes the file's length.")
                f.seek(off)
                f.write(data)
        extra = {}
        try:
            extra["proof"] = _hex_proofs(p, dst, patches)
        except Exception:
            pass
        return Output(pol.place([dst], p, Path(".")), f"{len(patches)} change{'s' if len(patches) != 1 else ''} made in a copy. The original was not touched.", extra=extra)
    return {"job": ops.start("hexpatch", "Patching a copy", [Task(p.name, fn, p)], workers=1).id}


# ================================================================== picture touch-up
RATIOS = {"1:1": (1, 1), "4:3": (4, 3), "3:2": (3, 2), "16:9": (16, 9), "9:16": (9, 16), "3:4": (3, 4), "2:3": (2, 3), "5:4": (5, 4), "A4": (210, 297), "A4 wide": (297, 210)}


def touchup_image(im: Image.Image, o: dict) -> Image.Image:
    im = ImageOps.exif_transpose(im)
    has_alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
    alpha = im.convert("RGBA").getchannel("A") if has_alpha else None
    rgb = im.convert("RGB")
    trim = float(o.get("trim", 0) or 0)
    if trim > 0:
        dx, dy = int(rgb.width * trim / 100), int(rgb.height * trim / 100)
        box = (dx, dy, rgb.width - dx, rgb.height - dy)
        rgb = rgb.crop(box)
        alpha = alpha.crop(box) if alpha is not None else None
    ratio = o.get("ratio")
    if ratio in RATIOS:
        rw, rh = RATIOS[ratio]
        w, h = rgb.size
        if w * rh > h * rw:
            nw = int(h * rw / rh); x0 = (w - nw) // 2; box = (x0, 0, x0 + nw, h)
        else:
            nh = int(w * rh / rw); y0 = (h - nh) // 2; box = (0, y0, w, y0 + nh)
        rgb = rgb.crop(box)
        alpha = alpha.crop(box) if alpha is not None else None
    if o.get("auto"):
        rgb = ImageOps.autocontrast(rgb, cutoff=1)
    b = float(o.get("brightness", 0) or 0)
    if b:
        rgb = ImageEnhance.Brightness(rgb).enhance(1 + b / 100)
    c = float(o.get("contrast", 0) or 0)
    if c:
        rgb = ImageEnhance.Contrast(rgb).enhance(1 + c / 100)
    s = float(o.get("saturation", 0) or 0)
    if s:
        rgb = ImageEnhance.Color(rgb).enhance(1 + s / 100)
    sh = float(o.get("sharpen", 0) or 0)
    if sh > 0:
        rgb = rgb.filter(ImageFilter.UnsharpMask(radius=2, percent=int(sh * 2), threshold=2))
    look = o.get("look")
    if look == "gray":
        rgb = ImageOps.grayscale(rgb).convert("RGB")
    elif look == "bw":
        rgb = ImageOps.grayscale(rgb).point(lambda v: 255 if v > 128 else 0).convert("RGB")
    elif look == "sepia":
        g = ImageOps.grayscale(rgb)
        rgb = ImageOps.colorize(g, "#2b1a0a", "#f4e3c1")
    elif look == "invert":
        rgb = ImageOps.invert(rgb)
    bw = int(o.get("border", 0) or 0)
    if bw > 0:
        col = str(o.get("border_color") or "#ffffff")
        rgb = ImageOps.expand(rgb, bw, fill=col)
        alpha = ImageOps.expand(alpha, bw, fill=255) if alpha is not None else None
    rc = float(o.get("round", 0) or 0)
    out = rgb.convert("RGBA")
    if alpha is not None:
        out.putalpha(alpha)
    if rc > 0:
        r = int(min(out.size) * rc / 200)
        mask = Image.new("L", out.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, out.width - 1, out.height - 1), radius=r, fill=255)
        a0 = out.getchannel("A")
        out.putalpha(ImageChops.multiply(a0, mask))
    return out


def touchup_start(paths: list[str], recursive: bool, o: dict, output: dict) -> dict:
    pol = OutputPolicy.from_dict(output)
    files = expand_sources(paths, recursive, skip_junk=True)
    if not files:
        raise UserError("Add the pictures to touch up.")

    def make(src: Path, rel: Path):
        def fn(ctx: Ctx, task: Task) -> Output:
            if formats.category(formats.detect(src)) != "image":
                return Output([], "Only pictures can be touched up.", skipped=True)
            im0 = Image.open(src)
            exif = im0.info.get("exif")
            res = touchup_image(im0, o)
            ext = src.suffix.lower()
            d = ctx.scratch_dir()
            dst = d / (src.stem + "_touched" + (src.suffix if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff") else ".png"))
            if dst.suffix.lower() in (".jpg", ".jpeg"):
                kw = {"quality": 95, "subsampling": 0}
                if exif:
                    kw["exif"] = exif
                white = Image.new("RGB", res.size, (255, 255, 255))
                white.paste(res, mask=res.getchannel("A"))
                white.save(dst, **kw)
            elif dst.suffix.lower() in (".bmp",):
                res.convert("RGB").save(dst)
            else:
                res.save(dst)
            extra = {}
            try:
                from app import proof
                P = proof.Proofs(proof.new_sid(), limit=2)
                b0 = ImageOps.exif_transpose(im0).convert("RGB")
                a0 = res.convert("RGB")
                if b0.size == a0.size:
                    bx = proof.image_diff_boxes(b0, a0)
                    proof.picture_change(P, "Touched-up picture", src.name, b0, bx, a0, bx, "object", "Where the picture was changed")
                else:
                    P.add("Touched-up picture", src.name, proof.framed(b0), proof.framed(a0), f"Size changed: {b0.width}×{b0.height} → {a0.width}×{a0.height}")
                extra["proof"] = P.result()
            except Exception:
                pass
            return Output(pol.place([dst], src, rel), "Touched-up copy saved. The original was not touched.", extra=extra)
        return fn
    return {"job": ops.start("touchup", "Touching up", [Task(s.name, make(s, r), s, rel=r) for s, r in files], workers=3).id}
