"""Open virtual disks (VHD, VHDX, VMDK, VDI, SquashFS, ISO...) and Docker image layers and take files out, without mounting anything."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tarfile
from pathlib import Path

from app import ops
from app.convert.core import ConvertError, Ctx, unique_path
from app.convert.eng_misc import sevenzip_exe
from app.ops import Output, OutputPolicy, Task
from app.service import UserError

DISK_EXT = {".vhd", ".vhdx", ".vmdk", ".vdi", ".qcow2", ".img", ".iso", ".squashfs", ".sfs", ".wim", ".dmg", ".hdd", ".raw", ".ext4", ".ext3", ".ext2", ".ntfs", ".fat", ".fat32", ".exfat", ".hfs", ".apfs", ".xfs"}
INNER = DISK_EXT | {".part"}


def kind_of(p: Path) -> str:
    n = p.name.lower()
    if n.endswith((".tar", ".tar.gz", ".tgz")):
        return "docker" if _is_docker(p) else "tar"
    if p.suffix.lower() in DISK_EXT:
        return "disk"
    return "other"


def _is_docker(p: Path) -> bool:
    try:
        with tarfile.open(p) as t:
            names = t.getnames()[:400]
        return "manifest.json" in names or any(n.endswith("/layer.tar") for n in names) or any(n.startswith("blobs/sha256/") for n in names)
    except (tarfile.TarError, OSError):
        return False


def _7z() -> str:
    exe = sevenzip_exe()
    if not exe:
        raise UserError("Opening virtual disks needs 7-Zip. The Fathom installer adds it; or install it from 7-zip.org and start Fathom again.")
    return exe


def _parse_slt(text: str) -> list[dict]:
    rows, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if "Path" in cur:
                rows.append(cur)
            cur = {}
        elif " = " in line:
            k, v = line.split(" = ", 1); cur[k] = v
    if "Path" in cur:
        rows.append(cur)
    return rows[1:] if rows and ("Type" in rows[0] and "Physical Size" in rows[0] and "Size" not in rows[0]) else rows


def list_entries(path: str, limit: int = 20000) -> dict:
    p = Path(path)
    if not p.is_file():
        raise UserError("Choose a virtual disk or Docker image file.")
    k = kind_of(p)
    if k == "docker":
        rows = []
        with tarfile.open(p) as t:
            layers = _docker_layers(t)
            for i, ln in enumerate(layers):
                try:
                    lt = tarfile.open(fileobj=t.extractfile(ln))
                except (KeyError, tarfile.TarError):
                    continue
                for m in lt:
                    if len(rows) >= limit:
                        break
                    if not m.isdir():
                        rows.append({"path": m.name.lstrip("./"), "size": m.size, "layer": i + 1, "dir": False})
        return {"kind": "docker", "entries": rows, "layers": len(layers), "truncated": len(rows) >= limit}
    import subprocess
    exe = _7z()
    r = subprocess.run([exe, "l", "-slt", "-sccUTF-8", str(p)], capture_output=True, text=True, errors="replace", creationflags=0x08000000 if sys.platform == "win32" else 0)
    if r.returncode not in (0, 1) and not r.stdout:
        raise UserError("This image could not be read: " + (r.stderr.strip()[:200] or "unknown error"))
    rows = [{"path": e["Path"], "size": int(e.get("Size") or 0), "dir": e.get("Folder") == "+", "nested": Path(e["Path"]).suffix.lower() in INNER or e["Path"].split("/")[-1].split("\\")[-1].split(".")[-1] in ("ntfs", "ext4", "fat", "img")} for e in _parse_slt(r.stdout) if "Path" in e]
    return {"kind": k if k != "other" else "archive", "entries": rows[:limit], "truncated": len(rows) > limit}


def _docker_layers(t: tarfile.TarFile) -> list[str]:
    names = t.getnames()
    if "manifest.json" in names:
        mani = json.load(t.extractfile("manifest.json"))
        return mani[0].get("Layers", [])
    if "index.json" in names:                                          # OCI layout
        idx = json.load(t.extractfile("index.json"))
        man = json.load(t.extractfile("blobs/sha256/" + idx["manifests"][0]["digest"].split(":")[1]))
        return ["blobs/sha256/" + l["digest"].split(":")[1] for l in man["layers"]]
    return [n for n in names if n.endswith("layer.tar")] or [p for p in names if p.endswith(".tar")]


def _safe(base: Path, name: str) -> Path | None:
    parts = [x for x in name.replace("\\", "/").split("/") if x not in ("", ".")]
    if any(x == ".." for x in parts) or (parts and re.match(r"^[A-Za-z]:$", parts[0])):
        return None
    return base.joinpath(*parts)


def _extract_docker(src: Path, dst: Path, want: set[str] | None, ctx: Ctx) -> int:
    """Applies the layers bottom to top, honouring whiteouts, so the folder looks like the container's file system."""
    count = 0
    with tarfile.open(src) as t:
        layers = _docker_layers(t)
        for i, ln in enumerate(layers):
            ctx.check(); ctx.progress(i / max(1, len(layers)))
            fo = t.extractfile(ln)
            if fo is None:
                continue
            try:
                lt = tarfile.open(fileobj=fo, mode="r|*")
            except tarfile.TarError:
                continue
            for m in lt:
                name = m.name.lstrip("./")
                base = os.path.basename(name)
                if base == ".wh..wh..opq":
                    d = _safe(dst, os.path.dirname(name))
                    if d and d.is_dir():
                        for c in d.iterdir():
                            shutil.rmtree(c, ignore_errors=True) if c.is_dir() else c.unlink(missing_ok=True)
                    continue
                if base.startswith(".wh."):
                    target = _safe(dst, os.path.join(os.path.dirname(name), base[4:]))
                    if target:
                        shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink(missing_ok=True)
                    continue
                if want is not None and not any(name == w or name.startswith(w.rstrip("/") + "/") for w in want):
                    continue
                out = _safe(dst, name)
                if out is None or m.issym() or m.islnk() or m.isdev() or m.isfifo():
                    continue
                if m.isdir():
                    out.mkdir(parents=True, exist_ok=True); continue
                out.parent.mkdir(parents=True, exist_ok=True)
                f = lt.extractfile(m)
                if f is not None:
                    with open(out, "wb") as w:
                        shutil.copyfileobj(f, w)
                    count += 1
    return count


def extract_start(path: str, entries: list[str], output: dict, depth: int = 3) -> dict:
    p = Path(path)
    if not p.is_file():
        raise UserError("Choose a virtual disk or Docker image file.")
    pol = OutputPolicy.from_dict(output)
    kind = kind_of(p)
    want = {e.replace("\\", "/") for e in entries} or None

    def fn(ctx: Ctx, task: Task) -> Output:
        d = ctx.scratch_dir() / (p.stem + "_files"); d.mkdir(parents=True)
        if kind == "docker":
            n = _extract_docker(p, d, want, ctx)
        else:
            n = _extract_disk(p, d, want, ctx, depth)
        n = sum(1 for f in d.rglob("*") if f.is_file())
        if n == 0:
            raise ConvertError("Nothing could be taken out of this image.")
        return Output(pol.place([d], p, Path(".")), f"{n} file{'s' if n != 1 else ''} copied out.")

    return {"job": ops.start("vm", "Opening disk image", [Task(p.name, fn, p, heavy=True)], workers=1).id}


def _extract_disk(src: Path, dst: Path, want: set[str] | None, ctx: Ctx, depth: int) -> int:
    exe = _7z()
    cmd = [exe, "x", "-y", "-aoa", f"-o{dst}", str(src)]
    if want:
        cmd += ["-r"] + sorted(want)
    rc, out = ctx.run(cmd)
    if rc not in (0, 1) and not any(dst.rglob("*")):
        raise ConvertError("7-Zip could not open this image: " + out.strip().splitlines()[-1][:200] if out.strip() else "unknown error")
    # nested snapshots: a VMDK holds partition images, which hold the real folders
    for _ in range(max(0, depth)):
        inner = [f for f in dst.rglob("*") if f.is_file() and (f.suffix.lower() in INNER or re.fullmatch(r"\d+\.(ntfs|ext4|fat|hfs|apfs|squashfs|img)", f.name, re.I) or f.name.lower().endswith((".vhd", ".vmdk", ".vhdx")))]
        if not inner:
            break
        for f in inner:
            ctx.check()
            sub = f.with_name(f.name + "_contents"); sub.mkdir(exist_ok=True)
            rc, _o = ctx.run([exe, "x", "-y", "-aoa", f"-o{sub}", str(f)])
            if rc in (0, 1) and any(sub.iterdir()):
                f.unlink(missing_ok=True)
            else:
                shutil.rmtree(sub, ignore_errors=True)
    return sum(1 for f in dst.rglob("*") if f.is_file())
