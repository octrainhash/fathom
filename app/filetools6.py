"""File tools, part 6: check a redaction really removed the words, passport and ID photos, fit a video or song under a size limit.
Same plumbing as filetools4."""
from __future__ import annotations

import re
from pathlib import Path

from app.convert import formats
from app.convert.core import ConvertError, Opts
from app.filetools4 import _batch, _f, _is_pdf, _open_pdf
from app.service import UserError


# ---------------------------------------------------------------- did the redaction really remove it?
def redactcheck_start(paths, recursive, output, o) -> dict:
    raw = str(o.get("words") or "")
    words = [w.strip() for w in re.split(r"[\n,;]+", raw) if w.strip()]
    if not words and not o.get("hidden", True):
        raise UserError("Type the words that should be gone, or keep the hidden-data check on.")
    do_meta, do_hidden = bool(o.get("meta", True)), bool(o.get("hidden", True))

    def work(src, fmt, d, ctx):
        _fz, doc = _open_pdf(src, str(o.get("password") or ""))
        found: list[str] = []
        low = [w.lower() for w in words]
        for pno, page in enumerate(doc, 1):
            txt = page.get_text("text") or ""
            lt = txt.lower()
            for w, lw in zip(words, low):
                n = lt.count(lw)
                if n:
                    found.append(f"Page {pno}: the text layer still contains \"{w}\" ({n}x).")
            for a in (page.annots() or []):
                blob = " ".join(str(x) for x in (a.info.get("content"), a.info.get("title"), a.info.get("subject")) if x).lower()
                for w, lw in zip(words, low):
                    if lw in blob:
                        found.append(f"Page {pno}: a note or comment contains \"{w}\".")
            for wd in (page.widgets() or []):
                val = str(wd.field_value or "").lower()
                for w, lw in zip(words, low):
                    if lw in val:
                        found.append(f"Page {pno}: form field \"{wd.field_name}\" contains \"{w}\".")
            if do_hidden:
                try:
                    inv = 0
                    for b in page.get_text("dict", flags=0)["blocks"]:
                        for ln in b.get("lines", []):
                            for sp in ln.get("spans", []):
                                if sp.get("color") == 0xFFFFFF and sp.get("text", "").strip():
                                    inv += 1
                    if inv:
                        found.append(f"Page {pno}: {inv} piece(s) of white text, which is invisible on a white page but can be copied.")
                except Exception:
                    pass
                r = page.rect
                try:
                    for b in page.get_text("blocks"):
                        if b[2] < r.x0 - 2 or b[0] > r.x1 + 2 or b[3] < r.y0 - 2 or b[1] > r.y1 + 2:
                            found.append(f"Page {pno}: text hidden outside the page edge.")
                            break
                except Exception:
                    pass
        if do_meta:
            md = {k: v for k, v in (doc.metadata or {}).items() if v and k not in ("format", "encryption", "producer", "creator", "creationDate", "modDate", "trapped")}
            for k, v in md.items():
                for w, lw in zip(words, low):
                    if lw in str(v).lower():
                        found.append(f"Document details ({k}) contain \"{w}\".")
            xm = (doc.get_xml_metadata() or "").lower()
            for w, lw in zip(words, low):
                if lw in xm:
                    found.append(f"The hidden XMP data contains \"{w}\".")
            try:
                for name in doc.embfile_names():
                    found.append(f"An attached file is inside the PDF: {name}.")
            except Exception:
                pass
            try:
                for item in doc.get_toc():
                    for w, lw in zip(words, low):
                        if lw in str(item[1]).lower():
                            found.append(f"A bookmark contains \"{w}\".")
            except Exception:
                pass
        doc.close()
        dst = d / f"{src.stem} (redaction check).txt"
        verdict = "PASSED: nothing found." if not found else f"FAILED: {len(found)} leftover(s) found."
        body = [f"Redaction check for {src.name}", f"Words checked: {', '.join(words) or '(none, hidden-data check only)'}", "", verdict, ""] + found
        if found:
            body += ["", "How to fix: a black box drawn over text does NOT remove it. Use Find and replace or the Editor's redact tool so the text is truly deleted,", "then run this check again."]
        dst.write_text("\n".join(body), encoding="utf-8")
        return [dst], verdict

    return _batch("redactcheck", "Checking redactions", paths, recursive, output, _is_pdf, work, "Add a PDF file.")


# ---------------------------------------------------------------- passport and ID photos
PHOTO_SIZES = {"eu": (35, 45), "us": (51, 51), "uk": (35, 45), "in": (51, 51), "cn": (33, 48), "ca": (50, 70), "jp": (35, 45), "id": (25, 35), "au": (35, 45), "pk": (35, 45), "custom": (0, 0)}


def passport_start(paths, recursive, output, o) -> dict:
    size = str(o.get("size") or "eu")
    if size not in PHOTO_SIZES:
        raise UserError("Choose a photo size.")
    wmm, hmm = PHOTO_SIZES[size]
    if size == "custom":
        wmm, hmm = _f(o.get("w"), 35), _f(o.get("h"), 45)
    if not (10 <= wmm <= 120 and 10 <= hmm <= 160):
        raise UserError("Photo sizes must be between 10 and 160 millimetres.")
    dpi = int(max(150, min(600, _f(o.get("dpi"), 300))))
    head = max(0.5, min(0.9, _f(o.get("head"), 72) / 100.0))
    bg = str(o.get("bg") or "#ffffff")
    sheet = str(o.get("sheet") or "single")
    px = lambda mm: int(round(mm / 25.4 * dpi))

    def work(src, fmt, d, ctx):
        import cv2
        import numpy as np
        from PIL import Image, ImageOps

        from app import reference
        from app.convert.eng_image import load_frames, rw

        if fmt not in rw()[1]:
            raise ConvertError("Fathom cannot read this picture format.")
        frames, _d, _f0 = load_frames(src, fmt, all_frames=False)
        im = ImageOps.exif_transpose(frames[0]).convert("RGB")
        arr = np.array(im)
        faces = []
        if reference.faces_supported():
            if not reference.face_models_ready():
                reference.ensure_face_models()
            for row, _ft in reference._faces_in(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), True):
                faces.append((int(row[0]), int(row[1]), int(row[2]), int(row[3])))
        elif hasattr(cv2, "CascadeClassifier"):
            gray = cv2.equalizeHist(cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY))
            casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            faces = [tuple(int(v) for v in f) for f in casc.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))] if not casc.empty() else []
        if not faces:
            raise ConvertError("No face found. Use a clear front-facing photo with the whole face visible.")
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        cx, cy = x + w / 2, y + h / 2
        ch = h * 1.55 / head                      # the finder's box is about 1.4 times shorter than the whole head
        cw = ch * wmm / hmm
        left, top = cx - cw / 2, cy - ch * 0.5
        bgc = Image.new("RGB", im.size, bg).getpixel((0, 0))
        # crop with padding in the chosen colour where the picture runs out
        big = Image.new("RGB", (int(cw) + 2, int(ch) + 2), bgc)
        crop = im.crop((int(left), int(top), int(left) + int(cw) + 2, int(top) + int(ch) + 2))
        ox, oy = max(0, -int(left)), max(0, -int(top))
        big.paste(crop, (ox, oy))
        one = big.resize((px(wmm), px(hmm)), Image.LANCZOS)
        outs = []
        single = d / f"{src.stem} (passport {wmm:g}x{hmm:g}mm).jpg"
        one.save(single, quality=95, dpi=(dpi, dpi))
        outs.append(single)
        note = f"Photo {wmm:g} x {hmm:g} mm at {dpi} dpi."
        if sheet != "single":
            pw, ph = (px(152.4), px(101.6)) if sheet == "4x6" else (px(127), px(89)) if sheet == "5x3.5" else (px(210), px(297))
            if pw < ph and sheet != "a4":
                pw, ph = ph, pw
            gap = px(2)
            sh = Image.new("RGB", (pw, ph), "#ffffff")
            cols = max(1, (pw - gap) // (one.width + gap)); rows = max(1, (ph - gap) // (one.height + gap))
            gx = (pw - (cols * one.width + (cols - 1) * gap)) // 2; gy = (ph - (rows * one.height + (rows - 1) * gap)) // 2
            for r in range(rows):
                for c in range(cols):
                    sh.paste(one, (gx + c * (one.width + gap), gy + r * (one.height + gap)))
            sp = d / f"{src.stem} (passport sheet {sheet}).jpg"
            sh.save(sp, quality=95, dpi=(dpi, dpi))
            outs.append(sp)
            note += f" Print sheet with {cols * rows} copies."
        return outs, note

    return _batch("passport", "Making passport photos", paths, recursive, output, lambda f: formats.category(f) == "image", work, "Add a photo.")


# ---------------------------------------------------------------- fit under a size limit
def fitsize_start(paths, recursive, output, o) -> dict:
    mb = _f(o.get("mb"), 16)
    if not 0.1 <= mb <= 5000:
        raise UserError("The size limit must be between 0.1 and 5000 MB.")

    def work(src, fmt, d, ctx):
        from app.convert.eng_media import probe, run_ffmpeg

        if src.stat().st_size <= mb * 1024 * 1024:
            import shutil
            keep = d / src.name
            shutil.copy2(src, keep)
            return [keep], f"Already under {mb:g} MB, so it was left as it is."
        info = probe(ctx, src)
        dur = float(info["duration"] or 0)
        if dur <= 0:
            raise ConvertError("Could not read how long this file is.")
        cat = formats.category(fmt)
        budget = mb * 1024 * 1024 * 8 * 0.94
        for attempt in range(3):
            total = budget / dur * (0.88 ** attempt)
            if cat == "audio" or not info["video"]:
                kbps = int(max(24, min(320, total / 1000)))
                dst = d / f"{src.stem} ({mb:g}MB).mp3"
                run_ffmpeg(ctx, ["-i", src, "-vn", "-c:a", "libmp3lame", "-b:a", f"{kbps}k", dst], dur, "fit")
            else:
                akbps = 96 if total > 400_000 else 48
                vb = int(max(60_000, total - akbps * 1000))
                scale = "scale=-2:'min(ih,2160)'"
                h = 2160
                for limit, hh in ((150_000, 240), (350_000, 360), (800_000, 480), (1_600_000, 720), (3_500_000, 1080)):
                    if vb < limit:
                        h = hh
                        break
                scale = f"scale=-2:'min(ih,{h})'"
                dst = d / f"{src.stem} ({mb:g}MB).mp4"
                cmd = ["-i", src, "-vf", scale, "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(vb), "-maxrate", str(int(vb * 1.4)), "-bufsize", str(int(vb * 2)), "-pix_fmt", "yuv420p"]
                cmd += (["-c:a", "aac", "-b:a", f"{akbps}k", "-ac", "2"] if info["audio"] else ["-an"]) + ["-movflags", "+faststart", dst]
                run_ffmpeg(ctx, cmd, dur, "fit")
            if dst.exists() and dst.stat().st_size <= mb * 1024 * 1024:
                return [dst], f"Now {dst.stat().st_size / 1048576:.1f} MB (limit {mb:g} MB)."
        raise ConvertError(f"Could not get this under {mb:g} MB without ruining it. Try a higher limit or cut it shorter first.")

    return _batch("fitsize", "Fitting under the size limit", paths, recursive, output, lambda f: formats.category(f) in ("video", "audio"), work, "Add a video or song.", heavy=True)
