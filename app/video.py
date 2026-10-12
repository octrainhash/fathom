"""Search inside videos. Every match gets a timestamp, a highlighted+circled snapshot and a slow-motion clip."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.annotate import annotate_array, crop_thumb, save_image, union_box
from app.query import find_spans, make_snippet, span_to_box
from app.runtime import no_window_flags

STATIC_DIFF = 1.5     # frames this similar to the last checked one reuse its result (big speed-up on slides/screencasts)
CHANGE_DIFF = 32.0    # mean pixel change that counts as a cut / flash
MAX_CLIP_SIDE = 1280
FONT = cv2.FONT_HERSHEY_SIMPLEX


def stamp(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


@dataclass
class VideoInfo:
    fps: float
    frames: int
    width: int
    height: int

    @property
    def duration(self) -> float:
        return self.frames / self.fps if self.frames > 0 else 0.0


def probe(path: Path) -> VideoInfo:
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise RuntimeError("This video could not be opened (unsupported codec or damaged file).")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if not (1.0 <= fps <= 240.0):
            fps = 25.0
        return VideoInfo(fps, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))
    finally:
        cap.release()


def sample_frames(path: Path, every: float, fps: float, cancel):
    """Yield (seconds, BGR frame) about every `every` seconds. Frames in between are only skipped, not decoded to pictures."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError("This video could not be opened (unsupported codec or damaged file).")
    step = max(1, int(round(fps * every)))
    idx, last_t = 0, -1.0
    try:
        while not cancel.is_set():
            if not cap.grab():
                break
            if idx % step == 0:
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                    if not t > last_t:
                        t = idx / fps
                    last_t = t
                    yield t, frame
            idx += 1
    finally:
        cap.release()


# ------------------------------------------------------------------ events
@dataclass
class Event:
    t_first: float
    t_last: float
    score: float
    frame: np.ndarray          # best frame (BGR)
    boxes: list
    snippet: list
    timeline: list = field(default_factory=list)   # [(t, boxes)] so the circle follows the match in the clip
    t_best: float | None = None                    # the moment the whole result is best in view (the clip can pause here)
    eff: float = 0.0


def _completeness(boxes: list, frame: np.ndarray) -> float:
    """0..1.5: how much of the result is fully inside the picture (not cut off at an edge) and how many results show at once."""
    if not boxes:
        return 0.0
    h, w = frame.shape[:2]
    m = 3
    whole = sum(1 for b in boxes if b[0] > m and b[1] > m and b[2] < w - m and b[3] < h - m)
    return whole / len(boxes) + 0.5 * min(1.0, len(boxes) / 4.0)


class Grouper:
    """Hits that are close in time belong to one event (text staying on screen for 3 seconds is ONE result)."""

    def __init__(self, gap: float, close):
        self.gap, self.close, self.cur = gap, close, None

    def add(self, t: float, boxes: list, snippet: list, score: float, frame: np.ndarray) -> None:
        c = self.cur
        eff = score + _completeness(boxes, frame)
        if c is not None and t - c.t_last <= self.gap:
            c.t_last = t
            c.timeline.append((t, boxes))
            if eff > c.eff:
                c.eff, c.score, c.frame, c.boxes, c.snippet, c.t_best = eff, score, frame.copy(), boxes, snippet, t
            return
        self.flush()
        self.cur = Event(t, t, score, frame.copy(), boxes, snippet, [(t, boxes)], t)
        self.cur.eff = eff

    def tick(self, t: float) -> None:
        if self.cur is not None and t - self.cur.t_last > self.gap:
            self.flush()

    def flush(self) -> None:
        if self.cur is not None:
            ev, self.cur = self.cur, None
            self.close(ev)


def draw_label(arr: np.ndarray, text: str) -> None:
    h, w = arr.shape[:2]
    fs = max(0.5, w / 1280 * 0.75)
    th = max(1, int(round(fs * 2)))
    (tw, tht), base = cv2.getTextSize(text, FONT, fs, th)
    pad = int(8 * fs + 4)
    overlay = arr.copy()
    cv2.rectangle(overlay, (12, 12), (12 + tw + 2 * pad, 12 + tht + base + 2 * pad), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, arr, 0.4, 0, arr)
    cv2.putText(arr, text, (12 + pad, 12 + pad + tht), FONT, fs, (255, 235, 59), th, cv2.LINE_AA)


# ------------------------------------------------------------------ clip writer (frames -> ffmpeg -> H.264 mp4 that every player opens)
@lru_cache(maxsize=1)
def _ffmpeg() -> tuple[str, str]:
    import imageio_ffmpeg

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30, creationflags=no_window_flags()).stdout
    except Exception:
        out = ""
    for codec in ("libx264", "libopenh264", "h264_mf"):
        if codec in out:
            return exe, codec
    return exe, "libx264"


def _even(v: int) -> int:
    return max(2, v - (v % 2))


class ClipWriter:
    def __init__(self, out: Path, width: int, height: int, fps: float):
        exe, codec = _ffmpeg()
        args = ["-c:v", codec, "-pix_fmt", "yuv420p"]
        args += ["-preset", "veryfast", "-crf", "23"] if codec == "libx264" else ["-b:v", "4M"]
        cmd = [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", f"{fps:.3f}",
               "-i", "-", "-an", *args, "-movflags", "+faststart", str(out)]
        self.err = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.err, creationflags=no_window_flags())
        self.frames = 0

    def write(self, rgb: np.ndarray) -> None:
        self.proc.stdin.write(np.ascontiguousarray(rgb).tobytes())
        self.frames += 1

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        rc = self.proc.wait()
        self.err.seek(0)
        msg = self.err.read().decode("utf-8", "replace").strip()
        self.err.close()
        if rc != 0:
            raise RuntimeError(msg[-300:] or f"ffmpeg exited with {rc}")

    def abort(self) -> None:
        try:
            self.proc.kill()
        except Exception:
            pass


def _seek(cap, t: float, fps: float) -> float:
    """Jump close to t. Returns the real time of the next frame to be read."""
    if t <= 0.05:
        return 0.0
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
    pos = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
    if abs(pos - t) > 2.5:  # this file ignored the seek: walk there frame by frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        for _ in range(int(t * fps)):
            if not cap.grab():
                break
        pos = t
    return pos


def _nearest(timeline: list, t: float) -> list:
    return min(timeline, key=lambda item: abs(item[0] - t))[1]


def write_clip(path: Path, out: Path, info: VideoInfo, t_start: float, t_end: float, span: tuple[float, float], ev: Event,
               slowmo: float, clipmode: str, hold: float, mode: str) -> tuple[int, float]:
    """Writes the clip. Returns (frames, seconds it lasts).

    clipmode: "result" slows down while the result is on screen, "all" slows the whole clip, "pause" plays normally and freezes on the full result.
    `hold` seconds of freeze on the full result are added in every mode (0 = none)."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError("could not reopen the video")
    scale = min(1.0, MAX_CLIP_SIDE / max(info.width, info.height, 1))
    ow, oh = _even(int(info.width * scale)), _even(int(info.height * scale))
    out_fps = min(info.fps, 60.0)
    writer = ClipWriter(out, ow, oh, out_fps)
    factor = slowmo if (clipmode != "pause" and slowmo > 1.0) else 1.0
    hold_frames = int(round(hold * out_fps)) if hold > 0 else 0
    t_best = ev.t_best if ev.t_best is not None else ev.t_first
    prev = prev_t = prev_hold = None
    acc = 0.0
    held = False
    try:
        t = _seek(cap, t_start, info.fps)
        while t <= t_end:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if (frame.shape[1], frame.shape[0]) != (ow, oh):
                frame = cv2.resize(frame, (ow, oh), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            in_span = span[0] <= t <= span[1]
            if in_span:
                boxes = _nearest(ev.timeline, t)
                if boxes:   # every result on screen gets its highlight, circle and arrow for as long as it is shown
                    rgb = annotate_array(rgb, [tuple(v * scale for v in b) for b in boxes], "object" if mode == "object" else "text", arrows=True)
            slow = factor > 1.0 and (in_span or clipmode == "all")
            tag = f"{factor:g}x slow-mo" if slow else ""
            held_img = None
            if hold_frames and not held and t >= t_best - 0.5 / info.fps and in_span:
                held_img = rgb.copy()
                draw_label(held_img, f"{stamp(t)}  |  paused on the full result")
            draw_label(rgb, f"{stamp(t)}  |  {tag}" if tag else stamp(t))
            if prev is not None:   # each source frame is shown `factor` times longer, blended for smooth motion
                slow_prev = factor > 1.0 and (span[0] <= prev_t <= span[1] or clipmode == "all")
                acc += factor if slow_prev else 1.0
                n = int(acc)
                acc -= n
                for k in range(n):
                    a = k / n
                    writer.write(prev if k == 0 else cv2.addWeighted(prev, 1 - a, rgb, a, 0))
                if prev_hold is not None and not held:
                    for _ in range(hold_frames):
                        writer.write(prev_hold)
                    held = True
            prev, prev_t, prev_hold = rgb, t, held_img
            t += 1.0 / info.fps
        if prev is not None:
            writer.write(prev)
            if prev_hold is not None and not held:
                for _ in range(hold_frames):
                    writer.write(prev_hold)
        writer.close()
    except Exception:
        writer.abort()
        raise
    finally:
        cap.release()
    return writer.frames, writer.frames / max(out_fps, 1.0)


def finalize_event(ctx, path: Path, display: str, origin: Path, ev: Event, info: VideoInfo, every: float, kind: str, label_text: str = "") -> None:
    """Make the clip + the still picture for one event. They are ONE result: the still is the full result, circled, highlighted and pointed at."""
    opts = ctx.opts
    rid = ctx.next_id()
    t_start = max(0.0, ev.t_first - opts.before)
    t_end = min(info.duration or 1e9, ev.t_last + every + opts.after)
    span = (max(0.0, ev.t_first - min(0.4, every / 2)), ev.t_last + every * 0.8)
    clip_url, clip_len = None, 0.0
    try:
        _frames, clip_len = write_clip(path, ctx.out_dir / f"{rid}.mp4", info, t_start, t_end, span, ev, opts.slowmo, opts.clipmode, opts.hold, opts.mode)
        clip_url = ctx.url(f"{rid}.mp4")
    except Exception as exc:
        ctx.error(display, f"Found a match at {stamp(ev.t_first)} but could not make the slow-motion clip: {exc}")
    t_best = ev.t_best if ev.t_best is not None else ev.t_first
    rgb = cv2.cvtColor(ev.frame, cv2.COLOR_BGR2RGB)
    shown = annotate_array(rgb, ev.boxes, "object" if opts.mode == "object" else "text", arrows=True) if ev.boxes else rgb.copy()
    draw_label(shown, stamp(t_best))
    image = Image.fromarray(shown)
    full = save_image(image, ctx.out_dir / f"{rid}_full", photo_like=True)
    if ev.boxes:
        thumb_img = crop_thumb(image, union_box(ev.boxes))
    else:
        thumb_img = image.copy()
        thumb_img.thumbnail((520, 520))
    thumb_img.save(ctx.out_dir / f"{rid}_t.jpg", "JPEG", quality=84)
    result = {
        "file": display, "path": str(origin), "where": stamp(ev.t_first), "kind": kind, "t": round(ev.t_first, 3),
        "snippet": ev.snippet or ["", label_text or opts.query, ""],
        "thumb": ctx.url(f"{rid}_t.jpg"), "image": ctx.url(full), "still": ctx.url(full),
        "peak": stamp(t_best), "count": len(ev.boxes),
    }
    if clip_url:
        result["clip"] = clip_url
        result["clip_len"] = round(clip_len, 1)
    if kind == "object":
        result["score"] = round(float(ev.score), 2)
    ctx.emit(result)


# ------------------------------------------------------------------ the scan itself
def _gray_small(frame: np.ndarray) -> np.ndarray:
    return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)


def _scan_frame(ctx, frame: np.ndarray):
    """-> (boxes, snippet, score) for the words or the object being searched."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    if ctx.opts.mode == "object":
        from app.detect import find_objects

        found = find_objects(Image.fromarray(rgb), ctx.opts.query, ctx.opts.strictness, thorough=False)
        if not found:
            return [], [], 0.0
        return [f["bbox"] for f in found], ["", ctx.opts.query, ""], float(max(f["score"] for f in found))
    if not ctx.opts.ocr:
        return [], [], 0.0
    from app.ocr import ocr_boxes

    k = min(1.0, 1600 / max(rgb.shape[1], 1))
    small = cv2.resize(rgb, (int(rgb.shape[1] * k), int(rgb.shape[0] * k)), interpolation=cv2.INTER_AREA) if k < 1 else rgb
    boxes, snippet = [], []
    for tok in ocr_boxes(Image.fromarray(small)):
        for s, e in find_spans(ctx.pattern, tok["text"]):
            boxes.append(tuple(v / k for v in span_to_box(tok["text"], s, e, tok["bbox"])))
            if not snippet:
                snippet = make_snippet(tok["text"], s, e)
    return boxes, snippet, 1.0 if boxes else 0.0


def search_video(ctx, path: Path, display: str, origin: Path) -> None:
    """Searches one video the ways the user ticked: words on screen, the actual object, spoken words."""
    from app.search import _Sub, media_targets

    opts = ctx.opts
    info = probe(path)
    every = opts.scan_every or 1.0
    for mode in media_targets(opts):
        if ctx.cancelled:
            return
        _search_video_visual(_Sub(ctx, mode), path, display, origin, info, every)
    if opts.media_speech and not ctx.cancelled:
        try:
            from app.speech import search_spoken_in_video

            search_spoken_in_video(_Sub(ctx, "text"), path, display, origin, info, every, finalize_event)
        except Exception as exc:
            ctx.error(display, f"Spoken-word search did not run: {exc}")


def _search_video_visual(ctx, path: Path, display: str, origin: Path, info, every: float) -> None:
    opts = ctx.opts
    gap = max(every * 2.6, 1.5)
    kind = "object" if opts.mode == "object" else "video"
    hit_group = Grouper(gap, lambda ev: finalize_event(ctx, path, display, origin, ev, info, every, kind))
    change_group = Grouper(gap, lambda ev: finalize_event(ctx, path, display, origin, ev, info, every, "change", "sudden change"))
    prev = None
    last = ([], [], 0.0)
    checked = 0
    try:
        for t, frame in sample_frames(path, every, info.fps, ctx.cancel):
            small = _gray_small(frame)
            diff = float(np.abs(small - prev).mean()) if prev is not None else 0.0
            prev = small
            checked += 1
            if checked % 20 == 0:
                ctx.status(f"{display}: {stamp(t)} of {stamp(info.duration)}" if info.duration else f"{display}: {stamp(t)}")
            if checked == 1 or diff >= STATIC_DIFF:
                last = _scan_frame(ctx, frame)
            boxes, snippet, score = last
            if boxes:
                hit_group.add(t, boxes, snippet, score, frame)
            else:
                hit_group.tick(t)
            if opts.changes and diff >= CHANGE_DIFF:
                change_group.add(t, [], ["", "sudden change", ""], diff, frame)
            else:
                change_group.tick(t)
        if not ctx.cancelled:
            hit_group.flush()
            change_group.flush()
    except Exception:
        hit_group.cur = change_group.cur = None
        raise
