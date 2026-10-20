# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Fetch videos (and pictures) from web links so they can be searched like any file.

A page link (YouTube and most video sites) is handled by yt-dlp when it is installed.
A direct link to a file is downloaded as it is. Everything is saved under Fathom's data folder.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from app.paths import data_root

MAX_BYTES = 8 * 1024 ** 3
_URL = re.compile(r"^https?://", re.I)


def is_url(s: str) -> bool:
    return bool(_URL.match((s or "").strip()))


def _check_public(url: str) -> None:
    """Refuse addresses on this computer or its private network (keeps a shared Fathom from being used to probe it)."""
    host = urllib.parse.urlparse(url).hostname or ""
    if not host:
        raise ValueError("That link has no web address in it.")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise ValueError(f"Could not find {host}. Check the link and your connection.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("Links to this computer or your private network are not allowed.")


def links_dir() -> Path:
    d = data_root() / "links"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _have_ytdlp() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


def _direct(url: str, dest: Path, progress: Callable[[str], None], cancel) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "Fathom"})
    with urllib.request.urlopen(req, timeout=30) as r:
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype.startswith("text/html"):
            raise ValueError("That link is a web page, not a video file. Install the video-link helper (yt-dlp) to use page links.")
        name = Path(urllib.parse.unquote(urllib.parse.urlparse(r.geturl()).path)).name or "download"
        if "." not in name:
            name += {"video/mp4": ".mp4", "video/webm": ".webm", "image/jpeg": ".jpg", "image/png": ".png"}.get(ctype.split(";")[0], ".mp4")
        out = dest / name
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        with open(out, "wb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise ValueError("Cancelled.")
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                got += len(chunk)
                if got > MAX_BYTES:
                    raise ValueError("That file is larger than 8 GB.")
                f.write(chunk)
                progress(f"Downloading {name}… {got // 1048576} MB" + (f" of {total // 1048576} MB" if total else ""))
    return out


def _ytdlp(url: str, dest: Path, progress: Callable[[str], None], cancel) -> Path:
    import yt_dlp

    def hook(d):
        if cancel is not None and cancel.is_set():
            raise yt_dlp.utils.DownloadCancelled()
        if d.get("status") == "downloading":
            progress(f"Downloading video… {d.get('_percent_str', '').strip()}")

    opts = {"outtmpl": str(dest / "%(title).80s.%(ext)s"), "quiet": True, "no_warnings": True, "noplaylist": True,
            "format": "best[height<=1080]/best", "progress_hooks": [hook], "max_filesize": MAX_BYTES}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    if not path.exists():
        found = [p for p in dest.iterdir() if p.is_file()]
        if not found:
            raise ValueError("The video could not be saved.")
        path = found[0]
    return path


def fetch(url: str, progress: Callable[[str], None] = lambda s: None, cancel=None) -> Path:
    """Download `url` once (later searches reuse the saved copy). Raises ValueError with a plain message."""
    url = url.strip()
    _check_public(url)
    dest = links_dir() / hashlib.sha1(url.encode()).hexdigest()[:16]
    if dest.is_dir():
        have = [p for p in dest.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
        if have:
            return have[0]
    dest.mkdir(parents=True, exist_ok=True)
    path = None
    ytdlp_error = ""
    if _have_ytdlp():
        try:
            path = _ytdlp(url, dest, progress, cancel)
        except Exception as exc:  # fall back to a plain download for direct file links
            ytdlp_error = str(exc).splitlines()[-1][:200] if str(exc) else "unsupported link"
    if path is None:
        try:
            path = _direct(url, dest, progress, cancel)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Could not download {url}. {ytdlp_error or exc}")
    return path


def resolve(sources: list[str], progress: Callable[[str], None], cancel, on_error: Callable[[str, str], None]) -> list[str]:
    """Replace every link in `sources` with the downloaded file. A link that fails is reported and skipped."""
    out: list[str] = []
    for s in sources:
        if not is_url(s):
            out.append(s)
            continue
        try:
            out.append(str(fetch(s, progress, cancel)))
        except ValueError as exc:
            on_error(s, str(exc))
    return out
