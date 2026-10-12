"""Pictures, voice and video for the assistant.

  * design_image  - draws posters, cards, covers, banners, diagrams from layers (text, shapes, pictures, gradients). Works offline.
  * generate_image - photo-style / artistic pictures from a text description through an image service you set up (OpenAI-compatible or a local
                     Stable Diffusion server). Without one, it says so plainly.
  * speak          - text to speech (Windows voices, or an OpenAI-compatible voice service)
  * make_video     - slideshow-style videos with captions, motion (zoom / pan), fades, narration and music, finished as an H.264 .mp4
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from app.ai import store
from app.runtime import no_window_flags
from app.service import UserError


# ================================================================== fonts
def _font(size: int, bold: bool = False, family: str = "sans"):
    from PIL import ImageFont

    from app.ai import docs
    fam = docs._FAMILIES.get(family, docs._FAMILIES["sans"])
    for names in fam:
        p = docs._find_font(names[1] if bold else names[0])
        if p:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def _hex(c, default="#000000"):
    c = (c or default)
    if isinstance(c, (list, tuple)):
        return tuple(int(x) for x in c)
    c = str(c).strip()
    names = {"white": "#ffffff", "black": "#000000", "red": "#e03131", "blue": "#1c7ed6", "green": "#2f9e44", "yellow": "#fcc419", "orange": "#f76707", "purple": "#7048e8", "gray": "#868e96", "grey": "#868e96", "transparent": "#00000000"}
    c = names.get(c.lower(), c)
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(x * 2 for x in c)
    if len(c) == 6:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    if len(c) == 8:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4, 6))
    return (0, 0, 0, 255)


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split(" "):
            t = (cur + " " + word).strip()
            if draw.textlength(t, font=font) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _gradient(w: int, h: int, c1, c2, angle: float = 90):
    import numpy as np
    from PIL import Image

    a, b = np.array(_hex(c1)[:3], float), np.array(_hex(c2)[:3], float)
    ys, xs = np.mgrid[0:h, 0:w]
    th = np.deg2rad(angle)
    t = (xs / max(w - 1, 1)) * np.cos(th) + (ys / max(h - 1, 1)) * np.sin(th)
    t = (t - t.min()) / max(t.max() - t.min(), 1e-6)
    arr = a[None, None, :] * (1 - t[..., None]) + b[None, None, :] * t[..., None]
    return Image.fromarray(arr.astype("uint8")).convert("RGBA")


def design_image(spec: dict, path: Path, base_dir: Path | None = None) -> dict:
    """spec = {width,height,background: '#hex' | {gradient:[c1,c2],angle} | {image:path,fit:'cover'}, layers:[...]}
    layer types: text {text,x,y,size,color,bold,font:'sans|serif|mono',align:'left|center|right',max_width,line_height,shadow,stroke}
                 rect {x,y,w,h,color,radius,outline,width}   ellipse {x,y,w,h,color,outline,width}   line {x1,y1,x2,y2,color,width}
                 image {path,x,y,w,h,fit:'contain|cover',radius,opacity}   gradient {x,y,w,h,colors:[c1,c2],angle}
    x/y/w/h are pixels, or a string like '50%'. x:'center' centres horizontally."""
    from PIL import Image, ImageDraw, ImageFilter

    W, H = int(spec.get("width", 1280)), int(spec.get("height", 720))
    if W * H > 36_000_000:
        raise UserError("That picture size is too big to draw safely; use under 36 megapixels.")

    def px(v, total, default=0):
        if v is None:
            return default
        if isinstance(v, str):
            if v == "center":
                return None
            if v.endswith("%"):
                return int(float(v[:-1]) / 100 * total)
            return int(float(v))
        return int(v)

    bg = spec.get("background", "#ffffff")
    if isinstance(bg, dict) and bg.get("gradient"):
        g = bg["gradient"]
        img = _gradient(W, H, g[0], g[1], float(bg.get("angle", 90)))
    elif isinstance(bg, dict) and bg.get("image"):
        src = _open_img(bg["image"], base_dir)
        img = _fit(src, W, H, bg.get("fit", "cover"))
    else:
        img = Image.new("RGBA", (W, H), _hex(bg, "#ffffff"))
    for ly in spec.get("layers", []):
        t = ly.get("type", "text")
        ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        x, y = px(ly.get("x"), W), px(ly.get("y"), H)
        if t == "text":
            size = int(ly.get("size", 48))
            font = _font(size, bool(ly.get("bold")), ly.get("font", "sans"))
            maxw = px(ly.get("max_width"), W, W - 2 * (x or 0) if x is not None else W - 80)
            lines = _wrap(d, ly.get("text", ""), font, maxw)
            lh = int(size * float(ly.get("line_height", 1.25)))
            align = ly.get("align", "left")
            total_h = lh * len(lines)
            yy = (H - total_h) // 2 if ly.get("y") == "center" else y
            for ln in lines:
                lw = d.textlength(ln, font=font)
                if x is None:
                    xx = (W - lw) / 2
                elif align == "center":
                    xx = x + (maxw - lw) / 2
                elif align == "right":
                    xx = x + maxw - lw
                else:
                    xx = x
                if ly.get("shadow"):
                    d.text((xx + 3, yy + 3), ln, font=font, fill=(0, 0, 0, 110))
                d.text((xx, yy), ln, font=font, fill=_hex(ly.get("color"), "#111111"), stroke_width=int(ly.get("stroke", 0)), stroke_fill=_hex(ly.get("stroke_color"), "#000000"))
                yy += lh
        elif t in ("rect", "ellipse"):
            w, h = px(ly.get("w"), W, 100), px(ly.get("h"), H, 100)
            x0 = (W - w) // 2 if x is None else x
            y0 = (H - h) // 2 if ly.get("y") == "center" else y
            box = [x0, y0, x0 + w, y0 + h]
            kw = dict(fill=_hex(ly.get("color")) if ly.get("color") else None, outline=_hex(ly.get("outline")) if ly.get("outline") else None, width=int(ly.get("width", 2)))
            if t == "rect":
                d.rounded_rectangle(box, radius=int(ly.get("radius", 0)), **kw)
            else:
                d.ellipse(box, **kw)
        elif t == "line":
            d.line([px(ly.get("x1"), W), px(ly.get("y1"), H), px(ly.get("x2"), W), px(ly.get("y2"), H)], fill=_hex(ly.get("color"), "#000000"), width=int(ly.get("width", 3)))
        elif t == "gradient":
            w, h = px(ly.get("w"), W, W), px(ly.get("h"), H, H)
            c = ly.get("colors", ["#000000", "#ffffff"])
            g = _gradient(w, h, c[0], c[1], float(ly.get("angle", 90)))
            if ly.get("opacity") is not None:
                g.putalpha(int(255 * float(ly["opacity"])))
            img.alpha_composite(g, (x or 0, y or 0))
        elif t == "image":
            src = _open_img(ly.get("path", ""), base_dir)
            w, h = px(ly.get("w"), W, src.width), px(ly.get("h"), H, src.height)
            pic = _fit(src, w, h, ly.get("fit", "contain"), transparent=True)
            if ly.get("radius"):
                m = Image.new("L", pic.size, 0)
                ImageDraw.Draw(m).rounded_rectangle([0, 0, pic.width - 1, pic.height - 1], radius=int(ly["radius"]), fill=255)
                pic.putalpha(Image.composite(pic.getchannel("A"), Image.new("L", pic.size, 0), m))
            if ly.get("opacity") is not None:
                a = pic.getchannel("A").point(lambda v: int(v * float(ly["opacity"])))
                pic.putalpha(a)
            if ly.get("shadow"):
                sh = Image.new("RGBA", (pic.width + 40, pic.height + 40), (0, 0, 0, 0))
                sh.paste((0, 0, 0, 120), (20, 28, 20 + pic.width, 28 + pic.height), pic.getchannel("A"))
                sh = sh.filter(ImageFilter.GaussianBlur(10))
                img.alpha_composite(sh, ((W - pic.width) // 2 - 20 if x is None else x - 20, y - 20))
            img.alpha_composite(pic, ((W - pic.width) // 2 if x is None else x, y))
        if t in ("text", "rect", "ellipse", "line"):
            img.alpha_composite(ov)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".jpg", ".jpeg"):
        img.convert("RGB").save(path, quality=93)
    else:
        img.save(path)
    return {"path": str(path), "size": [W, H]}


def _open_img(src: str, base: Path | None):
    from PIL import Image

    if isinstance(src, str) and src.startswith("data:image"):
        return Image.open(io.BytesIO(base64.b64decode(src.split(",", 1)[1]))).convert("RGBA")
    p = Path(str(src))
    if not p.is_absolute() and base:
        p = base / p
    if not p.exists():
        raise UserError(f"Picture not found: {src}")
    try:
        im = Image.open(p)
        im.seek(0)
        return im.convert("RGBA")
    except Exception:
        from app import pdfview
        data, _m = pdfview.page_png(p, 1, 1600)
        return Image.open(io.BytesIO(data)).convert("RGBA")


def _fit(src, w: int, h: int, mode: str = "contain", transparent: bool = False):
    from PIL import Image

    sw, sh = src.size
    if mode == "cover":
        sc = max(w / sw, h / sh)
        im = src.resize((max(1, int(sw * sc)), max(1, int(sh * sc))), Image.LANCZOS)
        l, t = (im.width - w) // 2, (im.height - h) // 2
        return im.crop((l, t, l + w, t + h))
    if mode == "stretch":
        return src.resize((w, h), Image.LANCZOS)
    sc = min(w / sw, h / sh)
    im = src.resize((max(1, int(sw * sc)), max(1, int(sh * sc))), Image.LANCZOS)
    if transparent:
        return im
    out = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    out.paste(im, ((w - im.width) // 2, (h - im.height) // 2), im)
    return out


# ================================================================== image service
def _http_json(url: str, headers: dict, body: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")[:500]
        raise UserError(f"The image service said {e.code}: {txt}")
    except (urllib.error.URLError, OSError) as e:
        raise UserError(f"Could not reach the image service ({e}). Check its address in the Assistant settings.")


def generate_image(prompt: str, path: Path, size: str = "", negative: str = "", seed: int | None = None) -> dict:
    cfg = store.load()["image"]
    prov = cfg.get("provider", "none")
    if prov == "none":
        raise UserError("No picture-making service is set up yet. Open Assistant > Settings > Pictures and choose OpenAI (needs a key) or a local Stable Diffusion server. "
                        "Meanwhile I can still draw posters, cards, covers and diagrams myself with design_image.")
    size = size or cfg.get("size") or "1024x1024"
    path.parent.mkdir(parents=True, exist_ok=True)
    if prov == "openai":
        key = store.get_secret("image") or store.get_secret("openai")
        if not key:
            raise UserError("Add your image-service key in Assistant > Settings > Pictures.")
        model = cfg.get("model") or "gpt-image-1"
        body = {"model": model, "prompt": prompt, "size": size, "n": 1}
        if model.startswith("dall-e"):
            body["response_format"] = "b64_json"
        j = _http_json(cfg["base_url"].rstrip("/") + "/images/generations", {"Authorization": "Bearer " + key}, body)
        item = (j.get("data") or [{}])[0]
        if item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            raw = urllib.request.urlopen(item["url"], timeout=120).read()
        else:
            raise UserError("The image service returned no picture.")
    elif prov == "a1111":
        w, h = (int(x) for x in (size if "x" in size else "512x512").split("x"))
        body = {"prompt": prompt, "negative_prompt": negative, "width": w, "height": h, "steps": 28, "cfg_scale": 7}
        if seed is not None:
            body["seed"] = seed
        base = (cfg.get("base_url") or "http://127.0.0.1:7860").rstrip("/")
        j = _http_json(base + "/sdapi/v1/txt2img", {}, body, 900)
        if not j.get("images"):
            raise UserError("The local Stable Diffusion server returned no picture.")
        raw = base64.b64decode(j["images"][0].split(",", 1)[-1])
    else:
        raise UserError(f"Unknown image service '{prov}'.")
    from PIL import Image
    im = Image.open(io.BytesIO(raw))
    if path.suffix.lower() in (".jpg", ".jpeg"):
        im.convert("RGB").save(path, quality=94)
    else:
        im.save(path)
    return {"path": str(path), "size": list(im.size)}


# ================================================================== voice
def speak(text: str, path: Path, voice: str = "", lang: str = "") -> dict:
    cfg = store.load()["tts"]
    path.parent.mkdir(parents=True, exist_ok=True)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise UserError("There is nothing to read aloud.")
    if cfg.get("provider") == "openai":
        key = store.get_secret("tts") or store.get_secret("openai")
        if not key:
            raise UserError("Add your voice-service key in Assistant > Settings > Voice.")
        req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/audio/speech", data=json.dumps({"model": cfg.get("model") or "tts-1", "input": text[:4000], "voice": voice or cfg.get("voice") or "alloy", "response_format": "mp3"}).encode(),
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
        try:
            data = urllib.request.urlopen(req, timeout=180).read()
        except urllib.error.HTTPError as e:
            raise UserError(f"The voice service said {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
        out = path.with_suffix(".mp3")
        out.write_bytes(data)
        return {"path": str(out)}
    out = path.with_suffix(".wav")
    lang = (lang or "").split("-")[0].lower()
    if os.name == "nt":
        ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$picked=$false; if($env:FX_VOICE){try{$s.SelectVoice($env:FX_VOICE);$picked=$true}catch{}}; "
              "if(-not $picked -and $env:FX_LANG){$v=$s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq $env:FX_LANG } | Select-Object -First 1; if($v){$s.SelectVoice($v.VoiceInfo.Name)}}; "
              "if(-not $picked -and $env:FX_LANG -and $env:FX_LANG -ne 'en'){ "
              # no classic voice for this language: Windows' newer voices (Settings > Time & language > Speech) are read through the Windows speech API instead
              "try{ Add-Type -AssemblyName System.Runtime.WindowsRuntime; [void][Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime]; "
              "$m=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1; "
              "$vv=[Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.Language.Split('-')[0] -eq $env:FX_LANG } | Select-Object -First 1; "
              "if(-not $vv){ exit 3 }; "
              "$w=New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer; $w.Voice=$vv; "
              "$t=$m.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke($null,@($w.SynthesizeTextToStreamAsync($env:FX_TEXT))); [void]$t.Wait(-1); "
              "$st=[System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($t.Result); $f=[System.IO.File]::Create($env:FX_OUT); $st.CopyTo($f); $f.Close(); exit 0 "
              "}catch{ exit 3 } }; "
              "$s.SetOutputToWaveFile($env:FX_OUT); $s.Speak($env:FX_TEXT); $s.Dispose()")
        env = dict(os.environ, FX_TEXT=text, FX_OUT=str(out), FX_VOICE=voice or cfg.get("voice") or "", FX_LANG=lang)
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True, env=env, timeout=600, creationflags=no_window_flags())
        if r.returncode == 3:
            raise UserError("NOVOICE:" + lang)
        if r.returncode or not out.exists():
            raise UserError("Windows could not make the voice file: " + (r.stderr or "")[:300])
        return {"path": str(out)}
    if sys.platform == "darwin" and shutil.which("say"):
        aiff = path.with_suffix(".aiff")
        cmd = ["say", "-o", str(aiff)]
        if voice or cfg.get("voice"):
            cmd += ["-v", voice or cfg.get("voice")]
        subprocess.run(cmd + [text], capture_output=True, timeout=300)
        if aiff.exists():
            try:
                exe, _ = _ff()
                subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(aiff), str(out)], capture_output=True, timeout=120)
            finally:
                aiff.unlink(missing_ok=True)
            if out.exists():
                return {"path": str(out)}
    for exe, args in (("espeak-ng", (["-v", lang] if lang else []) + ["-w", str(out), text]), ("espeak", (["-v", lang] if lang else []) + ["-w", str(out), text]), ("flite", ["-t", text, "-o", str(out)])):
        if shutil.which(exe):
            subprocess.run([exe, *args], capture_output=True, timeout=300)
            if out.exists():
                return {"path": str(out)}
    raise UserError("No voice is available on this computer (Windows and macOS have one built in; on Linux install espeak-ng; or set up an online voice in Assistant > Settings > Voice).")


# ================================================================== video
def _ff() -> tuple[str, str]:
    from app import video
    return video._ffmpeg()


def _duration(path: Path) -> float:
    exe, _ = _ff()
    r = subprocess.run([exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True, creationflags=no_window_flags())
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def _scene_frame(sc: dict, W: int, H: int, theme: dict, base: Path | None):
    from PIL import Image, ImageDraw

    if sc.get("design"):
        tmp = Path(tempfile.mkdtemp()) / "s.png"
        d = dict(sc["design"])
        d.setdefault("width", W)
        d.setdefault("height", H)
        design_image(d, tmp, base)
        return Image.open(tmp).convert("RGB")
    bgc = sc.get("color") or theme.get("background") or "#10131c"
    if sc.get("image"):
        src = _open_img(sc["image"], base)
        im = _fit(src, W, H, sc.get("fit", "cover")).convert("RGB")
    elif isinstance(bgc, list):
        im = _gradient(W, H, bgc[0], bgc[1], 120).convert("RGB")
    else:
        im = Image.new("RGB", (W, H), _hex(bgc)[:3])
    base_im = im.convert("RGBA")
    ov = Image.new("RGBA", base_im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    if sc.get("title"):
        size = int(H * 0.085)
        font = _font(size, True)
        lines = _wrap(d, sc["title"], font, int(W * 0.84))
        total = len(lines) * int(size * 1.2)
        y = int(H * 0.3) - total // 2 if sc.get("text") else (H - total) // 2
        if sc.get("image"):
            d.rectangle([0, y - 30, W, y + total + 30], fill=(0, 0, 0, 120))
        for ln in lines:
            d.text(((W - d.textlength(ln, font=font)) / 2, y), ln, font=font, fill=_hex(theme.get("title_color"), "#ffffff"))
            y += int(size * 1.2)
    if sc.get("text"):
        size = int(H * 0.048)
        font = _font(size)
        lines = _wrap(d, sc["text"], font, int(W * 0.8))
        y = int(H * 0.5)
        if sc.get("image"):
            d.rectangle([int(W * 0.06), y - 20, int(W * 0.94), y + len(lines) * int(size * 1.4) + 20], fill=(0, 0, 0, 130))
        for ln in lines:
            d.text(((W - d.textlength(ln, font=font)) / 2, y), ln, font=font, fill=_hex(theme.get("text_color"), "#e9ecf5"))
            y += int(size * 1.4)
    base_im.alpha_composite(ov)
    return base_im.convert("RGB")


def _caption(im, text: str):
    from PIL import Image, ImageDraw

    W, H = im.size
    im = im.copy().convert("RGBA")
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    size = max(16, int(H * 0.042))
    font = _font(size, True)
    lines = _wrap(d, text, font, int(W * 0.84))
    lh = int(size * 1.3)
    top = H - int(H * 0.07) - lh * len(lines)
    d.rounded_rectangle([int(W * 0.06), top - 14, int(W * 0.94), top + lh * len(lines) + 10], radius=14, fill=(0, 0, 0, 150))
    for ln in lines:
        d.text(((W - d.textlength(ln, font=font)) / 2, top), ln, font=font, fill=(255, 255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0, 255))
        top += lh
    im.alpha_composite(ov)
    return im.convert("RGB")


def make_video(scenes: list[dict], path: Path, opts: dict | None = None, base_dir: Path | None = None, cancel=None, progress=None) -> dict:
    """scenes: [{image?|color?|design?, title?, text?, caption?, seconds?, narration?, motion?: 'zoom_in'|'zoom_out'|'pan_left'|'pan_right'|'none', transition?}]
    opts: {width,height,fps,music:path,music_volume,theme:{...},voice,fade:seconds}"""
    from PIL import Image

    opts = opts or {}
    if not scenes:
        raise UserError("A video needs at least one scene.")
    if len(scenes) > 200:
        raise UserError("Please keep a video to 200 scenes or fewer in one go; make it in parts and join them with Merge.")
    W, H = int(opts.get("width", 1280)), int(opts.get("height", 720))
    W, H = W - W % 2, H - H % 2
    fps = int(opts.get("fps", 30))
    fade = float(opts.get("fade", 0.4))
    theme = opts.get("theme") or {}
    exe, codec = _ff()
    work = Path(tempfile.mkdtemp(prefix="fxvid_"))
    clips = []
    try:
        for i, sc in enumerate(scenes):
            if cancel is not None and cancel.is_set():
                raise UserError("Cancelled.")
            if progress:
                progress(i / len(scenes), f"Scene {i + 1} of {len(scenes)}")
            secs = float(sc.get("seconds") or 4)
            audio = None
            if sc.get("narration") and opts.get("narrate", True):
                try:
                    a = speak(sc["narration"], work / f"a{i}", sc.get("voice") or opts.get("voice") or "")
                    audio = Path(a["path"])
                    secs = max(secs if sc.get("seconds") else 0, _duration(audio) + 0.35)
                except UserError as e:
                    if opts.get("narrate_required"):
                        raise
                    audio = None
            frame = _scene_frame(sc, W, H, theme, base_dir)
            if sc.get("caption"):
                frame = _caption(frame, sc["caption"])
            motion = sc.get("motion") or opts.get("motion") or ("zoom_in" if sc.get("image") else "none")
            # render the frames ourselves (Pillow) so every ffmpeg build works, with a slow zoom or pan
            n = max(1, int(round(secs * fps)))
            big = frame.resize((int(W * 1.18), int(H * 1.18)), Image.LANCZOS) if motion != "none" else frame
            png_dir = work / f"f{i}"
            png_dir.mkdir()
            for k in range(n):
                t = k / max(n - 1, 1)
                if motion == "none":
                    fr = frame
                else:
                    bw, bh = big.size
                    if motion == "zoom_out":
                        z = 1.18 - 0.18 * t
                    elif motion in ("pan_left", "pan_right"):
                        z = 1.12
                    else:
                        z = 1.0 + 0.18 * t
                    cw, ch = int(bw / 1.18 * z / 1.0), int(bh / 1.18 * z / 1.0)
                    cw, ch = min(bw, int(W * z)), min(bh, int(H * z))
                    if motion == "pan_left":
                        l = int((bw - cw) * (1 - t))
                    elif motion == "pan_right":
                        l = int((bw - cw) * t)
                    else:
                        l = (bw - cw) // 2
                    tp = (bh - ch) // 2
                    fr = big.crop((l, tp, l + cw, tp + ch)).resize((W, H), Image.BILINEAR)
                fr.save(png_dir / f"{k:05d}.jpg", quality=90)
            clip = work / f"c{i}.mp4"
            cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps), "-i", str(png_dir / "%05d.jpg")]
            if audio:
                cmd += ["-i", str(audio)]
            else:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
            vf = []
            if fade > 0 and secs > fade * 3:
                vf.append(f"fade=t=in:st=0:d={fade}")
                vf.append(f"fade=t=out:st={max(0, secs - fade):.2f}:d={fade}")
            cmd += (["-vf", ",".join(vf)] if vf else []) + ["-c:v", codec, "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-ar", "44100", "-ac", "2", "-t", f"{secs:.3f}", "-shortest", str(clip)]
            r = subprocess.run(cmd, capture_output=True, text=True, creationflags=no_window_flags())
            if r.returncode or not clip.exists():
                raise UserError("Video encoder failed: " + (r.stderr or "")[-400:])
            shutil.rmtree(png_dir, ignore_errors=True)
            clips.append(clip)
        lst = work / "list.txt"
        lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        joined = work / "joined.mp4"
        r = subprocess.run([exe, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)], capture_output=True, text=True, creationflags=no_window_flags())
        if r.returncode:
            raise UserError("Could not join the scenes: " + (r.stderr or "")[-300:])
        music = opts.get("music")
        if music and Path(music).exists():
            vol = float(opts.get("music_volume", 0.22))
            r = subprocess.run([exe, "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-stream_loop", "-1", "-i", str(music), "-filter_complex",
                                f"[1:a]volume={vol}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(path)],
                               capture_output=True, text=True, creationflags=no_window_flags())
            if r.returncode:
                raise UserError("Could not add the music: " + (r.stderr or "")[-300:])
        else:
            shutil.copy(joined, path)
        return {"path": str(path), "seconds": round(_duration(path), 1), "scenes": len(scenes), "size": [W, H]}
    finally:
        shutil.rmtree(work, ignore_errors=True)
