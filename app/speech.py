# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Optional: find spoken words in audio files and in videos (faster-whisper, runs offline once the model is downloaded)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.annotate import annotate, crop_thumb, save_image, union_box
from app.paths import data_root, models_dir
from app.query import find_spans, make_snippet
from app.runtime import ML_LOCK, cpu_threads, no_window_flags
from app.textsnap import get_font, render_snapshot

_models: dict = {}


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def _audio(path: Path):
    """The recording as 16 kHz mono numbers, decoded by the bundled ffmpeg.

    faster-whisper otherwise opens the file through PyAV, and PyAV versions disagree about its
    options (the error "open() got an unexpected keyword argument 'metadata_errors'"). Decoding here
    avoids that. If ffmpeg is missing or fails, the file path is returned and faster-whisper tries itself."""
    try:
        from app.convert.core import ffmpeg_exe

        exe = ffmpeg_exe()
        if not exe:
            return str(path)
        r = subprocess.run([exe, "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                           capture_output=True, timeout=600, creationflags=no_window_flags())
        if r.returncode or not r.stdout:
            return str(path)
        return np.frombuffer(r.stdout, dtype=np.float32).copy()
    except Exception:
        return str(path)


def _patch_av() -> None:
    """Old PyAV versions reject the 'metadata_errors' option that faster-whisper passes when it opens a recording
    ("open() got an unexpected keyword argument 'metadata_errors'"). When that happens, retry without the option."""
    try:
        import av
    except Exception:
        return
    if getattr(av, "_fathom_patched", False):
        return
    orig = av.open

    def _open(*args, **kwargs):
        try:
            return orig(*args, **kwargs)
        except TypeError as exc:
            if "unexpected keyword" in str(exc) and ("metadata_errors" in kwargs or "metadata_encoding" in kwargs):
                kwargs.pop("metadata_errors", None)
                kwargs.pop("metadata_encoding", None)
                return orig(*args, **kwargs)
            raise

    av.open = _open
    av._fathom_patched = True


def _model(size: str):
    if size not in _models:
        if not available():
            raise RuntimeError("Spoken-word search needs the optional 'faster-whisper' package (run Fathom.bat repair with internet to install it).")
        _patch_av()
        from faster_whisper import WhisperModel

        _models[size] = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=cpu_threads(), download_root=str(models_dir() / "whisper"))
    return _models[size]


WHISPER_SIZES = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo", "distil-large-v3", "tiny.en", "base.en", "small.en", "medium.en")


def _regroup(words: list[dict], maxchars: int) -> list[dict]:
    """Cuts long spoken passages into shorter subtitle lines at word boundaries."""
    out: list[dict] = []
    cur: list[dict] = []
    for w in words:
        cur.append(w)
        text = "".join(x["word"] for x in cur).strip()
        if len(text) >= maxchars or w["word"].strip().endswith((".", "?", "!", "。")) and len(text) > maxchars * 0.5:
            out.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": text})
            cur = []
    if cur:
        out.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": "".join(x["word"] for x in cur).strip()})
    return [x for x in out if x["text"]]


def transcribe(path: Path, size: str, cancel, task: str = "transcribe", language: str = "", beam: int = 5, vad: bool = True, prompt: str = "", maxchars: int = 0) -> list[dict]:
    """[{'start', 'end', 'text'}]. Cached, so searching the same recording again is instant.
    task='translate' writes English text whatever language is spoken (Whisper's own translation)."""
    size = size if size in WHISPER_SIZES else "base"
    st = path.stat()
    plain = task == "transcribe" and not language and beam == 5 and vad and not prompt and not maxchars
    extra = "" if plain else f"|{task}|{language}|{beam}|{vad}|{prompt}|{maxchars}"
    key = hashlib.sha1(f"{path}|{size}|{st.st_size}|{st.st_mtime_ns}{extra}".encode()).hexdigest()
    cache_dir = data_root() / "transcripts"
    cache_dir.mkdir(exist_ok=True)
    cache = cache_dir / f"{key}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    model = _model(size)
    segments = []
    with ML_LOCK:
        gen, _info = model.transcribe(_audio(path), vad_filter=bool(vad), task="translate" if task == "translate" else "transcribe", language=language or None,
                                      beam_size=max(1, min(10, int(beam))), initial_prompt=prompt or None, word_timestamps=bool(maxchars))
        for seg in gen:
            if cancel.is_set():
                return segments
            if maxchars and getattr(seg, "words", None):
                segments += _regroup([{"word": w.word, "start": float(w.start), "end": float(w.end)} for w in seg.words], int(maxchars))
                continue
            text = seg.text.strip()
            if text:
                segments.append({"start": float(seg.start), "end": float(seg.end), "text": text})
    cache.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    return segments


def _matches(ctx, segments):
    for i, seg in enumerate(segments):
        for s, e in find_spans(ctx.pattern, seg["text"]):
            frac = s / max(len(seg["text"]), 1)
            yield i, seg, s, e, seg["start"] + (seg["end"] - seg["start"]) * frac


def _mmss(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def search_audio(ctx, path: Path, display: str, origin: Path) -> None:
    from app.video import _ffmpeg, stamp

    segments = transcribe(path, ctx.opts.speech_model, ctx.cancel)
    for i, seg, s, e, t in _matches(ctx, segments):
        if ctx.cancelled:
            return
        lo, hi = max(0, i - 1), min(len(segments), i + 2)
        rows = [(_mmss(x["start"]), x["text"]) for x in segments[lo:hi]]
        image, boxes = render_snapshot(rows, [(i - lo, s, e)], title=f"{display}   -   spoken at {stamp(t)}")
        annotated = annotate(image, boxes[0], "text")
        rid = ctx.next_id()
        full = save_image(annotated, ctx.out_dir / f"{rid}_full", photo_like=False)
        crop_thumb(annotated, union_box(boxes[0])).save(ctx.out_dir / f"{rid}_t.jpg", "JPEG", quality=84)
        result = {
            "file": display, "path": str(origin), "where": stamp(t), "kind": "speech", "t": round(t, 3),
            "snippet": make_snippet(seg["text"], s, e), "thumb": ctx.url(f"{rid}_t.jpg"), "image": ctx.url(full),
        }
        try:
            exe, _ = _ffmpeg()
            out = ctx.out_dir / f"{rid}.m4a"
            pre, post = max(ctx.opts.before, 2.0), max(ctx.opts.after, 2.0)
            subprocess.run([exe, "-y", "-loglevel", "error", "-ss", f"{max(0.0, t - pre):.2f}", "-t", f"{pre + post + 1:.2f}",
                            "-i", str(path), "-vn", "-c:a", "aac", "-b:a", "128k", str(out)],
                           check=True, capture_output=True, creationflags=no_window_flags(), timeout=300)
            result["audio"] = ctx.url(out.name)
        except Exception as exc:
            ctx.error(display, f"Could not cut the audio snippet at {stamp(t)}: {exc}")
        ctx.emit(result)


def _grab_frame(path: Path, t: float):
    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def _caption(frame_bgr, text: str, s: int, e: int):
    """Burn the spoken sentence into the picture, with the matched words highlighted."""
    img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")
    w, h = img.size
    size = max(16, int(w / 48))
    font = get_font(size)
    lo, hi = max(0, s - 40), min(len(text), e + 40)
    pre = ("…" if lo > 0 else "") + text[lo:s]
    mid = text[s:e]
    post = text[e:hi] + ("…" if hi < len(text) else "")
    bar = int(size * 2.2)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([0, h - bar, w, h], fill=(0, 0, 0, 170))
    total = font.getlength(pre) + font.getlength(mid) + font.getlength(post)
    x, y = max(10.0, (w - total) / 2), h - bar + (bar - size) / 2 - 2
    d.text((x, y), pre, fill=(255, 255, 255, 255), font=font)
    x += font.getlength(pre)
    d.rectangle([x - 2, y - 2, x + font.getlength(mid) + 2, y + size + 4], fill=(255, 235, 59, 255))
    d.text((x, y), mid, fill=(0, 0, 0, 255), font=font)
    x += font.getlength(mid)
    d.text((x, y), post, fill=(255, 255, 255, 255), font=font)
    out = Image.alpha_composite(img, layer).convert("RGB")
    return cv2.cvtColor(np.asarray(out), cv2.COLOR_RGB2BGR)


def search_spoken_in_video(ctx, path: Path, display: str, origin: Path, info, every: float, finalize_event) -> None:
    from app.video import Event

    segments = transcribe(path, ctx.opts.speech_model, ctx.cancel)
    for i, seg, s, e, t in _matches(ctx, segments):
        if ctx.cancelled:
            return
        frame = _grab_frame(path, t)
        if frame is None:
            continue
        frame = _caption(frame, seg["text"], s, e)
        ev = Event(t, min(seg["end"], t + 1.0), 1.0, frame, [], make_snippet(seg["text"], s, e), [(t, [])])
        finalize_event(ctx, path, display, origin, ev, info, every, "speech", seg["text"][s:e])


def transcribe_any(path: Path, size: str = "small", language: str = "") -> dict:
    """Spoken words -> text in ANY of Whisper's ~99 languages (the language is detected unless you give it). {'text','language','prob'}"""
    model = _model(size)
    with ML_LOCK:
        gen, info = model.transcribe(_audio(path), vad_filter=True, language=language or None, beam_size=5)
        text = " ".join(seg.text.strip() for seg in gen).strip()
    return {"text": text, "language": getattr(info, "language", "") or "", "prob": round(float(getattr(info, "language_probability", 0) or 0), 2)}
