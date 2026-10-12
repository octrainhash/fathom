"""Draws the Fathom logo: assets/fathom.ico (taskbar, window, shortcuts), static/fathom.svg and static/fathom.png (favicon)."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
S = 1024  # drawing size; everything is scaled from here


def gradient(size: int) -> Image.Image:
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / (size - 1)
    t = (x * 0.55 + y * 0.9) / 1.45
    stops = [(0.0, (14, 17, 40)), (0.55, (52, 40, 190)), (1.0, (140, 84, 255))]
    out = np.zeros((size, size, 3), np.float32)
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        m = (t >= a) & (t <= b)
        k = ((t - a) / (b - a))[..., None]
        out = np.where(m[..., None], np.array(ca) * (1 - k) + np.array(cb) * k, out)
    return Image.fromarray(out.astype(np.uint8), "RGB")


def draw(size: int = S) -> Image.Image:
    k = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(58 * k), fill=255)
    img.paste(gradient(size), (0, 0), mask)
    # soft glow behind the dot
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = 128 * k, 134 * k
    for r, a in ((120, 18), (90, 26), (62, 34)):
        gd.ellipse([cx - r * k, cy - r * k, cx + r * k, cy + r * k], fill=(255, 235, 59, a))
    img = Image.alpha_composite(img, Image.composite(glow, Image.new("RGBA", glow.size, (0, 0, 0, 0)), mask))
    ripple = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ripple)
    for r, op, w in ((70, 235, 9), (108, 150, 8), (146, 95, 7), (184, 55, 6), (222, 30, 5)):   # ripples that spread from the find
        rd.ellipse([cx - r * k, cy - r * k, cx + r * k, cy + r * k], outline=(255, 255, 255, op), width=int(w * k))
    img = Image.alpha_composite(img, Image.composite(ripple, Image.new("RGBA", ripple.size, (0, 0, 0, 0)), mask))
    d = ImageDraw.Draw(img)
    d.ellipse([cx - 26 * k, cy - 26 * k, cx + 26 * k, cy + 26 * k], fill=(255, 235, 59, 255))                  # highlighted
    d.ellipse([cx - 42 * k, cy - 42 * k, cx + 42 * k, cy + 42 * k], outline=(232, 62, 40, 255), width=int(9 * k))   # circled
    return img


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0e1128"/><stop offset=".55" stop-color="#3428be"/><stop offset="1" stop-color="#8c54ff"/></linearGradient><clipPath id="c"><rect width="256" height="256" rx="58"/></clipPath></defs>
<rect width="256" height="256" rx="58" fill="url(#g)"/>
<circle cx="128" cy="134" r="62" fill="#ffeb3b" opacity=".13"/>
<g clip-path="url(#c)" fill="none" stroke="#fff"><circle cx="128" cy="134" r="70" stroke-width="9" opacity=".92"/><circle cx="128" cy="134" r="108" stroke-width="8" opacity=".59"/><circle cx="128" cy="134" r="146" stroke-width="7" opacity=".37"/><circle cx="128" cy="134" r="184" stroke-width="6" opacity=".22"/><circle cx="128" cy="134" r="222" stroke-width="5" opacity=".12"/></g>
<circle cx="128" cy="134" r="26" fill="#ffeb3b"/><circle cx="128" cy="134" r="42" fill="none" stroke="#e83e28" stroke-width="9"/></svg>
"""


def arc_pts(r: float):
    import math
    cx, cy = 128, 158
    f = lambda a: f"{cx + r * math.cos(math.radians(a)):.1f} {cy + r * math.sin(math.radians(a)):.1f}"
    return f(217), f(323)


if __name__ == "__main__":
    big = draw(S)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    (ROOT / "assets").mkdir(exist_ok=True)
    big.resize((256, 256), Image.Resampling.LANCZOS).save(ROOT / "assets" / "fathom.ico", sizes=[(s, s) for s in sizes])
    big.resize((256, 256), Image.Resampling.LANCZOS).save(ROOT / "static" / "fathom.png")
    a1, a2 = arc_pts(66); b1, b2 = arc_pts(98); c1, c2 = arc_pts(130)
    (ROOT / "static" / "fathom.svg").write_text(SVG, encoding="utf-8")
    print("icons written")
