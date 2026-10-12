"""Proof pictures for the tools that change files in a simple way (rotate, resize, clean pages, repair, photo details, hidden details, dates, permissions).
Called automatically when such a job finishes; never raises."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from app import proof

IMG = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
IMAGE_KINDS = {"rotate", "size", "scan", "repair", "steg-hide", "damage"}
META_KINDS = {"meta", "exif"}
Image.MAX_IMAGE_PIXELS = None


def _open(p: Path) -> Image.Image | None:
    try:
        im = Image.open(p)
        im.draft("RGB", (2400, 2400))
        im = ImageOps.exif_transpose(im)
        im.thumbnail((2000, 2000))
        return im.convert("RGB")
    except Exception:
        return None


def image_pair(src: Path, dst: Path, title: str) -> list[dict]:
    if src.suffix.lower() not in IMG or dst.suffix.lower() not in IMG:
        return []
    try:
        full_b = Image.open(src).size
        full_a = Image.open(dst).size
    except Exception:
        return []
    b, a = _open(src), _open(dst)
    if b is None or a is None:
        return []
    P = proof.Proofs(proof.new_sid(), limit=1)
    if full_b == full_a and b.size == a.size:
        bx = proof.image_diff_boxes(b, a)
        if not bx:
            return []                       # nothing visible changed: no picture
        proof.picture_change(P, title, src.name, b, bx, a, bx, "object", "Where the picture changed")
    else:
        note = f"Size {full_b[0]}×{full_b[1]} → {full_a[0]}×{full_a[1]}" if full_b != full_a else ""
        P.add(title, src.name, proof.framed(b), proof.framed(a), note or "The whole picture changed")
    return P.result()


# ---- picture details (EXIF) and document details
def _details(p: Path) -> list[str]:
    from PIL import ExifTags
    out: list[str] = []
    ext = p.suffix.lower()
    try:
        if ext in IMG:
            ex = Image.open(p).getexif()
            for k, v in ex.items():
                out.append(f"{ExifTags.TAGS.get(k, k)}  {str(v)[:60]}")
            try:
                gps = ex.get_ifd(0x8825)
                if gps:
                    out.append(f"GPS location  {len(gps)} values")
            except Exception:
                pass
            try:
                for k, v in ex.get_ifd(0x8769).items():
                    out.append(f"{ExifTags.TAGS.get(k, k)}  {str(v)[:60]}")
            except Exception:
                pass
        elif ext in (".docx", ".pptx", ".xlsx", ".odt", ".ods", ".odp"):
            import re
            import zipfile
            with zipfile.ZipFile(p) as z:
                for name in ("docProps/core.xml", "docProps/app.xml", "meta.xml"):
                    if name in z.namelist():
                        xml = z.read(name).decode("utf-8", "replace")
                        for m in re.finditer(r"<(?:dc:|cp:|dcterms:|meta:|)([A-Za-z\-]+)[^>]*>([^<]{1,80})</", xml):
                            out.append(f"{m.group(1)}  {m.group(2)}")
    except Exception:
        pass
    return out[:14]


def details_change(src: Path, dst: Path, title: str) -> list[dict]:
    b, a = _details(src), _details(dst)
    if b == a:
        return []
    P = proof.Proofs(proof.new_sid(), limit=1)
    changed_b = [i for i, ln in enumerate(b) if ln not in a]
    changed_a = [i for i, ln in enumerate(a) if ln not in b]

    def spans(lines, idx):
        out, off = [], 0
        for i, ln in enumerate(lines):
            if i in idx:
                out.append((off, off + len(ln)))
            off += len(ln) + 1
        return out
    bt = "\n".join(b) or "(no details stored)"
    at = "\n".join(a) or "(no details stored)"
    proof.text_change(P, title, src.name, bt, at, spans(b, changed_b), spans(a, changed_a), "Details removed or changed; the picture itself is the same")
    return P.result()


# ---- dates / permissions
def times_change(name: str, before: dict, after: dict) -> list[dict]:
    fmt = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    lines_b, lines_a, sb, sa = [], [], [], []
    ob = oa = 0
    for k in ("modified", "accessed"):
        lb, la = f"{k:<10} {fmt(before[k])}", f"{k:<10} {fmt(after[k])}"
        if lb != la:
            sb.append((ob + 11, ob + len(lb))); sa.append((oa + 11, oa + len(la)))
        lines_b.append(lb); lines_a.append(la)
        ob += len(lb) + 1; oa += len(la) + 1
    if not sb:
        return []
    P = proof.Proofs(proof.new_sid(), limit=1)
    proof.text_change(P, "Date changed", name, "\n".join(lines_b), "\n".join(lines_a), sb, sa)
    return P.result()


def perm_snapshot(p: Path) -> str:
    import os
    import stat
    st = p.stat()
    if os.name == "nt":
        a = getattr(st, "st_file_attributes", 0)
        return "\n".join([f"read-only   {'yes' if a & 1 else 'no'}", f"hidden      {'yes' if a & 2 else 'no'}"])
    return "\n".join([f"mode        {stat.filemode(st.st_mode)}  ({oct(st.st_mode & 0o777)[2:].zfill(3)})"])


def perm_change(name: str, before: str, after: str) -> list[dict]:
    if before == after:
        return []
    P = proof.Proofs(proof.new_sid(), limit=1)
    bl, al = before.split("\n"), after.split("\n")

    def sp(lines, other):
        out, off = [], 0
        for i, ln in enumerate(lines):
            if i >= len(other) or ln != other[i]:
                out.append((off + 12, off + len(ln)))
            off += len(ln) + 1
        return out
    proof.text_change(P, "Permissions changed", name, before, after, sp(bl, al), sp(al, bl))
    return P.result()


# ---- called by the job runner
def for_task(kind: str, src: Path | None, outs: list[Path]) -> list[dict]:
    if not src or not outs or not src.is_file():
        return []
    dst = outs[0]
    if not dst.is_file():
        return []
    if kind in META_KINDS:
        r = details_change(src, dst, "Hidden details" if kind == "meta" else "Photo details")
        return r
    if kind in IMAGE_KINDS:
        title = {"rotate": "Turned picture", "size": "Resized picture", "scan": "Cleaned page", "repair": "Repaired picture", "steg-hide": "Picture with hidden data", "damage": "Damaged copy"}[kind]
        return image_pair(src, dst, title)
    return []
