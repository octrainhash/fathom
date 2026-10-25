"""Video, audio and subtitles through ffmpeg (bundled with Fathom), plus speech-to-text."""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

from app.convert import adjust
from app.convert.core import ConvertError, Ctx, Edge, Engine, Opts, ffmpeg_exe, ffmpeg_all, safe_stem
from app.convert.formats import FORMATS
from app.runtime import no_window_flags

VIDEO_IN = {"mp4", "mkv", "webm", "avi", "mov", "flv", "wmv", "mpg", "ts", "m2ts", "vob", "ogv", "3gp", "3g2", "m4v", "asf",
            "divx", "f4v", "rm", "rmvb", "mxf", "swf", "gif", "apng"}
AUDIO_IN = {"mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "wma", "aiff", "ac3", "amr", "mka", "mp2", "au", "caf", "ape", "wv", "tta", "dts", "ra"}
FRAME_PICTURES = {"png", "jpg", "tif", "webp", "bmp", "avif", "jp2", "tga", "ppm"}
SUB_FMT = {"srt": "srt", "vtt": "webvtt", "ass": "ass", "ssa": "ssa"}

# video target -> (encoders it needs)
VIDEO_OUT = {"mp4": ["libx264", "aac"], "m4v": ["libx264", "aac"], "mov": ["libx264", "aac"], "mkv": ["libx264", "aac"],
             "3gp": ["libx264", "aac"], "ts": ["libx264", "aac"], "flv": ["libx264", "aac"], "webm": ["libvpx-vp9", "libopus"],
             "avi": ["mpeg4", "libmp3lame"], "wmv": ["wmv2", "wmav2"], "mpg": ["mpeg2video", "mp2"], "ogv": ["libtheora", "libvorbis"],
             "gif": []}
AUDIO_OUT = {"mp3": ["libmp3lame"], "wav": ["pcm_s16le"], "flac": ["flac"], "ogg": ["libvorbis"], "opus": ["libopus"], "m4a": ["aac"],
             "aac": ["aac"], "wma": ["wmav2"], "aiff": ["pcm_s16be"], "ac3": ["ac3"], "mka": ["aac"], "mp2": ["mp2"],
             "au": ["pcm_s16be"], "caf": ["pcm_s16le"], "amr": ["libopencore_amrnb"]}


@lru_cache(maxsize=8)
def _encoders_of(exe: str) -> set[str]:
    try:
        out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30, creationflags=no_window_flags()).stdout
    except Exception:
        return set()
    names = set()
    for line in out.splitlines():
        m = re.match(r"^\s[VAS][\w.]{5}\s+(\S+)", line)
        if m:
            names.add(m.group(1))
    return names


def _encoders() -> set[str]:
    exe = ffmpeg_exe()
    return _encoders_of(exe) if exe else set()


def gpu_exe() -> str | None:
    """An ffmpeg that can encode with an NVIDIA card (NVENC): the bundled one has no NVENC, so a full ffmpeg on the PATH is used."""
    for exe in ffmpeg_all():
        if "h264_nvenc" in _encoders_of(exe):
            return exe
    return None


def _ok(needs: list[str]) -> bool:
    enc = _encoders()
    return all(n in enc for n in needs)


def probe(ctx: Ctx, src: Path) -> dict:
    """Duration (seconds), size and which streams a media file has (read from ffmpeg's banner)."""
    text = ""
    for exe in ffmpeg_all():
        rc, text = ctx.run([exe, "-hide_banner", "-nostdin", "-i", src, "-t", "0", "-f", "null", "-"])
        if "Duration:" in text or "Stream #" in text:
            break
    info: dict = {"duration": 0.0, "video": False, "audio": False, "audio_n": 0, "w": 0, "h": 0, "fps": 0.0, "text": text}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for line in text.splitlines():
        if line.startswith("Output #"):
            break                     # below this line ffmpeg describes what it would write, not the file itself
        if "Stream #" not in line:
            continue
        if " Video:" in line and "attached pic" not in line:
            info["video"] = True
            sz = re.search(r"[,\s](\d{2,5})x(\d{2,5})[,\s\[]", line)
            if sz and not info["w"]:
                info["w"], info["h"] = int(sz.group(1)), int(sz.group(2))
            fp = re.search(r"([\d.]+)\s*fps", line)
            if fp and not info["fps"]:
                info["fps"] = float(fp.group(1))
        elif " Audio:" in line:
            info["audio"] = True
            info["audio_n"] += 1
    return info


def _crf(o: Opts, base: int) -> int:
    if int(o.video_crf) > 0:
        return max(10, min(51, int(o.video_crf)))      # the quality number chosen by hand: lower is better
    return {"high": base - 5, "balanced": base, "small": base + 5}.get(o.video_quality, base)


def _qv(o: Opts, high: int, bal: int, small: int) -> int:
    return {"high": high, "balanced": bal, "small": small}.get(o.video_quality, bal)


X264_TARGETS = ("mp4", "m4v", "mov", "mkv", "3gp", "ts", "flv")


def uses_gpu(t: str, o: Opts) -> bool:
    """True when this conversion should be encoded by the NVIDIA graphics card (H.264 targets only)."""
    return bool(o.video_gpu and t in X264_TARGETS and gpu_exe())


def video_args(t: str, o: Opts, has_audio: bool, dur: float = 0.0, copy_video: bool = False, cpu_only: bool = False) -> list[str]:
    """ffmpeg output options. copy_video keeps the picture untouched (only the sound is re-made, if it must be)."""
    vf: list[str] = []
    if not copy_video:
        vf += adjust.rotate_flip_filters(o)
        vf += adjust.aspect_filters(o)
        if o.video_height and o.video_height > 0:
            vf.append(f"scale=-2:'min({int(o.video_height)},ih)'")
        if o.fps and o.fps > 0:
            vf.append(f"fps={o.fps:g}")
        vf += adjust.look_filters(o)
        if adjust.speed_of(o) != 1.0:
            vf.append(f"setpts=PTS/{adjust.speed_of(o):.4f}")
    k = f"{max(32, int(o.audio_kbps))}k"
    preset = o.video_preset if o.video_preset in adjust.X264_PRESETS else "medium"
    venc: list[str]
    if t in X264_TARGETS:
        if uses_gpu(t, o) and not cpu_only:
            venc = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(_crf(o, 23)), "-b:v", "0", "-pix_fmt", "yuv420p"]
        else:
            venc = ["-c:v", "libx264", "-preset", preset, "-crf", str(_crf(o, 23)), "-pix_fmt", "yuv420p"]
        audio = ["-c:a", "aac", "-b:a", k]
    elif t == "webm":
        venc = ["-c:v", "libvpx-vp9", "-crf", str(_crf(o, 32)), "-b:v", "0", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4", "-pix_fmt", "yuv420p"]
        audio = ["-c:a", "libopus", "-b:a", k]
    elif t == "avi":
        venc = ["-c:v", "mpeg4", "-q:v", str(_qv(o, 2, 4, 8)), "-vtag", "xvid", "-pix_fmt", "yuv420p"]
        audio = ["-c:a", "libmp3lame", "-b:a", k]
    elif t == "wmv":
        venc = ["-c:v", "wmv2", "-q:v", str(_qv(o, 3, 5, 9)), "-pix_fmt", "yuv420p"]
        audio = ["-c:a", "wmav2", "-b:a", k]
    elif t == "mpg":
        venc = ["-c:v", "mpeg2video", "-q:v", str(_qv(o, 2, 4, 8)), "-pix_fmt", "yuv420p"]
        audio = ["-c:a", "mp2", "-b:a", k, "-ar", "44100"]
    elif t == "ogv":
        venc = ["-c:v", "libtheora", "-q:v", str(_qv(o, 9, 7, 4)), "-pix_fmt", "yuv420p"]
        audio = ["-c:a", "libvorbis", "-b:a", k]
    else:
        raise ConvertError(f"Cannot make {t} video.")
    if copy_video:
        venc = ["-c:v", "copy"]
    if t in ("mp4", "m4v", "mov"):
        venc += ["-movflags", "+faststart"]
    args: list[str] = list(venc)
    if vf:
        args = ["-vf", ",".join(vf)] + args
    if o.keep_audio and has_audio:
        args += audio + adjust.audio_filter_args(o, dur) + adjust.audio_out_args(o, "")
    else:
        args += ["-an"]
    return args


def audio_args(t: str, o: Opts) -> list[str]:
    k = f"{max(32, int(o.audio_kbps))}k"
    table = {
        "mp3": ["-c:a", "libmp3lame", "-b:a", k], "wav": ["-c:a", "pcm_s16le"], "flac": ["-c:a", "flac", "-compression_level", "8"],
        "ogg": ["-c:a", "libvorbis", "-b:a", k], "opus": ["-c:a", "libopus", "-b:a", f"{min(256, max(32, int(o.audio_kbps)))}k"],
        "m4a": ["-c:a", "aac", "-b:a", k], "aac": ["-c:a", "aac", "-b:a", k, "-f", "adts"], "wma": ["-c:a", "wmav2", "-b:a", k],
        "aiff": ["-c:a", "pcm_s16be"], "ac3": ["-c:a", "ac3", "-b:a", f"{min(640, int(o.audio_kbps))}k"], "mka": ["-c:a", "aac", "-b:a", k],
        "mp2": ["-c:a", "mp2", "-b:a", k], "au": ["-c:a", "pcm_s16be", "-f", "au"], "caf": ["-c:a", "pcm_s16le"],
        "amr": ["-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k"],
    }
    return table[t]


def run_ffmpeg(ctx: Ctx, args: list, duration: float = 0.0, what: str = "convert", exe: str | None = None) -> None:
    exes = [exe] if exe else ffmpeg_all()
    if not exes:
        raise ConvertError("ffmpeg is missing. Run Fathom.bat repair (with internet) to reinstall it.")

    def on_line(line: str) -> None:
        if duration > 0 and line.startswith("out_time_us="):
            try:
                ctx.progress(int(line.split("=", 1)[1]) / 1e6 / duration)
            except ValueError:
                pass

    rc, out = 1, ""
    for exe in exes:
        cmd = [exe, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-nostats", "-progress", "pipe:1", *args]
        rc, out = ctx.run(cmd, on_line)
        if rc == 0 or (rc > 0 and rc < 0xC0000000):
            break   # success, or an ordinary error; only a crash tries the next ffmpeg
    if rc != 0:
        errs = [l for l in out.splitlines() if not re.match(r"^(\w+=|progress)", l)]
        msg = " ".join(errs[-3:]) or "unknown error"
        if "Invalid data found" in msg or "moov atom not found" in msg:
            msg = "This file is damaged or is not really a media file. " + msg
        raise ConvertError(f"ffmpeg could not {what} this file: {msg[:300]}")


class MediaEngine(Engine):
    name = "media"
    label = "Video and audio"
    cost = 1.0
    heavy = True

    def available(self) -> bool:
        return bool(ffmpeg_exe())

    def reads(self) -> set[str]:
        return VIDEO_IN | AUDIO_IN

    def writes(self) -> set[str]:
        return {t for t, n in VIDEO_OUT.items() if _ok(n)} | {t for t, n in AUDIO_OUT.items() if _ok(n)}

    @staticmethod
    def _track(o: Opts, info: dict) -> int:
        """Zero-based index of the sound track to keep; a clear message when the file has fewer tracks."""
        want = max(1, int(o.audio_track))
        if want > 1 and want > info.get("audio_n", 0):
            raise ConvertError(f"This file has {info.get('audio_n', 0)} sound track{'s' if info.get('audio_n', 0) != 1 else ''}, so track {want} does not exist.")
        return want - 1

    SAME_NOTE = "Same type: only your adjustments are applied (sound, speed, cut, quality...)."

    same_ok = True

    def can(self, s: str, t: str) -> Edge | None:
        same = s == t
        if same and s in ("gif", "apng", "swf"):
            return None
        v_in, a_in = s in VIDEO_IN, s in AUDIO_IN
        v_out, a_out = t in VIDEO_OUT, t in AUDIO_OUT
        if not (v_in or a_in):
            return None
        if not (t in self.writes()):
            return None
        if v_in and v_out:
            return Edge(s, t, self, 2.6 if same else (1.0 if s != "gif" else 1.2), self.SAME_NOTE if same else "")
        if v_in and a_out:
            if s in ("gif", "apng", "swf"):
                return None
            return Edge(s, t, self, 1.1, "Only the sound is kept.")
        if a_in and a_out:
            return Edge(s, t, self, 2.6 if same else 1.0, self.SAME_NOTE if same else "")
        return None   # a sound cannot become a video

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / f"{safe_stem(src)}.{t}"
        if s == t and not adjust.media_changes(o):
            raise ConvertError("Nothing to change. Pick a setting first (volume, speed, cut, quality, size...) or choose a different type.")
        info = probe(ctx, src)
        dur = info["duration"]
        eff = adjust.effective_duration(o, dur)   # how long the result will be (also drives the progress bar)
        pre = adjust.trim_in(o)
        if t in AUDIO_OUT:
            if not info["audio"]:
                raise ConvertError("This file has no sound to extract.")
            track = self._track(o, info)
            aargs = [*adjust.audio_filter_args(o, dur, silence=True), *audio_args(t, o), *adjust.audio_out_args(o, t)]
            run_ffmpeg(ctx, [*pre, "-i", src, "-vn", "-map", f"0:a:{track}", *aargs, dst], 0 if o.audio_silence else eff, "extract the sound from" if s in VIDEO_IN else "change the sound of")
            return [dst]
        if s in AUDIO_IN:
            raise ConvertError("A sound file cannot be turned into a video.")
        if not info["video"] and s not in ("gif", "apng"):
            raise ConvertError("This file has no picture to convert.")
        if t == "gif":
            w = max(16, int(o.gif_width))
            vf = f"fps={max(1, int(o.gif_fps))},scale='min({w},iw)':-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5"
            run_ffmpeg(ctx, [*pre, "-i", src, "-an", "-vf", vf, "-loop", "0", dst], eff, "make a GIF from")
            return [dst]
        extra: list = []
        track = self._track(o, info)
        if (t == "mkv" or t == "mp4" or track > 0) and info["video"]:
            extra = ["-map", "0:v:0", "-map", f"0:a:{track}?"]
        # Copy-only: keep the existing picture as it is (and the sound too, unless it must be changed). Very fast, same quality.
        # Works when the codecs fit the new container (e.g. H.264 + AAC in MKV). Falls back to a normal convert if copying fails.
        if (o.video_copy and info["video"] and s in VIDEO_IN and s not in ("gif", "apng") and t in VIDEO_OUT and t != "gif"
                and not adjust.video_needs_reencode(o)):
            try:
                if o.keep_audio and not (adjust.audio_active(o) and info["audio"]):
                    cargs = ["-c", "copy"]                                       # everything copied untouched
                else:
                    cargs = video_args(t, o, info["audio"], dur, copy_video=True)   # picture copied; sound removed or re-made
                run_ffmpeg(ctx, [*pre, "-i", src, *extra, *cargs, dst], eff, "copy into")
                return [dst]
            except ConvertError:
                if dst.exists():
                    dst.unlink()
        # a full conversion; with the graphics card first when asked for, then the processor if the card cannot do it
        attempts = [False, True] if uses_gpu(t, o) else [True]
        for n, cpu_only in enumerate(attempts):
            try:
                args = video_args(t, o, info["audio"], dur, cpu_only=cpu_only)
                run_ffmpeg(ctx, [*pre, "-i", src, *extra, *args, dst], eff, "convert", exe=None if cpu_only else gpu_exe())
                return [dst]
            except ConvertError:
                if n == len(attempts) - 1:
                    raise
                if dst.exists():
                    dst.unlink()
        return [dst]


class FrameEngine(Engine):
    """video -> a picture (one frame) and picture -> video (a still shown for a few seconds)."""
    name = "frames"
    label = "Frames and stills"
    cost = 1.6
    heavy = True

    def available(self) -> bool:
        return bool(ffmpeg_exe())

    def reads(self) -> set[str]:
        from app.convert.eng_image import rw

        return (VIDEO_IN - {"gif", "apng"}) | rw()[0]

    def writes(self) -> set[str]:
        from app.convert.eng_image import rw

        return (rw()[1] & FRAME_PICTURES) | {"mp4", "webm", "mkv", "mov", "avi"}

    def can(self, s: str, t: str) -> Edge | None:
        from app.convert.eng_image import rw

        r, w = rw()
        if s in VIDEO_IN and s not in ("gif", "apng") and t in w and t in FRAME_PICTURES:
            return Edge(s, t, self, self.cost, "One picture from the video is saved (set the second in the options).")
        if s in r and s not in ("apng", "gif") and t in ("mp4", "webm", "mkv", "mov", "avi") and t in MediaEngine().writes():
            return Edge(s, t, self, 2.0, "The picture is shown as a still video for a few seconds.")
        return None

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        from app.convert.eng_image import load_frames, save_pil

        out_dir.mkdir(parents=True, exist_ok=True)
        stem = safe_stem(src)
        if s in VIDEO_IN:
            tmp_png = ctx.scratch(".png")
            info = probe(ctx, src)
            at = o.frame_time
            if info["duration"] and at >= info["duration"]:
                at = max(0.0, info["duration"] - 0.1)
            pre = ["-ss", f"{at:.3f}"] if at > 0 else []
            run_ffmpeg(ctx, [*pre, "-i", src, "-frames:v", "1", "-an", tmp_png], 0, "take a picture from")
            if not tmp_png.exists() or tmp_png.stat().st_size == 0:   # some files only seek accurately after opening
                run_ffmpeg(ctx, ["-i", src, "-ss", f"{at:.3f}", "-frames:v", "1", "-an", tmp_png], 0, "take a picture from")
            if not tmp_png.exists() or tmp_png.stat().st_size == 0:
                raise ConvertError("There is no picture at that time in the video.")
            dst = out_dir / f"{stem}.{t}"
            if t == "png":
                tmp_png.replace(dst)
            else:
                frames, d, first = load_frames(tmp_png, "png", all_frames=False)
                save_pil(frames, d, dst, t, o, first)
            return [dst]
        # picture -> still video
        frames, _d, _f = load_frames(src, s, all_frames=False)
        png = ctx.scratch(".png")
        im = frames[0]
        if im.mode not in ("RGB", "L", "RGBA"):
            im = im.convert("RGB")
        im.save(png)
        dst = out_dir / f"{stem}.{t}"
        secs = max(0.5, float(o.still_seconds))
        o2 = Opts.from_dict({**o.__dict__, "keep_audio": False, "video_height": o.video_height, "fps": 0})
        args = video_args(t, o2, False)
        # an even width and height is required by most video codecs
        pre = ["-loop", "1", "-framerate", "25", "-t", f"{secs:g}", "-i", png]
        vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        if "-vf" in args:
            i = args.index("-vf")
            args[i + 1] = vf + "," + args[i + 1]
        else:
            args = ["-vf", vf] + args
        run_ffmpeg(ctx, [*pre, *args, dst], secs, "make a video from")
        return [dst]


class SubtitleEngine(Engine):
    name = "subtitles"
    label = "Subtitles"
    cost = 1.0

    def available(self) -> bool:
        return bool(ffmpeg_exe())

    def reads(self) -> set[str]:
        return set(SUB_FMT)

    def writes(self) -> set[str]:
        return set(SUB_FMT)

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / f"{safe_stem(src)}.{t}"
        run_ffmpeg(ctx, ["-i", src, dst], 0, "convert subtitles in")
        return [dst]


class SpeechEngine(Engine):
    """Spoken words in audio or video -> a transcript or subtitles (needs the optional speech model)."""
    name = "speech"
    label = "Speech to text"
    cost = 3.0
    heavy = True
    needs = "the speech package (faster-whisper)"

    def available(self) -> bool:
        from app import speech

        return speech.available()

    def reads(self) -> set[str]:
        return (VIDEO_IN - {"gif", "apng", "swf"}) | AUDIO_IN

    def writes(self) -> set[str]:
        return {"txt", "srt", "vtt"}

    def can(self, s: str, t: str) -> Edge | None:
        e = super().can(s, t)
        if e:
            e.note = "The speech is typed out by an AI model; check names and numbers."
        return e

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        from app import speech

        ctx.status("Listening… (the first time this downloads the speech model)")
        segs = speech.transcribe(src, o.whisper_model if o.whisper_model in ("tiny", "base", "small", "medium") else "base", ctx.cancel)
        ctx.check()
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / f"{safe_stem(src)}.{t}"
        if t == "txt":
            dst.write_text("\n".join(x["text"] for x in segs), encoding="utf-8")
        else:
            def ts(x: float) -> str:
                ms = int(round(x * 1000))
                h, ms = divmod(ms, 3600000)
                m, ms = divmod(ms, 60000)
                sec, ms = divmod(ms, 1000)
                return f"{h:02d}:{m:02d}:{sec:02d}{',' if t == 'srt' else '.'}{ms:03d}"

            lines = ["WEBVTT", ""] if t == "vtt" else []
            for i, x in enumerate(segs, 1):
                if t == "srt":
                    lines.append(str(i))
                lines += [f"{ts(x['start'])} --> {ts(x['end'])}", x["text"], ""]
            dst.write_text("\n".join(lines), encoding="utf-8")
        return [dst]
