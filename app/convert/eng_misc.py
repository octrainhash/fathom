"""Archives (zip, 7z, tar, gz, rar and more), "any file -> compressed / text-encoded", fonts and 3D models."""
from __future__ import annotations

import base64
import bz2
import gzip
import lzma
import os
import shutil
import subprocess
import tarfile
import zipfile
from functools import lru_cache
from pathlib import Path

from app.convert.core import ConvertError, Ctx, Edge, Engine, Opts, find_program, safe_stem
from app.convert.formats import FORMATS, ext_of
from app.runtime import no_window_flags


def _have(mod: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


@lru_cache(maxsize=1)
def bsdtar_exe() -> str | None:
    """Windows 10/11 ship bsdtar as tar.exe, which can read RAR, 7z, ISO, CAB and more."""
    exe = find_program("bsdtar", "tar", "tar.exe", extra=[r"C:\Windows\System32\tar.exe"])
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15, creationflags=no_window_flags()).stdout.lower()
    except Exception:
        return None
    return exe if ("bsdtar" in out or "libarchive" in out) else None


@lru_cache(maxsize=1)
def sevenzip_exe() -> str | None:
    pf = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
    return find_program("7z", "7zz", "7za", extra=[os.path.join(p, "7-Zip", "7z.exe") for p in pf])


NATIVE_IN = {"zip", "jar", "tar", "tar.gz", "tar.bz2", "tar.xz", "gz", "bz2", "xz", "cbz"}
EXTERNAL_IN = {"rar", "cab", "iso", "cpio", "lzh", "deb", "rpm"}
PACK_OUT = {"zip", "tar", "tar.gz", "tar.bz2", "tar.xz", "gz", "bz2", "xz", "7z"}


def _safe_join(base: Path, name: str) -> Path | None:
    name = name.replace("\\", "/").lstrip("/")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or (parts and ":" in parts[0]):
        return None
    target = base.joinpath(*parts)
    try:
        target.resolve().relative_to(base.resolve())
    except ValueError:
        return None
    return target


def extract_to(src: Path, s: str, dest: Path, o: Opts, ctx: Ctx) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if s in ("zip", "jar", "cbz"):
        try:
            zf = zipfile.ZipFile(src)
        except zipfile.BadZipFile:
            raise ConvertError("This ZIP file is damaged.")
        with zf:
            pw = o.password.encode() if o.password else None
            members = zf.infolist()
            for n, info in enumerate(members, 1):
                ctx.check()
                target = _safe_join(dest, info.filename)
                if target is None:
                    continue
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with zf.open(info, pwd=pw) as fin, open(target, "wb") as fout:
                        shutil.copyfileobj(fin, fout, 1 << 20)
                except RuntimeError as exc:
                    if "password" in str(exc).lower() or "encrypted" in str(exc).lower():
                        raise ConvertError("This ZIP is password-protected. Enter the password in the options and try again.")
                    raise
                ctx.progress(n / len(members))
        return
    if s.startswith("tar"):
        mode = {"tar": "r:", "tar.gz": "r:gz", "tar.bz2": "r:bz2", "tar.xz": "r:xz"}[s]
        try:
            tf = tarfile.open(src, mode)
        except tarfile.TarError as exc:
            raise ConvertError(f"This TAR file could not be opened ({exc}).")
        with tf:
            for member in tf:
                ctx.check()
                target = _safe_join(dest, member.name)
                if target is None or not (member.isfile() or member.isdir()):
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                fobj = tf.extractfile(member)
                if fobj is None:
                    continue
                with fobj, open(target, "wb") as fout:
                    shutil.copyfileobj(fobj, fout, 1 << 20)
        return
    if s in ("gz", "bz2", "xz"):
        opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[s]
        name = src.name[: -(len(s) + 1)] if src.name.lower().endswith("." + s) else src.stem
        with opener(src, "rb") as fin, open(dest / (name or "file"), "wb") as fout:
            shutil.copyfileobj(fin, fout, 1 << 20)
        return
    if s == "7z":
        if _have("py7zr"):
            import py7zr

            try:
                with py7zr.SevenZipFile(src, "r", password=o.password or None) as z:
                    z.extractall(dest)
            except py7zr.exceptions.PasswordRequired:
                raise ConvertError("This 7z archive is password-protected. Enter the password in the options.")
            except Exception as exc:
                raise ConvertError(f"This 7z archive could not be opened ({exc}).")
            return
    exe7 = sevenzip_exe()
    if exe7:
        cmd = [exe7, "x", "-y", f"-o{dest}", str(src)] + ([f"-p{o.password}"] if o.password else [])
        rc, out = ctx.run(cmd, timeout=7200)
        if rc == 0:
            return
        raise ConvertError("7-Zip could not open this archive: " + (out.splitlines()[-1] if out else ""))
    bt = bsdtar_exe()
    if bt:
        rc, out = ctx.run([bt, "-xf", str(src), "-C", str(dest)], timeout=7200)
        if rc == 0:
            return
        raise ConvertError("This archive could not be opened: " + (out.splitlines()[-1] if out else ""))
    raise ConvertError("Nothing on this PC can open this kind of archive.")


def _files_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file())


def pack_from(folder: Path, dst: Path, t: str, o: Opts, ctx: Ctx, single_name: str | None = None) -> None:
    files = _files_in(folder)
    if not files:
        raise ConvertError("There is nothing inside to pack.")
    level = max(1, min(9, int(o.level or 9)))
    total = max(1, sum(f.stat().st_size for f in files))
    done = 0
    if t == "zip":
        if o.password:
            if not _have("pyzipper"):
                raise ConvertError("Password-protected ZIP files need the 'pyzipper' package (run Fathom.bat repair with internet).")
            import pyzipper

            zf = pyzipper.AESZipFile(dst, "w", compression=pyzipper.ZIP_DEFLATED, compresslevel=level, encryption=pyzipper.WZ_AES)
            zf.setpassword(o.password.encode())
        else:
            zf = zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=level, allowZip64=True)
        with zf:
            for f in files:
                ctx.check()
                zf.write(f, f.relative_to(folder).as_posix())
                done += f.stat().st_size
                ctx.progress(done / total)
    elif t.startswith("tar"):
        mode = {"tar": "w:", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[t]
        kw = {"compresslevel": level} if t in ("tar.gz", "tar.bz2") else ({"preset": level} if t == "tar.xz" else {})
        with tarfile.open(dst, mode, **kw) as tf:
            for f in files:
                ctx.check()
                tf.add(f, f.relative_to(folder).as_posix(), recursive=False)
                done += f.stat().st_size
                ctx.progress(done / total)
    elif t in ("gz", "bz2", "xz"):
        if len(files) != 1:
            raise ConvertError(f".{t} can hold only one file. Choose .tar.{t} or .zip for several files.")
        opener = {"gz": lambda p: gzip.GzipFile(p, "wb", compresslevel=level), "bz2": lambda p: bz2.BZ2File(p, "wb", compresslevel=level),
                  "xz": lambda p: lzma.LZMAFile(p, "wb", preset=level)}[t]
        with open(files[0], "rb") as fin, opener(str(dst)) as fout:
            while True:
                ctx.check()
                block = fin.read(1 << 20)
                if not block:
                    break
                fout.write(block)
                done += len(block)
                ctx.progress(done / total)
    elif t == "7z":
        if _have("py7zr"):
            import py7zr

            filters = [{"id": py7zr.FILTER_LZMA2, "preset": level}]
            with py7zr.SevenZipFile(dst, "w", filters=filters, password=o.password or None) as z:
                for f in files:
                    ctx.check()
                    z.write(f, f.relative_to(folder).as_posix())
            return
        exe7 = sevenzip_exe()
        if exe7:
            cmd = [exe7, "a", "-t7z", f"-mx={level}", str(dst), "*"] + ([f"-p{o.password}", "-mhe=on"] if o.password else [])
            rc, out = ctx.run(cmd, cwd=folder, timeout=7200)
            if rc != 0:
                raise ConvertError("7-Zip could not create the archive: " + (out.splitlines()[-1] if out else ""))
            return
        raise ConvertError("Making 7z files needs the 'py7zr' package (run Fathom.bat repair with internet).")
    else:
        raise ConvertError(f"Cannot make {t} archives.")


class ArchiveEngine(Engine):
    name = "archive"
    label = "Archives and compressed files"
    cost = 1.0

    def reads(self) -> set[str]:
        r = set(NATIVE_IN) | {"cbz"}
        if _have("py7zr") or sevenzip_exe() or bsdtar_exe():
            r.add("7z")
        if sevenzip_exe() or bsdtar_exe():
            r |= EXTERNAL_IN
        return r

    def writes(self) -> set[str]:
        w = set(PACK_OUT) - {"7z"} | {"folder", "b64", "hex"}
        if _have("py7zr") or sevenzip_exe():
            w.add("7z")
        return w

    def can(self, s: str, t: str) -> Edge | None:
        if s == t or s in ("folder", "b64", "hex"):
            return None
        is_arch = s in self.reads()
        if t not in self.writes():
            return None
        if is_arch:
            if t in ("gz", "bz2", "xz") and s not in ("gz", "bz2", "xz"):
                return None   # these hold one file only; an archive of many needs .tar.gz or .zip
            if t == "folder":
                return Edge(s, t, self, 1.0, "The files are unpacked into a folder.")
            if t in PACK_OUT:
                return Edge(s, t, self, 1.2)
            return None
        # any other file: compress it or write it out as text
        if t in PACK_OUT:
            return Edge(s, t, self, 1.5 if s != "bin" else 1.0, "")
        if t in ("b64", "hex"):
            return Edge(s, t, self, 1.6, "The file's bytes are written out as text.")
        return None

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = safe_stem(src)
        if t == "b64":
            dst = out_dir / f"{src.name}.b64"
            with open(src, "rb") as fin, open(dst, "w", encoding="ascii") as fout:
                while True:
                    ctx.check()
                    block = fin.read(57 * 4096)
                    if not block:
                        break
                    fout.write(base64.encodebytes(block).decode("ascii"))
            return [dst]
        if t == "hex":
            dst = out_dir / f"{src.name}.hex.txt"
            with open(src, "rb") as fin, open(dst, "w", encoding="ascii") as fout:
                off = 0
                while True:
                    ctx.check()
                    block = fin.read(16 * 4096)
                    if not block:
                        break
                    for i in range(0, len(block), 16):
                        chunk = block[i:i + 16]
                        hexs = " ".join(f"{b:02x}" for b in chunk).ljust(47)
                        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                        fout.write(f"{off + i:08x}  {hexs}  |{asc}|\n")
                    off += len(block)
            return [dst]
        if s in self.reads():
            work = ctx.scratch_dir()
            extract_to(src, s, work, o, ctx)
            if t == "folder":
                dest = out_dir / stem
                shutil.move(str(work), str(dest))
                return [dest]
            dst = out_dir / f"{stem}.{t}"
            pack_from(work, dst, t, o, ctx)
            return [dst]
        # plain file -> archive
        work = ctx.scratch_dir()
        try:
            os.link(src, work / src.name)
        except OSError:
            shutil.copy2(src, work / src.name)
        dst = out_dir / (f"{src.name}.{t}" if t in ("gz", "bz2", "xz") else f"{stem}.{t}")
        pack_from(work, dst, t, o, ctx)
        return [dst]


# ---------------------------------------------------------------- fonts
class FontEngine(Engine):
    name = "fonts"
    label = "Fonts"
    cost = 1.0

    def available(self) -> bool:
        return _have("fontTools")

    def reads(self) -> set[str]:
        return {"ttf", "otf", "woff", "woff2"}

    def writes(self) -> set[str]:
        w = {"ttf", "otf", "woff"}
        if _have("brotli"):
            w.add("woff2")
        return w

    def can(self, s: str, t: str) -> Edge | None:
        if s == t or s not in self.reads() or t not in self.writes():
            return None
        if t in ("ttf", "otf") and s in ("ttf", "otf"):
            return None   # TrueType and OpenType outlines are different drawings and cannot be converted into one another
        if s in ("woff", "woff2") and t in ("woff", "woff2"):
            return Edge(s, t, self, 1.0)
        return Edge(s, t, self, 1.0, "Web fonts keep the same letter shapes." if t in ("woff", "woff2") else "")

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        from fontTools.ttLib import TTFont, TTLibError

        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            font = TTFont(str(src), lazy=False)
        except TTLibError as exc:
            raise ConvertError(f"This font could not be read ({exc}). Font collections (.ttc) are not supported.")
        is_ttf = "glyf" in font
        if t == "ttf" and not is_ttf:
            raise ConvertError("This font uses OpenType (CFF) outlines, so it can only become .otf, not .ttf.")
        if t == "otf" and is_ttf:
            raise ConvertError("This font uses TrueType outlines, so it can only become .ttf, not .otf.")
        font.flavor = {"woff": "woff", "woff2": "woff2"}.get(t)
        dst = out_dir / f"{safe_stem(src)}.{t}"
        font.save(str(dst))
        return [dst]


# ---------------------------------------------------------------- 3D models
class MeshEngine(Engine):
    name = "mesh"
    label = "3D models"
    cost = 1.0
    needs = "trimesh"

    def available(self) -> bool:
        return _have("trimesh")

    def reads(self) -> set[str]:
        return {"stl", "obj", "ply", "off", "glb", "gltf", "3mf", "dae"} if self.available() else set()

    def writes(self) -> set[str]:
        return {"stl", "obj", "ply", "off", "glb", "gltf"} if self.available() else set()

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        import trimesh

        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            loaded = trimesh.load(str(src), file_type=("gltf" if s == "gltf" else s))
        except Exception as exc:
            raise ConvertError(f"This 3D model could not be read ({exc}).")
        dst = out_dir / f"{safe_stem(src)}.{t}"
        if t in ("glb", "gltf"):
            loaded.export(str(dst), file_type=t)
        else:
            mesh = loaded.dump(concatenate=True) if isinstance(loaded, trimesh.Scene) else loaded
            mesh.export(str(dst), file_type=t)
        return [dst]
