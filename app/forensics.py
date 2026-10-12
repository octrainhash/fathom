"""Forensics lab: hidden NTFS streams, hidden-attribute override, data carving from raw storage, steganography.

Everything here only READS the thing under examination unless the user explicitly asks to strip/expose/hide."""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

from app import ops
from app.convert.core import ConvertError, Ctx, file_bytes, safe_stem, unique_path
from app.ops import Output, OutputPolicy, Task
from app.opsvc import expand_sources
from app.service import UserError

WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"
NOWIN = 0x08000000 if WIN else 0


def _run(cmd: list[str], timeout: float = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NOWIN, errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


# ================================================================== 1. NTFS alternate data streams
def list_streams(path: Path) -> list[dict]:
    """Every named stream of a file. The ordinary content ('::$DATA') is not listed."""
    if not WIN:
        return []
    from ctypes import wintypes

    class FSD(ctypes.Structure):
        _fields_ = [("StreamSize", ctypes.c_longlong), ("StreamName", ctypes.c_wchar * 296)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.FindFirstStreamW.restype = wintypes.HANDLE
    k.FindFirstStreamW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.FindNextStreamW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k.FindClose.argtypes = [wintypes.HANDLE]
    data, out = FSD(), []
    h = k.FindFirstStreamW(str(path), 0, ctypes.byref(data), 0)
    if h in (None, wintypes.HANDLE(-1).value, 0xFFFFFFFFFFFFFFFF, -1):
        return out
    try:
        while True:
            name = data.StreamName
            if name != "::$DATA":
                m = re.match(r":(.*):\$DATA$", name)
                out.append({"name": m.group(1) if m else name, "size": data.StreamSize})
            if not k.FindNextStreamW(h, ctypes.byref(data)):
                break
    finally:
        k.FindClose(h)
    return out


def _sniff(blob: bytes) -> str:
    if blob[:2] == b"MZ": return "a Windows program"
    if blob[:4] == b"\x7fELF": return "a Linux program"
    if blob[:4] == b"%PDF": return "a PDF"
    if blob[:2] == b"PK": return "a ZIP / Office file"
    if blob[:3] == b"\xff\xd8\xff" or blob[:8] == b"\x89PNG\r\n\x1a\n": return "a picture"
    if blob[:5].lower() in (b"<?xml", b"<html", b"<scri") or blob[:2] == b"#!": return "a script or markup"
    if blob and sum(32 <= c < 127 or c in (9, 10, 13) for c in blob[:512]) > 0.95 * len(blob[:512]): return "text"
    return "binary data"


def ads_scan_start(paths: list[str], recursive: bool, strip_known: bool = False) -> dict:
    files = expand_sources(paths, recursive, skip_junk=False)
    if not files:
        raise UserError("There are no files to examine.")

    def make(src):
        def fn(ctx: Ctx, task: Task) -> Output:
            st = list_streams(src)
            if not st:
                return Output([], "No hidden streams.", skipped=True)
            rows = []
            for s in st:
                try:
                    with open(f"{src}:{s['name']}", "rb") as fh:
                        head = fh.read(512)
                except OSError:
                    head = b""
                kind = "Windows download mark (harmless)" if s["name"] == "Zone.Identifier" else _sniff(head)
                rows.append({"file": str(src), "stream": s["name"], "size": s["size"], "kind": kind,
                             "risk": "low" if s["name"] in ("Zone.Identifier", "SummaryInformation", "DocumentSummaryInformation") else ("high" if "program" in kind or "script" in kind else "medium")})
            ctx.job.data.setdefault("streams", []).extend(rows)  # type: ignore[attr-defined]
            return Output([], f"{len(rows)} hidden stream{'s' if len(rows) != 1 else ''} found.", extra={"streams": rows})
        return fn

    tasks = [Task(src.name, make(src), src, rel=rel) for src, rel in files]
    job = ops.start("ads", "Looking for hidden streams", tasks, workers=4)
    job.data["windows_only"] = not WIN
    return {"job": job.id, "count": len(tasks), "supported": WIN}


def ads_strip(items: list[dict], save_to: str = "") -> dict:
    """items: [{file, stream}]. Optionally copies each payload out before deleting it."""
    if not WIN:
        raise UserError("Hidden streams only exist on NTFS drives, so this works on Windows.")
    done, failed = 0, []
    dest = Path(save_to) if save_to else None
    if dest:
        dest.mkdir(parents=True, exist_ok=True)
    for it in items:
        f, s = it.get("file", ""), it.get("stream", "")
        if not f or not s or "\\" in s or "/" in s:
            continue
        try:
            if dest:
                out = unique_path(dest / f"{Path(f).name}.{_nm(s)}.stream")
                with open(f"{f}:{s}", "rb") as a, open(out, "wb") as b:
                    shutil.copyfileobj(a, b)
            os.remove(f"{f}:{s}")
            done += 1
        except OSError as e:
            failed.append({"file": f, "stream": s, "error": str(e)})
    return {"removed": done, "failed": failed}


# ================================================================== 2. attribute override
def _flags(p: Path) -> dict:
    out = {"name": p.name, "path": str(p), "hidden": False, "system": False, "readonly": False, "dot": p.name.startswith(".")}
    try:
        st = p.lstat()
        if WIN:
            a = getattr(st, "st_file_attributes", 0)
            out.update(hidden=bool(a & 2), system=bool(a & 4), readonly=bool(a & 1), index_off=bool(a & 0x2000))
        else:
            fl = getattr(st, "st_flags", 0)
            out["hidden"] = bool(fl & 0x8000) if MAC else out["dot"]      # UF_HIDDEN is 0x8000
            out["readonly"] = not os.access(p, os.W_OK)
            if MAC:
                out["uchg"] = bool(fl & 0x2)
    except OSError as e:
        out["error"] = str(e)
    return out


def find_hidden(root: str, recursive: bool = True, limit: int = 5000) -> list[dict]:
    """Everything the operating system keeps out of sight inside a folder."""
    base, rows = Path(root), []
    if not base.exists():
        raise UserError("That folder does not exist.")
    it = os.walk(base) if recursive else [(str(base), [d.name for d in os.scandir(base) if d.is_dir()], [f.name for f in os.scandir(base) if f.is_file()])]
    for cur, dirs, files in it:
        for n in dirs + files:
            f = _flags(Path(cur) / n)
            if f["hidden"] or f["system"] or (f["dot"] and not WIN):
                f["dir"] = n in dirs
                rows.append(f)
                if len(rows) >= limit:
                    return rows
    return rows


def attr_apply(paths: list[str], action: str, recursive: bool = False) -> dict:
    """action: hide | show | system_on | system_off | readonly_on | readonly_off. On Linux 'hide'/'show' add/remove the leading dot."""
    todo: list[Path] = []
    for p in paths:
        pp = Path(p)
        if not pp.exists() and not pp.is_symlink():
            continue
        todo.append(pp)
        if recursive and pp.is_dir():
            for cur, ds, fs in os.walk(pp):
                todo.extend(Path(cur) / n for n in ds + fs)
    done, failed, renames = 0, [], []
    for p in todo:
        try:
            if WIN:
                flag = {"hide": "+h", "show": "-h", "system_on": "+s", "system_off": "-s", "readonly_on": "+r", "readonly_off": "-r"}[action]
                rc, out = _run(["attrib", flag, str(p)])
                if rc:
                    raise OSError(out.strip())
            elif MAC and action in ("hide", "show"):
                rc, out = _run(["chflags", "hidden" if action == "hide" else "nohidden", str(p)])
                if rc:
                    raise OSError(out.strip())
            elif action in ("hide", "show"):
                if action == "hide" and not p.name.startswith("."):
                    new = unique_path(p.with_name("." + p.name)); p.rename(new); renames.append((str(p), str(new)))
                elif action == "show" and p.name.startswith(".") and len(p.name) > 1:
                    new = unique_path(p.with_name(p.name.lstrip(".") or p.name)); p.rename(new); renames.append((str(p), str(new)))
            elif action.startswith("readonly"):
                m = p.stat().st_mode
                os.chmod(p, (m & ~0o222) if action == "readonly_on" else (m | 0o200))
            else:
                continue
            done += 1
        except (OSError, KeyError) as e:
            failed.append({"path": str(p), "error": str(e)})
    return {"changed": done, "failed": failed, "renamed": renames}


# ================================================================== 3. data carving
SIGS = {   # name: (header, footer or None, max bytes, extension, label)
    "jpg": (b"\xff\xd8\xff", b"\xff\xd9", 40 << 20, "jpg", "JPEG picture"),
    "png": (b"\x89PNG\r\n\x1a\n", b"IEND\xaeB`\x82", 60 << 20, "png", "PNG picture"),
    "gif": (b"GIF8", b"\x00\x3b", 40 << 20, "gif", "GIF picture"),
    "bmp": (b"BM", None, 60 << 20, "bmp", "BMP picture"),
    "pdf": (b"%PDF-", b"%%EOF", 200 << 20, "pdf", "PDF document"),
    "zip": (b"PK\x03\x04", b"PK\x05\x06", 500 << 20, "zip", "ZIP / Office / APK"),
    "rar": (b"Rar!\x1a\x07", None, 500 << 20, "rar", "RAR archive"),
    "7z": (b"7z\xbc\xaf\x27\x1c", None, 500 << 20, "7z", "7-Zip archive"),
    "mp3": (b"ID3", None, 30 << 20, "mp3", "MP3 song"),
    "wav": (b"RIFF", None, 300 << 20, "wav", "WAV / AVI (RIFF)"),
    "mp4": (b"\x00\x00\x00\x18ftyp", None, 1500 << 20, "mp4", "MP4 / MOV video"),
    "mp4b": (b"\x00\x00\x00\x20ftyp", None, 1500 << 20, "mp4", "MP4 / MOV video"),
    "mkv": (b"\x1a\x45\xdf\xa3", None, 2000 << 20, "mkv", "MKV / WebM video"),
    "sqlite": (b"SQLite format 3\x00", None, 300 << 20, "sqlite", "SQLite database"),
    "exe": (b"MZ\x90\x00", None, 100 << 20, "exe", "Windows program"),
    "ole": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", None, 100 << 20, "doc", "Old Word / Excel / PPT"),
    "psd": (b"8BPS", None, 400 << 20, "psd", "Photoshop file"),
    "flac": (b"fLaC", None, 200 << 20, "flac", "FLAC audio"),
    "ogg": (b"OggS", None, 100 << 20, "ogg", "OGG audio"),
}
CARVE_LABELS = {k: v[4] for k, v in SIGS.items() if k != "mp4b"}
SECTOR = 4096


def _open_raw(src: str):
    p = src
    if WIN and re.fullmatch(r"[A-Za-z]:?\\?", src):
        p = "\\\\.\\" + src[0].upper() + ":"
    try:
        return open(p, "rb", buffering=0)
    except PermissionError:
        raise UserError("Windows needs administrator rights to read a whole drive. Start Fathom as administrator (Fathom.bat does this)." if WIN else "Reading a whole drive needs root. Run with sudo, or point this at a disk image file.")
    except OSError as e:
        raise UserError(f"Could not open {src}: {e}")


def _read_at(fh, off: int, n: int) -> bytes:
    a = off - off % SECTOR
    fh.seek(a)
    want = ((off - a + n + SECTOR - 1) // SECTOR) * SECTOR
    blob = fh.read(want)
    return blob[off - a: off - a + n]


def _end_of(fh, off: int, name: str, size_limit: int) -> int | None:
    """Where a carved file most likely ends (absolute offset) or None if no sane end could be found."""
    head, foot, mx, _e, _l = SIGS[name]
    mx = min(mx, size_limit - off)
    if name == "bmp":
        h = _read_at(fh, off, 14)
        sz = struct.unpack("<I", h[2:6])[0] if len(h) >= 6 else 0
        return off + sz if 54 <= sz <= mx and h[6:10] == b"\0\0\0\0" else None
    if name == "wav":
        h = _read_at(fh, off, 12)
        if h[8:12] not in (b"WAVE", b"AVI "):
            return None
        sz = struct.unpack("<I", h[4:8])[0] + 8
        return off + sz if 44 <= sz <= mx else None
    if name in ("mp4", "mp4b"):          # walk the top-level boxes
        pos = off
        while pos - off < mx:
            h = _read_at(fh, pos, 8)
            if len(h) < 8:
                break
            sz, typ = struct.unpack(">I4s", h)
            if not re.fullmatch(rb"[a-z0-9 ]{4}", typ) or sz < 8:
                break
            pos += sz
        return pos if pos - off > 1024 else None
    if name == "sqlite":
        h = _read_at(fh, off, 100)
        ps = struct.unpack(">H", h[16:18])[0]; pages = struct.unpack(">I", h[28:32])[0]
        ps = 65536 if ps == 1 else ps
        return off + ps * pages if ps and pages and ps * pages <= mx else None
    if foot is None:
        return None
    pos, tail = off, b""
    while pos - off < mx:
        blob = _read_at(fh, pos, 1 << 20)
        if not blob:
            break
        hay = tail + blob
        i = hay.find(foot)
        if i >= 0:
            end = pos - len(tail) + i + len(foot)
            if name == "zip":
                end += 18                    # end-of-central-directory record
            return end
        tail = hay[-len(foot):]
        pos += len(blob)
    return None


def carve_start(source: str, kinds: list[str], output: dict, min_kb: int = 1, aligned: bool = True, max_files: int = 100000) -> dict:
    """Scans a drive / partition / disk image for file headers and rebuilds what it finds into the output folder."""
    if not source:
        raise UserError("Choose the drive or disk image to scan.")
    if not os.path.exists(source) and not (WIN and re.fullmatch(r"[A-Za-z]:?\\?", source)):
        raise UserError("That drive or image does not exist.")
    pol = OutputPolicy.from_dict(output)
    if pol.mode != "folder" or not pol.dir:
        raise UserError("Choose a folder to save the recovered files in. Pick a different drive from the one you are scanning, otherwise recovered data can overwrite what you are trying to recover.")
    names = [k for k in (kinds or list(CARVE_LABELS)) if k in SIGS]
    if "mp4" in names and "mp4b" not in names:
        names.append("mp4b")

    def fn(ctx: Ctx, task: Task) -> Output:
        fh = _open_raw(source)
        try:
            try:
                total = os.path.getsize(source) if os.path.isfile(source) else 0
                if not total:
                    fh.seek(0, 2); total = fh.tell()
            except OSError:
                total = 0
            if not total and WIN:
                total = _win_disk_size(source)
            step, ov = 8 << 20, 64
            pos, found = 0, 0
            outdir = Path(pol.dir); outdir.mkdir(parents=True, exist_ok=True)
            heads = sorted({SIGS[n][0]: n for n in names}.items())
            first = {}
            for h, n in heads:
                first.setdefault(h[:2], []).append((h, n))
            recovered = ctx.job.data.setdefault("carved", [])  # type: ignore[attr-defined]
            last_end = -1
            while (not total or pos < total) and found < max_files:
                ctx.check()
                fh.seek(pos - pos % SECTOR)
                blob = fh.read(step + ov)
                if not blob:
                    break
                base = pos - pos % SECTOR
                hits = []
                for h, n in heads:
                    i = blob.find(h)
                    while i != -1:
                        hits.append((base + i, n))
                        i = blob.find(h, i + 1)
                for a, n in sorted(hits):
                    if (a >= pos or base == pos) and a >= last_end and (not aligned or a % 512 == 0):
                        end = _end_of(fh, a, n, total or (a + SIGS[n][2]))
                        if end and end - a >= min_kb * 1024:
                            _, _, _, ext, label = SIGS[n]
                            dst = unique_path(outdir / f"{n.rstrip('b')}_{a:012d}.{ext}")
                            _copy_range(fh, a, end - a, dst, ctx)
                            recovered.append({"offset": a, "size": end - a, "type": label, "path": str(dst)})
                            found += 1
                            if n in ("jpg", "png", "gif", "pdf", "zip", "mp4", "mp4b", "bmp", "wav", "sqlite"):
                                last_end = end
                pos += step
                ctx.progress(min(1.0, pos / total) if total else 0.0)
                ctx.status(f"Scanned {pos >> 20} MB · {found} files rebuilt")
            ctx.job.data["scanned"] = pos  # type: ignore[attr-defined]
            return Output([], f"Rebuilt {found} file{'s' if found != 1 else ''} from {min(pos, total or pos) >> 20} MB.", extra={"count": found})
        finally:
            fh.close()

    task = Task(Path(source).name or source, fn, None, heavy=True)
    job = ops.start("carve", "Scanning storage for deleted files", [task], workers=1)
    return {"job": job.id}


def _win_disk_size(src: str) -> int:
    rc, out = _run(["powershell", "-NoProfile", "-Command", f"(Get-Volume -DriveLetter {src[0]}).Size"])
    try:
        return int(out.strip())
    except ValueError:
        return 0


def _copy_range(fh, off: int, n: int, dst: Path, ctx: Ctx) -> None:
    with open(dst, "wb") as out:
        done = 0
        while done < n:
            ctx.check()
            blob = _read_at(fh, off + done, min(4 << 20, n - done))
            if not blob:
                break
            out.write(blob)
            done += len(blob)


# ================================================================== 4. steganography
STEG_MAGIC = b"FSTG1"


def _nm(name: str) -> str:
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", os.path.basename(name.replace("\\", "/"))).strip(". ")
    return n[:120]


def _lsb_bits(path: Path):
    """Yields the flat array of values whose lowest bit may carry data, plus a rebuild function."""
    import numpy as np

    ext = path.suffix.lower()
    if ext == ".wav":
        import wave
        with wave.open(str(path), "rb") as w:
            if w.getsampwidth() != 2:
                raise ConvertError("Only 16-bit WAV audio is supported for hidden data.")
            params = w.getparams(); raw = w.readframes(w.getnframes())
        arr = np.frombuffer(raw, dtype="<i2").copy()
        return arr, lambda a, dst: _write_wav(dst, params, a)
    from PIL import Image
    im = Image.open(path)
    if im.format in ("JPEG", "GIF", "WEBP") and not getattr(im, "is_animated", False) and im.format == "JPEG":
        raise ConvertError("JPEG pictures lose hidden pixel data when they are saved. Use PNG, BMP, TIFF or WAV.")
    im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    arr = np.array(im, dtype=np.uint8)
    shape, mode = arr.shape, im.mode
    return arr.reshape(-1).copy(), lambda a, dst: Image.fromarray(a.reshape(shape).astype(np.uint8), mode).save(dst, "PNG")


def _write_wav(dst, params, arr) -> None:
    import wave
    with wave.open(str(dst), "wb") as w:
        w.setparams(params); w.writeframes(arr.astype("<i2").tobytes())


def _bits_to_bytes(bits) -> bytes:
    import numpy as np
    n = len(bits) // 8 * 8
    return np.packbits(bits[:n]).tobytes()


def _pack_packet(payload: bytes, name: str, password: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from app.filetools2 import _kdf
    salt, nonce = os.urandom(16), os.urandom(12)
    body = struct.pack(">H", len(name.encode())) + name.encode() + payload
    ct = AESGCM(_kdf(password, salt)).encrypt(nonce, body, STEG_MAGIC) if password else body
    flag = b"\x01" if password else b"\x00"
    return STEG_MAGIC + flag + salt + nonce + struct.pack(">I", len(ct)) + ct


def steg_capacity(path: str) -> int:
    arr, _ = _lsb_bits(Path(path))
    return max(0, len(arr) // 8 - 5 - 1 - 16 - 12 - 4 - 16 - 2)


def steg_hide_start(cover: str, secret: str, password: str, output: dict) -> dict:
    import numpy as np
    c, s = Path(cover), Path(secret)
    if not c.is_file() or not s.is_file():
        raise UserError("Choose a cover picture or WAV file and the file to hide.")
    pol = OutputPolicy.from_dict(output)

    def fn(ctx: Ctx, task: Task) -> Output:
        arr, rebuild = _lsb_bits(c)
        packet = _pack_packet(s.read_bytes(), s.name, password)
        bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
        if len(bits) > len(arr):
            raise ConvertError(f"The cover can hold {len(arr) // 8 - 100} bytes but the secret needs {len(packet)}. Use a bigger picture or a smaller secret.")
        arr[:len(bits)] = arr[:len(bits)] - (arr[:len(bits)] & 1) + bits.astype(arr.dtype)
        dst = ctx.scratch_dir() / (c.stem + ("_hidden.wav" if c.suffix.lower() == ".wav" else "_hidden.png"))
        rebuild(arr.astype(arr.dtype), dst)
        return Output(pol.place([dst], c, Path(".")), "Secret hidden inside. Send it as a PNG/WAV and never re-save or resize it, or the secret is lost.")
    return {"job": ops.start("steg-hide", "Hiding data", [Task(c.name, fn, c)], workers=1).id}


def _detect(arr) -> dict:
    """Statistical hint that the lowest bits are not natural: random-looking LSBs plus a balanced ones ratio."""
    import numpy as np
    n = min(len(arr), 200000)
    lsb = (arr[:n] & 1).astype(np.uint8)
    ones = float(lsb.mean()) if n else 0
    pair = float((lsb[1:] == lsb[:-1]).mean()) if n > 1 else 1
    return {"ones": round(ones, 3), "pair": round(pair, 3), "suspicious": n > 5000 and abs(ones - 0.5) < 0.02 and abs(pair - 0.5) < 0.03}


def steg_scan_start(paths: list[str], recursive: bool, password: str, output: dict) -> dict:
    import numpy as np
    pol = OutputPolicy.from_dict(output)
    files = [(p, r) for p, r in expand_sources(paths, recursive, skip_junk=False) if p.suffix.lower() in (".png", ".bmp", ".tif", ".tiff", ".wav", ".jpg", ".jpeg", ".gif", ".webp")]
    if not files:
        raise UserError("Add pictures (PNG, BMP, TIFF) or WAV audio files.")

    def make(src, rel):
        def fn(ctx: Ctx, task: Task) -> Output:
            notes = []
            tail = _trailing(src)
            if tail:
                dst = ctx.scratch_dir() / (src.stem + ".appended.bin"); dst.write_bytes(tail)
                notes.append(f"{len(tail)} bytes were appended after the end of the file")
                outs = [dst]
            else:
                outs = []
            try:
                arr, _ = _lsb_bits(src)
            except ConvertError as e:
                if not outs:
                    return Output([], str(e), skipped=True)
                arr = None
            if arr is not None:
                head = _bits_to_bytes(arr[:8 * 40] & 1)
                if head[:5] == STEG_MAGIC:
                    enc = head[5] == 1
                    ln = struct.unpack(">I", _bits_to_bytes(arr[8 * (5 + 1 + 16 + 12):8 * (5 + 1 + 16 + 12 + 4)] & 1))[0]
                    total = 5 + 1 + 16 + 12 + 4 + ln
                    if ln > len(arr) // 8:
                        raise ConvertError("A hidden packet header was found but it is damaged.")
                    raw = _bits_to_bytes(arr[:8 * total] & 1)
                    packet = raw
                    salt, nonce, ct = raw[6:22], raw[22:34], raw[38:total]
                    if enc and password:
                        from cryptography.exceptions import InvalidTag
                        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                        from app.filetools2 import _kdf
                        try:
                            body = AESGCM(_kdf(password, salt)).decrypt(nonce, ct, STEG_MAGIC)
                        except InvalidTag:
                            raise ConvertError("A hidden encrypted packet is inside, but the password is wrong.")
                        nl = struct.unpack(">H", body[:2])[0]
                        name = _nm(body[2:2 + nl].decode("utf-8", "replace")) or "hidden.bin"
                        dst = ctx.scratch_dir() / name; dst.write_bytes(body[2 + nl:])
                        outs.append(dst); notes.append(f"unlocked hidden file '{name}' ({len(body) - 2 - nl} bytes)")
                    elif not enc:
                        nl = struct.unpack(">H", ct[:2])[0]
                        name = _nm(ct[2:2 + nl].decode("utf-8", "replace")) or "hidden.bin"
                        dst = ctx.scratch_dir() / name; dst.write_bytes(ct[2 + nl:])
                        outs.append(dst); notes.append(f"hidden file '{name}' found (not encrypted)")
                    else:
                        dst = ctx.scratch_dir() / (src.stem + ".packet.fstg"); dst.write_bytes(packet)
                        outs.append(dst); notes.append(f"a hidden ENCRYPTED packet of {ln} bytes was isolated; type the password to open it")
                else:
                    d = _detect(arr)
                    if d["suspicious"]:
                        notes.append("the lowest bits look random, so something may be hidden with a method Fathom cannot open (no matching Fathom packet)")
            if not notes:
                return Output([], "Nothing hidden found.", skipped=True)
            placed = pol.place(outs, src, rel, src.stem + "_hidden") if outs else []
            return Output(placed, ("; ".join(notes))[:1].upper() + ("; ".join(notes))[1:] + ".")
        return fn

    return {"job": ops.start("steg", "Looking for hidden data", [Task(s.name, make(s, r), s, rel=r) for s, r in files], workers=2).id, "count": len(files)}


def _trailing(p: Path) -> bytes:
    """Bytes stored after the real end of a PNG / JPEG / GIF (a classic hiding place)."""
    try:
        data = p.read_bytes() if file_bytes(p) < (200 << 20) else b""
    except OSError:
        return b""
    ends = {b"\x89PNG": b"IEND\xaeB`\x82", b"\xff\xd8\xff": b"\xff\xd9", b"GIF8": b"\x00\x3b"}
    for h, f in ends.items():
        if data.startswith(h):
            i = data.rfind(f)
            extra = data[i + len(f):] if i >= 0 else b""
            return extra if len(extra) > 16 else b""
    return b""


# ================================================================== 5. drive -> image file (read only) and verification
def image_start(source: str, output: dict, name: str = "") -> dict:
    """Copies a drive, partition or device to one image file, reading only. Unreadable spots are zero-filled and counted. A SHA-256 is made while copying."""
    import hashlib
    if not source:
        raise UserError("Choose the drive, disk or file to copy.")
    pol = OutputPolicy.from_dict(output)
    if pol.mode != "folder" or not pol.dir:
        raise UserError("Choose a folder for the image file, on a different drive from the one you copy. Pick it on the left.")
    out_dir = Path(pol.dir)
    if WIN and re.fullmatch(r"[A-Za-z]:?\\?", source) and out_dir.drive.upper()[:1] == source[0].upper():
        raise UserError("The image would be saved on the drive you are copying. Choose a folder on another drive.")

    def fn(ctx: Ctx, task: Task) -> Output:
        fh = _open_raw(source)
        try:
            fh.seek(0, 2); total = fh.tell()
        except OSError:
            total = 0
        if not total and WIN:
            total = _win_disk_size(source)
        if total:
            free = shutil.disk_usage(out_dir if out_dir.exists() else out_dir.parent).free
            if free < total + (64 << 20):
                raise ConvertError(f"The image needs {total >> 20} MB but the save folder has {free >> 20} MB free.")
        out_dir.mkdir(parents=True, exist_ok=True)
        base = safe_stem(Path(name or (re.sub(r"[^\w]+", "_", source).strip("_") or "disk"))) + ".img"
        dst = unique_path(out_dir / base)
        sha, bad, pos, step = hashlib.sha256(), 0, 0, 4 << 20
        try:
            with open(dst, "wb") as out:
                while not total or pos < total:
                    ctx.check()
                    want = step if not total else min(step, total - pos)
                    fh.seek(pos)
                    try:
                        blob = fh.read(want)
                    except OSError:
                        blob = b""
                        for s in range(0, want, SECTOR):            # retry sector by sector, keep going past bad spots
                            try:
                                fh.seek(pos + s); b = fh.read(SECTOR)
                            except OSError:
                                b = b""
                            if len(b) < SECTOR:
                                b = b + bytes(SECTOR - len(b)); bad += 1
                            blob += b
                    if not blob:
                        break
                    out.write(blob); sha.update(blob); pos += len(blob)
                    ctx.progress(min(1.0, pos / total) if total else 0.0)
                    ctx.status(f"{pos >> 20} MB copied" + (f" · {bad} unreadable sectors" if bad else ""))
        finally:
            fh.close()
        Path(str(dst) + ".sha256").write_text(f"{sha.hexdigest()}  {dst.name}\n")
        ctx.job.data.update(image=str(dst), sha256=sha.hexdigest(), bad_sectors=bad, bytes=pos)  # type: ignore[attr-defined]
        return Output([dst], f"{pos >> 20} MB copied, SHA-256 {sha.hexdigest()[:16]}…" + (f" · {bad} unreadable sectors were filled with zeros" if bad else " · no read errors"))
    return {"job": ops.start("image", "Copying drive to an image", [Task(source, fn, None, heavy=True)], workers=1).id}


# ================================================================== 6. repair damaged files (always works on a copy)
def _repair_png(data: bytes) -> tuple[bytes, list[str]]:
    notes, out, pos = [], [data[:8]], 8
    seen_idat = seen_end = False
    while pos + 12 <= len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        if not re.fullmatch(rb"[A-Za-z]{4}", typ) or pos + 12 + ln > len(data):
            notes.append("cut off damaged end"); break
        body = data[pos + 8:pos + 8 + ln]
        crc = struct.unpack(">I", data[pos + 8 + ln:pos + 12 + ln])[0]
        good = zlib_crc(typ + body)
        if crc != good:
            notes.append(f"fixed checksum of {typ.decode()}")
        out.append(data[pos:pos + 8 + ln] + struct.pack(">I", good))
        seen_idat |= typ == b"IDAT"; seen_end |= typ == b"IEND"
        pos += 12 + ln
        if seen_end:
            break
    if not seen_end:
        out.append(struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib_crc(b"IEND"))); notes.append("added the missing end marker")
    return b"".join(out), notes


def zlib_crc(b: bytes) -> int:
    import zlib
    return zlib.crc32(b) & 0xFFFFFFFF


def _repair_zip(src: Path, dst: Path) -> list[str]:
    import zipfile
    import zlib
    data = src.read_bytes()
    n_ok = n_bad = 0
    pos = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        while True:
            i = data.find(b"PK\x03\x04", pos)
            if i < 0 or i + 30 > len(data):
                break
            (_v, flag, meth, _t, _d, crc, csz, usz, nl, el) = struct.unpack("<HHHHHIIIHH", data[i + 4:i + 30])
            name = data[i + 30:i + 30 + nl].decode("utf-8" if flag & 0x800 else "cp437", "replace")
            start = i + 30 + nl + el
            pos = i + 4
            if flag & 8 or not csz:           # sizes live after the data: inflate until the stream ends
                try:
                    d = zlib.decompressobj(-15); raw = d.decompress(data[start:]) if meth == 8 else data[start:start + usz]
                except zlib.error:
                    n_bad += 1; continue
            else:
                chunk = data[start:start + csz]
                try:
                    raw = zlib.decompress(chunk, -15) if meth == 8 else chunk
                except zlib.error:
                    n_bad += 1; continue
            if name.endswith("/"):
                continue
            z.writestr(name.lstrip("/"), raw); n_ok += 1
    if n_ok == 0:
        dst.unlink(missing_ok=True)
        raise ConvertError("No readable files could be found inside this ZIP.")
    return [f"recovered {n_ok} file{'s' if n_ok != 1 else ''}" + (f", {n_bad} too damaged" if n_bad else "")]


def repair_start(paths: list[str], recursive: bool, output: dict) -> dict:
    pol = OutputPolicy.from_dict(output)
    files = expand_sources(paths, recursive, skip_junk=False)
    if not files:
        raise UserError("Add the damaged files.")

    def make(src: Path, rel: Path):
        def fn(ctx: Ctx, task: Task) -> Output:
            from PIL import Image, ImageFile
            head = src.read_bytes()[:16] if file_bytes(src) else b""
            d = ctx.scratch_dir()
            ext = src.suffix.lower()
            if head[:8] == b"\x89PNG\r\n\x1a\n" or ext == ".png":
                if head[:8] != b"\x89PNG\r\n\x1a\n":
                    data = b"\x89PNG\r\n\x1a\n" + src.read_bytes()[8:]; notes = ["restored the file signature"]
                else:
                    data, notes = _repair_png(src.read_bytes())
                dst = d / (src.stem + "_repaired.png"); dst.write_bytes(data)
                try:
                    Image.open(dst).load()
                except Exception:
                    ImageFile.LOAD_TRUNCATED_IMAGES = True
                    try:
                        im = Image.open(dst); im.load(); im.save(dst, "PNG"); notes.append("kept the part of the picture that could be read")
                    except Exception:
                        raise ConvertError("The picture data is too damaged to rebuild.")
                    finally:
                        ImageFile.LOAD_TRUNCATED_IMAGES = False
            elif head[:3] == b"\xff\xd8\xff" or ext in (".jpg", ".jpeg"):
                data = src.read_bytes(); notes = []
                if head[:3] != b"\xff\xd8\xff":
                    i = data.find(b"\xff\xd8\xff")
                    if i < 0:
                        raise ConvertError("No JPEG data found in this file.")
                    data = data[i:]; notes.append("cut away junk before the picture")
                if not data.rstrip(b"\x00").endswith(b"\xff\xd9"):
                    data = data.rstrip(b"\x00") + b"\xff\xd9"; notes.append("added the missing end marker")
                dst = d / (src.stem + "_repaired.jpg"); dst.write_bytes(data)
                ImageFile.LOAD_TRUNCATED_IMAGES = True
                try:
                    im = Image.open(dst); im.load()
                    if notes == [] or "end marker" in " ".join(notes):
                        pass
                    im.save(dst, "JPEG", quality=95, subsampling=0); notes.append("re-saved the readable part at high quality")
                except Exception:
                    raise ConvertError("The picture data is too damaged to rebuild.")
                finally:
                    ImageFile.LOAD_TRUNCATED_IMAGES = False
            elif head[:2] == b"PK" or ext in (".zip", ".docx", ".xlsx", ".pptx", ".odt", ".jar", ".apk", ".epub"):
                dst = d / (src.stem + "_repaired" + (ext if ext else ".zip")); notes = _repair_zip(src, dst)
            elif head[:4] == b"GIF8":
                data = src.read_bytes()
                if not data.endswith(b"\x3b"):
                    data += b"\x3b"
                dst = d / (src.stem + "_repaired.gif"); dst.write_bytes(data); notes = ["added the missing end marker"]
            elif head[:4] == b"%PDF" or ext == ".pdf":
                import fitz  # type: ignore
                doc = fitz.open(src)
                dst = d / (src.stem + "_repaired.pdf"); doc.save(dst, garbage=4, clean=True, deflate=True); notes = ["rebuilt the page index"]
            else:
                return Output([], "This kind of file cannot be repaired automatically.", skipped=True)
            return Output(pol.place([dst], src, rel), "Repaired copy made: " + ", ".join(notes) + ". The original is untouched.")
        return fn

    return {"job": ops.start("repair", "Repairing files", [Task(s.name, make(s, r), s, rel=r) for s, r in files], workers=2).id, "count": len(files)}
