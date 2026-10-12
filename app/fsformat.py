"""Linux-family file systems (ext2/3/4, Btrfs, XFS, F2FS, ZFS), only where the system can really make them.

* Linux: format a disk image file, or a real disk partition (root, unmounted, typed confirmation).
* Windows: Windows itself cannot make these, so Fathom only creates a disk IMAGE FILE formatted through WSL (Windows Subsystem for Linux), if WSL is installed.
* macOS: not offered."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from app import ops
from app.convert.core import ConvertError, Ctx, unique_path
from app.ops import Output, OutputPolicy, Task
from app.service import UserError

WIN, MAC = sys.platform == "win32", sys.platform == "darwin"
NOWIN = 0x08000000 if WIN else 0
FS = {   # id: (label, tool, min MB, label option builder, device-only)
    "ext4": ("ext4 (Linux standard)", "mkfs.ext4", 8, lambda l: ["-F", "-L", l] if l else ["-F"], False),
    "ext3": ("ext3", "mkfs.ext3", 8, lambda l: ["-F", "-L", l] if l else ["-F"], False),
    "ext2": ("ext2", "mkfs.ext2", 8, lambda l: ["-F", "-L", l] if l else ["-F"], False),
    "btrfs": ("Btrfs", "mkfs.btrfs", 120, lambda l: ["-f", "-L", l] if l else ["-f"], False),
    "xfs": ("XFS", "mkfs.xfs", 310, lambda l: ["-f", "-L", l] if l else ["-f"], False),
    "f2fs": ("F2FS (flash)", "mkfs.f2fs", 40, lambda l: ["-f", "-l", l] if l else ["-f"], False),
    "zfs": ("ZFS pool", "zpool", 0, None, True),
}


def _wsl() -> bool:
    if not WIN or not shutil.which("wsl"):
        return False
    try:
        r = subprocess.run(["wsl", "--status"], capture_output=True, timeout=15, creationflags=NOWIN)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def capabilities() -> dict:
    plat = "windows" if WIN else "mac" if MAC else "linux"
    wsl = _wsl() if WIN else False
    root = (os.geteuid() == 0) if hasattr(os, "geteuid") else False
    fmts = []
    for k, (label, tool, mn, _l, dev_only) in FS.items():
        if WIN:
            ok = wsl and not dev_only
            why = "" if ok else ("Windows cannot make this itself. Install WSL (wsl --install) to create disk image files." if not wsl else "ZFS pools need a real Linux system.")
        elif MAC:
            ok, why = False, "macOS cannot make this file system."
        else:
            ok = bool(shutil.which(tool))
            why = "" if ok else f"The '{tool}' tool is not installed (install your distribution's package, e.g. e2fsprogs, btrfs-progs, xfsprogs, f2fs-tools, zfsutils-linux)."
        fmts.append({"id": k, "label": label, "available": ok, "why": why, "min_mb": mn, "device_only": dev_only})
    return {"platform": plat, "wsl": wsl, "root": root, "formats": fmts, "devices": _devices() if plat == "linux" else []}


def _mounted() -> set[str]:
    out = set()
    try:
        for ln in open("/proc/mounts"):
            out.add(ln.split()[0])
    except OSError:
        pass
    return out


def _devices() -> list[dict]:
    """Unmounted partitions that look safe to format (never the ones holding the system)."""
    try:
        r = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINTS,RM"], capture_output=True, text=True, timeout=15)
        import json
        rows = []
        def walk(n):
            for d in n:
                if d.get("type") in ("part", "disk") and not any(d.get("mountpoints") or []) and not d.get("children"):
                    rows.append({"path": d["path"], "size": int(d.get("size") or 0), "fs": d.get("fstype") or "", "label": d.get("label") or "", "removable": bool(d.get("rm"))})
                walk(d.get("children") or [])
        walk(json.loads(r.stdout).get("blockdevices", []))
        return rows
    except Exception:
        return []


def _wslpath(p: Path) -> str:
    r = subprocess.run(["wsl", "wslpath", "-a", str(p)], capture_output=True, text=True, creationflags=NOWIN)
    if r.returncode or not r.stdout.strip():
        raise ConvertError("WSL could not find the image path.")
    return r.stdout.strip()


def format_start(fs: str, kind: str, output: dict, name: str, size_mb: int, label: str, device: str, confirm: str) -> dict:
    caps = {f["id"]: f for f in capabilities()["formats"]}
    if fs not in FS or fs not in caps:
        raise UserError("Choose a file system.")
    if not caps[fs]["available"]:
        raise UserError(caps[fs]["why"])
    label = re.sub(r"[^\w .\-]", "", label or "")[:16]
    _l, tool, mn, lab, dev_only = FS[fs][0], FS[fs][1], FS[fs][2], FS[fs][3], FS[fs][4]
    if kind == "device":
        if WIN or MAC:
            raise UserError("Formatting real disks with this file system is only offered on Linux. On Windows, create a disk image file instead.")
        if not device.startswith("/dev/") or not os.path.exists(device):
            raise UserError("Choose a disk partition from the list.")
        if os.geteuid() != 0:
            raise UserError("Formatting a disk needs root. Start Fathom with sudo.")
        if device in _mounted() or any(d.startswith(device) for d in _mounted() if d.startswith("/dev/")):
            raise UserError("That disk is in use (mounted). Unmount it first.")
        if device not in {d["path"] for d in _devices()}:
            raise UserError("Fathom only formats unmounted partitions that are not in use by the system.")
        if confirm.strip() != device:
            raise UserError(f"To format, type the exact device name ({device}). Everything on it will be erased.")

        def fn(ctx: Ctx, task: Task) -> Output:
            cmd = ["zpool", "create", "-f", re.sub(r"\W", "", label) or "pool", device] if fs == "zfs" else [tool, *lab(label), device]
            rc, out = ctx.run(cmd)
            if rc:
                raise ConvertError("Formatting failed: " + (out.strip().splitlines() or ["unknown error"])[-1][:200])
            return Output([], f"{device} is now {FS[fs][0]}.")
        return {"job": ops.start("fsformat", "Formatting", [Task(device, fn, None, heavy=True)], workers=1).id}

    # disk image file
    if dev_only:
        raise UserError("ZFS needs a real disk. Choose 'a disk' on Linux.")
    pol = OutputPolicy.from_dict(output)
    if pol.mode != "folder" or not pol.dir:
        raise UserError("Choose the folder where the image file is saved (on the left).")
    size_mb = int(size_mb or 0)
    if size_mb < mn:
        raise UserError(f"{FS[fs][0]} needs an image of at least {mn} MB.")

    def fn(ctx: Ctx, task: Task) -> Output:
        d = Path(pol.dir); d.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(d).free
        dst = unique_path(d / ((re.sub(r"[^\w.\-]+", "_", name) or f"{fs}-disk") + ".img"))
        with open(dst, "wb") as f:
            f.truncate(size_mb << 20)                       # sparse: takes almost no room until used
        try:
            if WIN:
                cmd = ["wsl", tool, *lab(label), _wslpath(dst)]
            else:
                cmd = [tool, *lab(label), str(dst)]
            rc, out = ctx.run(cmd)
            if rc:
                raise ConvertError("Formatting failed: " + (out.strip().splitlines() or ["unknown error"])[-1][:200])
        except BaseException:
            dst.unlink(missing_ok=True); raise
        return Output([dst], f"Made a {size_mb} MB {FS[fs][0]} disk image. " + ("Open it in WSL or Linux (mount -o loop)." ))
    return {"job": ops.start("fsformat", "Making a disk image", [Task(name or fs, fn, None, heavy=True)], workers=1).id}
