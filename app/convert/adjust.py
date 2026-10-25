# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Adjustments that can be applied while converting: sound (volume, loudness, fades, tone, channels), cutting and speed,
how a video looks (turn, flip, light and colour, clean-up, speed of encoding) and how a picture looks.
Every function here only builds ffmpeg arguments or answers a yes/no question about the options; nothing runs a program."""
from __future__ import annotations

from app.convert.core import Opts

X264_PRESETS = {"ultrafast", "veryfast", "fast", "medium", "slow", "veryslow"}
ASPECTS = {"16:9": (16, 9), "4:3": (4, 3), "3:2": (3, 2), "1:1": (1, 1), "9:16": (9, 16), "2:3": (2, 3), "21:9": (21, 9)}


# ---------------------------------------------------------------- numbers from the options
def speed_of(o: Opts) -> float:
    s = float(o.speed or 1.0)
    if s <= 0 or abs(s - 1.0) < 1e-3:
        return 1.0
    return max(0.25, min(4.0, s))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def trim_active(o: Opts) -> bool:
    return o.trim_start > 0 or (o.trim_end > 0 and o.trim_end > o.trim_start)


def trim_in(o: Opts) -> list[str]:
    """ffmpeg input options that keep only the part between 'start' and 'end' seconds."""
    args: list[str] = []
    start = max(0.0, float(o.trim_start or 0))
    end = float(o.trim_end or 0)
    if start > 0:
        args += ["-ss", f"{start:g}"]
    if end > start:
        args += ["-t", f"{end - start:g}"]
    return args


def effective_duration(o: Opts, dur: float) -> float:
    """How long the finished file will be (for the progress bar and for fading out at the end). 0 when unknown."""
    start = max(0.0, float(o.trim_start or 0))
    end = float(o.trim_end or 0)
    stop = end if end > start else dur
    if not stop or stop <= start:
        return 0.0
    return (stop - start) / speed_of(o)


# ---------------------------------------------------------------- sound
def _atempo(speed: float) -> list[str]:
    out: list[str] = []
    s = speed
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    out.append(f"atempo={s:.4f}")
    return out


def audio_active(o: Opts) -> bool:
    """True when the sound itself must be changed (so it cannot simply be copied)."""
    return bool(
        int(o.audio_volume) != 100 or o.audio_normalize or o.audio_fade_in > 0 or o.audio_fade_out > 0
        or o.audio_channels in ("mono", "stereo") or int(o.audio_rate) > 0 or o.audio_denoise
        or int(o.audio_bass) != 0 or int(o.audio_treble) != 0 or speed_of(o) != 1.0)


def audio_filters(o: Opts, dur: float = 0.0, silence: bool = False) -> list[str]:
    """silence=True is only used when the result is sound alone (cutting silence would put a video out of step)."""
    f: list[str] = []
    cut_silence = bool(silence and o.audio_silence)
    if cut_silence:
        f.append("silenceremove=start_periods=1:start_threshold=-50dB:stop_periods=-1:stop_duration=1:stop_threshold=-50dB")
    sp = speed_of(o)
    if sp != 1.0:
        f += _atempo(sp)
    if o.audio_denoise:
        f.append("afftdn=nf=-25")
    bass, treble = int(_clamp(int(o.audio_bass), -15, 15)), int(_clamp(int(o.audio_treble), -15, 15))
    if bass:
        f.append(f"bass=g={bass}")
    if treble:
        f.append(f"treble=g={treble}")
    vol = int(_clamp(int(o.audio_volume), 0, 500))
    if vol != 100:
        f.append(f"volume={vol / 100:.3f}")
    if o.audio_normalize:
        f.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    elif vol > 100 or bass > 0 or treble > 0:
        f.append("alimiter=limit=0.95")      # louder sound would otherwise crackle where it clips
    eff = effective_duration(o, dur)
    fin, fout = float(o.audio_fade_in or 0), float(o.audio_fade_out or 0)
    if fin > 0:
        f.append(f"afade=t=in:st=0:d={fin:g}")
    if fout > 0 and eff > fout and not cut_silence:
        f.append(f"afade=t=out:st={eff - fout:.3f}:d={fout:g}")
    return f


def audio_filter_args(o: Opts, dur: float = 0.0, silence: bool = False) -> list[str]:
    f = audio_filters(o, dur, silence)
    return ["-af", ",".join(f)] if f else []


def audio_out_args(o: Opts, t: str = "") -> list[str]:
    """Channels and sample rate. Types that fix these themselves (AMR) are left alone."""
    if t == "amr":
        return []
    a: list[str] = []
    if o.audio_channels == "mono":
        a += ["-ac", "1"]
    elif o.audio_channels == "stereo":
        a += ["-ac", "2"]
    rate = int(o.audio_rate) if int(o.audio_rate) > 0 else (48000 if o.audio_normalize else 0)
    if rate:
        a += ["-ar", str(rate)]
    return a


# ---------------------------------------------------------------- video look
def aspect_filters(o: Opts) -> list[str]:
    """Crop to fill a new shape, or add black bars to fit it. Sizes are made even, as most video codecs need."""
    ratio = ASPECTS.get(str(o.video_aspect))
    if not ratio:
        return []
    n, d = ratio
    if o.video_aspect_mode == "crop":
        f = [f"crop='trunc(min(iw,ih*{n}/{d})/2)*2':'trunc(min(ih,iw*{d}/{n})/2)*2'"]
    else:
        f = [f"pad='trunc(max(iw,ih*{n}/{d})/2)*2':'trunc(max(ih,iw*{d}/{n})/2)*2':'(ow-iw)/2':'(oh-ih)/2':black"]
    return f


def rotate_flip_filters(o: Opts) -> list[str]:
    f: list[str] = []
    if o.video_deinterlace:
        f.append("yadif")
    r = str(o.video_rotate)
    if r == "90":
        f.append("transpose=1")
    elif r == "180":
        f += ["transpose=1", "transpose=1"]
    elif r == "270":
        f.append("transpose=2")
    if o.video_flip in ("h", "both"):
        f.append("hflip")
    if o.video_flip in ("v", "both"):
        f.append("vflip")
    return f


def look_filters(o: Opts) -> list[str]:
    f: list[str] = []
    if o.video_denoise:
        f.append("hqdn3d=3:2:3:2")
    b, c, s = int(o.video_brightness), int(o.video_contrast), int(o.video_saturation)
    if b != 0 or c != 100 or s != 100:
        f.append(f"eq=brightness={_clamp(b, -100, 100) / 250:.3f}:contrast={_clamp(c, 0, 300) / 100:.2f}:saturation={_clamp(s, 0, 300) / 100:.2f}")
    if o.video_grayscale:
        f.append("hue=s=0")
    if o.video_sharpen:
        f.append("unsharp=5:5:0.8:3:3:0.4")
    return f


def video_needs_reencode(o: Opts) -> bool:
    """True when the picture itself must be changed or squeezed again, so copying is not enough."""
    return bool(
        o.video_height > 0 or o.fps > 0 or o.video_quality != "balanced" or o.video_preset != "medium" or o.video_gpu
        or int(o.video_crf) > 0 or str(o.video_aspect) in ASPECTS or o.video_deinterlace
        or str(o.video_rotate) in ("90", "180", "270") or o.video_flip in ("h", "v", "both")
        or int(o.video_brightness) != 0 or int(o.video_contrast) != 100 or int(o.video_saturation) != 100
        or o.video_grayscale or o.video_denoise or o.video_sharpen or speed_of(o) != 1.0)


def media_changes(o: Opts) -> bool:
    """Anything at all asked for: used to refuse a pointless 'MP3 to MP3' with no change."""
    return bool(video_needs_reencode(o) or audio_active(o) or o.audio_silence or trim_active(o) or int(o.audio_kbps) != 192
                or not o.keep_audio or int(o.audio_track) > 1)


# ---------------------------------------------------------------- pictures
def image_active(o: Opts) -> bool:
    """True when the colours, sharpness, turn or flip of a picture must be changed."""
    return bool(
        int(o.img_brightness) != 100 or int(o.img_contrast) != 100 or int(o.img_saturation) != 100 or int(o.img_sharpness) != 100
        or o.img_blur > 0 or o.img_grayscale or o.img_invert or o.img_auto_levels
        or str(o.img_rotate) in ("90", "180", "270") or o.img_flip in ("h", "v", "both"))


def image_shape_active(o: Opts) -> bool:
    """Cut empty edges, or crop to a new shape (done before any resizing)."""
    return bool(o.img_autotrim or str(o.img_aspect) in ASPECTS)


def image_finish_active(o: Opts) -> bool:
    """Fewer colours and a border (done last)."""
    return bool(int(o.img_palette) > 0 or int(o.img_border) > 0)


def image_changes(o: Opts) -> bool:
    return bool(image_active(o) or image_shape_active(o) or image_finish_active(o)
                or o.resize != "none" or int(o.image_quality) != 90 or o.strip_metadata or int(o.img_dpi) > 0)
