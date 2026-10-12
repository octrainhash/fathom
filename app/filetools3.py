"""File tools, part 3: page scanner, sensitive-data finder, shredder, encodings, permissions, dates, photo details, PDF page arranger."""
from __future__ import annotations

import base64
import binascii
import io
import os
import quopri
import random
import re
import shutil
import time
import zlib
from datetime import datetime
from pathlib import Path

from app import ops
from app.convert import formats
from app.convert.core import ConvertError, Ctx, Opts, file_bytes, safe_stem
from app.ops import Output, OutputPolicy, Task
from app.opsvc import expand_sources
from app.service import UserError

# ================================================================== page scanner (phone photo / scanner image -> clean flat page)
def _order_quad(pts):
    import numpy as np

    pts = np.array(pts, dtype="float32").reshape(4, 2)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype="float32")


def find_page_quad(bgr):
    """Corners of the biggest four-sided shape (the paper) as a 4x2 array in full-size pixels, or None."""
    import cv2
    import numpy as np

    h, w = bgr.shape[:2]
    k = 800.0 / max(h, w)
    small = cv2.resize(bgr, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else bgr.copy()
    k = small.shape[1] / w
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    best, best_area = None, 0.0
    area_img = small.shape[0] * small.shape[1]
    for variant in range(2):
        g = cv2.GaussianBlur(gray, (5, 5), 0)
        if variant == 0:
            edges = cv2.Canny(g, 40, 140)
        else:   # bright paper on darker table
            _t, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            edges = cv2.Canny(th, 50, 150)
        edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=2)
        cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:8]:
            area = cv2.contourArea(c)
            if area < area_img * 0.18:
                break
            peri = cv2.arcLength(c, True)
            for eps in (0.02, 0.03, 0.05):
                ap = cv2.approxPolyDP(c, eps * peri, True)
                if len(ap) == 4 and cv2.isContourConvex(ap):
                    if area > best_area:
                        best, best_area = ap.reshape(4, 2) / k, area
                    break
        if best is not None:
            break
    return None if best is None else _order_quad(best)


def flatten_page(bgr, quad):
    import cv2
    import numpy as np

    tl, tr, br, bl = quad
    wa, wb = np.linalg.norm(br - bl), np.linalg.norm(tr - tl)
    ha, hb = np.linalg.norm(tr - br), np.linalg.norm(tl - bl)
    W, H = int(max(wa, wb)), int(max(ha, hb))
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype="float32")
    return cv2.warpPerspective(bgr, cv2.getPerspectiveTransform(quad, dst), (W, H), flags=cv2.INTER_CUBIC)


def clean_page(bgr, mode: str, sharpen: bool):
    """mode: color | gray | bw | magic. All of them first remove shadows by dividing out the paper's own brightness."""
    import cv2
    import numpy as np

    if mode == "original":
        out = bgr
    else:
        k = max(31, (min(bgr.shape[:2]) // 12) | 1)
        chans = cv2.split(bgr)
        flat = []
        for ch in chans:
            bg = cv2.medianBlur(cv2.dilate(ch, np.ones((7, 7), np.uint8)), k)
            flat.append(cv2.divide(ch, bg, scale=255))
        out = cv2.merge(flat)
        if mode == "gray":
            out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
            out = cv2.normalize(out, None, 0, 255, cv2.NORM_MINMAX)
        elif mode == "bw":
            g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
            out = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, max(15, (min(g.shape) // 40) | 1), 12)
        elif mode == "magic":
            lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
            cl = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            lab[..., 0] = cl.apply(lab[..., 0])
            out = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
            out = cv2.convertScaleAbs(out, alpha=1.15, beta=-12)
    if sharpen:
        blur = cv2.GaussianBlur(out, (0, 0), 1.6)
        out = cv2.addWeighted(out, 1.7, blur, -0.7, 0)
    return out


def scan_start(paths: list[str], recursive: bool, mode: str, crop: bool, sharpen: bool, out_kind: str, output: dict) -> dict:
    policy = OutputPolicy.from_dict(output)
    files = [(p, r) for p, r in expand_sources(paths, recursive) if formats.category(formats.detect(p)) == "image" or formats.detect(p) == "pdf"]
    if not files:
        raise UserError("Add photos or scans of pages first.")
    pages: list[tuple[int, Path]] = []
    one_pdf = out_kind == "pdf_one"

    def make_fn(src, rel, idx):
        def fn(ctx: Ctx, task: Task) -> Output:
            import cv2
            import numpy as np
            from PIL import Image

            from app.convert.eng_image import load_frames

            d = ctx.scratch_dir()
            fmt = formats.detect(src)
            if fmt == "pdf":
                from app.convert.eng_docs import get_fitz, open_doc

                doc = open_doc(src, Opts())
                frames = []
                for pg in doc:
                    pix = pg.get_pixmap(dpi=200)
                    frames.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
                doc.close()
            else:
                frames, _d, _f = load_frames(src, fmt, all_frames=True)
            outs, notes = [], []
            for n, fr in enumerate(frames, 1):
                ctx.check()
                bgr = cv2.cvtColor(np.asarray(fr.convert("RGB")), cv2.COLOR_RGB2BGR)
                found = False
                if crop:
                    q = find_page_quad(bgr)
                    if q is not None:
                        bgr = flatten_page(bgr, q)
                        found = True
                res = clean_page(bgr, mode, sharpen)
                rgb = cv2.cvtColor(res, cv2.COLOR_GRAY2RGB) if res.ndim == 2 else cv2.cvtColor(res, cv2.COLOR_BGR2RGB)
                suffix = f"_p{n}" if len(frames) > 1 else ""
                if out_kind == "png":
                    dst = d / f"{safe_stem(src)} (scan){suffix}.png"
                    Image.fromarray(rgb).save(dst, "PNG")
                else:
                    dst = d / f"{safe_stem(src)} (scan){suffix}.jpg"
                    Image.fromarray(rgb).save(dst, "JPEG", quality=92, optimize=True)
                outs.append(dst)
                notes.append("page found and straightened" if found else ("no page edges found, kept whole picture" if crop else "cleaned"))
                ctx.progress(n / len(frames))
            if out_kind in ("pdf_each", "pdf_one"):
                ims = [Image.open(p).convert("RGB") for p in outs]
                if one_pdf:
                    # pages for the combined PDF are collected after every file is done
                    kept = []
                    for p in outs:
                        keep = ctx.job.tmp / f"{idx:05d}_{p.name}"       # type: ignore[attr-defined]
                        keep.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(p, keep)
                        kept.append(keep)
                    ctx.job.data.setdefault("pages", []).extend((idx, str(k)) for k in kept)  # type: ignore[attr-defined]
                    return Output([], f"{len(outs)} page(s) cleaned: {notes[0]}")
                pdf = d / f"{safe_stem(src)} (scan).pdf"
                ims[0].save(pdf, "PDF", save_all=True, append_images=ims[1:], resolution=200.0)
                return Output(policy.place([pdf], src, rel), notes[0])
            return Output(policy.place(outs, src, rel, group_name=safe_stem(src) + " (scan)"), notes[0])
        return fn

    tasks = [Task(src.name, make_fn(src, rel, i), src, rel=rel) for i, (src, rel) in enumerate(files)]

    def after(job) -> None:
        if not one_pdf:
            return
        from PIL import Image

        pages = sorted(job.data.get("pages", []))
        if not pages:
            return
        ims = [Image.open(p).convert("RGB") for _i, p in pages]
        dst = job.tmp / "Scanned pages.pdf"
        ims[0].save(dst, "PDF", save_all=True, append_images=ims[1:], resolution=200.0)
        placed = policy.place([dst], files[0][0], files[0][1])
        job.add({"name": "Scanned pages.pdf", "src": "", "status": "done", "outputs": [{"path": str(placed[0]), "name": placed[0].name, "bytes": file_bytes(placed[0]), "dir": False}],
                 "bytes_in": 0, "bytes_out": file_bytes(placed[0]), "note": f"{len(ims)} pages in one PDF, in the order you added them.", "error": "", "extra": {}, "secs": 0})

    return {"job": ops.start("scan", "Cleaning pages", tasks, workers=2, after=after).id, "count": len(tasks)}


# ================================================================== sensitive-data finder
def _luhn(num: str) -> bool:
    ds = [int(c) for c in re.sub(r"\D", "", num)]
    if not 13 <= len(ds) <= 19:
        return False
    tot = 0
    for i, d in enumerate(reversed(ds)):
        if i % 2:
            d *= 2
            d -= 9 if d > 9 else 0
        tot += d
    return tot % 10 == 0


def _iban_ok(v: str) -> bool:
    v = v.replace(" ", "").upper()
    if not 15 <= len(v) <= 34:
        return False
    r = v[4:] + v[:4]
    return int("".join(str(int(c, 36)) for c in r)) % 97 == 1


PATTERNS: dict[str, tuple[str, str, object | None]] = {
    "email": ("Email addresses", r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", None),
    "phone": ("Phone numbers", r"(?<![\w.])(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?)?\d{2,4}[\s.\-]\d{3,4}[\s.\-]?\d{3,4}(?![\w])", lambda v: 9 <= len(re.sub(r"\D", "", v)) <= 15 and not re.fullmatch(r"(?:\d{4}[ .\-]?){3,}", v)),
    "ipv4": ("IP addresses (IPv4)", r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b", None),
    "ipv6": ("IP addresses (IPv6)", r"\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b", None),
    "mac": ("MAC addresses", r"\b(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}\b", None),
    "url": ("Web addresses", r"https?://[^\s<>\"')\]]+", None),
    "card": ("Payment card numbers (checked with the Luhn test)", r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)", _luhn),
    "ssn": ("US social security numbers", r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b", None),
    "iban": ("Bank account numbers (IBAN)", r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b", _iban_ok),
    "aws": ("Amazon AWS access keys", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", None),
    "google": ("Google API keys", r"\bAIza[0-9A-Za-z_\-]{35}\b", None),
    "github": ("GitHub tokens", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", None),
    "slack": ("Slack tokens", r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b", None),
    "stripe": ("Stripe keys", r"\b[sr]k_live_[A-Za-z0-9]{16,}\b", None),
    "jwt": ("Login tokens (JWT)", r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b", None),
    "privkey": ("Private keys", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----", None),
    "password": ("Passwords written in text (password = …)", r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|token)\b\s*[:=]\s*[\"']?[^\s\"',;]{4,}", None),
}


def mask(kind: str, v: str) -> str:
    if kind in ("card", "ssn", "iban", "aws", "google", "github", "slack", "stripe", "jwt", "password", "privkey"):
        keep = 4 if len(v) > 10 else 0
        return v[:keep] + "•" * max(4, len(v) - keep - 2) + (v[-2:] if len(v) > 8 else "")
    return v


def _text_stream(src: Path, ocr: bool):
    """(where, text) for any file Fathom can read text from."""
    from app import extract

    kind = extract.classify(src)
    if kind == "text":
        for _lab, where, text in extract.iter_text_lines(src):
            yield where, text
    elif kind == "office":
        for _lab, where, text in extract.iter_office_text(src):
            yield where, text
    elif kind == "pdf":
        from app.convert.eng_docs import get_fitz

        fitz = get_fitz()
        if fitz:
            doc = fitz.open(str(src))
            for i, pg in enumerate(doc, 1):
                for ln in pg.get_text().splitlines():
                    yield f"page {i}", ln
            doc.close()
    elif kind == "image" and ocr:
        from app.ocr import ocr_boxes

        for _lab, im in extract.iter_image_frames(src):
            for tok in ocr_boxes(im):
                yield "in picture", tok["text"]
    elif kind == "binary":
        for _lab, where, text in extract.iter_binary_strings(src):
            yield where, text


def scrape_start(paths: list[str], recursive: bool, kinds: list[str], custom: str, ocr: bool, binary: bool) -> dict:
    kinds = [k for k in kinds if k in PATTERNS]
    rx_list = [(k, re.compile(PATTERNS[k][1]), PATTERNS[k][2]) for k in kinds]
    if custom.strip():
        try:
            rx_list.append(("custom", re.compile(custom), None))
        except re.error as exc:
            raise UserError(f"Your pattern is not valid: {exc}")
    if not rx_list:
        raise UserError("Choose what to look for (or type your own pattern).")
    tasks = []
    files = expand_sources(paths, recursive)
    if not files:
        raise UserError("Add files or folders to look through.")
    from app import extract

    def make(src):
        def fn(ctx: Ctx, task: Task) -> Output:
            found = []
            if not binary and extract.classify(src) == "binary":
                return Output([], "Skipped (binary file).", skipped=True)
            n = 0
            for where, text in _text_stream(src, ocr):
                n += 1
                if n % 2000 == 0:
                    ctx.check()
                if len(text) > 20000:
                    text = text[:20000]
                for kind, rx, ok in rx_list:
                    for m in rx.finditer(text):
                        v = m.group().strip()
                        if ok and not ok(v):
                            continue
                        found.append({"kind": kind, "value": v, "masked": mask(kind, v) if kind != "custom" else v, "where": where, "file": str(src)})
                        if len(found) >= 20000:
                            break
            with ctx.job.lock:  # type: ignore[attr-defined]
                ctx.job.data.setdefault("findings", []).extend(found)  # type: ignore[attr-defined]
            return Output([], f"{len(found)} found." if found else "Nothing found.", extra={"count": len(found)})
        return fn

    for src, rel in files:
        tasks.append(Task(src.name, make(src), src, rel=rel))
    job = ops.start("scrape", "Looking for data", tasks)
    job.data["labels"] = {k: v[0] for k, v in PATTERNS.items()}
    return {"job": job.id, "count": len(tasks)}


def scrape_export(job_id: str, output: dict, reveal: bool) -> dict:
    import csv

    job = ops.OPJOBS.get(job_id)
    if not job or "findings" not in job.data:
        raise UserError("Run the search first.")
    policy = OutputPolicy.from_dict(output)
    base = Path(job.data["findings"][0]["file"]) if job.data["findings"] else Path(".")
    tmp = Path(os.environ.get("TEMP") or "/tmp") / f"fathom-data-{os.getpid()}.csv"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Type", "Value", "File", "Where"])
        for f in job.data["findings"]:
            w.writerow([job.data["labels"].get(f["kind"], f["kind"]), f["value"] if reveal else f["masked"], f["file"], f["where"]])
    placed = policy.place([tmp], base, Path("."))
    return {"path": str(placed[0])}


# ================================================================== shredder
def _gutmann():
    r = "rand"
    pats = [bytes([0x55]), bytes([0xAA]), bytes([0x92, 0x49, 0x24]), bytes([0x49, 0x24, 0x92]), bytes([0x24, 0x92, 0x49])]
    pats += [bytes([i * 0x11]) for i in range(16)]
    pats += [bytes([0x92, 0x49, 0x24]), bytes([0x49, 0x24, 0x92]), bytes([0x24, 0x92, 0x49]), bytes([0x6D, 0xB6, 0xDB]), bytes([0xB6, 0xDB, 0x6D]), bytes([0xDB, 0x6D, 0xB6])]
    return [r] * 4 + pats + [r] * 4


METHODS = {
    "nist": ("NIST SP 800-88 (1 pass of random data)", ["rand"]),
    "hmg": ("British HMG IS5 enhanced (3 passes)", [b"\x00", b"\xff", "rand"]),
    "dod3": ("DoD 5220.22-M (3 passes)", [b"\x00", b"\xff", "rand"]),
    "dod7": ("DoD 5220.22-M ECE (7 passes)", [b"\x00", b"\xff", "rand", b"\x00", b"\xff", "rand", "rand"]),
    "vsitr": ("German VSITR (7 passes)", [b"\x00", b"\xff", b"\x00", b"\xff", b"\x00", b"\xff", b"\xaa"]),
    "gutmann": ("Gutmann (35 passes)", _gutmann()),
}


def _danger(p: Path) -> str | None:
    s = str(p.resolve()).rstrip("\\/").lower()
    if len(s) <= 3 or s in ("/", "/home", "/usr", "/etc", "/bin", "/var"):
        return "a whole drive or system folder"
    win = (os.environ.get("WINDIR") or "").lower()
    if win and (s == win or s.startswith(win + os.sep)):
        return "the Windows folder"
    pf = [(os.environ.get(k) or "").lower() for k in ("ProgramFiles", "ProgramFiles(x86)")]
    if any(x and (s == x or s.startswith(x + os.sep)) for x in pf):
        return "Program Files"
    return None


def _overwrite(path: Path, passes: list, ctx: Ctx, base_done: float, share: float) -> None:
    size = file_bytes(path)
    if size == 0:
        return
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass
    with open(path, "r+b", buffering=0) as fh:
        for pi, pat in enumerate(passes):
            fh.seek(0)
            left = size
            blk = (pat * ((1 << 20) // len(pat) + 1))[: 1 << 20] if pat != "rand" else b""
            while left > 0:
                ctx.check()
                n = min(1 << 20, left)
                fh.write(os.urandom(n) if pat == "rand" else blk[:n])
                left -= n
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
            ctx.progress(base_done + share * (pi + 1) / len(passes))
        fh.truncate(0)


def shred_start(paths: list[str], recursive: bool, method: str, confirm: str) -> dict:
    if confirm.strip().upper() != "SHRED":
        raise UserError("To shred, type SHRED in the box. Shredded files cannot be recovered by anyone.")
    if method not in METHODS:
        raise UserError("Choose a shredding method.")
    for p in paths:
        why = _danger(Path(p))
        if why:
            raise UserError(f"{p} is {why}. Fathom will not shred that.")
    passes = METHODS[method][1]
    files = expand_sources(paths, recursive, skip_junk=False)
    if not files:
        raise UserError("There are no files to shred.")
    roots = [Path(p) for p in paths if Path(p).is_dir()]

    def make(src):
        def fn(ctx: Ctx, task: Task) -> Output:
            _overwrite(src, passes, ctx, 0.0, 1.0)
            final = src
            for _ in range(3):   # scramble the name too so it does not stay in the file list
                new = src.with_name(os.urandom(6).hex())
                try:
                    final.rename(new)
                    final = new
                except OSError:
                    break
            final.unlink()
            return Output([], f"Overwritten {len(passes)}× and deleted.")
        return fn

    tasks = [Task(src.name, make(src), src, rel=rel) for src, rel in files]

    def after(job) -> None:
        for root in roots:   # remove the now-empty folders too
            for cur, dirs, fs in os.walk(root, topdown=False):
                try:
                    if not os.listdir(cur):
                        os.rmdir(cur)
                except OSError:
                    pass
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                pass

    return {"job": ops.start("shred", "Shredding", tasks, workers=2, after=after).id, "count": len(tasks), "method": METHODS[method][0]}


# ================================================================== encodings and text<->binary codings
TEXT_ENC = {"utf-8": "utf-8", "utf-8-bom": "utf-8-sig", "utf-16": "utf-16", "utf-16le": "utf-16-le", "utf-16be": "utf-16-be", "utf-32": "utf-32", "ascii": "ascii",
            "latin-1": "latin-1", "windows-1252": "cp1252", "windows-1250": "cp1250", "windows-1251": "cp1251", "windows-1256": "cp1256", "iso-8859-2": "iso8859-2", "iso-8859-15": "iso8859-15",
            "ebcdic": "cp037", "ebcdic-500": "cp500", "shift-jis": "shift_jis", "gbk": "gbk", "big5": "big5", "euc-kr": "euc_kr", "koi8-r": "koi8_r", "mac-roman": "mac_roman"}
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58e(b: bytes) -> bytes:
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return ("1" * (len(b) - len(b.lstrip(b"\x00"))) + out).encode()


def _b58d(t: bytes) -> bytes:
    s = t.decode().strip()
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + body


def _uu_e(b: bytes) -> bytes:
    lines = [b"begin 644 data"]
    for i in range(0, len(b), 45):
        lines.append(binascii.b2a_uu(b[i:i + 45]).rstrip(b"\n"))
    lines += [b"`", b"end", b""]
    return b"\n".join(lines)


def _uu_d(t: bytes) -> bytes:
    out = b""
    for ln in t.splitlines():
        if ln.startswith((b"begin", b"end")) or ln.strip() in (b"", b"`"):
            continue
        out += binascii.a2b_uu(ln)
    return out


CODECS = {
    "base64": ("Base64", lambda b: base64.encodebytes(b), lambda t: base64.b64decode(t)),
    "base32": ("Base32", lambda b: base64.b32encode(b), lambda t: base64.b32decode(re.sub(rb"\s", b"", t))),
    "hex": ("Hexadecimal", lambda b: binascii.hexlify(b), lambda t: binascii.unhexlify(re.sub(rb"\s", b"", t))),
    "binary": ("Binary (0 and 1)", lambda b: " ".join(f"{x:08b}" for x in b).encode(), lambda t: bytes(int(x, 2) for x in t.split())),
    "ascii85": ("Ascii85", lambda b: base64.a85encode(b), lambda t: base64.a85decode(t.strip())),
    "base85": ("Base85", lambda b: base64.b85encode(b), lambda t: base64.b85decode(t.strip())),
    "base58": ("Base58", _b58e, _b58d),
    "uuencode": ("UUencode", _uu_e, _uu_d),
    "quoted-printable": ("Quoted-Printable", lambda b: quopri.encodestring(b), lambda t: quopri.decodestring(t)),
}


def codec_start(paths: list[str], recursive: bool, kind: str, op: str, codec: str, source: str, target: str, newline: str, output: dict) -> dict:
    policy = OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in expand_sources(paths, recursive):
        def fn(ctx: Ctx, task: Task, src=src, rel=rel) -> Output:
            d = ctx.scratch_dir()
            if kind == "text":
                from app.extract import detect_encoding

                enc_in = TEXT_ENC.get(source) if source != "auto" else detect_encoding(src)
                enc_out = TEXT_ENC.get(target)
                if not enc_out:
                    raise ConvertError("Choose a text encoding to convert to.")
                dst = d / f"{src.stem} ({target}){src.suffix}"
                nl = {"lf": "\n", "crlf": "\r\n", "cr": "\r"}.get(newline)
                size = max(1, file_bytes(src))
                done = 0
                with open(src, "r", encoding=enc_in, errors="replace", newline="") as fi, open(dst, "w", encoding=enc_out, errors="replace", newline="") as fo:
                    while True:
                        ctx.check()
                        chunk = fi.read(1 << 20)
                        if not chunk:
                            break
                        if nl:
                            chunk = chunk.replace("\r\n", "\n").replace("\r", "\n").replace("\n", nl)
                        fo.write(chunk)
                        done += len(chunk)
                        ctx.progress(min(0.99, done / size))
                return Output(policy.place([dst], src, rel), f"Saved as {target}." + (" Characters that do not exist in the new encoding were replaced with ?." if enc_out in ("ascii", "latin-1", "cp1252") else ""))
            if codec not in CODECS:
                raise ConvertError("Choose a coding.")
            label, enc, dec = CODECS[codec]
            data = src.read_bytes()
            ctx.progress(0.2)
            if op == "decode":
                try:
                    out = dec(data)
                except Exception as exc:
                    raise ConvertError(f"This does not look like valid {label} ({exc}).")
                name = src.name.rsplit(".", 1)[0] if "." in src.name else src.name + ".decoded"
                dst = d / name
            else:
                out = enc(data)
                dst = d / (src.name + {"base64": ".b64", "hex": ".hex", "uuencode": ".uue", "quoted-printable": ".qp"}.get(codec, "." + codec.replace("-", "")) )
            dst.write_bytes(out)
            return Output(policy.place([dst], src, rel), f"{label} {'decoded' if op == 'decode' else 'encoded'}.")

        tasks.append(Task(src.name, fn, src, rel=rel))
    if not tasks:
        raise UserError("Add files first.")
    return {"job": ops.start("codec", "Converting encoding", tasks).id, "count": len(tasks)}


# ================================================================== permissions and attributes
def perms_view(paths: list[str]) -> list[dict]:
    out = []
    for p, _r in expand_sources(paths, False)[:200]:
        row = {"path": str(p), "name": p.name}
        try:
            st = p.stat()
            row["size"] = st.st_size
            if os.name == "nt":
                a = getattr(st, "st_file_attributes", 0)
                row.update(readonly=bool(a & 1), hidden=bool(a & 2), system=bool(a & 4), archive=bool(a & 32))
                from app.drives import ps_quick

                row["acl"] = ps_quick(f"icacls {_q(str(p))}", 15).strip()[:1500]
            else:
                import grp
                import pwd

                row["mode"] = oct(st.st_mode & 0o777)[2:].zfill(3)
                try:
                    row["owner"], row["group"] = pwd.getpwuid(st.st_uid).pw_name, grp.getgrgid(st.st_gid).gr_name
                except KeyError:
                    row["owner"], row["group"] = str(st.st_uid), str(st.st_gid)
        except OSError as exc:
            row["error"] = str(exc)
        out.append(row)
    return out


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def perms_apply(paths: list[str], recursive: bool, readonly: str, hidden: str, mode: str, acl_action: str, principal: str, rights: str) -> dict:
    """readonly/hidden: '' (leave) | 'on' | 'off'. mode: octal like 644 (Mac/Linux). acl_action: '' | grant | deny | remove | reset (Windows)."""
    files = [p for p, _r in expand_sources(paths, recursive, skip_junk=False)]
    if not files:
        raise UserError("Add files first.")
    if acl_action in ("grant", "deny", "remove") and not re.fullmatch(r"[\w .\\@\-]{1,64}", principal or ""):
        raise UserError("Type a user or group name, for example Everyone or Users.")
    if rights not in ("R", "RX", "W", "M", "F"):
        rights = "R"
    if mode and not re.fullmatch(r"[0-7]{3,4}", mode):
        raise UserError("The mode must be octal digits like 644 or 755.")

    def fn_for(p: Path):
        def fn(ctx: Ctx, task: Task) -> Output:
            notes = []
            try:
                from app import autoproof as _ap
                snap_before = _ap.perm_snapshot(p)
            except Exception:
                _ap, snap_before = None, ""
            if os.name == "nt":
                flags = []
                if readonly: flags.append(("+" if readonly == "on" else "-") + "R")
                if hidden: flags.append(("+" if hidden == "on" else "-") + "H")
                if flags:
                    rc, text = ctx.run(["attrib", *flags, str(p)])
                    if rc: raise ConvertError(text[-200:])
                    notes.append("attributes changed")
                if acl_action:
                    args = {"grant": ["/grant", f"{principal}:({rights})"], "deny": ["/deny", f"{principal}:({rights})"], "remove": ["/remove", principal], "reset": ["/reset"]}[acl_action]
                    rc, text = ctx.run(["icacls", str(p), *args])
                    if rc: raise ConvertError("Windows did not allow that change. " + text[-200:])
                    notes.append("permissions changed")
            else:
                if mode:
                    os.chmod(p, int(mode, 8)); notes.append("mode set")
                elif readonly:
                    os.chmod(p, (p.stat().st_mode & ~0o222) if readonly == "on" else (p.stat().st_mode | 0o200)); notes.append("attributes changed")
            extra = {}
            try:
                if _ap and notes:
                    extra["proof"] = _ap.perm_change(p.name, snap_before, _ap.perm_snapshot(p))
            except Exception:
                pass
            return Output([], ", ".join(notes) or "Nothing to change.", skipped=not notes, extra=extra)
        return fn

    return {"job": ops.start("perms", "Changing permissions", [Task(p.name, fn_for(p), p) for p in files]).id, "count": len(files)}


# ================================================================== dates
def times_start(paths: list[str], recursive: bool, mode: str, when: str, shift_minutes: float, which: list[str]) -> dict:
    files = [p for p, _r in expand_sources(paths, recursive, skip_junk=False)]
    if not files:
        raise UserError("Add files first.")
    ts = None
    if mode == "set":
        try:
            ts = datetime.fromisoformat(when.strip()).timestamp()
        except ValueError:
            raise UserError("Enter the date and time like 2024-05-17 14:30.")
    which = [w for w in which if w in ("modified", "created", "accessed")] or ["modified"]

    def fn_for(p: Path):
        def fn(ctx: Ctx, task: Task) -> Output:
            st = p.stat()
            new = ts
            if mode == "shift":
                new = st.st_mtime + shift_minutes * 60
            elif mode == "taken":
                new = _date_taken(p)
                if new is None:
                    return Output([], "No 'date taken' stored in this picture.", skipped=True)
            atime = new if "accessed" in which else st.st_atime
            mtime = new if "modified" in which else st.st_mtime
            os.utime(p, (atime, mtime))
            if "created" in which and os.name == "nt":
                _set_creation(p, new)
            extra = {}
            try:
                from app import autoproof
                extra["proof"] = autoproof.times_change(p.name, {"modified": st.st_mtime, "accessed": st.st_atime}, {"modified": mtime, "accessed": atime})
            except Exception:
                pass
            return Output([], datetime.fromtimestamp(new).strftime("%Y-%m-%d %H:%M"), extra=extra)
        return fn

    return {"job": ops.start("times", "Changing dates", [Task(p.name, fn_for(p), p) for p in files]).id, "count": len(files)}


def _date_taken(p: Path) -> float | None:
    try:
        from PIL import Image

        ex = Image.open(p).getexif()
        v = ex.get_ifd(0x8769).get(0x9003) or ex.get(0x0132)
        return datetime.strptime(str(v), "%Y:%m:%d %H:%M:%S").timestamp() if v else None
    except Exception:
        return None


def _set_creation(p: Path, ts: float) -> None:
    import ctypes
    from ctypes import wintypes

    k = ctypes.windll.kernel32
    k.CreateFileW.restype = wintypes.HANDLE
    h = k.CreateFileW(str(p), 0x100, 0, None, 3, 0x02000000, None)   # FILE_WRITE_ATTRIBUTES, OPEN_EXISTING, BACKUP_SEMANTICS
    if h in (None, wintypes.HANDLE(-1).value, -1):
        return
    v = int((ts + 11644473600) * 10_000_000)
    ft = wintypes.FILETIME(v & 0xFFFFFFFF, v >> 32)
    k.SetFileTime(h, ctypes.byref(ft), None, None)
    k.CloseHandle(h)


# ================================================================== photo details editor (lossless: only the details block is changed)
def exif_edit_start(paths: list[str], recursive: bool, remove_gps: bool, date_taken: str, artist: str, copyright_: str, description: str, output: dict) -> dict:
    try:
        import piexif  # type: ignore
    except ImportError:
        raise UserError("Editing photo details needs the 'piexif' package (run Fathom.bat repair with internet).")
    policy = OutputPolicy.from_dict(output)
    dt = None
    if date_taken.strip():
        try:
            dt = datetime.fromisoformat(date_taken.strip()).strftime("%Y:%m:%d %H:%M:%S")
        except ValueError:
            raise UserError("Enter the date like 2024-05-17 14:30.")
    tasks = []
    for src, rel in expand_sources(paths, recursive):
        if formats.detect(src) not in ("jpg", "tif", "webp"):
            continue

        def fn(ctx: Ctx, task: Task, src=src, rel=rel) -> Output:
            import shutil

            dst = ctx.scratch_dir() / src.name
            shutil.copyfile(src, dst)
            try:
                ex = piexif.load(str(dst))
            except Exception:
                ex = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            if remove_gps:
                ex["GPS"] = {}
            if dt:
                ex["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt.encode()
                ex["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt.encode()
                ex["0th"][piexif.ImageIFD.DateTime] = dt.encode()
            if artist.strip():
                ex["0th"][piexif.ImageIFD.Artist] = artist.encode("utf-8", "replace")
            if copyright_.strip():
                ex["0th"][piexif.ImageIFD.Copyright] = copyright_.encode("utf-8", "replace")
            if description.strip():
                ex["0th"][piexif.ImageIFD.ImageDescription] = description.encode("utf-8", "replace")
            piexif.insert(piexif.dump(ex), str(dst))
            out = dst.with_name(f"{src.stem} (edited){src.suffix}")
            dst.rename(out)
            return Output(policy.place([out], src, rel), "Details changed; the picture itself was not touched.")

        tasks.append(Task(src.name, fn, src, rel=rel))
    if not tasks:
        raise UserError("Add JPEG, TIFF or WebP photos.")
    return {"job": ops.start("exif", "Editing photo details", tasks).id, "count": len(tasks)}


# ================================================================== PDF page arranger
def _order_pages(spec: str, n: int) -> list[tuple[int | None, int]]:
    """[(page index or None for a blank page, extra turn in degrees)]. Tokens: 3  1-4  8-5 (reverse)  end  end-2  3r90 (turn page 3)  2-4r180  blank"""
    out: list[tuple[int | None, int]] = []
    for part in re.split(r"[;,\s]+", spec.strip()):
        if not part:
            continue
        low = part.lower()
        if low == "blank":
            out.append((None, 0))
            continue
        m = re.fullmatch(r"(\d+|end|last)(?:-(\d+|end|last))?(?:r(90|180|270|-90))?", low)
        if not m:
            raise UserError(f"“{part}” is not a page or range. Use numbers like 3, 1-4 or 8-5 (reverse); add r90 to turn (3r90) or write blank for an empty page.")
        a = n if m[1] in ("end", "last") else int(m[1])
        b = a if m[2] is None else (n if m[2] in ("end", "last") else int(m[2]))
        rot = int(m[3]) % 360 if m[3] else 0
        if not (1 <= a <= n and 1 <= b <= n):
            raise UserError(f"Page {max(a, b)} does not exist. This PDF has {n} pages.")
        out += [(i, rot) for i in (range(a - 1, b) if a <= b else range(a - 1, b - 2, -1))]
    if not out:
        raise UserError("Type the pages you want, in the order you want them.")
    return out


def pdf_arrange_start(paths: list[str], spec: str, rotate: int, output: dict) -> dict:
    policy = OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in expand_sources(paths, True):
        if formats.detect(src) != "pdf":
            continue

        def fn(ctx: Ctx, task: Task, src=src, rel=rel) -> Output:
            from pypdf import PdfReader, PdfWriter

            reader = PdfReader(str(src))
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    pass
                if reader.is_encrypted:
                    raise ConvertError("This PDF is locked with a password. Remove the password first (Protect → PDF password).")
            n = len(reader.pages)
            pages = _order_pages(spec, n) if spec.strip() else [(i, 0) for i in range(n)]
            w = PdfWriter()
            for pg, extra_turn in pages:
                ctx.check()
                if pg is None:                                    # an empty page the size of the first page
                    first = reader.pages[0]
                    w.add_blank_page(width=float(first.mediabox.width), height=float(first.mediabox.height))
                    continue
                page = w.add_page(reader.pages[pg])
                turn = (rotate + extra_turn) % 360
                if turn:
                    page.rotate(turn)
            dst = ctx.scratch_dir() / f"{src.stem} (rearranged).pdf"
            with open(dst, "wb") as fh:
                w.write(fh)
            return Output(policy.place([dst], src, rel), f"{len(pages)} pages.")

        tasks.append(Task(src.name, fn, src, rel=rel))
    if not tasks:
        raise UserError("Add a PDF first.")
    return {"job": ops.start("arrange", "Rearranging pages", tasks).id, "count": len(tasks)}


# ================================================================== damaged test copies (pairs with Repair)
DAMAGE_MODES = {"header": "Scramble the start (header)", "footer": "Scramble the end", "zero": "Zero out a chunk (bad sector)", "flip": "Scatter random byte changes", "truncate": "Cut the file short"}


def damage_start(paths: list[str], recursive: bool, mode: str, strength: float, output: dict) -> dict:
    """Makes a DAMAGED COPY of each file, to see how other software (or Fathom's own Repair tool) copes with a broken file. The original is never touched."""
    if mode not in DAMAGE_MODES:
        raise UserError("Choose how to damage the files.")
    strength = max(1.0, min(100.0, float(strength or 10)))
    policy = OutputPolicy.from_dict(output)
    files = expand_sources(paths, recursive, skip_junk=False)
    if not files:
        raise UserError("Add the files to make damaged test copies of.")

    def make(src: Path, rel: Path):
        def fn(ctx: Ctx, task: Task) -> Output:
            size = file_bytes(src)
            if size == 0:
                return Output([], "Empty file, nothing to damage.", skipped=True)
            dst = ctx.scratch_dir() / (src.stem + "_damaged" + src.suffix)
            shutil.copyfile(src, dst)
            with open(dst, "r+b") as f:
                if mode == "truncate":
                    cut = max(1, int(size * strength / 100))
                    f.truncate(max(0, size - cut))
                    note = f"cut off the last {cut:,} bytes"
                elif mode == "header":
                    n = min(size, max(8, int(512 * strength / 100)))
                    f.write(os.urandom(n))
                    note = f"scrambled the first {n:,} bytes"
                elif mode == "footer":
                    n = min(size, max(8, int(512 * strength / 100)))
                    f.seek(max(0, size - n)); f.write(os.urandom(min(n, size)))
                    note = f"scrambled the last {n:,} bytes"
                elif mode == "zero":
                    n = max(1, int(size * strength / 100))
                    start = random.randint(0, max(0, size - n))
                    f.seek(start); f.write(b"\x00" * n)
                    note = f"zeroed {n:,} bytes starting at byte {start:,}"
                else:  # flip: a random byte changed in many scattered blocks
                    blocks = max(1, (size + 4095) // 4096)
                    touch = min(max(1, int(blocks * strength / 100)), 20000, blocks)
                    for i in random.sample(range(blocks), touch):
                        ctx.check()
                        f.seek(min(i * 4096, size - 1)); f.write(os.urandom(1))
                    note = f"changed a random byte in {touch:,} scattered places"
            return Output(policy.place([dst], src, rel), f"Damaged test copy made: {note}. The original file was not touched.")
        return fn

    tasks = [Task(src.name, make(src, rel), src, rel=rel) for src, rel in files]
    return {"job": ops.start("damage", "Making damaged test copies", tasks, workers=3).id, "count": len(tasks)}
