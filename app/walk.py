"""Find every file under the files/folders the user added."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterator

SKIP_DIR_NAMES = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "$recycle.bin",
    "system volume information", "$winreagent", ".cache",
}
SKIP_FILE_NAMES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log.tmp", "dumpstack.log"}
OFFLINE_ATTRS = 0x1000 | 0x40000 | 0x400000  # offline, recall-on-open, recall-on-data-access (OneDrive "online-only")


def _is_cloud_only(entry: os.DirEntry) -> bool:
    try:
        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & OFFLINE_ATTRS)


def discover(
    sources: list[str],
    recursive: bool = True,
    skip_junk: bool = True,
    include_cloud: bool = False,
    exclude: list[Path] | None = None,
    on_skip: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[tuple[Path, str]]:
    """Yields (path, display name). Names of files inside a folder start with that folder's name,
    so the user sees 'Holiday/IMG_0001.jpg'."""
    seen: set[str] = set()
    exclude_norm = [os.path.normcase(os.path.abspath(p)) for p in (exclude or [])]

    def excluded(p: str) -> bool:
        n = os.path.normcase(os.path.abspath(p))
        return any(n == x or n.startswith(x + os.sep) for x in exclude_norm)

    def emit(path: Path, display: str):
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            return None
        seen.add(key)
        return path, display

    for raw in sources:
        root = Path(raw)
        if not root.exists():
            if on_skip:
                on_skip(f"missing: {raw}")
            continue
        if root.is_file():
            item = emit(root, root.name)
            if item:
                yield item
            continue
        base = root.parent
        stack = [root]
        while stack:
            if should_stop and should_stop():
                return
            folder = stack.pop()
            if excluded(str(folder)):
                continue
            try:
                entries = list(os.scandir(folder))
            except OSError as exc:
                if on_skip:
                    on_skip(f"cannot open folder {folder}: {exc.strerror or exc}")
                continue
            entries.sort(key=lambda e: e.name.lower(), reverse=True)  # reversed: stack pops in A-Z order
            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    junction = getattr(entry, "is_junction", lambda: False)()
                    is_link = entry.is_symlink()
                except OSError:
                    continue
                if is_dir:
                    if junction or is_link:
                        continue  # avoids endless loops like Windows' 'Application Data' junctions
                    if skip_junk and entry.name.lower() in SKIP_DIR_NAMES:
                        continue
                    if recursive:
                        stack.append(Path(entry.path))
                    continue
                if entry.name.lower() in SKIP_FILE_NAMES:
                    continue
                if not include_cloud and _is_cloud_only(entry):
                    if on_skip:
                        on_skip(f"online-only (not downloaded): {entry.path}")
                    continue
                if excluded(entry.path):
                    continue
                path = Path(entry.path)
                try:
                    display = path.relative_to(base).as_posix()
                except ValueError:
                    display = path.name
                item = emit(path, display)
                if item:
                    yield item
