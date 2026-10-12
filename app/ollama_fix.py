"""Repairs for one known Ollama-on-Windows problem.

Ollama 0.40 can store a model's record (in the folder `manifests-v2`) as a SYMBOLIC LINK. Windows often refuses to follow
such a link ("untrusted mount point", or "The system cannot find the path specified"), so Ollama says the model is
"not found" or "bad manifest" even though every file is on disk. The fix: replace each link with a real copy of the
file it points to. Nothing else is touched. Safe to run any time; it does nothing when there are no links."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

_REPARSE = 0x400


def models_dir() -> Path:
    return Path(os.environ.get("OLLAMA_MODELS") or (Path.home() / ".ollama" / "models"))


def _is_link(p: Path) -> bool:
    try:
        if p.is_symlink():
            return True
        st = os.lstat(p)
        return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)
    except OSError:
        return False


def _target(p: Path) -> str:
    try:
        t = os.readlink(p)
    except OSError:
        return ""
    for pre in ("\\\\?\\", "\\??\\"):
        if t.startswith(pre):
            t = t[len(pre):]
    return t


def _candidates(link: Path, target: str, base: Path) -> list[Path]:
    out: list[Path] = []
    if target:
        t = Path(target)
        out.append(t if t.is_absolute() else link.parent / t)
        last = target.replace("\\", "/").rstrip("/").split("/")[-1].replace(":", "-")
        out.append(base / "blobs" / last)
        out.append(base / "manifests-v2" / last)
    return out


def find_links(base: Path | None = None) -> list[Path]:
    base = base or models_dir()
    found: list[Path] = []
    for sub in ("manifests-v2", "manifests"):
        root = base / sub
        if not root.exists():
            continue
        for dirpath, dirs, files in os.walk(root):
            for name in list(dirs) + list(files):
                p = Path(dirpath) / name
                if _is_link(p):
                    found.append(p)
    return found


def repair_links(base: Path | None = None, say=None) -> int:
    """Replace every symbolic link in Ollama's record folders with a real copy. Returns how many were fixed (or removed when dangling)."""
    base = base or models_dir()
    say = say or (lambda m="": None)
    fixed = 0
    for link in find_links(base):
        target = _target(link)
        src = None
        for c in _candidates(link, target, base):
            try:
                if c.exists() and not _is_link(c):
                    src = c
                    break
            except OSError:
                continue
        try:
            try:
                os.unlink(link)
            except (IsADirectoryError, PermissionError, OSError):
                os.rmdir(link)
            if src is not None:
                if src.is_dir():
                    shutil.copytree(src, link)
                else:
                    shutil.copyfile(src, link)
                say(f"    replaced a link with a real copy: {link.name}")
            else:
                say(f"    removed a broken link (its file is missing): {link.name}")
            fixed += 1
        except Exception as exc:
            say(f"    could not repair {link}: {exc}")
    return fixed


def describe_links(base: Path | None = None) -> list[str]:
    base = base or models_dir()
    return [f"{p.relative_to(base)} -> {_target(p) or '(unreadable)'}" for p in find_links(base)]
