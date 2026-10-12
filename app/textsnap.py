"""Turn text hits (from .txt, .docx, .xlsx, binaries... anything without a real picture) into a picture
with the match highlighted and circled."""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = (252, 252, 249)
INK = (28, 31, 36)
MUTED = (139, 146, 158)
BAR = (236, 239, 243)
_CTRL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\CascadiaMono.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]
_font_cache: dict[int, ImageFont.ImageFont] = {}
SCALE = 2  # snapshots are drawn at 2x so they stay sharp when enlarged in the viewer


def get_font(size: int = 18):
    if size in _font_cache:
        return _font_cache[size]
    font = None
    for cand in _FONT_CANDIDATES:
        if Path(cand).exists():
            try:
                font = ImageFont.truetype(cand, size)
                break
            except Exception:
                continue
    if font is None:
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:
            font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def _prepare_row(text: str, spans: list[tuple[int, int, int]], radius: int = 150):
    """Keep character offsets valid: swap control chars, expand tabs, trim very long lines around the hits.
    spans = [(hit_index, start, end)]. Returns (display_text, [(hit_index, start, end)])."""
    text = _CTRL.sub("·", text)
    if "\t" in text:
        mapped = [(h, len(text[:s].expandtabs(4)), len(text[:e].expandtabs(4))) for h, s, e in spans]
        text = text.expandtabs(4)
    else:
        mapped = list(spans)
    if len(text) > 600 and mapped:
        lo = max(0, min(s for _, s, _ in mapped) - radius)
        hi = min(len(text), max(e for _, _, e in mapped) + radius)
        if hi - lo > 1200:  # hits are far apart: show around the first one
            hi = min(len(text), lo + 1200)
        cut = text[lo:hi]
        lead = "…" if lo > 0 else ""
        tail = "…" if hi < len(text) else ""
        mapped = [(h, max(0, s - lo) + len(lead), min(len(cut), e - lo) + len(lead)) for h, s, e in mapped if e > lo and s < hi]
        text = lead + cut + tail
    return text, mapped


def render_snapshot(rows: list[tuple[str, str]], hits: list[tuple[int, int, int]], title: str = "", cols: int = 96):
    """rows = [(label, text)], hits = [(row_index, start, end)].
    Returns (PIL image, boxes_per_hit) where boxes_per_hit[i] lists the rectangles for hits[i]."""
    S = SCALE
    font = get_font(18 * S)
    tfont = get_font(15 * S)
    line_h, margin = 27 * S, 18 * S
    visual: list[tuple[str, str]] = []
    hit_parts: list[list[tuple[int, int, int]]] = [[] for _ in hits]  # per hit: (visual_row, a, b)
    for ri, (label, text) in enumerate(rows):
        row_spans = [(hi, s, e) for hi, (r, s, e) in enumerate(hits) if r == ri]
        disp, spans = _prepare_row(text, row_spans)
        first_visual = len(visual)
        chunks = [disp[i:i + cols] for i in range(0, max(len(disp), 1), cols)] or [""]
        for ci, chunk in enumerate(chunks):
            visual.append((label if ci == 0 else "", chunk))
        for hi, s, e in spans:
            for ci, chunk in enumerate(chunks):
                off = ci * cols
                a, b = max(s, off), min(e, off + len(chunk))
                if b > a:
                    hit_parts[hi].append((first_visual + ci, a - off, b - off))
    label_w = max([font.getlength(v[0]) for v in visual] + [24.0 * S])
    text_w = max([font.getlength(v[1]) for v in visual] + [120.0 * S])
    bar_h = 38 * S if title else 0
    gutter = int(label_w) + 22 * S
    width = int(min(1700 * S, max(640 * S, gutter + text_w + margin * 2)))
    height = int(bar_h + margin * 2 + line_h * len(visual))
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    if title:
        draw.rectangle([0, 0, width, bar_h], fill=BAR)
        clipped = title if len(title) < 110 else title[:107] + "…"
        draw.text((margin, 9 * S), clipped, fill=(70, 76, 88), font=tfont)
    y = bar_h + margin
    ys = []
    for label, chunk in visual:
        ys.append(y)
        if label:
            draw.text((gutter - 12 * S - font.getlength(label), y), label, fill=MUTED, font=font)
        draw.text((gutter + margin - 6 * S, y), chunk, fill=INK, font=font)
        y += line_h
    boxes_per_hit: list[list[tuple[float, float, float, float]]] = []
    for parts in hit_parts:
        boxes = []
        for vi, a, b in parts:
            chunk = visual[vi][1]
            x0 = gutter + margin - 6 * S + font.getlength(chunk[:a])
            x1 = gutter + margin - 6 * S + font.getlength(chunk[:b])
            boxes.append((x0 - S, ys[vi] + S, max(x1, x0 + 6 * S), ys[vi] + line_h - 3 * S))
        boxes_per_hit.append(boxes)
    return image, boxes_per_hit
