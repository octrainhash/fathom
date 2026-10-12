"""Send a file to the Recycle Bin (so anything Fathom removes can be brought back)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def to_recycle_bin(path: Path, keep: bool = True) -> None:
    """keep=True also keeps a private copy so Activity & Undo can put the file back with one click."""
    path = Path(path)
    copy = ""
    if keep:
        try:
            from app import history
            copy = history.keep_copy(path)
        except Exception:
            copy = ""
    _send(path)
    if keep:
        try:
            from app import history
            if not getattr(history._tl, "quiet", False):
                history.note_removed(path, copy)
        except Exception:
            pass


def _send(path: Path) -> None:
    try:
        from send2trash import send2trash  # type: ignore

        send2trash(str(path))
        return
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", wintypes.LPCWSTR)]

        op = SHFILEOPSTRUCTW()
        op.wFunc = 3                       # FO_DELETE
        op.pFrom = str(path.resolve()) + "\0"
        op.fFlags = 0x40 | 0x10 | 0x4 | 0x400   # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if rc != 0 or op.fAnyOperationsAborted:
            raise OSError(f"Windows could not move this to the Recycle Bin (code {rc}).")
        return
    raise OSError("No Recycle Bin is available on this system, so nothing was deleted.")
