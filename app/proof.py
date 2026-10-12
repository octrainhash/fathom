"""Proof pictures: for anything Fathom changes or adds, a BEFORE and an AFTER picture where the changed thing is highlighted in yellow and circled
in red (the same marking the Find tool uses). Pictures are kept with the other saved results (Saved results in the top bar clears them)."""
from __future__ import annotations

import difflib
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from PIL import Image

from app import annotate, textsnap
from app.paths import sessions_dir

MAX_PER_FILE = 6


def new_sid() -> str:
    return uuid.uuid4().hex


class Proofs:
    """collects proof items for one file (or one action); items are plain dicts the screen can show"""

    def __init__(self, sid: str, limit: int = MAX_PER_FILE):
        self.sid, self.limit = sid, limit
        self.dir = sessions_dir() / sid
        self.dir.mkdir(parents=True, exist_ok=True)
        self.items: list[dict] = []
        self.more = 0
        self._n = 0

    def full(self) -> bool:
        return len(self.items) >= self.limit

    def _save(self, im: Image.Image, tag: str) -> str:
        self._n += 1
        name = f"proof_{self._n:03d}_{uuid.uuid4().hex[:6]}.png"
        annotate.to_rgb(im).save(self.dir / name, "PNG")
        return f"/media/{self.sid}/{name}"

    def add(self, title: str, where: str, before: Image.Image | None, after: Image.Image | None, note: str = "") -> None:
        if self.full():
            self.more += 1
            return
        self.items.append({"title": title, "where": where, "note": note, "before": self._save(before, "b") if before is not None else "", "after": self._save(after, "a") if after is not None else ""})

    def result(self) -> list[dict]:
        out = list(self.items)
        if self.more:
            out.append({"title": f"… and {self.more} more change{'s' if self.more != 1 else ''} not pictured", "where": "", "note": "", "before": "", "after": ""})
        return out


# ------------------------------------------------------------------ text cards
def _widen(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """grow every span to whole words and join spans that touch, so the picture marks words and not stray letters"""
    out: list[tuple[int, int]] = []
    for a, b in spans:
        while a > 0 and not text[a - 1].isspace():
            a -= 1
        while b < len(text) and not text[b].isspace():
            b += 1
        if out and a <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def diff_spans(a: str, b: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """character ranges that differ (as whole words): (spans in a, spans in b)"""
    sa, sb = [], []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sm.ratio() < 0.5:                      # mostly different: mark everything
        return ([(0, len(a))] if a else []), ([(0, len(b))] if b else [])
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            sa.append((i1, i2))
        if j2 > j1:
            sb.append((j1, j2))
    if not sa and not sb and a != b:
        sa, sb = [(0, len(a))], [(0, len(b))]
    sa, sb = _widen(a, sa), _widen(b, sb)
    if len(sa) > 3 or len(sb) > 3:            # many scattered bits: one block from the first to the last
        sa = [(sa[0][0], sa[-1][1])] if sa else []
        sb = [(sb[0][0], sb[-1][1])] if sb else []
    return sa, sb


def _window(text: str, spans: list[tuple[int, int]], radius: int = 240) -> tuple[str, list[tuple[int, int]]]:
    if len(text) <= 2 * radius + 200 or not spans:
        return text, spans
    lo = max(0, min(s for s, _ in spans) - radius)
    hi = min(len(text), max(e for _, e in spans) + radius)
    lead = "…" if lo else ""
    return lead + text[lo:hi] + ("…" if hi < len(text) else ""), [(s - lo + len(lead), e - lo + len(lead)) for s, e in spans]


def _short(s: str, n: int = 16) -> str:
    return s if len(s) <= n else "…" + s[-(n - 1):]


def card(label: str, text: str, spans: list[tuple[int, int]], title: str = "") -> Image.Image:
    """one picture of a piece of text with the changed words highlighted and circled"""
    text = text.replace("\r", "")
    lines = text.split("\n")
    rows, hits, off = [], [], 0
    starts = []
    for i, ln in enumerate(lines):
        starts.append(off)
        off += len(ln) + 1
        rows.append((label if i == 0 else "", ln))
    for s, e in spans:
        for i, ln in enumerate(lines):
            a, b = max(s, starts[i]), min(e, starts[i] + len(ln))
            if b > a or (s == e and starts[i] <= s <= starts[i] + len(ln)):
                hits.append((i, a - starts[i], max(b - starts[i], a - starts[i] + 1)))
    img, boxes = textsnap.render_snapshot(rows[:14], [h for h in hits if h[0] < 14], title=title)
    flat = [b for bs in boxes for b in bs]
    if flat:
        img = annotate.annotate(img, flat, "text")
    return img


def line_context(text: str, s: int, e: int, lines: int = 1) -> tuple[str, int, int]:
    """the line(s) around text[s:e] plus a line above and below; returns (snippet, s, e) relative to the snippet"""
    lo = s
    for _ in range(lines + 1):
        lo = text.rfind("\n", 0, max(0, lo - 1)) if lo > 0 else -1
        if lo < 0:
            lo = -1
            break
    lo += 1
    hi = e
    for _ in range(lines + 1):
        nx = text.find("\n", hi + 1) if hi < len(text) else -1
        if nx < 0:
            hi = len(text)
            break
        hi = nx
    return text[lo:hi], s - lo, e - lo


def text_change(P: Proofs, title: str, where: str, before: str, after: str, bspans=None, aspans=None, note: str = "") -> None:
    if bspans is None or aspans is None:
        bspans, aspans = diff_spans(before, after)
    if len(before) > 1500 or len(after) > 1500:
        text_diff(P, title, before, after, note)     # a whole file: one picture per changed place
        return
    if P.full():
        P.more += 1
        return
    b, bs = _window(before, bspans)
    a, as_ = _window(after, aspans)
    lab = _short(where.split("·")[-1].strip() if "·" in where else (Path(where).name if "/" in where else where), 22) if where else "text"
    P.add(title, where, card(lab, b, bs, "BEFORE  ·  " + title) if before != "" or bs else None, card(lab, a, as_, "AFTER  ·  " + title) if after != "" or as_ else None, note)


def text_diff(P: Proofs, title: str, before: str, after: str, note: str = "", context: int = 1) -> None:
    """compare two whole texts line by line: one picture per changed place, with a line above and below"""
    bl, al = before.split("\n"), after.split("\n")
    sm = difflib.SequenceMatcher(None, bl, al, autojunk=False)

    def block(lines: list[str], lo: int, hi: int, mark_lo: int, mark_hi: int):
        a, b = max(0, lo - context), min(len(lines), hi + context)
        txt = "\n".join(lines[a:b])
        off = len("\n".join(lines[a:mark_lo])) + (1 if mark_lo > a else 0)
        end = off + len("\n".join(lines[mark_lo:mark_hi]))
        return txt, off, end, a
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if P.full():
            P.more += 1
            continue
        bt, b0, b1, ba = block(bl, i1, i2, i1, i2)
        at, a0, a1, aa = block(al, j1, j2, j1, j2)
        bsp, asp = ([(b0, b1)] if i2 > i1 else []), ([(a0, a1)] if j2 > j1 else [])
        if i2 - i1 == 1 and j2 - j1 == 1:         # one line edited: mark only the words that changed
            ds, dt = diff_spans(bl[i1], al[j1])
            base_b, base_a = b0, a0
            bsp, asp = [(base_b + x, base_b + y) for x, y in ds] or bsp, [(base_a + x, base_a + y) for x, y in dt] or asp
        what = "changed" if tag == "replace" else "removed" if tag == "delete" else "added"
        P.add(title, f"line {i1 + 1}" if tag != "insert" else f"after line {i1}",
              card(f"line {ba + 1}", bt, bsp, "BEFORE  ·  " + title) if i2 > i1 or tag == "insert" else None,
              card(f"line {aa + 1}", at, asp, "AFTER  ·  " + title) if j2 > j1 or tag == "delete" else None,
              note or f"Line {what}")


# ------------------------------------------------------------------ pages and pictures
def render_pdf_page(path: Path, pno: int, dpi: int = 110) -> tuple[Image.Image, float] | None:
    try:
        from app.convert.eng_docs import get_fitz
        fitz = get_fitz()
        if fitz is not None:
            doc = fitz.open(str(path))
            pix = doc[pno].get_pixmap(dpi=dpi)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            doc.close()
            return im, dpi / 72.0
    except Exception:
        pass
    exe = shutil.which("pdftoppm")
    if exe:
        try:
            with tempfile.TemporaryDirectory() as d:
                subprocess.run([exe, "-f", str(pno + 1), "-l", str(pno + 1), "-r", str(dpi), "-png", str(path), str(Path(d) / "p")], capture_output=True, timeout=60)
                f = next(Path(d).glob("p*.png"), None)
                if f:
                    return Image.open(f).convert("RGB"), dpi / 72.0
        except Exception:
            pass
    return None


def _fit(im: Image.Image, boxes, side: int = 1500):
    im, boxes = annotate.shrink_for_display(im, boxes, side)
    return im, boxes


def picture_change(P: Proofs, title: str, where: str, before: Image.Image | None, bboxes, after: Image.Image | None, aboxes, mode: str = "object", note: str = "") -> None:
    if P.full():
        P.more += 1
        return
    b = a = None
    if before is not None:
        bi, bb = _fit(annotate.to_rgb(before), bboxes or [])
        b = annotate.annotate(bi, bb, mode, arrows=True) if bb else bi
    if after is not None:
        ai, ab = _fit(annotate.to_rgb(after), aboxes or [])
        a = annotate.annotate(ai, ab, mode, arrows=True) if ab else ai
    P.add(title, where, b, a, note)


def framed(im: Image.Image) -> Image.Image:
    """the whole picture changed (turned, resized ...): no yellow wash, just a red frame around all of it"""
    from PIL import ImageDraw
    im = annotate.to_rgb(im)
    im, _ = _fit(im, [])
    pad = max(10, min(im.size) // 40)
    out = Image.new("RGB", (im.width + 2 * pad, im.height + 2 * pad), (255, 255, 255))
    out.paste(im, (pad, pad))
    ImageDraw.Draw(out).rounded_rectangle((pad // 2, pad // 2, out.width - pad // 2, out.height - pad // 2), radius=pad, outline=(226, 60, 40), width=max(4, pad // 2))
    return out


def pdf_page_changes(P: Proofs, src_pdf: Path | None, out_pdf: Path | None, pages: dict[int, list[tuple]], title: str, mode: str = "text", max_pages: int = 3) -> bool:
    """pages: {page_no (0-based): [(x0, y0, x1, y1) in PDF points, ...]}. Returns False when pages cannot be drawn on this computer."""
    ok = False
    for pno in sorted(pages)[:max_pages]:
        b = render_pdf_page(src_pdf, pno) if src_pdf else None
        a = render_pdf_page(out_pdf, pno) if out_pdf else None
        if b is None and a is None:
            return ok
        ok = True
        boxes = pages[pno]
        picture_change(P, f"{title} · page {pno + 1}", f"page {pno + 1}", b[0] if b else None, [tuple(v * b[1] for v in bx) for bx in boxes] if b else [], a[0] if a else None, [tuple(v * a[1] for v in bx) for bx in boxes] if a else [], mode)
    if len(pages) > max_pages:
        P.more += len(pages) - max_pages
    return ok


def image_diff_boxes(a: Image.Image, b: Image.Image, limit: int = 8):
    """rectangles where two same-sized pictures differ (empty when the sizes differ)"""
    import cv2
    import numpy as np
    if a.size != b.size:
        return []
    d = np.asarray(annotate.to_rgb(a), dtype=np.int16) - np.asarray(annotate.to_rgb(b), dtype=np.int16)
    mask = (np.abs(d).max(axis=2) > 14).astype("uint8") * 255
    if mask.mean() > 200:         # nearly everything changed: no useful rectangles
        return []
    k = max(5, min(a.size) // 60)
    mask = cv2.dilate(mask, np.ones((k, k), np.uint8))
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(mask)
    boxes = [(int(s[0]), int(s[1]), int(s[0] + s[2]), int(s[1] + s[3])) for s in stats[1:] if s[4] > 20]
    boxes.sort(key=lambda b_: -(b_[2] - b_[0]) * (b_[3] - b_[1]))
    return boxes[:limit]


def hex_rows(data: bytes, base: int, changed: set[int]) -> tuple[str, list[tuple[int, int]]]:
    """one hex dump text and the character ranges of changed bytes"""
    lines, spans, pos = [], [], 0
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        txt = f"{base + i:08X}  " + " ".join(f"{b:02X}" for b in chunk)
        for j in range(len(chunk)):
            if base + i + j in changed:
                s = pos + 10 + j * 3
                spans.append((s, s + 2))
        lines.append(txt)
        pos += len(txt) + 1
    merged: list[tuple[int, int]] = []
    for a, b in spans:                       # neighbouring bytes become one marked block
        if merged and a - merged[-1][1] <= 1 and "\n" not in "":
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return "\n".join(lines), merged
