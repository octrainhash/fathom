"""Shared pieces of every converter: options, a work context (progress, cancel, helper processes) and the engine base class."""
from __future__ import annotations

import dataclasses
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.runtime import no_window_flags


class Cancelled(Exception):
    pass


class ConvertError(Exception):
    """A problem the user can understand (shown as-is next to the file)."""


@dataclass
class Opts:
    # pictures
    image_quality: int = 90          # 1-100 (JPEG, WebP, AVIF, HEIC)
    resize: str = "none"             # none | percent | fit
    resize_percent: int = 100
    max_width: int = 0
    max_height: int = 0
    strip_metadata: bool = False
    background: str = "#ffffff"      # fills transparent areas when the target has no transparency
    all_frames: bool = False         # animated picture / multipage TIFF -> one file per frame
    ico_sizes: str = "16,24,32,48,64,128,256"
    # PDF / documents
    pdf_dpi: int = 150
    pages: str = ""                  # "1-3,7" (empty = all pages)
    # video / audio
    video_quality: str = "balanced"  # high | balanced | small
    video_height: int = 0            # 0 = keep the size
    fps: float = 0                   # 0 = keep
    keep_audio: bool = True
    audio_kbps: int = 192
    gif_fps: int = 12
    gif_width: int = 480
    frame_time: float = 0.0          # video -> picture: which second to grab
    still_seconds: float = 5.0       # picture -> video: how long
    # text / speech
    whisper_model: str = "base"
    password: str = ""
    level: int = 9                   # archive compression 1-9

    @classmethod
    def from_dict(cls, data: dict | None) -> "Opts":
        names = {f.name: f for f in dataclasses.fields(cls)}
        clean = {}
        for key, val in (data or {}).items():
            f = names.get(key)
            if f is None or val is None:
                continue
            try:
                kind = type(getattr(cls(), key))
                clean[key] = kind(val) if kind is not bool else bool(val)
            except (TypeError, ValueError):
                pass
        return cls(**clean)


def kill_tree(proc: subprocess.Popen) -> None:
    """Stops a helper program and everything it started (LibreOffice and Calibre launch child processes)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, creationflags=no_window_flags(), timeout=20)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class Ctx:
    """What a conversion needs from the app: a scratch folder, progress, cancel, and a way to run helper programs."""

    def __init__(self, tmp: Path, cancel: threading.Event | None = None,
                 progress: Callable[[float], None] | None = None, status: Callable[[str], None] | None = None):
        self.tmp = tmp
        self.cancel = cancel or threading.Event()
        self._progress = progress or (lambda f: None)
        self.span = (0.0, 1.0)      # which slice of the overall progress the current step covers
        self._status = status or (lambda s: None)
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()
        tmp.mkdir(parents=True, exist_ok=True)

    # -- control
    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    def progress(self, frac: float) -> None:
        lo, hi = self.span
        self._progress(lo + max(0.0, min(1.0, frac)) * (hi - lo))

    def status(self, text: str) -> None:
        self._status(text)

    def scratch(self, suffix: str = "") -> Path:
        p = self.tmp / (uuid.uuid4().hex[:10] + suffix)
        return p

    def scratch_dir(self) -> Path:
        p = self.tmp / uuid.uuid4().hex[:10]
        p.mkdir(parents=True, exist_ok=True)
        return p

    # -- helper programs
    def kill_all(self) -> None:
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            kill_tree(p)

    def run(self, cmd: list, on_line: Callable[[str], None] | None = None, cwd: Path | None = None,
            env: dict | None = None, timeout: float | None = None) -> tuple[int, str]:
        """Runs a program without a console window; stops it when the user cancels. Returns (exit code, output)."""
        self.check()
        proc = subprocess.Popen([str(c) for c in cmd], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                cwd=str(cwd) if cwd else None, env=env, creationflags=no_window_flags())
        with self._lock:
            self._procs.add(proc)
        lines: list[str] = []

        def drain() -> None:
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    lines.append(line)
                    if len(lines) > 400:
                        del lines[:200]
                    if on_line:
                        try:
                            on_line(line)
                        except Exception:
                            pass

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        waited = 0.0
        try:
            while True:
                try:
                    proc.wait(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    waited += 0.25
                    if self.cancel.is_set():
                        kill_tree(proc)
                        proc.wait()
                        raise Cancelled()
                    if timeout and waited > timeout:
                        kill_tree(proc)
                        proc.wait()
                        raise ConvertError("The helper program took too long and was stopped.")
        finally:
            reader.join(timeout=3)
            with self._lock:
                self._procs.discard(proc)
        return proc.returncode, "\n".join(lines)


@dataclass
class Edge:
    src: str
    dst: str
    engine: "Engine"
    cost: float = 1.0
    note: str = ""
    multi: bool = False     # may produce several files (one per page / sheet / frame)


class Engine:
    name = "engine"
    label = "Engine"
    cost = 1.0
    heavy = False           # heavy work (video, Office, OCR) runs one at a time
    needs = ""              # what to install when it is missing

    def available(self) -> bool:
        return True

    def reads(self) -> set[str]:
        return set()

    def writes(self) -> set[str]:
        return set()

    def can(self, s: str, t: str) -> Edge | None:
        if s != t and s in self.reads() and t in self.writes():
            return Edge(s, t, self, self.cost)
        return None

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        raise NotImplementedError


# ---------------------------------------------------------------- helpers shared by engines
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_stem(path: Path) -> str:
    stem = path.name
    for compound in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if stem.lower().endswith(compound):
            stem = stem[: -len(compound)]
            break
    else:
        stem = path.stem
    return _BAD.sub("_", stem).strip(" .") or "file"


def unique_path(path: Path) -> Path:
    """name.ext, or name (2).ext, name (3).ext ... so nothing is ever overwritten."""
    if not path.exists():
        return path
    stem, suffix = path.name, ""
    for compound in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if stem.lower().endswith(compound):
            stem, suffix = stem[: -len(compound)], stem[-len(compound):]
            break
    else:
        stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        cand = path.with_name(f"{stem} ({n}){suffix}")
        if not cand.exists():
            return cand
        n += 1


def parse_pages(spec: str, total: int) -> list[int]:
    """'1-3,7,9-' (also odd, even, last, end-2, every 3, !4 ...) -> zero-based page numbers. Empty means every page."""
    from app import pagesel
    from app.service import UserError
    try:
        pages = pagesel.parse(spec, total)
    except UserError as e:
        raise ConvertError(f"I don't understand the page list '{spec}'. {e}")
    if not pages:
        raise ConvertError(f"The page list '{spec}' has no pages that exist (the file has {total}).")
    return pages


def find_program(*names: str, extra: list[str] | None = None) -> str | None:
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    for p in extra or []:
        if p and os.path.exists(p):
            return p
    return None


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


def ffmpeg_all() -> list[str]:
    """Every working-looking ffmpeg: the bundled one first, then one on PATH (used when the first crashes on a file)."""
    out: list[str] = []
    first = ffmpeg_exe()
    if first:
        out.append(first)
    other = shutil.which("ffmpeg")
    if other and other not in out:
        out.append(other)
    return out


def file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
